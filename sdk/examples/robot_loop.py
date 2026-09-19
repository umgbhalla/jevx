"""Robot loop: LLM-free tick control with safety contracts, sim robot included.

Ports the split-brain shape: Jev picks ONE verb per tick from an allowlist;
code owns confirm lists, budgets, abort conditions, confidence floors, and
the 8-in-a-row handover. SimBot stands in for hardware: battery drains,
wheels slip near edges, killswitch works.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from jevx.client import Client
from jevx.py import Questions, ask

VERBS = ("forward", "back", "left", "right", "stop", "dock", "snapshot", "done")
CONFIRM = {"dock"}
FLOORS = {"forward": 0.50, "back": 0.50, "left": 0.50, "right": 0.50,
          "stop": 0.0, "dock": 0.90, "snapshot": 0.60, "done": 0.50}


class Tick(Questions):
    verb: Literal["forward", "back", "left", "right", "stop", "dock", "snapshot", "done"] = \
        ask("which single verb advances the mission?")
    escalate: bool = ask("is the situation beyond the verb list?", threshold=0.5)
    done: bool = ask("is the mission complete?", threshold=0.5)


@dataclass
class SimBot:
    x: float = 0.0
    y: float = 0.0
    battery: float = 100.0
    goal: tuple = (9.0, 0.0)
    edge: float = 10.0
    log: list = field(default_factory=list)
    killed: bool = False

    def observe(self) -> dict:
        dx = self.goal[0] - self.x
        return {"pos": (round(self.x, 1), round(self.y, 1)),
                "goal_dx": round(dx, 1), "battery": round(self.battery, 1),
                "near_edge": self.x > self.edge - 1.5}

    def exec(self, verb: str) -> str:
        if self.killed:
            return "killed"
        self.battery -= 1.0
        self.log.append(verb)
        if verb == "forward":
            self.x += 0.5 if self.x > self.edge - 1.5 else 1.0  # wheels slip at edge
        elif verb == "back":
            self.x -= 1.0
        elif verb == "stop":
            pass
        elif verb == "dock":
            self.battery = 100.0
        return "ok"

    def abort_when(self) -> str | None:
        if self.battery <= 5:
            return "battery critical"
        if self.x > self.edge:
            return "over edge"
        return None


def mission(bot: SimBot, contract: dict, s1, max_steps: int = 40) -> dict:
    """contract: {confirm: [...], budgets: {max_steps}, abort_when: [...]}."""
    repeats, last = 0, ""
    for step in range(min(max_steps, contract.get("budgets", {}).get("max_steps", max_steps))):
        if bot.killed:
            return {"result": "killed", "steps": step}
        if why := bot.abort_when():
            bot.exec("stop")
            return {"result": "aborted", "why": why, "steps": step}
        obs = bot.observe()
        t = Tick(client=s1)({"obs": obs, "goal": bot.goal})  # 1 request
        if t.escalate:
            return {"result": "escalated", "obs": obs}
        v = t.verb
        if v == last:
            repeats += 1
            if repeats >= 8:
                return {"result": "handover", "why": "8 same verbs in a row"}
        else:
            repeats, last = 0, v
        if t.confidence("verb") < FLOORS[v]:
            continue  # below floor: hold position this tick
        if v in contract.get("confirm", CONFIRM):
            return {"result": "confirm", "verb": v, "obs": obs}
        if v == "done":
            return {"result": "done", "steps": step}
        bot.exec(v)
    return {"result": "budget", "x": bot.x}
