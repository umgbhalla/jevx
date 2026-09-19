"""Effect drivers + coroutine interpreter: one Ask stream, many interpreters.

    from jevx.fx import Ask, run, LiveDriver, ReplayDriver, ScriptDriver

    async def flow(ticket):
        answers = await Ask({"triage": Noul("urgent?")}, state=ticket)
        ...

    run(LiveDriver(), flow("..."))     # real API
    run(ReplayDriver("run.jsonl"), flow("..."))  # offline replay, zero network

Drivers also transform (poutine discipline): condition() overrides answers,
trace() records them in memory.
"""

from __future__ import annotations

import contextvars
import json
from typing import Any

from .answers import parse_answer
from .client import Client, Response

_stack: contextvars.ContextVar = contextvars.ContextVar("jevx_drivers", default=())


class Ask:
    """An effect instruction: judge `questions` against `state`. Await it inside
    run(); the driver answers. Never construct answers yourself."""

    def __init__(self, questions: dict, state: Any = ""):
        self.questions = questions
        self.state = state

    def __await__(self):
        answers = yield self
        return answers


def run(driver: "Driver", coro):
    """Drive a coroutine to completion, answering every Ask via driver."""
    value = None
    while True:
        try:
            yielded = coro.send(value)
        except StopIteration as e:
            return e.value
        if not isinstance(yielded, Ask):
            raise TypeError(f"flow yielded {type(yielded).__name__}, only Ask allowed")
        payload = {k: (v.to_json() if hasattr(v, "to_json") else v)
                   for k, v in yielded.questions.items()}
        value = driver.answer(yielded.state, payload)


class Driver:
    def answer(self, state: Any, questions: dict) -> dict[str, Any]:
        raise NotImplementedError


class LiveDriver(Driver):
    def __init__(self, client: Client | None = None):
        self.client = client

    def answer(self, state: Any, questions: dict) -> dict[str, Any]:
        resp = (self.client or Client()).system_one(state, questions)
        return dict(resp.answers)


class ScriptDriver(Driver):
    """qid -> queue of raw answer dicts. Exhaustion raises loudly."""

    def __init__(self, script: dict[str, list[dict]]):
        self.script = {k: list(v) for k, v in script.items()}
        self.calls: list = []

    def answer(self, state: Any, questions: dict) -> dict[str, Any]:
        self.calls.append(sorted(questions))
        out = {}
        for k in questions:
            try:
                out[k] = parse_answer(k, self.script[k].pop(0))
            except (KeyError, IndexError):
                raise AssertionError(f"ScriptDriver: no answer left for {k!r}") from None
        return out


class ReplayDriver(Driver):
    """Serve a JSONL log in order; sha mismatch -> StaleReplay."""

    def __init__(self, path: str):
        from .py import StaleReplay, _sha
        self._StaleReplay = StaleReplay
        self._sha = _sha
        self.rows = [json.loads(l) for l in open(path) if l.strip()]
        self.n = 0

    def answer(self, state: Any, questions: dict) -> dict[str, Any]:
        if self.n >= len(self.rows):
            raise self._StaleReplay("replay log exhausted")
        row = self.rows[self.n]
        self.n += 1
        if row["sha"] != self._sha(state, questions):
            raise self._StaleReplay(f"question mismatch at step {self.n}")
        return {k: parse_answer(k, v) for k, v in row["answers"].items()}


class RecordDriver(Driver):
    """Delegate to inner driver, append every decision as JSONL."""

    def __init__(self, path: str, inner: Driver | None = None):
        from .py import _freeze, _sha
        self._freeze, self._sha = _freeze, _sha
        self.path = path
        self.inner = inner or LiveDriver()

    def answer(self, state: Any, questions: dict) -> dict[str, Any]:
        out = self.inner.answer(state, questions)
        with open(self.path, "a") as fh:
            fh.write(json.dumps({
                "sha": self._sha(state, questions), "state": state,
                "questions": questions,
                "answers": {k: self._freeze(v) for k, v in out.items()},
            }, default=str) + "\n")
        return out


class ConditionDriver(Driver):
    """Override selected answers (poutine.condition): {(qid): raw-answer}."""

    def __init__(self, overrides: dict[str, dict], inner: Driver):
        self.overrides = overrides
        self.inner = inner

    def answer(self, state: Any, questions: dict) -> dict[str, Any]:
        out = self.inner.answer(state, questions)
        for k, raw in self.overrides.items():
            if k in out:
                out[k] = parse_answer(k, raw)
        return out


class TraceDriver(Driver):
    """Record every (state, questions, answers) in memory (poutine.trace)."""

    def __init__(self, inner: Driver):
        self.inner = inner
        self.trace: list = []

    def answer(self, state: Any, questions: dict) -> dict[str, Any]:
        out = self.inner.answer(state, questions)
        self.trace.append({"state": state, "questions": questions, "answers": out})
        return out


def use(driver: Driver):
    """Push a driver for sync _decide calls. Inner-most wins."""

    class _Ctx:
        def __enter__(self):
            self._tok = _stack.set(_stack.get() + (driver,))
            return driver

        def __exit__(self, *exc):
            _stack.reset(self._tok)

    return _Ctx()


def current() -> Driver | None:
    stack = _stack.get()
    return stack[-1] if stack else None
