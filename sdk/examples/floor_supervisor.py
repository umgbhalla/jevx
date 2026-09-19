"""Factory foreman: live-supervise any worker's event stream.

Ports: 9-Noul battery, safety-ordered FactoryPolicy, debounce queue
(dirty/force + important events), bounded observation builder, steering
messages with percentages, verifier pass, run persistence. Single worker;
bounds: 20 iters, 1 retry, 1 steer, 30s steer grace (in loop steps).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Callable

from jevx.client import Client
from jevx.py import Questions, ask
from jevx.s2 import CodexSystem2, System2

# thresholds (FactoryPolicy order matters: human -> stuck/off-track -> finish -> verify)
T_HUMAN, T_STUCK, T_OFF, T_FINISH, T_REQ, T_TESTS, T_IMPL, T_VERIFY = \
    0.80, 0.80, 0.80, 0.85, 0.80, 0.75, 0.75, 0.65
MAX_ITERS, MAX_RETRIES, MAX_STEERS = 20, 1, 1
MIN_INTERVAL, PERIODIC, TAIL, MAX_EVENTS = 5.0, 30.0, 12000, 30


class Assess(Questions):
    implementation_complete: bool = ask("Is the implementation work required by the original job complete?", threshold=T_IMPL)
    tests_sufficient: bool = ask("Does the work have sufficient relevant test coverage and passing verification?", threshold=T_TESTS)
    requirements_satisfied: bool = ask("Does the current repository satisfy the original free-form job as a whole?", threshold=T_REQ)
    needs_verification: bool = ask("Does the current state warrant an independent verification pass before finishing?", threshold=T_VERIFY)
    meaningful_progress: bool = ask("Is the active or most recent worker making meaningful progress toward the job?")
    worker_stuck: bool = ask("Does the active or most recent worker appear stuck, looping, or unable to advance?", threshold=T_STUCK)
    work_off_track: bool = ask("Is the current work drifting from the original job or making unrelated changes?", threshold=T_OFF)
    ready_to_finish: bool = ask("Given all evidence, is the factory job ready to be declared complete?", threshold=T_FINISH)
    needs_human: bool = ask("Does this situation require human judgment, credentials, clarification, or permission?", threshold=T_HUMAN)


IMPORTANT = {"WORKER_COMPLETED", "WORKER_FAILED", "WORKER_STOPPED", "VERIFICATION_COMPLETED"}

Worker = Callable[[str | None], tuple[list[str], bool]]


def build_observation(job: str, events: list[str], prior: str = "") -> dict:
    tails = "\n".join(events[-MAX_EVENTS:])
    return {"job": job, "event_tail": tails[-TAIL:], "event_count": len(events), "prior": prior[-2000:]}


def build_steer(progress: float, stuck: float, off_track: float, events: list[str]) -> str:
    direction = ("Re-read the original job and make the smallest change that advances it."
                 if off_track >= T_OFF else
                 "Pause new edits. Find the root cause of the stall, try a different path, "
                 "and reproduce with the narrowest test first.")
    return (f"Supervisory update:\n- meaningful progress: {progress:.0%}\n"
            f"- worker stuck: {stuck:.0%}\n- off track: {off_track:.0%}\n"
            f"Direction: {direction}\nRecent:\n" + "\n".join(events[-10:]))


def _p(ans) -> float:
    return float(ans.prob)


def decide(a: dict, steers_used: int, retries_used: int, verified: bool) -> str:
    if a["needs_human"] >= T_HUMAN:
        return "ESCALATE"
    if a["worker_stuck"] >= T_STUCK or a["work_off_track"] >= T_OFF:
        if steers_used < MAX_STEERS:
            return "STEER"
        return "RETRY" if retries_used < MAX_RETRIES else "ESCALATE"
    if a["ready_to_finish"] >= T_FINISH and a["requirements_satisfied"] >= T_REQ \
            and a["tests_sufficient"] >= T_TESTS and a["implementation_complete"] >= T_IMPL:
        if a["needs_verification"] >= T_VERIFY and not verified:
            return "START_VERIFIER"
        return "FINISH"
    return "CONTINUE"


def supervise(task: str, worker: Worker, s1: Client | None = None,
              s2: System2 | None = None, runs_dir: str | None = None,
              repo: str = ".") -> dict:
    from jevx.prompts import render
    os.makedirs(runs_dir, exist_ok=True) if runs_dir else None
    logfh = open(f"{runs_dir}/events.jsonl", "a") if runs_dir else None

    def log(ev: dict) -> None:
        if logfh:
            logfh.write(json.dumps({"t": time.time(), **ev}) + "\n")

    events: list[str] = [f"TASK: {task}"]
    queue: list[str] = []
    feedback: str | None = None
    steers = retries = 0
    verified = False
    prior = ""
    last_assess = 0.0
    dirty = force = False
    it = 0
    log({"kind": "START", "task": task})

    while it < MAX_ITERS:
        it += 1
        try:
            new, claimed = worker(feedback)
        except Exception as e:
            log({"kind": "WORKER_FAILED", "error": str(e)})
            return {"action": "ESCALATE", "why": f"worker error: {e}"}
        feedback = None
        queue.extend(new)
        if claimed:
            queue.append("WORKER_COMPLETED")
        # drain burst; lifecycle bypasses debounce, routine output respects it
        while queue:
            ev = queue.pop(0)
            events.append(ev)
            dirty = True
            if ev in IMPORTANT or (claimed and ev == "WORKER_COMPLETED"):
                force = True
        now = time.time()
        if not force and not (dirty and now - last_assess >= MIN_INTERVAL) \
                and not (now - last_assess >= PERIODIC):
            continue
        dirty = force = False
        last_assess = now
        obs = build_observation(task, events, prior)
        try:
            w = Assess(client=s1)(obs)  # 1 request, 9 Nouls
        except Exception as e:
            return {"action": "ESCALATE", "why": f"S1 error: {e}"}
        a = {k: _p(w.answers[k]) for k in
             ("implementation_complete", "tests_sufficient", "requirements_satisfied",
              "needs_verification", "meaningful_progress", "worker_stuck",
              "work_off_track", "ready_to_finish", "needs_human")}
        log({"kind": "ASSESS", "probs": a})
        prior = f"ready={a['ready_to_finish']:.2f} stuck={a['worker_stuck']:.2f}"
        act = decide(a, steers, retries, verified)
        log({"kind": act})

        if act == "FINISH":
            logfh.close() if logfh else None
            return {"action": "FINISH", "iters": it, "steers": steers}
        if act == "ESCALATE":
            logfh.close() if logfh else None
            return {"action": "ESCALATE", "probs": a}
        if act == "START_VERIFIER":
            s2 = s2 or CodexSystem2()
            out = s2.ask(render("verify", job=task))
            events.append(f"VERIFICATION_COMPLETED: {out[:2000]}")
            verified = True
            force = True
        elif act == "STEER":
            steers += 1
            feedback = build_steer(a["meaningful_progress"], a["worker_stuck"],
                                   a["work_off_track"], events)
        elif act == "RETRY":
            retries += 1
            feedback = "Start over minimally: smallest change satisfying the job, then tests."
    logfh.close() if logfh else None
    return {"action": "ESCALATE", "why": "iter budget exhausted"}
