"""Class-composed flow: backends as bases via Uses().

Swap Sim(...) for Live() and the same flow runs against real backends —
no signature changes, no client threading. Self-contained: the battery
lives here, not in another example.
"""

from __future__ import annotations

from typing import Literal

from jevx.backends import Backend
from jevx.backends import Sim
from jevx.backends import Uses
from jevx.py import Questions
from jevx.py import ask


class Triage(Questions):
    urgent: bool = ask("reply within the hour?")
    team: Literal["billing", "bug"] = ask("which team owns it?")


_DEMO = Sim(
    s1_script={
        "urgent": [{"type": "noul", "noul": 0.9}],
        "team": [
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


class _Bk(Backend):
    def __init__(self, flow):
        self.flow = flow

    def s1(self):
        return self.flow.make_s1()

    def s2(self):
        return self.flow.make_s2()


class Flow(Uses(_DEMO)):
    """Same run() works under Uses(Live()): swap one base, nothing else."""

    def run(self, ticket: str) -> dict:
        t = Triage(client=self.make_s1()).ask(ticket)
        if t.confidence("team") < 0.6:
            return {"action": "route:human"}
        return {"action": f"route:{t.team}", "urgent": t.urgent}
