"""Durable runs: checkpoint every S2 call, resume without redoing S1.

Honestly scoped: Python execution itself isn't snapshotted. Instead the S2
call journal grows monotonically, so a resumed run replays answered prefixes
for free and only new calls go live. Positional AND content-checked: row k
must equal (prompt, kwargs) or Divergence raises instead of serving stale text.
"""

from __future__ import annotations

import json
import os
from typing import Any


class Divergence(Exception):
    pass


class Checkpoint:
    """Wrap an S2 worker: log each (prompt, kwargs, reply) to one JSONL journal."""

    def __init__(self, path: str, inner):
        self.journal = f"{path}.jsonl" if not path.endswith(".jsonl") else path
        self.inner = inner
        self._pos = 0
        if os.path.exists(self.journal):
            with open(self.journal) as fh:
                self._rows = [json.loads(line) for line in fh if line.strip()]
        else:
            self._rows = []

    def ask(self, prompt: str, **kwargs: Any) -> str:
        if self._pos < len(self._rows):
            row = self._rows[self._pos]
            if row.get("prompt") != prompt or row.get("kwargs", {}) != kwargs:
                raise Divergence(f"checkpoint diverged at call {self._pos}")
            self._pos += 1
            return row["reply"]
        reply = self.inner.ask(prompt, **kwargs)
        row = {"prompt": prompt, "kwargs": kwargs, "reply": reply}
        tmp = f"{self.journal}.{os.getpid()}.tmp"
        with open(tmp, "w") as fh:
            json.dump(row, fh)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        with open(self.journal, "a") as fh:
            with open(tmp) as src:
                fh.write(src.read())
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.remove(tmp)
        except OSError:
            pass
        self._rows.append(row)
        self._pos += 1
        return reply

    def new_thread(self) -> None:
        self.inner.new_thread()


def checkpointed(path: str, backend):
    """Clone a backend with a Checkpoint-wrapped S2. S1 untouched (replayable)."""
    from .backends import Backend

    class _B(Backend):
        def s1(_self):
            return backend.s1()

        def s2(_self):
            return Checkpoint(path, backend.s2())

    return _B()
