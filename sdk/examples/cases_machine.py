"""Small machine combining lazy algebraic guards with Python match cases.

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
    """Batch the guard expression, then map its confidence band with match."""
    capped = cases(
        state,
        (lambda s: s["attempt"] >= s["max_attempts"], lambda s: True),
        ("else", lambda s: False),
    )
    if capped:
        return {**state, "phase": "ESCALATE", "reason": "attempt limit"}

    safety = (
        noul("is the verified result safe to finish?")
        & ~noul("does the result expose a remaining risk?")
    ).ask(state)
    match safety.band(review_at=0.35, act_at=0.75):
        case "yes":
            return {**state, "phase": "DONE", "reason": "verified safe"}
        case "review":
            return {**state, "phase": "REVIEW", "reason": "uncertain safety"}
        case "no":
            return {**state, "phase": "RETRY", "attempt": state["attempt"] + 1}
        case unexpected:
            raise AssertionError(f"unexpected safety band: {unexpected}")


def demo() -> list[dict[str, Any]]:
    driver = TraceDriver(
        ScriptDriver(
            {
                "q0": [
                    {"type": "noul", "noul": 0.99},
                    {"type": "noul", "noul": 0.8},
                ],
                "q1": [
                    {"type": "noul", "noul": 0.05},
                    {"type": "noul", "noul": 0.4},
                ],
            }
        )
    )
    states = []
    with use(driver):
        states.append(advance({"phase": "VERIFY", "attempt": 0, "max_attempts": 3}))
        states.append(advance({"phase": "VERIFY", "attempt": 1, "max_attempts": 3}))
        states.append(advance({"phase": "VERIFY", "attempt": 3, "max_attempts": 3}))
    assert [s["phase"] for s in states] == ["DONE", "REVIEW", "ESCALATE"]
    assert len(driver.trace) == 2  # cap branch makes no request
    assert all(set(row["questions"]) == {"q0", "q1"} for row in driver.trace)
    assert states[0]["reason"] == "verified safe"
    return states


if __name__ == "__main__":
    for state in demo():
        print(state)
