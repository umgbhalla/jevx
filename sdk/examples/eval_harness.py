"""Eval harness: accuracy + calibration + latency for any router/gate.

Runs a gold set through a decide() function, then reports accuracy, expected
calibration error over confidence bins, latency stats, and $ estimate.
Stdlib-only; the harness routers ship without one.
"""

from __future__ import annotations

import time

from jevx.backends import Backend
from jevx.contracts import ensure


@ensure(lambda *a, result=None, **k: 0.0 <= result["accuracy"] <= 1.0, msg="accuracy in range")
def evaluate(
    decide,
    gold: list[dict],
    backend: Backend | None = None,
    bins: int = 5,
    price_per_mtok: float = 0.042,
) -> dict:
    """decide(case, backend) -> {"pick": str, "confidence": float}.
    gold: [{..., "label": str, "input_tokens": int}]."""
    rows, lat = [], []
    for case in gold:
        t0 = time.perf_counter()
        try:
            out = decide(case, backend)
        except Exception as e:
            rows.append({"label": case["label"], "pick": None, "confidence": 0.0, "error": str(e)})
            continue
        lat.append(time.perf_counter() - t0)
        rows.append(
            {
                "label": case["label"],
                "pick": out.get("pick"),
                "confidence": float(out.get("confidence", 0.0)),
            }
        )
    ok = [r for r in rows if r["pick"] is not None]
    acc = sum(1 for r in ok if r["pick"] == r["label"]) / max(len(ok), 1)
    ece, counts = 0.0, [0] * bins
    for r in ok:
        b = min(int(r["confidence"] * bins), bins - 1)
        counts[b] += 1
    for b in range(bins):
        members = [r for r in ok if min(int(r["confidence"] * bins), bins - 1) == b]
        if not members:
            continue
        ece += (
            abs(
                sum(1 for r in members if r["pick"] == r["label"]) / len(members)
                - sum(r["confidence"] for r in members) / len(members)
            )
            * len(members)
            / len(ok)
        )
    toks = sum(c.get("input_tokens", 0) for c in gold)
    lat_sorted = sorted(lat)
    return {
        "accuracy": acc,
        "ece": ece,
        "n": len(rows),
        "errors": len(rows) - len(ok),
        "latency": {
            "p50": lat_sorted[len(lat_sorted) // 2] if lat_sorted else 0.0,
            "max": max(lat_sorted) if lat_sorted else 0.0,
        },
        "est_usd": toks / 1e6 * price_per_mtok,
        "bins": counts,
    }
