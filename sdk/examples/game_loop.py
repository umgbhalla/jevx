"""Game loop: structured telemetry in, one Choice + Noul + Score per tick.

Ports the Mario pattern without an emulator: SimWorld emits object-centric
snapshots (motion, jump trajectory, upcoming hazards, measured delay, stall
counter, progress); S1 picks a macro, verifies jump urgency, scores danger.
No pixels cross the boundary — telemetry only. Heuristic policy included for
offline smoke runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Literal

from jevx.backends import Live
from jevx.contracts import ensure
from jevx.contracts import require
from jevx.py import Questions
from jevx.py import Score
from jevx.py import ask

ACTIONS = {
    "noop": "Release controls, keep momentum.",
    "right": "Move right at normal speed.",
    "right_jump": "Start a controlled forward jump, or hold while rising.",
    "right_run": "Run right only while trusted ground is clear and no jump is due.",
    "right_run_jump": "Start a running jump when terrain or contact requires it.",
    "jump": "Jump mostly in place; forward motion unsafe.",
    "left": "Move left to evade or recover.",
}
JUMP_HOLD = {"right_jump": "right", "right_run_jump": "right_run", "jump": "noop"}


class Tick(Questions):
    action: Literal[
        "noop", "right", "right_jump", "right_run", "right_run_jump", "jump", "left"
    ] = ask("Which controller macro should commit next?")
    jump_needed: bool = ask("Should a forward jump begin or remain held now?")
    danger: Score[Literal["safe", "caution", "threat"]] = ask("How dangerous is the immediate situation?")


@dataclass
class SimWorld:
    length: int = 60
    gaps: set = field(default_factory=lambda: {20, 21, 40})
    foes: dict = field(default_factory=lambda: {30: 0, 50: 0})  # x -> dx/frame toward mario
    x: float = 0.0
    vy: float = 0.0
    y: float = 0.0
    air: int = 0
    stalled: int = 0
    tick: int = 0
    alive: bool = True
    won: bool = False
    last_x: float = 0.0

    def snapshot(self) -> dict:
        ahead = [g for g in sorted(self.gaps) if self.x < g <= self.x + 5]
        near = {str(k): v for k, v in self.foes.items() if abs(k - self.x) <= 6}
        contact = any(abs(k - self.x) < 1.5 and self.y == 0 for k in self.foes)
        return {
            "player": {
                "x": round(self.x, 1),
                "airborne": self.air > 0,
                "jump_phase": "rising" if self.vy > 0 else ("falling" if self.air else "ground"),
            },
            "terrain": {"gap_ahead": ahead[:1], "trusted": True},
            "hazard": {
                "foes": near,
                "contact": contact,
                "jump_must_start": contact and self.air == 0,
            },
            "episode": {"stalled": self.stalled, "progress": round(self.x / self.length, 2)},
        }

    def step(self, action: str) -> None:
        self.tick += 1
        dx = {
            "noop": 0,
            "right": 1,
            "right_jump": 1,
            "right_run": 2,
            "right_run_jump": 2,
            "jump": 0,
            "left": -1,
        }[action]
        if action in JUMP_HOLD or action == "jump":
            if self.air == 0:
                self.vy, self.air = 3.0, 1
        self.x = max(0, self.x + dx)
        if self.air:
            self.y += self.vy
            self.vy -= 1.0
            self.air += 1
            if self.y <= 0:
                self.y, self.vy, self.air = 0.0, 0.0, 0
        xi = int(self.x)
        if xi in self.gaps and self.air == 0:
            self.alive = False
        for k in self.foes:
            if abs(k - self.x) < 1.0 and self.y == 0:
                self.alive = False
        self.stalled = self.stalled + 1 if abs(self.x - self.last_x) < 0.01 else 0
        self.last_x = self.x
        if self.x >= self.length:
            self.won = True


JUMP_MAP = {
    "right": "right_jump",
    "right_run": "right_run_jump",
    "noop": "jump",
    "left": "jump",
    "jump": "jump",
    "right_jump": "right_jump",
    "right_run_jump": "right_run_jump",
}


@ensure(
    lambda *a, result=None, **k: result["result"] in ("won", "died", "timeout"),
    msg="known game result",
)
@require(
    lambda world, backend=None, max_ticks=200, **k: 1 <= max_ticks <= 1000, msg="ticks in range"
)
def play(world: SimWorld, backend=None, max_ticks: int = 200) -> dict:
    s1 = (backend or Live()).s1()
    trace = []
    for _ in range(max_ticks):
        snap = world.snapshot()
        t = Tick(client=s1).ask(snap)  # 1 request: Choice + Noul + Score
        a = t.action
        if world.air > 0 and a in JUMP_HOLD:  # hold continuation: don't drop the jump mid-air
            a = {"right_jump": "right_jump", "right_run_jump": "right_run_jump"}.get(a, a)
        elif t.jump_needed:
            a = JUMP_MAP.get(a, "jump")
        world.step(a)
        trace.append(
            {
                "tick": world.tick,
                "action": a,
                "danger": float(t.danger),
                "x": world.x,
                "conf": t.confidence("action"),
            }
        )
        if not world.alive:
            return {"result": "died", "x": world.x, "ticks": world.tick}
        if world.won:
            return {"result": "won", "ticks": world.tick, "trace": trace}
    return {"result": "timeout", "x": world.x}


def heuristic(snap: dict) -> str:
    """Offline driver without S1: run right, jump at gaps/foes. For smoke only."""
    if snap["hazard"]["jump_must_start"] or snap["terrain"]["gap_ahead"]:
        return "right_run_jump"
    return "right_run"
