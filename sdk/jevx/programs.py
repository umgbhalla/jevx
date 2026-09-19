"""Compiled deciders, repair loops, value dispatch, surrogates, route compilers."""

from __future__ import annotations

import ast
import inspect
from typing import Any

from .client import Client
from .py import P
from .py import Predicate
from .py import Questions
from .py import _decide
from .py import _NoulQ
from .py import feels


class Decider:
    """A validated battery compiled to a closure: thresholds baked, one call.

    dec = compile(Triage)
    dec(ticket)  -> Triage.Result namedtuple (validated fields only)
    """

    def __init__(self, owner: type, client: Client | None = None):
        self.owner = owner
        self.client = client

    def __call__(self, state: Any, client: Client | None = None) -> Any:
        c = client or self.client
        result = self.owner(client=c).ask(state)
        nt = getattr(self.owner, "Result")
        return result.as_named(nt)


def compile(owner: type, client: Client | None = None) -> Decider:
    """Validate a Questions battery once; get a callable returning typed results."""
    if not (isinstance(owner, type) and issubclass(owner, Questions)):
        raise TypeError("compile() needs a Questions subclass")
    if not owner._fields_:
        raise ValueError("compile() needs at least one ask() field")
    return Decider(owner, client)


def _maybe_client(fn: Any, client: Client | None) -> dict:
    """Pass client= only to callables that accept it."""
    if client is None:
        return {}
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return {}
    return {"client": client} if "client" in params else {}


def repair(
    output: Any, check: Any, revise: Any, *, rounds: int = 2, client: Client | None = None
) -> tuple[Any, bool]:
    """Generate -> check -> repair interpreter.

    check(output) -> (ok: bool, critique: str); revise(output, critique) makes
    the next candidate. Returns (final, ok). Bounded; never spins.
    check/revise may be Questions batteries, callables, or S2-backed fns.
    """
    current = output() if callable(output) and not isinstance(output, str) else output
    for _ in range(rounds + 1):
        ok, critique = _run_check(check, current, client)
        if ok:
            return current, True
        if callable(revise):
            current = revise(current, critique, **_maybe_client(revise, client))
        else:
            current = revise
    return current, False


def _run_check(check: Any, current: Any, client: Client | None) -> tuple[bool, str]:
    if isinstance(check, type) and issubclass(check, Questions):
        r = check(client=client).ask(current)
        bad = [k for k, v in r.as_dict().items() if v is False]
        return (not bad, f"failed: {bad}" if bad else "")
    out = check(current)
    if isinstance(out, tuple):
        return bool(out[0]), str(out[1]) if len(out) > 1 else ""
    return bool(out), ""


def cases(state: Any, *branches: tuple[Any, Any], client: Client | None = None) -> Any:
    """Value dispatch in order: first branch whose predicate holds wins.

    Each branch: (question: str | P | bool | Callable[[], bool], handler).
    str -> feels(question, state).over() (default 0.5; "q? @0.8" suffix sets bar).
    An else-branch is ("else", handler). No match -> raises LookupError.
    """
    for pred, handler in branches:
        if pred == "else" or _holds(pred, state, client):
            return handler(state) if callable(handler) else handler
    raise LookupError("cases(): no branch held and no else")


def _holds(pred: Any, state: Any, client: Client | None) -> bool:
    if isinstance(pred, bool):
        return pred
    if isinstance(pred, P):
        return pred.over()
    if isinstance(pred, Predicate):
        return pred.ask(state, client=client).over()
    if callable(pred):
        try:
            n = len(inspect.signature(pred).parameters)
        except (TypeError, ValueError):
            n = 0
        return bool(pred(state, **_maybe_client(pred, client)) if n else pred())
    if isinstance(pred, str):
        q, _, bar = pred.rpartition("@")
        try:
            threshold = float(bar) if bar else 0.5
        except ValueError:
            raise ValueError(f"cases(): bad bar in {pred!r}, use 'question @0.8'") from None
        p = feels(q.strip(), state, client=client)
        return p.over(threshold)
    raise TypeError(f"cases(): bad predicate {pred!r}")


def _keep_client(target: Any, kwargs: dict, client: Client | None) -> dict:
    """Keep the client kwarg only for targets that accept it."""
    if "client" in kwargs and "client" not in _maybe_client(target, client):
        return {k: v for k, v in kwargs.items() if k != "client"}
    return kwargs


def surrogate(
    *,
    question: str,
    reference: Any,
    over: float = 0.8,
    log: list | None = None,
    client: Client | None = None,
):
    """Dual-implementation functions (distil/dispatch pattern).

    S1 answers the SHAPE directly when confident (dispatch: no body runs);
    otherwise the expensive reference runs (and its trace is logged, distil-style).
    Every real run appends (question, state) -> result to `log` when given,
    growing the calibration set for free.

        @surrogate(question="safe to auto-reply?", reference=write_reply, log=CALIB)
        def reply(ticket): ...

    Returns (result, {"path": "surrogate"|"reference", "prob": ...}).
    """

    def deco(fn):
        import functools as _f

        @_f.wraps(fn)
        def wrapper(state: Any, *args: Any, **kwargs: Any):
            call_client = kwargs.get("client", client)
            (a,) = _decide(state, {"s": _NoulQ(question)}, call_client).values()
            p = float(a.prob)
            if P(p).over(over):
                kw = _keep_client(fn, kwargs, client)
                return fn(state, *args, **kw), {"path": "surrogate", "prob": p}
            kw = _keep_client(reference, kwargs, client)
            result = reference(state, *args, **kw)
            if log is not None:
                log.append({"question": question, "state": state, "result": result})
            return result, {"path": "reference", "prob": p}

        return wrapper

    return deco


def routes_from(fn: Any, var: str) -> dict[str, None]:
    """Compile a match statement's string arms into Choice options.

    Reads fn's source AST, finds `match <var>:` with `case "literal":` arms,
    returns {literal: None}. Guards and captures are ignored (can't be options).

        def handle(team, t):
            match team:
                case "billing": ...
                case "bug": ...
        routes_from(handle, "team")  # {"billing": None, "bug": None}
    """
    src = inspect.getsource(fn)
    tree = ast.parse(src)
    out: dict[str, None] = {}
    for node in ast.walk(tree):
        if (
            not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            or node.name != fn.__name__
        ):
            continue
        for child in ast.walk(node):
            if child is node or not isinstance(child, ast.Match):
                continue
            subj = child.subject
            name = subj.id if isinstance(subj, ast.Name) else None
            if name != var:
                continue
            for case in child.cases:
                if case.guard is not None:
                    continue
                for pat in _or_values(case.pattern):
                    if isinstance(pat, ast.Constant) and isinstance(pat.value, str):
                        out[pat.value] = None
    if not out:
        raise ValueError(f"routes_from(): no string arms for {var!r} in {fn.__name__}")
    return out


def _or_values(pattern: ast.AST) -> list:
    if isinstance(pattern, ast.MatchOr):
        out = []
        for p in pattern.patterns:
            out.extend(_or_values(p))
        return out
    if isinstance(pattern, ast.MatchValue):
        return [pattern.value]
    return []


# ---------------------------------------------------------------- shared loop helpers


def session(backend: Any = None) -> tuple[Any, Any]:
    """One backend in, (s1, s2) out. Replaces `bk or Live(); bk.s1(); bk.s2()`."""
    from .backends import Live as _Live

    bk = backend or _Live()
    return bk.s1(), bk.s2()


def band(p: float, *, act_at: float, review_at: float) -> str:
    """3-way band for any probability (Choice confidence, Noul prob, Score conf)."""
    if p >= act_at:
        return "act"
    if p >= review_at:
        return "review"
    return "skip"


def topk(scored: list[tuple[float, Any]], *, k: int, floor: float = 0.0) -> list[Any]:
    """Top-k values above floor, descending. Passages, skills, hunks, edges."""
    return [v for p, v in sorted(scored, reverse=True)[:k] if p >= floor]


def joint(*confs: float) -> float:
    """Joint confidence: the weakest link. One unsure input spoils the batch."""
    return min(confs) if confs else 0.0


def verify_each(items: list, ask_fn: Any, *, over: float) -> tuple[list, list]:
    """Split items into (ok, bad) by ask_fn(item) probability."""
    ok, bad = [], []
    for item in items:
        (ok if float(ask_fn(item)) >= over else bad).append(item)
    return ok, bad


def stuck(history: list, *, window: int = 3) -> bool:
    """True when the last `window` entries show no change marker."""
    if len(history) < window:
        return False
    tail = history[-window:]
    return all(not (e.get("page_changed", True) if isinstance(e, dict) else e) for e in tail)


def assess_due(
    dirty: bool, force: bool, last: float, *, min_interval: float, periodic: float, now: float
) -> bool:
    """Debounce predicate: lifecycle force, dirty+interval, or periodic poll."""
    return bool(force or (dirty and now - last >= min_interval) or now - last >= periodic)


def tail(events: list[str], n: int = 30, chars: int = 12000) -> dict:
    """Bounded observation tail for watcher state."""
    t = events[-n:]
    return {"event_tail": "\n".join(t)[-chars:], "event_count": len(events)}
