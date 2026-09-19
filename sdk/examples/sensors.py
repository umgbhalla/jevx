"""Sensors: Jev answers as readings + intent mapping (HA-style).

Each sensor is a named question evaluated on a tick; readings carry
probability/confidence/distribution for automations to threshold in code.
Intents map natural commands to built-in actions with a confidence floor.
"""

from __future__ import annotations

from jevx.backends import Backend
from jevx.backends import Live
from jevx.contracts import ensure
from jevx.py import case
from jevx.py import noul
from jevx.py import score
from jevx.py import vector

ROOM = vector(
    occupied=noul("is the room occupied?"),
    comfort=score("thermal comfort?", ("cold", "fine", "hot")),
    quiet_hours=noul("is it night/quiet hours?"),
)


@ensure(
    lambda *a, result=None, **k: result is not None and isinstance(result["readings"], dict),
    msg="readings dict",
)
def tick(state: dict, backend: Backend | None = None) -> dict:
    s1 = (backend or Live()).s1()
    r = ROOM.ask(state, client=s1)  # 1 request: three named readings
    return {
        "readings": {
            "occupied": {"prob": float(r.occupied)},
            "comfort": {
                "score": float(r.comfort),
                "confidence": r.confidence("comfort"),
                "probs": r.comfort.probabilities,
            },
            "quiet_hours": {"prob": float(r.quiet_hours)},
        }
    }


@ensure(
    lambda *a, result=None, **k: result is not None and "action" in result, msg="intent resolves"
)
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
    return case[
        c.confidence < floor : {"action": None, "why": "below floor", "top": c.choice},
        ... : {"action": c.choice, "confidence": c.confidence},
    ].ask({})
