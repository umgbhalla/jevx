"""Small machine with lazy algebraic guards and ordered expression cases.

Run offline with ``uv run python examples/cases_machine.py``.
"""

from __future__ import annotations

import argparse
from typing import Any

from jevx.fx import ScriptDriver
from jevx.fx import TraceDriver
from jevx.fx import use
from jevx.py import case
from jevx.py import noul


def advance(state: dict[str, Any]) -> dict[str, Any]:
    """Batch the guard expression, then select the first matching transition."""
    if state["attempt"] >= state["max_attempts"]:
        return {**state, "phase": "ESCALATE", "reason": "attempt limit"}

    safety = noul("is the verified result safe to finish?") * ~noul(
        "does the result expose a remaining risk?"
    )
    transition = case[
        safety >= 0.75 : {"phase": "DONE", "reason": "verified safe"},
        safety < 0.35 : {"phase": "RETRY", "attempt": state["attempt"] + 1},
        ... : {"phase": "REVIEW", "reason": "uncertain safety"},
    ].ask(state)
    return {**state, **transition}


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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="use the live TypeSafe API")
    args = parser.parse_args()
    states = (
        [
            advance(
                {
                    "phase": "VERIFY",
                    "attempt": 0,
                    "max_attempts": 3,
                    "result": "A completed change with passing checks and no private data.",
                }
            )
        ]
        if args.live
        else demo()
    )
    for state in states:
        print(state)
