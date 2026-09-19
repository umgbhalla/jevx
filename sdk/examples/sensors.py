"""Sensors: Jev answers as readings + intent mapping (HA-style).

Each sensor is a named question evaluated on a tick; readings carry
probability/confidence/distribution for automations to threshold in code.
Intents map natural commands to built-in actions with a confidence floor.
"""

from __future__ import annotations

import jevx as j
from jevx.backends import Backend
from jevx.backends import Live
from jevx.contracts import ensure

x = j.x

ROOM = j.vector(
    occupied=j.noul("is the room occupied?"),
    comfort=j.score("thermal comfort?", ("cold", "fine", "hot")),
    quiet_hours=j.noul("is it night/quiet hours?"),
)


def _readings(r):
    return {
        "occupied": {"prob": float(r.occupied)},
        "comfort": {
            "score": float(r.comfort),
            "confidence": r.comfort.confidence,
            "probs": r.comfort.probabilities,
        },
        "quiet_hours": {"prob": float(r.quiet_hours)},
    }


ROOM_TICK = (
    j.input(state=x)
    | j.keep(room=ROOM.on(x.state))
    | j.keep(readings=j.compute(_readings, x.room))
)


@ensure(
    lambda *a, result=None, **k: result is not None and isinstance(result["readings"], dict),
    msg="readings dict",
)
def tick(state: dict, backend: Backend | None = None) -> dict:
    s1 = (backend or Live()).s1()
    return {"readings": ROOM_TICK.run(state=state, client=s1)["readings"]}


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
    return j.case[
        c.confidence < floor : {"action": None, "why": "below floor", "top": c.choice},
        ... : {"action": c.choice, "confidence": c.confidence},
    ].ask({})
