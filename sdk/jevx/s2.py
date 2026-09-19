"""System 2 backends: organic non-deterministic workers behind a tiny protocol.

System 1 (jevx) decides; System 2 (Codex) does open-ended work. The boundary is
deliberate: every Codex turn is launched, scoped, and verified by Jev judgments.
Swap the backend without touching the algebra: FakeSystem2 replays scripts.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol


class System2(Protocol):
    def ask(self, prompt: str, **kwargs: Any) -> str: ...
    def new_thread(self) -> None: ...


class CodexSystem2:
    """Real backend: openai-codex threads. Requires `pip install jevx[codex]`."""

    def __init__(self, model: str = "gpt-5.6", sandbox: str = "workspace-write", workdir: str = "."):
        try:
            from openai_codex import Codex, Sandbox
        except ImportError:
            raise ImportError("pip install jevx[codex]  (needs openai-codex)") from None
        presets = {
            "read-only": Sandbox.read_only,
            "workspace-write": Sandbox.workspace_write,
            "full": Sandbox.full_access,
        }
        self._cx = Codex()
        self._thread = self._cx.thread_start(
            model=model, sandbox=presets.get(sandbox, Sandbox.workspace_write),
        )
        self._workdir = workdir

    def new_thread(self) -> None:
        raise NotImplementedError("create a new CodexSystem2 for a fresh thread")

    def ask(self, prompt: str, **kwargs: Any) -> str:
        return self._thread.run(prompt, **kwargs).final_response

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
            return self.script(prompt)
        if not self.script:
            raise AssertionError("FakeSystem2 script exhausted")
        return self.script.pop(0)
