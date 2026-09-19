"""Indexed handoffs: the computation records its state transition.

Ix[I, O, A]: run with I, produce A, land in O. ``>>`` joins indexed stages:
the left stage's output label must match the right stage's input label. A
wrong handoff raises TypeError when the pipeline is built.

    flow = start("ticket", "judged", judge) >> classify
    outcome, state = flow(ticket)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Ix[I, O, A]:
    needs: str
    leaves: str
    run: Callable[[Any], tuple[Any, Any]]

    def bind[N, B](self, nxt: IxStage) -> Ix[I, N, B]:
        if not isinstance(nxt, IxStage):
            raise TypeError("bind() needs an IxStage built by stage()")
        if nxt.needs != self.leaves:
            raise TypeError(f"cannot sequence {self.leaves!r} -> {nxt.needs!r}")
        inner = self

        def run(state: Any) -> tuple[Any, Any]:
            value, mid = inner.run(state)
            return nxt.run(mid, value)

        return Ix(inner.needs, nxt.leaves, run)

    def __rshift__[N, B](self, nxt: IxStage) -> Ix[I, N, B]:
        """Pipe into a stage whose input name matches this stage's output."""
        return self.bind(nxt)

    def __call__(self, state: Any) -> tuple[Any, Any]:
        return self.run(state)


@dataclass(frozen=True)
class IxStage:
    needs: str
    leaves: str
    fn: Callable[[Any, Any], tuple[Any, Any]]

    def run(self, state: Any, value: Any) -> tuple[Any, Any]:
        return self.fn(state, value)


def stage(needs: str, leaves: str):
    """@stage("ticket", "draft") def write(state, value): ..."""

    def deco(fn: Callable[[Any, Any], tuple[Any, Any]]) -> IxStage:
        return IxStage(needs, leaves, fn)

    return deco


def start(needs: str, leaves: str, fn: Callable[[Any], tuple[Any, Any]]) -> Ix:
    return Ix(needs, leaves, fn)
