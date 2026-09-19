"""Model router with asymmetric bars: cheap to upgrade, expensive to downgrade.

One request: tier Choice + effort Score + risky Noul. Upgrades (spend more)
need confidence 0.3; downgrades need 0.6. risky>0.7 forces deep + effort>=2
and skips the bars. Errors leave the current tier untouched (fail-closed).
"""

from __future__ import annotations

from typing import Literal

from jevx.backends import Backend
from jevx.backends import Live
from jevx.py import Questions
from jevx.py import Score
from jevx.py import ask

TIERS = ("fast", "balanced", "deep")


class RouteQ(Questions):
    tier: Literal["fast", "balanced", "deep"] = ask("which tier fits this work?")
    effort: Score[Literal["low", "medium", "high", "xhigh"]] = ask("effort required?")
    risky: bool = ask("is this risky, irreversible, or security-sensitive?")


def choose(
    state: str,
    current: str = "balanced",
    backend: Backend | None = None,
    up_at: float = 0.3,
    down_at: float = 0.6,
) -> dict:
    s1 = (backend or Live()).s1()
    try:
        r = RouteQ(client=s1).ask(state)  # 1 request
    except Exception:
        return {"tier": current, "why": "S1 error, fail closed"}
    risky_p = float(r.answers["risky"].prob)
    want, conf = r.tier, r.confidence("tier") or 0.0
    ci, wi = TIERS.index(current), TIERS.index(want)
    delta = wi - ci
    match (risky_p > 0.7, delta, conf):
        case (True, _, _):
            return {"tier": "deep", "effort": max(float(r.effort), 2.0), "why": "risky"}
        case (False, change, confidence) if change > 0 and confidence >= up_at:
            return {"tier": want, "effort": float(r.effort), "why": "upgrade"}
        case (False, change, confidence) if change < 0 and confidence >= down_at:
            return {"tier": want, "effort": float(r.effort), "why": "downgrade"}
        case (False, 0, _):
            return {"tier": current, "effort": float(r.effort), "why": "stay"}
        case _:
            return {"tier": current, "effort": float(r.effort), "why": "bars not met"}
