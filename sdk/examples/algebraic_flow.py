"""A typed outcome and a lazy judgment piped into a local decision."""

from __future__ import annotations

from dataclasses import dataclass

import jevx as j
from jevx.fx import ScriptDriver
from jevx.fx import TraceDriver
from jevx.fx import use
from jevx.py import P


@dataclass(frozen=True)
class Allowed:
    confidence: float


@dataclass(frozen=True)
class HumanReview:
    confidence: float


@dataclass(frozen=True)
class Retry:
    confidence: float


type Outcome = Allowed | HumanReview | Retry


SAFETY = (
    j.noul("Does the answer resolve the ticket?")
    & ~j.noul("Does the answer expose a private detail?")
)


@j.step
def classify(confidence: P) -> Outcome:
    """Turn an evaluated degree into an explicit typed outcome."""
    match confidence.band(review_at=0.35, act_at=0.75):
        case "yes":
            outcome: Outcome = Allowed(float(confidence))
        case "review":
            outcome = HumanReview(float(confidence))
        case "no":
            outcome = Retry(float(confidence))
        case unexpected:
            raise AssertionError(f"unexpected confidence band: {unexpected}")
    return outcome


FLOW = j.flow(SAFETY) | classify


def demo() -> list[Outcome]:
    trace = TraceDriver(
        ScriptDriver(
            {
                "q0": [
                    {"type": "noul", "noul": 0.95},
                    {"type": "noul", "noul": 0.8},
                    {"type": "noul", "noul": 0.1},
                ],
                "q1": [
                    {"type": "noul", "noul": 0.02},
                    {"type": "noul", "noul": 0.4},
                    {"type": "noul", "noul": 0.9},
                ],
            }
        )
    )
    outcomes = []
    with use(trace):
        for ticket in ("answerable", "uncertain", "unsafe"):
            outcomes.append(FLOW.run(ticket))

    assert [type(outcome) for outcome in outcomes] == [Allowed, HumanReview, Retry]
    assert len(trace.trace) == 3
    assert all(set(row["questions"]) == {"q0", "q1"} for row in trace.trace)
    match outcomes[0]:
        case Allowed(confidence=probability) if probability >= 0.75:
            pass
        case _:
            raise AssertionError("expected a confident allow result")
    return outcomes


if __name__ == "__main__":
    for result in demo():
        print(result)
