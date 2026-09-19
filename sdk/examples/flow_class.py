"""Class-composed flow: backends as bases via Uses().

Swap Sim(...) for Live() and the same flow runs against real backends —
no signature changes, no client threading.
"""

from __future__ import annotations

from jevx.backends import Backend, Sim, Uses
from examples.support_copilot import handle


class _SimBackend(Backend):
    def __init__(self, flow):
        self.flow = flow

    def s1(self):
        return self.flow.make_s1()

    def s2(self):
        return self.flow.make_s2()


_DEMO = Sim(
    s1_script={
        "urgent": [{"type": "noul", "noul": 0.9}],
        "team": [{"type": "choice", "choice": "billing",
                  "probabilities": {"billing": 0.95, "x": 0.05}, "confidence": 0.95}],
        "autoreply_ok": [{"type": "noul", "noul": 0.9}],
    },
    s2_texts=[],
)


class Flow(Uses(_DEMO)):
    def run(self, ticket: str) -> dict:
        return handle(ticket, backend=_SimBackend(self))
