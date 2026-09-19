"""Small machine with lazy algebraic guards and ordered expression cases.

Run offline with ``uv run python examples/cases_machine.py``.
"""

from __future__ import annotations

import argparse
from typing import Any

import jevx as j
from jevx.fx import ScriptDriver
from jevx.fx import TraceDriver
from jevx.fx import use

x = j.x


MACHINE = (
    j.input(state=x)
    | j.case[
        x.state.attempt >= x.state.max_attempts:
            j.stop("ESCALATE", phase="ESCALATE", reason="attempt limit"),
        ...: j.pass_,
    ]
    | j.keep(
        safety=j.noul("Is the verified result safe to finish?")
        * ~j.noul("Does the result expose a remaining risk?")
    )
    | j.case[
        x.safety >= 0.75:
            j.stop("DONE", phase="DONE", reason="verified safe"),
        x.safety < 0.35:
            j.stop("RETRY", phase="RETRY", attempt=x.state.attempt + 1),
        ...: j.stop("REVIEW", phase="REVIEW", reason="uncertain safety"),
    ]
)


def advance(state: dict[str, Any]) -> dict[str, Any]:
    """Execute one declared machine transition."""
    result = MACHINE.run(state=state)
    return {**state, **{key: value for key, value in result.items() if key != "action"}}


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
