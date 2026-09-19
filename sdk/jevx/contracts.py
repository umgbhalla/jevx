"""Runtime contracts for gates and policies. Cheap, explicit, no dependency.

@require checks arguments, @ensure checks the return. Predicates get the
same args as the function (require) or (args..., result) for ensure.
Violation raises ContractError naming the function and clause.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any


class ContractError(AssertionError):
    pass


def require(pred: Callable[..., bool], msg: str):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any):
            if not pred(*args, **kwargs):
                raise ContractError(f"{fn.__name__} requires {msg}")
            return fn(*args, **kwargs)

        return wrapper

    return deco


def ensure(pred: Callable[..., bool], msg: str):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any):
            result = fn(*args, **kwargs)
            if not pred(*args, result=result, **kwargs):
                raise ContractError(f"{fn.__name__} ensures {msg}")
            return result

        return wrapper

    return deco


def prob(x: Any) -> bool:
    return isinstance(x, (int, float)) and 0.0 <= x <= 1.0


def within(lo: float, hi: float):
    """Value-equation predicate: lo <= x <= hi (jaxtyping-style, runtime)."""
    return lambda x: lo <= x <= hi


def clamped(lo: float, hi: float):
    return lambda x: max(lo, min(hi, x))


def action_in(*actions: str):
    return lambda *a, result=None, **k: result in actions
