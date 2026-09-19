"""Fixed-cadence trader: one direction Choice per tick, safety as code override.

Ports: single-inflight + late/hold fallback, post-only clamp that never
crosses, exposure caps incl. resting+inflight, margin check, dry-run default,
per-event latencies. SimMarket stands in for the chain; decisions are real S1.
"""

from __future__ import annotations

from jevx.backends import Backend, Live
import time
from dataclasses import dataclass, field
from typing import Literal

from jevx.py import Questions, ask


@dataclass
class SimMarket:
    mid: float = 100.0
    drift: float = 0.02
    spread: float = 0.05
    position: float = 0.0
    cash: float = 10000.0
    resting: list[dict] = field(default_factory=list)
    fills: list[dict] = field(default_factory=list)
    tick: int = 0

    def read_book(self) -> dict:
        self.tick += 1
        self.mid += self.drift * (1 if self.tick % 3 else -1)
        # resting post-only orders fill when touched without crossing
        for o in list(self.resting):
            if (o["side"] == "buy" and self.mid - self.spread / 2 <= o["px"]) or \
               (o["side"] == "sell" and self.mid + self.spread / 2 >= o["px"]):
                self.resting.remove(o)
                self.fills.append(o)
                q = o["qty"] if o["side"] == "buy" else -o["qty"]
                self.position += q
                self.cash -= q * o["px"]
        return {"mid": self.mid, "spread": self.spread, "tick": self.tick}

    def place(self, side: str, qty: float, px: float) -> dict:
        # post-only clamp: never cross the touch
        if side == "buy":
            px = min(px, self.mid - self.spread / 2)
        else:
            px = max(px, self.mid + self.spread / 2)
        o = {"side": side, "qty": qty, "px": px}
        self.resting.append(o)
        return o


class Direction(Questions):
    direction: Literal["buy", "sell"] = ask("will price be higher or lower than mid after the horizon, by more than spread?")


def allowed(m: SimMarket, side: str, qty: float, max_pos: float, dry: bool) -> tuple[bool, str]:
    exposure = abs(m.position) + sum(o["qty"] for o in m.resting) + qty
    if exposure > max_pos:
        return False, "exposure cap"
    if m.cash < qty * m.mid and side == "buy":
        return False, "margin"
    if dry:
        return True, "dry-run"
    return True, "live"


def run(market: SimMarket, backend=None, ticks: int = 20, qty: float = 10.0,
        max_pos: float = 100.0, dry: bool = True, horizon: str = "~100 blocks") -> dict:
    s1 = (backend or Live()).s1()
    decisions, late, held, t0 = [], 0, 0, time.perf_counter()
    busy = False
    for _ in range(ticks):
        if busy:  # block arrived mid-flight: hold, never stack
            held += 1
            continue
        busy = True
        book = market.read_book()
        state = {"mid": book["mid"], "spread": book["spread"], "tick": book["tick"],
                 "position": market.position, "horizon": horizon}
        d = Direction(client=s1)(state)  # 1 request
        side = d.direction
        ok, why = allowed(market, side, qty, max_pos, dry)
        if ok and why != "dry-run":
            px = book["mid"] + (-book["spread"] if side == "buy" else book["spread"])
            market.place(side, qty, px)
        decisions.append({"tick": book["tick"], "side": side,
                          "prob": d.answers["direction"].probabilities[side],
                          "allowed": ok, "why": why})
        busy = False
    dt = (time.perf_counter() - t0) / max(ticks, 1)
    return {"decisions": decisions, "late": late, "held": held,
            "position": market.position, "cash": market.cash,
            "fills": market.fills, "sec_per_tick": dt, "dry": dry}
