"""Class-composed flow: backends as bases via Uses().

Swap Sim(...) for Live() and the same flow runs against real backends —
no client threading. A vector batches the related judgments.
"""

from __future__ import annotations

import jevx as j
from jevx.backends import Sim
from jevx.backends import Uses

TRIAGE = j.vector(
    urgent=j.noul("Reply within the hour?") >= 0.5,
    team=j.choice("Which team owns this ticket?", ("billing", "bug")),
)


_DEMO = Sim(
    s1_script={
        "q0": [{"type": "noul", "noul": 0.9}],
        "q1": [
            {
                "type": "choice",
                "choice": "billing",
                "probabilities": {"billing": 0.95, "bug": 0.05},
                "confidence": 0.95,
            }
        ],
    },
    s2_texts=[],
)


class Flow(Uses(_DEMO)):
    """Same run() works under Uses(Live()): swap one base, nothing else."""

    def run(self, ticket: str) -> dict:
        t = TRIAGE.ask(ticket, client=self.make_s1())
        return j.case[
            t.team.confidence >= 0.6:
                {"action": f"route:{t.team.choice}", "urgent": t.urgent},
            ...: {"action": "route:human"},
        ].ask({})
