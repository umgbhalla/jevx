"""Effect drivers + coroutine interpreter: one Ask stream, many interpreters.

    from jevx.fx import Ask, run, LiveDriver, ReplayDriver, ScriptDriver

    async def flow(ticket):
        answers = await Ask({"triage": Noul(instructions="urgent?")}, state=ticket)
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
from .client import Client
from .questions import to_json

_stack: contextvars.ContextVar = contextvars.ContextVar("jevx_drivers", default=())


class Ask:
    """An effect instruction: judge `questions` against `state`. Await it inside
    run(); the driver answers. Never construct answers yourself."""

    def __init__(self, questions: dict, state: Any = ""):
        if not isinstance(questions, dict) or not questions:
            raise ValueError("Ask needs a non-empty questions dict")
        if not all(isinstance(k, str) for k in questions):
            raise ValueError("Ask question ids must be strings")
        self.questions = questions
        self.state = state

    def __await__(self):
        answers = yield self
        return answers


def run(driver: Driver, coro):
    """Drive a coroutine to completion, answering every Ask via driver.

    Driver errors are thrown back into the flow (try/finally honored);
    the coroutine is always closed. The driver is published on the stack
    so nested sync _decide calls see it.
    """
    tok = _stack.set(_stack.get() + (driver,))
    value = None
    try:
        while True:
            try:
                yielded = coro.send(value)
            except StopIteration as e:
                return e.value
            if not isinstance(yielded, Ask):
                raise TypeError(f"flow yielded {type(yielded).__name__}, only Ask allowed")
            payload = {k: to_json(v) for k, v in yielded.questions.items()}
            try:
                value = driver.answer(yielded.state, payload)
            except BaseException as e:
                try:
                    yielded = coro.throw(e)
                except StopIteration as se:
                    return se.value
                payload = {k: to_json(v) for k, v in yielded.questions.items()}
                value = driver.answer(yielded.state, payload)
    finally:
        _stack.reset(tok)
        close = getattr(coro, "close", None)
        if callable(close):
            close()


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
        from .py import StaleReplay
        from .py import _sha

        self._StaleReplay = StaleReplay
        self._sha = _sha
        with open(path) as fh:
            self.rows = [json.loads(line) for line in fh if line.strip()]
        self.n = 0

    def answer(self, state: Any, questions: dict) -> dict[str, Any]:
        if self.n >= len(self.rows):
            raise self._StaleReplay("replay log exhausted")
        row = self.rows[self.n]
        for field in ("sha", "answers"):
            if field not in row:
                raise self._StaleReplay(f"replay row {self.n} missing {field!r}")
        if row["sha"] != self._sha(state, questions):
            raise self._StaleReplay(f"question mismatch at step {self.n}")
        self.n += 1
        try:
            return {k: parse_answer(k, v) for k, v in row["answers"].items()}
        except (KeyError, TypeError, ValueError) as e:
            raise self._StaleReplay(f"replay row {self.n - 1} malformed: {e}") from e


class RecordDriver(Driver):
    """Delegate to inner driver, append every decision as JSONL."""

    def __init__(self, path: str, inner: Driver | None = None):
        import threading as _t

        from .py import _freeze
        from .py import _sha

        self._freeze, self._sha = _freeze, _sha
        self.path = path
        self.inner = inner or LiveDriver()
        self._lock = _t.Lock()

    def answer(self, state: Any, questions: dict) -> dict[str, Any]:
        out = self.inner.answer(state, questions)
        line = (
            json.dumps(
                {
                    "sha": self._sha(state, questions),
                    "state": state,
                    "questions": questions,
                    "answers": {k: self._freeze(v) for k, v in out.items()},
                },
                default=str,
                sort_keys=True,
            )
            + "\n"
        )
        with self._lock, open(self.path, "a") as fh:
            fh.write(line)
            fh.flush()
        return out


class ConditionDriver(Driver):
    """Override selected answers (poutine.condition): {(qid): raw-answer}."""

    def __init__(self, overrides: dict[str, dict], inner: Driver):
        self.overrides = overrides
        self.inner = inner

    def answer(self, state: Any, questions: dict) -> dict[str, Any]:
        out = self.inner.answer(state, questions)
        unknown = [k for k in self.overrides if k not in questions]
        if unknown:
            raise KeyError(f"ConditionDriver: override for unknown question(s) {unknown}")
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
        import copy as _copy

        out = self.inner.answer(state, questions)
        self.trace.append(
            {
                "state": _copy.deepcopy(state),
                "questions": _copy.deepcopy(questions),
                "answers": _copy.deepcopy(out),
            }
        )
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
