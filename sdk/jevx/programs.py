"""Compiled deciders, repair loops, value dispatch, surrogates, route compilers."""

from __future__ import annotations

import ast
import inspect
from typing import Any

from .client import Client
from .py import (
    P,
    Questions,
    _build,
    _decide,
    _hints,
    feels,
    pick,
)


class Decider:
    """A validated battery compiled to a closure: thresholds baked, one call.

    dec = compile(Triage, act_at=0.7)
    dec(ticket)  -> Triage.Result namedtuple (validated fields only)
    """

    def __init__(self, owner: type, act_at: float = 0.7, client: Client | None = None):
        self.owner = owner
        self.act_at = act_at
        self.client = client

    def __call__(self, state: Any) -> Any:
        result = self.owner(client=self.client)(state)
        return result.as_named(self.owner.Result)


def compile(owner: type, act_at: float = 0.7, client: Client | None = None) -> Decider:
    """Validate a Questions battery once; get a callable returning typed results."""
    if not (isinstance(owner, type) and issubclass(owner, Questions)):
        raise TypeError("compile() needs a Questions subclass")
    if not owner._fields_:
        raise ValueError("compile() needs at least one ask() field")
    return Decider(owner, act_at, client)


def repair(output: Any, check: Any, revise: Any, *,
           rounds: int = 2, client: Client | None = None) -> tuple[Any, bool]:
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
        current = revise(current, critique)
    return current, False


def _run_check(check: Any, current: Any, client: Client | None) -> tuple[bool, str]:
    if isinstance(check, type) and issubclass(check, Questions):
        r = check(client=client)(current)
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
    if callable(pred):
        return bool(pred())
    if isinstance(pred, str):
        q, _, bar = pred.partition("@")
        p = feels(q.strip(), state, client=client)
        return p.over(float(bar) if bar else 0.5)
    raise TypeError(f"cases(): bad predicate {pred!r}")


def surrogate(*, question: str, reference: Any, over: float = 0.8,
              log: list | None = None, client: Client | None = None):
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
            call_client = kwargs.pop("client", client)
            from .py import _NoulQ, _decide as _d
            (a,) = _d(state, {"s": _NoulQ(question)}, call_client).values()
            p = float(a.prob)
            if P(p).over(over):
                return fn(state, *args, **kwargs), {"path": "surrogate", "prob": p}
            result = reference(state, *args, **kwargs)
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
        if not isinstance(node, ast.Match):
            continue
        subj = node.subject
        name = subj.id if isinstance(subj, ast.Name) else None
        if name != var:
            continue
        for case in node.cases:
            pat = case.pattern
            if isinstance(pat, ast.MatchValue) and isinstance(pat.value, ast.Constant) \
                    and isinstance(pat.value.value, str):
                out[pat.value.value] = None
    if not out:
        raise ValueError(f"routes_from(): no string arms for {var!r} in {fn.__name__}")
    return out
