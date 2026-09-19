"""Inert workflow expressions composed with ``|`` and executed by ``.run()``."""

from __future__ import annotations

import copy
from collections.abc import Callable
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .client import Client
from .py import Select
from .py import _evaluate
from .s2 import LazyS2
from .s2 import S2Call
from .s2 import System2

_MISSING = object()


@dataclass(frozen=True)
class Stop:
    action: Any
    fields: Mapping[str, Any]

    def result(self, state: Any, client: Client | None, s2: System2) -> Any:
        fields = {key: _resolve(value, state, client, s2) for key, value in self.fields.items()}
        return {"action": self.action, **fields}


class _Pass:
    def __call__(self, value: Any) -> Any:
        return value


pass_ = _Pass()


@dataclass(frozen=True)
class Input:
    fields: Mapping[str, Any]

    def resolve(self, supplied: Mapping[str, Any]) -> dict[str, Any]:
        unknown = supplied.keys() - self.fields.keys()
        if unknown:
            raise TypeError(f"unknown flow input(s): {sorted(unknown)}")
        state = {}
        for name, default in self.fields.items():
            if name in supplied:
                state[name] = supplied[name]
            elif isinstance(default, Select) and not default._steps:
                raise TypeError(f"missing required flow input {name!r}")
            else:
                state[name] = copy.deepcopy(default)
        return state


@dataclass(frozen=True)
class Keep:
    fields: Mapping[str, Any]

    def apply(self, state: Any, client: Client | None, s2: System2) -> dict[str, Any]:
        if not isinstance(state, Mapping):
            raise TypeError("keep() needs a mapping as its current value")
        fields = {key: value for key, value in self.fields.items() if not _has_s2(value)}
        out = _evaluate(fields, state, client) if fields else {}
        for key, value in self.fields.items():
            if key not in fields:
                out[key] = _resolve(value, state, client, s2)
        return {**state, **out}


@dataclass(frozen=True)
class When:
    condition: Any
    action: Any

    def apply(self, state: Any, client: Client | None, s2: System2) -> Any:
        condition = _evaluate(self.condition, state, client)
        if not isinstance(condition, bool):
            raise TypeError("when() condition must be a hard rule or bool")
        if not condition:
            return pass_
        if isinstance(self.action, Stop):
            return self.action
        if isinstance(self.action, S2Call):
            return self.action.execute(state, s2, client)
        if callable(getattr(self.action, "ask", None)):
            return self.action.ask(state, client=client)
        return self.action(state) if callable(self.action) else self.action


@dataclass(frozen=True)
class Require:
    value: Any
    fields: tuple[str, ...]
    fallback: Stop

    def apply(self, state: Any, client: Client | None, s2: System2) -> Any:
        value = _evaluate(self.value, state, client)
        if not isinstance(value, Mapping):
            return self.fallback
        if any(name not in value or value[name] is None for name in self.fields):
            return self.fallback
        return pass_


@dataclass(frozen=True)
class Step:
    fn: Callable[[Any], Any]

    def __call__(self, value: Any) -> Any:
        return self.fn(value)

    def __or__(self, other: Any) -> Flow:
        return Flow((self,)) | other

    def __ror__(self, other: Any) -> Flow:
        return Flow((_stage(other), self))


@dataclass(frozen=True)
class Flow:
    """Immutable linear schedule. Construction is inert; ``run`` executes it."""

    stages: tuple[Any, ...]

    def __post_init__(self) -> None:
        if not self.stages:
            raise ValueError("flow needs at least one stage")
        if any(isinstance(stage, Input) for stage in self.stages[1:]):
            raise ValueError("input() must start a flow")

    def __or__(self, other: Any) -> Flow:
        return Flow((*self.stages, _stage(other)))

    def __ror__(self, other: Any) -> Flow:
        return Flow((_stage(other), *self.stages))

    def run(
        self,
        value: Any = _MISSING,
        *,
        client: Client | None = None,
        s2: System2 | None = None,
        backend: Any = None,
        **inputs: Any,
    ) -> Any:
        if backend is not None:
            if client is not None or s2 is not None:
                raise TypeError("pass backend or client/s2, not both")
            client, s2 = backend.s1(), backend.s2()
        if s2 is None:
            s2 = LazyS2()
        if isinstance(self.stages[0], Input):
            if value is not _MISSING:
                raise TypeError("input() flows take named values, not a positional value")
            state = self.stages[0].resolve(inputs)
            stages = self.stages[1:]
        else:
            if value is _MISSING:
                if not inputs:
                    raise TypeError("flow.run() needs an input value")
                value = inputs
            elif inputs:
                raise TypeError("pass either one positional value or named flow inputs")
            state = value
            stages = self.stages

        for stage in stages:
            if stage is pass_:
                continue
            if isinstance(stage, Stop):
                return stage.result(state, client, s2)
            apply = getattr(stage, "apply", None)
            ask = getattr(stage, "ask", None)
            if callable(apply):
                result = apply(state, client, s2)
            elif isinstance(stage, S2Call):
                result = stage.execute(state, s2, client)
            elif callable(ask):
                result = ask(state, client=client)
            elif callable(stage):
                result = stage(state)
            else:
                raise TypeError(f"flow stage must be callable or askable, got {stage!r}")
            if result is pass_:
                continue
            if isinstance(result, Stop):
                return result.result(state, client, s2)
            state = result
        return state

    __call__ = run


def _stage(value: Any) -> Any:
    if (
        callable(value)
        or callable(getattr(value, "ask", None))
        or callable(getattr(value, "apply", None))
        or isinstance(value, S2Call)
        or isinstance(value, Stop)
        or value is pass_
    ):
        return value
    raise TypeError(f"flow stage must be callable or askable, got {value!r}")


def flow(first: Any) -> Flow:
    """Start a flow from an askable expression or one-input Python function."""
    return Flow((_stage(first),))


def step(fn: Callable[[Any], Any]) -> Step:
    """Wrap a one-input Python function so it composes with ``|`` directly."""
    if not callable(fn):
        raise TypeError("step() needs a callable")
    return Step(fn)


def input(**fields: Any) -> Flow:
    """Declare named flow inputs and defaults; a ``j.x`` value is required."""
    return Flow((Input(fields),))


def keep(**fields: Any) -> Keep:
    """Evaluate fields against this record and merge them into the next record."""
    if not fields:
        raise ValueError("keep() needs at least one field")
    return Keep(fields)


def stop(outcome: Any, **fields: Any) -> Stop:
    """Build a terminal value for an ordered case or conditional branch."""
    return Stop(outcome, fields)


def when(condition: Any, action: Any) -> When:
    """Run the selected local action only when a hard rule passes."""
    return When(condition, action)


def require(value: Any, *fields: str, else_: Stop) -> Require:
    """Stop before later nodes when a mapping lacks required non-null fields."""
    if not fields:
        raise ValueError("require() needs at least one field name")
    return Require(value, fields, else_)


def _has_s2(value: Any) -> bool:
    if isinstance(value, S2Call):
        return True
    if isinstance(value, Mapping):
        return any(_has_s2(child) for child in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_s2(child) for child in value)
    return False


def _resolve(value: Any, state: Any, client: Client | None, s2: System2) -> Any:
    if isinstance(value, S2Call):
        return value.execute(state, s2, client)
    if isinstance(value, Mapping):
        return {key: _resolve(child, state, client, s2) for key, child in value.items()}
    if isinstance(value, list):
        return [_resolve(child, state, client, s2) for child in value]
    if isinstance(value, tuple):
        return tuple(_resolve(child, state, client, s2) for child in value)
    return _evaluate(value, state, client)
