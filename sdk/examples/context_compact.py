"""Context compaction: one yes/no per exchange, blank the dead ones.

Never rewrites text — only keep or drop. Keeps the verbatim history the model
already saw, so nothing gets reworded into a lie. Threshold-gated; audit log
of what was dropped.
"""

from __future__ import annotations

from jevx.backends import Backend, Live
from jevx.py import feels


def compact(exchanges: list[dict], goal: str, backend: Backend | None = None,
            keep_at: float = 0.5) -> dict:
    """exchanges: [{role, content}]. Returns kept list + drop stats."""
    s1 = (backend or Live()).s1()
    kept, dropped = [], []
    for i, ex in enumerate(exchanges):
        p = feels("is this exchange still needed for the goal?",
                  {"goal": goal, "exchange": ex, "index": i, "total": len(exchanges)},
                  client=s1)
        if float(p) >= keep_at:
            kept.append(ex)
        else:
            dropped.append({"index": i, "prob": float(p), "preview": ex["content"][:120]})
    return {"kept": kept, "dropped": dropped,
            "kept_tokens": sum(len(e["content"]) for e in kept),
            "total_tokens": sum(len(e["content"]) for e in exchanges)}
