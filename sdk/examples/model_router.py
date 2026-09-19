"""Model router with asymmetric bars: cheap to upgrade, expensive to downgrade.

One request: tier Choice + effort Score + risky Noul. Upgrades (spend more)
need confidence 0.3; downgrades need 0.6. risky>0.7 forces deep + effort>=2
and skips the bars. Errors leave the current tier untouched (fail-closed).
"""

from __future__ import annotations

from jevx.backends import Backend
from jevx.backends import Live
from jevx.py import case
from jevx.py import choice
from jevx.py import noul
from jevx.py import score
from jevx.py import vector

TIERS = ("fast", "balanced", "deep")


ROUTE = vector(
    tier=choice("which tier fits this work?", TIERS),
    effort=score("effort required?", ("low", "medium", "high", "xhigh")),
    risky=noul("is this risky, irreversible, or security-sensitive?"),
)


def choose(
    state: str,
    current: str = "balanced",
    backend: Backend | None = None,
    up_at: float = 0.3,
    down_at: float = 0.6,
) -> dict:
    s1 = (backend or Live()).s1()
    try:
        r = ROUTE.ask(state, client=s1)  # 1 request: choice + score + Noul
    except Exception:
        return {"tier": current, "why": "S1 error, fail closed"}
    risky_p = float(r.risky)
    want, conf = r.tier.choice, r.tier.confidence
    ci, wi = TIERS.index(current), TIERS.index(want)
    delta = wi - ci
    return case[
        risky_p > 0.7 : {"tier": "deep", "effort": max(float(r.effort), 2.0), "why": "risky"},
        delta > 0 and conf >= up_at : {"tier": want, "effort": float(r.effort), "why": "upgrade"},
        delta < 0 and conf >= down_at : {
            "tier": want,
            "effort": float(r.effort),
            "why": "downgrade",
        },
        delta == 0 : {"tier": current, "effort": float(r.effort), "why": "stay"},
        ... : {"tier": current, "effort": float(r.effort), "why": "bars not met"},
    ].ask({})
