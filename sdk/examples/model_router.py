"""Model router with asymmetric bars: cheap to upgrade, expensive to downgrade.

One request: tier Choice + effort Score + risky Noul. Upgrades (spend more)
need confidence 0.3; downgrades need 0.6. risky>0.7 forces deep + effort>=2
and skips the bars. Errors leave the current tier untouched (fail-closed).
"""

from __future__ import annotations

from typing import Literal

from jevx.client import Client
from jevx.py import Questions, Score, ask

TIERS = ("fast", "balanced", "deep")


class RouteQ(Questions):
    tier: Literal["fast", "balanced", "deep"] = ask("which tier fits this work?")
    effort: Score["low", "medium", "high", "xhigh"] = ask("effort required?")
    risky: bool = ask("is this risky, irreversible, or security-sensitive?", threshold=0.70)


def choose(state: str, current: str = "balanced", s1: Client | None = None,
           up_at: float = 0.3, down_at: float = 0.6) -> dict:
    try:
        r = RouteQ(client=s1)(state)  # 1 request
    except Exception:
        return {"tier": current, "why": "S1 error, fail closed"}
    if r.risky:
        return {"tier": "deep", "effort": max(float(r.effort), 2.0), "why": "risky"}
    want, conf = r.tier, r.confidence("tier") or 0.0
    ci, wi = TIERS.index(current), TIERS.index(want)
    if wi > ci and conf >= up_at:
        return {"tier": want, "effort": float(r.effort), "why": "upgrade"}
    if wi < ci and conf >= down_at:
        return {"tier": want, "effort": float(r.effort), "why": "downgrade"}
    if wi == ci:
        return {"tier": current, "effort": float(r.effort), "why": "stay"}
    return {"tier": current, "effort": float(r.effort), "why": "bars not met"}
