"""Context compaction: one yes/no per exchange, blank the dead ones.

Never rewrites text — only keep or drop. Keeps the verbatim history the model
already saw, so nothing gets reworded into a lie. Threshold-gated; audit log
of what was dropped.
"""

from __future__ import annotations

from typing import Any

from jevx.backends import Backend
from jevx.backends import Live
from jevx.contracts import ensure
from jevx.relational import Table


@ensure(
    lambda *a, result=None, **k: len(result["kept"]) + len(result["dropped"]) == len(a[0]),
    msg="keep+drop covers all",
)
def compact(
    exchanges: list[dict], goal: str, backend: Backend | None = None, keep_at: float = 0.5
) -> dict:
    """exchanges: [{role, content}]. Returns kept list + drop stats."""
    s1 = (backend or Live()).s1()
    rows: list[dict[str, Any]] = [
        {"index": i, "exchange": exchange} for i, exchange in enumerate(exchanges)
    ]
    scores = Table(rows, client=s1, context={"goal": goal, "total": len(rows)}).noul(
        {"question": "Is this exchange still needed to complete the goal?"},
        true={"what": "The exchange contains information needed for a correct next action."},
        false={"what": "The exchange is stale or irrelevant to the current goal."},
    )
    kept_mask = [p >= keep_at for p in scores]
    kept = [row["exchange"] for row, keep in zip(rows, kept_mask, strict=True) if keep]
    dropped = [
        {"index": row["index"], "prob": float(p), "preview": row["exchange"]["content"][:120]}
        for row, p, keep in zip(rows, scores, kept_mask, strict=True)
        if not keep
    ]
    return {
        "kept": kept,
        "dropped": dropped,
        "kept_tokens": sum(len(e["content"]) for e in kept),
        "total_tokens": sum(len(e["content"]) for e in exchanges),
    }
