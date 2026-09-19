"""System 2 backends: organic non-deterministic workers behind a tiny protocol.

System 1 (jevx) decides; System 2 (Codex) does open-ended work. The boundary is
deliberate: every Codex turn is launched, scoped, and verified by Jev judgments.
Swap the backend without touching the algebra: FakeSystem2 replays scripts.
"""

from __future__ import annotations

import inspect
import json
import textwrap
from collections.abc import Callable
from typing import Any
from typing import Protocol
from typing import get_origin
from typing import get_type_hints
from typing import runtime_checkable


@runtime_checkable
class System2(Protocol):
    """Existential backend: callers keep `ask` without knowing Codex vs fake."""

    def ask(self, prompt: str, **kwargs: Any) -> str: ...
    def new_thread(self) -> None: ...
    def capabilities(self) -> frozenset: ...
    def close(self) -> None: ...


class CodexSystem2:
    """Real backend: openai-codex threads. Requires `pip install jevx[codex]`."""

    def __init__(
        self, model: str = "gpt-5.6", sandbox: str = "workspace-write", workdir: str = "."
    ):
        try:
            from openai_codex import Codex  # ty: ignore[unresolved-import]
            from openai_codex import Sandbox  # ty: ignore[unresolved-import]
        except ImportError:
            raise ImportError("pip install jevx[codex]  (needs openai-codex)") from None
        presets = {
            "read-only": Sandbox.read_only,
            "workspace-write": Sandbox.workspace_write,
            "full": Sandbox.full_access,
        }
        self._model = model
        self._sandbox = presets.get(sandbox, Sandbox.workspace_write)
        self._workdir = workdir  # reserved: thread cwd once the SDK exposes it
        self._cx = Codex()
        self._thread = self._cx.thread_start(model=model, sandbox=self._sandbox)

    def new_thread(self) -> None:
        self.close()
        from openai_codex import Codex as _Cx  # ty: ignore[unresolved-import]

        self._cx = _Cx()
        self._thread = self._cx.thread_start(model=self._model, sandbox=self._sandbox)

    def ask(self, prompt: str, **kwargs: Any) -> str:
        return self._thread.run(prompt, **kwargs).final_response

    def capabilities(self) -> frozenset:
        return frozenset({"live", "threads", "sandbox"})

    def close(self) -> None:
        self._cx.close()


class FakeSystem2:
    """Scripted backend for tests/demos. Replies in order; records prompts."""

    def __init__(self, script: list[str] | Callable[[str], str]):
        self.script = script
        self.prompts: list[str] = []
        self.threads = 1

    def new_thread(self) -> None:
        self.threads += 1

    def ask(self, prompt: str, **kwargs: Any) -> str:
        self.prompts.append(prompt)
        if callable(self.script):
            result = self.script(prompt)
            if not isinstance(result, str):
                raise TypeError(f"script callable must return str, got {type(result).__name__}")
            return result
        if not self.script:
            raise AssertionError("FakeSystem2 script exhausted")
        return self.script.pop(0)

    def capabilities(self) -> frozenset:
        return frozenset({"scripted"})

    def close(self) -> None:
        pass


class LazyS2:
    """CodexSystem2 constructed on first ask (import + key needed only then)."""

    def __init__(self, model: str = "gpt-5.6", sandbox: str = "workspace-write"):
        self.model = model
        self.sandbox = sandbox
        self._real: CodexSystem2 | None = None

    def new_thread(self) -> None:
        if self._real is not None:
            self._real.close()
            self._real = None

    def ask(self, prompt: str, **kwargs: Any) -> str:
        if self._real is None:
            self._real = CodexSystem2(model=self.model, sandbox=self.sandbox)
        return self._real.ask(prompt, **kwargs)

    def capabilities(self) -> frozenset:
        if self._real is None:
            return frozenset({"lazy"})
        return self._real.capabilities()

    def close(self) -> None:
        if self._real is not None:
            self._real.close()
            self._real = None


class S2Call:
    def __init__(self, task: S2Task, args: tuple, kwargs: dict):
        self.task = task
        self.args = args
        self.kwargs = kwargs

    def execute(self, state: Any, backend: System2, client: Any = None) -> Any:
        from .py import _evaluate

        bound = self.task.signature.bind(*self.args, **self.kwargs)
        values = {
            name: _evaluate(value, state, client) for name, value in bound.arguments.items()
        }
        prompt = f"{self.task.instructions}\n\nInputs:\n{json.dumps(values, indent=2, default=str)}"
        result = backend.ask(prompt)
        if self.task.returns_json:
            try:
                return json.loads(result)
            except json.JSONDecodeError as error:
                raise ValueError(f"{self.task.name} must return valid JSON: {error}") from error
        return result


class S2Task:
    """Docstring-defined System 2 operation; calling it builds an inert S2Call."""

    def __init__(self, fn: Callable):
        self.fn = fn
        self.name = getattr(fn, "__name__", type(fn).__name__)
        self.signature = inspect.signature(fn)
        self.instructions = textwrap.dedent(inspect.getdoc(fn) or "").strip()
        returns = get_type_hints(fn).get("return", self.signature.return_annotation)
        self.returns_json = get_origin(returns) is dict or returns is dict
        if not self.instructions:
            raise ValueError(f"{self.name} needs a prompt docstring")

    def __call__(self, *args: Any, **kwargs: Any) -> S2Call:
        self.signature.bind(*args, **kwargs)
        return S2Call(self, args, kwargs)


def s2(fn: Callable) -> S2Task:
    """Declare an S2 prompt from a function signature and docstring."""
    return S2Task(fn)
