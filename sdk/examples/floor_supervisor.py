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
from collections.abc import Callable

import jevx as j
from jevx.backends import Backend
from jevx.contracts import ensure
from jevx.programs import assess_due
from jevx.programs import session
from jevx.programs import tail
from jevx.py import Result

x = j.x

# thresholds (FactoryPolicy order matters: human -> stuck/off-track -> finish -> verify)
T_HUMAN, T_STUCK, T_OFF, T_FINISH, T_REQ, T_TESTS, T_IMPL, T_VERIFY = (
    0.80,
    0.80,
    0.80,
    0.85,
    0.80,
    0.75,
    0.75,
    0.65,
)
MAX_ITERS, MAX_RETRIES, MAX_STEERS = 20, 1, 1
MIN_INTERVAL, PERIODIC, TAIL, MAX_EVENTS = 5.0, 30.0, 12000, 30


ASSESS = j.vector(
    implementation_complete=j.noul(
        "Is the implementation work required by the original job complete?"
    ),
    tests_sufficient=j.noul(
        "Does the work have sufficient relevant test coverage and passing verification?"
    ),
    requirements_satisfied=j.noul(
        "Does the current repository satisfy the original free-form job as a whole?"
    ),
    needs_verification=j.noul(
        "Does the current state warrant an independent verification pass before finishing?"
    ),
    meaningful_progress=j.noul(
        "Is the active or most recent worker making meaningful progress toward the job?"
    ),
    worker_stuck=j.noul(
        "Does the active or most recent worker appear stuck, looping, or unable to advance?"
    ),
    work_off_track=j.noul(
        "Is the current work drifting from the original job or making unrelated changes?"
    ),
    ready_to_finish=j.noul(
        "Given all evidence, is the factory job ready to be declared complete?"
    ),
    needs_human=j.noul(
        "Does this situation require human judgment, credentials, clarification, or permission?"
    ),
)


IMPORTANT = {"WORKER_COMPLETED", "WORKER_FAILED", "WORKER_STOPPED", "VERIFICATION_COMPLETED"}

Worker = Callable[[str | None], tuple[list[str], bool]]


def build_observation(job: str, events: list[str], prior: str = "") -> dict:
    return {
        "job": job,
        **tail(events, n=MAX_EVENTS, chars=TAIL),
        "prior": prior[-2000:],
    }


def build_steer(progress: float, stuck: float, off_track: float, events: list[str]) -> str:
    direction = (
        "Re-read the original job and make the smallest change that advances it."
        if off_track >= T_OFF
        else "Pause new edits. Find the root cause of the stall, try a different path, "
        "and reproduce with the narrowest test first."
    )
    return (
        f"Supervisory update:\n- meaningful progress: {progress:.0%}\n"
        f"- worker stuck: {stuck:.0%}\n- off track: {off_track:.0%}\n"
        f"Direction: {direction}\nRecent:\n" + "\n".join(events[-10:])
    )


_STUCK = (x.assessment.worker_stuck >= T_STUCK) | (x.assessment.work_off_track >= T_OFF)
_READY = (
    (x.assessment.ready_to_finish >= T_FINISH)
    & (x.assessment.requirements_satisfied >= T_REQ)
    & (x.assessment.tests_sufficient >= T_TESTS)
    & (x.assessment.implementation_complete >= T_IMPL)
)

DECIDE = (
    j.input(assessment=x, steers=x, retries=x, verified=x)
    | j.case[
        x.assessment.needs_human >= T_HUMAN: j.stop("ESCALATE"),
        _STUCK & (x.steers < MAX_STEERS): j.stop("STEER"),
        _STUCK & (x.steers >= MAX_STEERS) & (x.retries < MAX_RETRIES): j.stop("RETRY"),
        _STUCK: j.stop("ESCALATE"),
        _READY & (x.assessment.needs_verification >= T_VERIFY) & (x.verified == 0):
            j.stop("START_VERIFIER"),
        _READY: j.stop("FINISH"),
        ...: j.stop("CONTINUE"),
    ]
)


@ensure(
    lambda *a, result=None, **k: (
        result in ("ESCALATE", "STEER", "RETRY", "FINISH", "START_VERIFIER", "CONTINUE")
    ),
    "action is a known FactoryAction",
)
def decide(a: Result, steers_used: int, retries_used: int, verified: bool) -> str:
    return DECIDE.run(assessment=a, steers=steers_used, retries=retries_used, verified=verified)[
        "action"
    ]


def supervise(
    task: str,
    worker: Worker,
    backend: Backend | None = None,
    runs_dir: str | None = None,
    repo: str = ".",
) -> dict:
    from collections import deque as _dq

    from jevx.prompts import render

    os.makedirs(runs_dir, exist_ok=True) if runs_dir else None
    logfh = open(f"{runs_dir}/events.jsonl", "a") if runs_dir else None

    def log(ev: dict) -> None:
        if logfh:
            logfh.write(json.dumps({"t": time.time(), **ev}) + "\n")

    def close() -> None:
        if logfh:
            try:
                logfh.flush()
            finally:
                logfh.close()

    events: list[str] = [f"TASK: {task}"]
    queue = _dq()
    feedback: str | None = None
    steers = retries = grace = 0
    verified = False
    prior = ""
    last_assess = 0.0
    dirty = force = False
    it = 0
    s1, s2 = session(backend)
    log({"kind": "START", "task": task})

    try:
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
                ev = queue.popleft()
                events.append(ev)
                dirty = True
                if ev in IMPORTANT or (claimed and ev == "WORKER_COMPLETED"):
                    force = True
            now = time.time()
            if grace:
                grace -= 1
                continue
            if not assess_due(
                dirty,
                force,
                last_assess,
                min_interval=MIN_INTERVAL,
                periodic=PERIODIC,
                now=now,
            ):
                continue
            dirty = force = False
            last_assess = now
            obs = build_observation(task, events, prior)
            try:
                w = ASSESS.ask(obs, client=s1)  # 1 request, 9 Nouls
            except Exception as e:
                return {"action": "ESCALATE", "why": f"S1 error: {e}"}
            a = {key: float(value) for key, value in w.as_dict().items()}
            log({"kind": "ASSESS", "probs": a})
            prior = f"ready={a['ready_to_finish']:.2f} stuck={a['worker_stuck']:.2f}"
            act = decide(w, steers, retries, verified)
            log({"kind": act})

            if act == "FINISH":
                return {"action": "FINISH", "iters": it, "steers": steers}
            if act == "ESCALATE":
                return {"action": "ESCALATE", "probs": a}
            if act == "START_VERIFIER":
                try:
                    out = s2.ask(render("verify", job=task))
                except Exception as e:
                    return {"action": "ESCALATE", "why": f"verifier error: {e}"}
                if not out.strip():
                    return {"action": "ESCALATE", "why": "verifier empty"}
                events.append(f"VERIFICATION_COMPLETED: {out[:2000]}")
                verified = True
                force = True
            elif act == "STEER":
                steers += 1
                grace = 2
                feedback = build_steer(
                    a["meaningful_progress"], a["worker_stuck"], a["work_off_track"], events
                )
            elif act == "RETRY":
                retries += 1
                feedback = "Start over minimally: smallest change satisfying the job, then tests."
        return {"action": "ESCALATE", "why": "iter budget exhausted"}
    finally:
        close()
