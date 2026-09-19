"""Fluent task scope: bound backends, typed decisions, and parent-linked history."""

from __future__ import annotations

from collections.abc import Iterator
from collections.abc import Mapping
from collections.abc import Sequence
from contextlib import contextmanager
from typing import Any
from typing import overload

from .answers import ChoiceAnswer
from .backends import Backend
from .backends import Live
from .fx import LiveDriver
from .fx import TraceDriver
from .fx import use
from .py import P
from .py import Predicate
from .py import Questions
from .py import Result
from .py import Rule
from .py import Vector
from .py import _freeze
from .py import pick as _pick
from .questions import JSONContent
from .s2 import System2


class _TrackedS2:
    def __init__(self, owner: TaskRun, inner: System2):
        self.owner = owner
        self.inner = inner

    def ask(self, prompt: str, **kwargs: Any) -> str:
        reply = self.inner.ask(prompt, **kwargs)
        self.owner.record("s2.ask", summary=prompt[:160], prompt=prompt, kwargs=kwargs, reply=reply)
        return reply

    def new_thread(self) -> None:
        self.inner.new_thread()
        self.owner.record("s2.new_thread", summary="started new S2 thread")

    def capabilities(self) -> frozenset[str]:
        return self.inner.capabilities()

    def close(self) -> None:
        close = getattr(self.inner, "close", None)
        if callable(close):
            close()


class TaskRun:
    """One task, one backend pair, and one branching decision history.

    Use ``with task(name, backend) as run``. Questions are typed; control flow
    remains ordinary Python. Branch blocks restore the parent head on exit
    unless ``restore=False`` keeps the selected branch as the active path.
    """

    def __init__(self, name: str, backend: Backend | None = None):
        self.name = name
        self.backend = backend if backend is not None else Live()
        self._s1 = self.backend.s1()
        self.s2 = _TrackedS2(self, self.backend.s2())
        self.history: list[dict[str, Any]] = []
        self.head: int | None = None
        self.record("task", summary=name)

    def __enter__(self) -> TaskRun:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.s2.close()

    def record(self, kind: str, *, summary: str = "", **data: Any) -> int:
        event_id = len(self.history)
        self.history.append(
            {"id": event_id, "parent": self.head, "kind": kind, "summary": summary, **data}
        )
        self.head = event_id
        return event_id

    def context(self, *, limit: int = 8) -> dict[str, Any]:
        if limit < 0:
            raise ValueError("context limit must be non-negative")
        by_id = {event["id"]: event for event in self.history}
        path = []
        current = self.head
        while current is not None:
            event = by_id[current]
            path.append({"id": event["id"], "kind": event["kind"], "summary": event["summary"]})
            current = event["parent"]
        path.reverse()
        selected = path[-limit:] if limit else []
        return {"task": self.name, "head": self.head, "history": selected}

    @contextmanager
    def branch(self, name: str, *, restore: bool = True) -> Iterator[TaskRun]:
        parent = self.head
        self.record("branch", summary=name, branch=name)
        try:
            yield self
        finally:
            if restore:
                self.head = parent

    @overload
    def ask[ResultT](self, battery: type[Questions[ResultT]], state: Any) -> ResultT: ...

    @overload
    def ask[StateT](self, predicate: Predicate[StateT], state: StateT) -> P: ...

    @overload
    def ask(self, battery: Vector, state: Any) -> Result: ...

    @overload
    def ask(self, rule: Rule, state: Any) -> bool: ...

    def ask(self, operation: Any, state: Any) -> Any:
        if isinstance(operation, type) and issubclass(operation, Questions):

            def invoke():
                return operation().ask(state)

            kind = "jev.battery"
            summary = operation.__name__
        elif isinstance(operation, Predicate):

            def invoke():
                return operation.ask(state)

            kind = "jev.predicate"
            summary = "fuzzy judgment expression"
        elif isinstance(operation, Rule):

            def invoke():
                return operation.ask(state)

            kind = "jev.rule"
            summary = "threshold rule"
        elif isinstance(operation, Vector):

            def invoke():
                return operation.ask(state)

            kind = "jev.vector"
            summary = ", ".join(operation.fields)
        else:
            raise TypeError("run.ask() expects a Questions class, Vector, Predicate, or Rule")
        trace = TraceDriver(LiveDriver(self._s1))
        with use(trace):
            result = invoke()
        row = trace.trace[-1]
        self.record(
            kind,
            summary=summary,
            state=row["state"],
            questions=row["questions"],
            answers={key: _freeze(value) for key, value in row["answers"].items()},
        )
        return result

    def pick[ChoiceT: str](
        self,
        question: JSONContent,
        state: Any,
        options: Mapping[ChoiceT, JSONContent | None] | Sequence[ChoiceT],
    ) -> ChoiceAnswer:
        trace = TraceDriver(LiveDriver(self._s1))
        with use(trace):
            result = _pick(question, state, options)
        row = trace.trace[-1]
        self.record(
            "jev.pick",
            summary=(
                f"{question[:80]} -> {result.choice}"
                if isinstance(question, str)
                else f"structured choice -> {result.choice}"
            ),
            state=row["state"],
            questions=row["questions"],
            answers={key: _freeze(value) for key, value in row["answers"].items()},
        )
        return result


def task(name: str, backend: Backend | None = None) -> TaskRun:
    """Create a task-scoped backend and history context manager."""
    return TaskRun(name, backend)
