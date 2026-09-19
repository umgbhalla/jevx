"""Sensors: Jev answers as readings + intent mapping (HA-style).

Each sensor is a named question evaluated on a tick; readings carry
probability/confidence/distribution for automations to threshold in code.
Intents map natural commands to built-in actions with a confidence floor.
"""

from __future__ import annotations

from typing import Literal

from jevx.answers import ChoiceAnswer
from jevx.backends import Backend
from jevx.backends import Live
from jevx.contracts import ensure
from jevx.py import Questions
from jevx.py import Score
from jevx.py import ask


class Room(Questions):
    occupied: bool = ask("is the room occupied?")
    comfort: Score[Literal["cold", "fine", "hot"]] = ask("thermal comfort?")
    quiet_hours: bool = ask("is it night/quiet hours?", threshold=0.6)


@ensure(
    lambda *a, result=None, **k: result is not None and isinstance(result["readings"], dict),
    msg="readings dict",
)
def tick(state: dict, backend: Backend | None = None) -> dict:
    s1 = (backend or Live()).s1()
    r = Room(client=s1).ask(state)  # 1 request
    return {
        "readings": {
            "occupied": {"prob": r.answers["occupied"].prob},
            "comfort": {
                "score": float(r.comfort),
                "confidence": r.confidence("comfort"),
                "probs": r.answers["comfort"].probabilities,
            },
            "quiet_hours": {"prob": r.answers["quiet_hours"].prob},
        }
    }


@ensure(lambda *a, result=None, **k: result is not None and "action" in result, msg="intent resolves")
def interpret(
    command: str, actions: dict, backend: Backend | None = None, floor: float = 0.6
) -> dict:
    """actions: {name: description}. Below floor -> clarification, not action."""
    from jevx.py import pick

    s1 = (backend or Live()).s1()
    c = pick(
        "which built-in intent does this command map to?",
        {"command": command},
        dict(actions),
        client=s1,
    )
    match c:
        case ChoiceAnswer(confidence=confidence) if confidence < floor:
            return {"action": None, "why": "below floor", "top": c.choice}
        case ChoiceAnswer(choice=action, confidence=confidence):
            return {"action": action, "confidence": confidence}
