"""Streaming snapshots: accumulate S2 text chunks into validated structures.

Partial[T]-style discipline in stdlib: feed chunks, read the best-effort
snapshot any time, validate only when complete. Never act on a partial.
"""

from __future__ import annotations

import json


class Partial:
    """Accumulates text; snapshot() repairs + parses best-effort, done() validates."""

    def __init__(self):
        self.chunks: list[str] = []
        self._done = False

    def feed(self, chunk: str) -> None:
        if self._done:
            raise ValueError("Partial already done")
        self.chunks.append(chunk)

    @property
    def text(self) -> str:
        return "".join(self.chunks)

    def snapshot(self) -> dict | None:
        """Best-effort parse of the prefix so far; None if nothing parses."""
        txt = self.text.strip()
        for end in (txt, _truncate(txt)):
            try:
                v = json.loads(end)
                return v if isinstance(v, dict) else {"value": v}
            except ValueError:
                continue
        return None

    def done(self, required: tuple = ()) -> dict:
        """Mark complete; raise unless all required keys present with values."""
        self._done = True
        snap = self.snapshot()
        if not isinstance(snap, dict):
            raise ValueError("stream never formed an object")
        missing = [k for k in required if not snap.get(k)]
        if missing:
            raise ValueError(f"incomplete: missing {missing}")
        return snap


def _truncate(txt: str) -> str:
    """Close open braces/brackets/quotes greedily for prefix parsing."""
    depth, instr, esc = 0, False, False
    cut = len(txt)
    for i, ch in enumerate(txt):
        if esc:
            esc = False
            continue
        if ch == "\\" and instr:
            esc = True
            continue
        if ch == '"':
            instr = not instr
        elif not instr and ch in "{[":
            depth += 1
        elif not instr and ch in "}]":
            depth -= 1
    if instr:
        cut = txt.rfind('"')
    s = txt[:cut] + ('"' if instr else "")
    s += "}" * max(depth, 0)
    return s
