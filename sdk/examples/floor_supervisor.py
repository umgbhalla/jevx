"""Floor supervisor: watcher loop over any worker's event stream.

Worker emits events (stdout lines, diffs, status); supervisor batches them
(debounce), asks one S1 battery, and a deterministic policy picks CONTINUE /
STEER / STOP / FINISH / ESCALATE. Worker never decides done — S1 does.
Bounds: max_iters, max_steers, steer cooldown. Fail-closed on S1 error.
"""

from __future__ import annotations

from typing import Any, Callable

from jevx.client import Client
from jevx.py import Questions, ask


class Watch(Questions):
    complete: bool = ask("is the job fully done?", threshold=0.85)
    tests_ok: bool = ask("do tests cover and pass the change?", threshold=0.65)
    stuck: bool = ask("is the worker stuck or looping?", threshold=0.80)
    off_track: bool = ask("is the work off-task?", threshold=0.80)
    needs_human: bool = ask("does this need a human?", threshold=0.80)


# step(feedback) -> (new_events, finished_claim)
Worker = Callable[[str | None], tuple[list[str], bool]]


def policy(w, events: int) -> str:
    if w.needs_human:
        return "ESCALATE"
    if w.stuck or w.off_track:
        return "STEER"
    if w.complete and w.tests_ok:
        return "FINISH"
    if w.complete:
        return "VERIFY"
    return "CONTINUE"


STEER_MSG = "You are stuck or off-track. Recent events:\n{events}\nReplan minimally and continue."


def supervise(task: str, worker: Worker, s1: Client | None = None,
              max_iters: int = 20, max_steers: int = 2, batch: int = 5) -> dict:
    seen: list[str] = [f"TASK: {task}"]
    feedback: str | None = None
    steers, it = 0, 0
    while it < max_iters:
        it += 1
        try:
            new_events, claimed = worker(feedback)
        except Exception as e:  # worker crashed: fail closed
            return {"action": "ESCALATE", "why": f"worker error: {e}", "events": seen}
        feedback = None
        seen.extend(new_events)
        if len(new_events) < batch and not claimed:
            continue  # debounce: wait for a full batch or a done claim
        window = seen[-30:]
        try:
            w = Watch(client=s1)({"task": task, "events": window})  # 1 request
        except Exception as e:
            return {"action": "ESCALATE", "why": f"S1 error: {e}", "events": seen}
        act = policy(w, len(window))
        if act == "FINISH":
            return {"action": "FINISH", "iters": it, "steers": steers}
        if act == "ESCALATE":
            return {"action": "ESCALATE", "why": "watch flagged human", "events": seen}
        if act in ("STEER", "VERIFY"):
            if steers >= max_steers:
                return {"action": "ESCALATE", "why": "steer budget exhausted", "events": seen}
            steers += 1
            feedback = STEER_MSG.format(events="\n".join(window[-10:])) if act == "STEER" \
                else "Run the tests and show output."
    return {"action": "ESCALATE", "why": "iter budget exhausted", "events": seen}
