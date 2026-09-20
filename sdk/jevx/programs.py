"""Repair loops, semantic surrogates, and small program helpers."""

from __future__ import annotations

import inspect
from typing import Any

from .client import Client
from .py import P
from .py import Vector
from .py import _decide
from .py import _NoulQ
from .questions import JSONContent


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
    check may be a callable or hard-rule Vector; revise may be callable or text.
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
    if isinstance(check, Vector):
        values = check.ask(current, client=client).as_dict()
        if any(not isinstance(value, bool) for value in values.values()):
            raise TypeError("repair() vectors must contain hard rules that return bool")
        failed = [name for name, passed in values.items() if not passed]
        return not failed, f"failed: {failed}" if failed else ""
    out = check(current)
    if isinstance(out, tuple):
        return bool(out[0]), str(out[1]) if len(out) > 1 else ""
    return bool(out), ""


def _keep_client(target: Any, kwargs: dict, client: Client | None) -> dict:
    """Keep the client kwarg only for targets that accept it."""
    if "client" in kwargs and "client" not in _maybe_client(target, client):
        return {k: v for k, v in kwargs.items() if k != "client"}
    return kwargs


def surrogate(
    *,
    question: JSONContent,
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
            (a,) = _decide(state, {"s": _NoulQ(instructions=question)}, call_client).values()
            p = float(a.noul)
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
