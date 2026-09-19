"""A typed sum, a fuzzy predicate expression, and an indexed ``>>`` pipeline."""

from __future__ import annotations

from dataclasses import dataclass

from jevx.fx import ScriptDriver
from jevx.fx import TraceDriver
from jevx.fx import use
from jevx.ix import stage
from jevx.ix import start
from jevx.py import P
from jevx.py import noul


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


def judge(ticket: str) -> tuple[P, dict[str, str]]:
    """Compose two Noul leaves; Jev evaluates both in one request."""
    safety = (
        noul("does the answer resolve the ticket?")
        & ~noul("does the answer expose a private detail?")
    )
    return safety.ask(ticket), {"ticket": ticket}


@stage("judged", "outcome")
def classify(state: dict[str, str], confidence: P) -> tuple[Outcome, dict[str, str]]:
    """Turn an uncertain degree into a typed sum, then carry it forward."""
    match confidence.band(review_at=0.35, act_at=0.75):
        case "yes":
            outcome: Outcome = Allowed(float(confidence))
        case "review":
            outcome = HumanReview(float(confidence))
        case "no":
            outcome = Retry(float(confidence))
        case unexpected:
            raise AssertionError(f"unexpected confidence band: {unexpected}")
    return outcome, {**state, "confidence": str(float(confidence))}


FLOW = start("ticket", "judged", judge) >> classify


def demo() -> list[Outcome]:
    try:
        start("ticket", "wrong", lambda ticket: (None, ticket)) >> classify
    except TypeError as error:
        assert "cannot sequence" in str(error)
    else:
        raise AssertionError("mismatched stage labels must fail during composition")

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
            outcome, _ = FLOW(ticket)
            outcomes.append(outcome)

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
