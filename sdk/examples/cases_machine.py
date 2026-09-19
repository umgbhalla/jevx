"""Small deterministic state machine with one Jev predicate guard.

Run offline with ``uv run python examples/cases_machine.py``.
"""

from __future__ import annotations

from typing import Any

from jevx.fx import ScriptDriver
from jevx.fx import TraceDriver
from jevx.fx import use
from jevx.programs import cases
from jevx.py import noul


def advance(state: dict[str, Any]) -> dict[str, Any]:
    """First matching code rule wins; the Jev guard is one lazy Noul leaf."""
    return cases(
        state,
        (
            lambda s: s["attempt"] >= s["max_attempts"],
            lambda s: {**s, "phase": "ESCALATE", "reason": "attempt limit"},
        ),
        (
            noul("is the verified result safe to finish?"),
            lambda s: {**s, "phase": "DONE", "reason": "verified safe"},
        ),
        (
            "else",
            lambda s: {**s, "phase": "RETRY", "attempt": s["attempt"] + 1},
        ),
    )


def demo() -> list[dict[str, Any]]:
    driver = TraceDriver(
        ScriptDriver(
            {
                "q0": [
                    {"type": "noul", "noul": 0.9},
                    {"type": "noul", "noul": 0.2},
                ]
            }
        )
    )
    states = []
    with use(driver):
        states.append(advance({"phase": "VERIFY", "attempt": 0, "max_attempts": 3}))
        states.append(advance({"phase": "VERIFY", "attempt": 3, "max_attempts": 3}))
    assert [s["phase"] for s in states] == ["DONE", "ESCALATE"]
    assert len(driver.trace) == 1  # attempt-limit branch needs no Jev request
    assert states[0]["reason"] == "verified safe"
    return states


if __name__ == "__main__":
    for state in demo():
        print(state)
