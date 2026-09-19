"""Model router with asymmetric bars: cheap to upgrade, expensive to downgrade.

One request: tier Choice + effort Score + risky Noul. Upgrades (spend more)
need confidence 0.3; downgrades need 0.6. risky>0.7 forces deep + effort>=2
and skips the bars. Errors leave the current tier untouched (fail-closed).
"""

from __future__ import annotations

import jevx as j
from jevx.backends import Backend
from jevx.backends import Live

x = j.x

TIERS = ("fast", "balanced", "deep")


ROUTE = j.vector(
    tier=j.choice("Which tier fits this work?", TIERS),
    effort=j.score("Effort required?", ("low", "medium", "high", "xhigh")),
    risky=j.noul("Is this risky, irreversible, or security-sensitive?"),
)


def _delta(current: str, wanted: str) -> int:
    return TIERS.index(wanted) - TIERS.index(current)


POLICY = (
    j.input(state=x, current="balanced", up_at=0.3, down_at=0.6)
    | j.keep(route=ROUTE.on(x.state))
    | j.keep(delta=j.compute(_delta, x.current, x.route.tier.choice))
    | j.case[
        x.route.risky > 0.7:
            j.stop("ROUTE", tier="deep", effort=j.max(x.route.effort, 2.0), why="risky"),
        (x.delta > 0) & (x.route.tier.confidence >= x.up_at):
            j.stop("ROUTE", tier=x.route.tier.choice, effort=x.route.effort, why="upgrade"),
        (x.delta < 0) & (x.route.tier.confidence >= x.down_at):
            j.stop("ROUTE", tier=x.route.tier.choice, effort=x.route.effort, why="downgrade"),
        x.delta == 0:
            j.stop("ROUTE", tier=x.current, effort=x.route.effort, why="stay"),
        ...:
            j.stop("ROUTE", tier=x.current, effort=x.route.effort, why="bars not met"),
    ]
)


def choose(
    state: str,
    current: str = "balanced",
    backend: Backend | None = None,
    up_at: float = 0.3,
    down_at: float = 0.6,
) -> dict:
    try:
        result = POLICY.run(
            state=state,
            current=current,
            up_at=up_at,
            down_at=down_at,
            backend=backend or Live(),
        )
    except Exception:
        return {"tier": current, "why": "S1 error, fail closed"}
    return {key: value for key, value in result.items() if key != "action"}
