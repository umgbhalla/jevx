"""Durable runs: checkpoint after every S2 call, resume without redoing S1.

Monty-style suspension, honestly scoped: Python execution itself isn't
snapshotted — instead the S1 decision log grows monotonically, so resume()
replays judged prefixes for free and only S2 calls from the suspension point
run live. Checkpoint = record-split: one JSONL per S2 call index.
"""

from __future__ import annotations

import glob
import json
import os
from typing import Any

from . import fx as _fx


class Checkpoint:
    """Wrap an S2 worker: log each (prompt -> reply) pair durably."""

    def __init__(self, path: str, inner):
        self.path = path
        self.inner = inner
        self.n = len(glob.glob(f"{path}.*.json"))

    def ask(self, prompt: str, **kwargs: Any) -> str:
        for i in range(self.n):
            with open(f"{self.path}.{i}.json") as fh:
                row = json.load(fh)
            if row["prompt"] == prompt:
                return row["reply"]
        reply = self.inner.ask(prompt, **kwargs)
        with open(f"{self.path}.{self.n}.json", "w") as fh:
            json.dump({"prompt": prompt, "reply": reply}, fh)
        self.n += 1
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
