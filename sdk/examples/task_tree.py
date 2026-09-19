"""A bounded, branching incident investigation with replayable context.

Each Jev turn and S2 proposal is a node in one task tree. Candidate causes
fork from the same route decision. Code selects the branch and the next state.
Run this file for an offline demo of the complete path.
"""

from __future__ import annotations

import json
import time
from typing import Literal

from jevx.backends import Backend
from jevx.backends import Sim
from jevx.fx import ScriptDriver
from jevx.fx import TraceDriver
from jevx.fx import use
from jevx.programs import assess_due
from jevx.programs import band
from jevx.programs import joint
from jevx.programs import stuck
from jevx.programs import tail
from jevx.programs import topk
from jevx.py import noul
from jevx.task import task as task_scope

Cause = Literal["database_pool", "recent_deploy", "upstream"]

CAUSES: dict[Cause, str] = {
    "database_pool": "connection pool exhaustion or database locks",
    "recent_deploy": "a recent deploy changed request or retry behavior",
    "upstream": "an external service is slow or unavailable",
}


def _context(run) -> dict:
    events = run.context(limit=8)["history"]
    lines = [f"{event['kind']}: {event['summary']}" for event in events]
    return {
        "ancestor_ids": [event["id"] for event in events],
        **tail(lines, n=8, chars=3000),
        "event_count": len(run.history),
    }


def investigate(
    task: str,
    evidence: str,
    backend: Backend | None = None,
    *,
    prior_observations: list[dict] | None = None,
    dirty: bool = True,
    force: bool = False,
    last_assessed: float = 0.0,
    now: float | None = None,
) -> dict:
    """Pick a likely cause, explore sibling branches, then verify one plan."""
    with task_scope("incident", backend) as run:
        run.record("input", summary=task, evidence=evidence)
        observations = list(prior_observations or [])
        if stuck(observations, window=3):
            return {"action": "ESCALATE", "why": "three observations show no change", "history": run.history}

        clock = time.monotonic() if now is None else now
        if not assess_due(
            dirty=dirty,
            force=force,
            last=last_assessed,
            min_interval=0.0,
            periodic=60.0,
            now=clock,
        ):
            return {"action": "WAIT", "history": run.history}

        route_state = {"task": task, "evidence": evidence, **_context(run)}
        route = run.pick("Which cause best explains the evidence?", route_state, CAUSES)
        candidates = topk(
            [(prob, cause) for cause, prob in route.probabilities.items()], k=2, floor=0.2
        )
        scores: dict[Cause, float] = {}
        branch_heads: dict[Cause, int] = {}
        accepted, rejected = [], []

        for cause in candidates:
            with run.branch(f"candidate: {cause}"):
                state = {
                    "task": task,
                    "evidence": evidence,
                    "cause": CAUSES[cause],
                    **_context(run),
                }
                support = noul(f"Does the evidence support cause '{cause}'?")
                contradiction = noul(f"Does the evidence contradict cause '{cause}'?")
                probability = run.ask(support & ~contradiction, state)
                scores[cause] = float(probability)
                branch_heads[cause] = run.head
                (accepted if probability >= 0.5 else rejected).append(cause)

        if not accepted:
            return {
                "action": "ESCALATE",
                "why": "no candidate passed verification",
                "rejected": rejected,
                "history": run.history,
            }

        best = topk([(scores[cause], cause) for cause in accepted], k=1)[0]
        confidence = joint(route.confidence, scores[best])
        decision = band(confidence, act_at=0.75, review_at=0.5)
        selected = branch_heads[best]
        run.checkout(selected)
        if decision != "act":
            return {
                "action": "HUMAN_REVIEW" if decision == "review" else "ESCALATE",
                "cause": best,
                "confidence": confidence,
                "history": run.history,
                "head": selected,
            }

        prompt_context = _context(run)
        prompt = (
            f"Give a short investigation plan. Task: {task}. Cause: {CAUSES[best]}. "
            f"Evidence: {evidence}. Prior task events: {prompt_context['event_tail']}"
        )
        proposal = run.s2.ask(prompt)
        verify_state = {
            "task": task,
            "cause": best,
            "proposal": proposal,
            **_context(run),
        }
        verified = run.ask(
            noul("Does this plan address the task using the selected supported cause?"),
            verify_state,
        )
        observations.append({"page_changed": float(verified) >= 0.75})
        if float(verified) < 0.75:
            return {
                "action": "ESCALATE",
                "why": "plan did not pass verification",
                "cause": best,
                "history": run.history,
                "head": run.head,
            }
        return {
            "action": "PLAN_READY",
            "cause": best,
            "confidence": confidence,
            "plan": proposal,
            "history": run.history,
            "head": run.head,
        }

def demo() -> dict:
    """Offline end-to-end check: two candidate branches, one selected plan."""
    recorder = TraceDriver(
        ScriptDriver(
            {
                "q0": [{"type": "noul", "noul": 0.8}],
                "q1": [{"type": "noul", "noul": 0.1}],
            }
        )
    )
    expression = noul("is relevant?") & ~noul("is contradicted?")
    with use(recorder):
        combined = expression.ask({"evidence": "measured"})
    assert len(recorder.trace) == 1
    assert set(recorder.trace[0]["questions"]) == {"q0", "q1"}
    assert combined.over(0.7)

    script = {
        "c": [
            {
                "type": "choice",
                "choice": "database_pool",
                "probabilities": {"database_pool": 0.65, "recent_deploy": 0.30, "upstream": 0.05},
                "confidence": 0.82,
            }
        ],
        "q0": [
            {"type": "noul", "noul": 0.85},
            {"type": "noul", "noul": 0.35},
            {"type": "noul", "noul": 0.90},
        ],
        "q1": [{"type": "noul", "noul": 0.10}, {"type": "noul", "noul": 0.90}],
    }
    result = investigate(
        "Reduce intermittent request timeouts",
        "Timeouts rise with database connection count; no deploy occurred.",
        Sim(s1_script=script, s2_texts=["Inspect pool limits, then test a lower cap."]),
        now=1.0,
    )
    assert result["action"] == "PLAN_READY"
    branches = [n for n in result["history"] if n["kind"] == "branch"]
    assert len(branches) == 2
    assert branches[0]["parent"] == branches[1]["parent"]
    assert result["head"] == result["history"][-1]["id"]
    assert (
        investigate(
            "no progress",
            "unchanged",
            Sim(),
            prior_observations=[{"page_changed": False}] * 3,
            now=1.0,
        )["action"]
        == "ESCALATE"
    )
    assert (
        investigate(
            "not due yet",
            "unchanged",
            Sim(),
            dirty=False,
            last_assessed=100.0,
            now=101.0,
        )["action"]
        == "WAIT"
    )
    return result


if __name__ == "__main__":
    result = demo()
    print(
        json.dumps(
            {
                "action": result["action"],
                "cause": result["cause"],
                "confidence": result["confidence"],
                "plan": result["plan"],
                "history": [
                    {
                        "id": n["id"],
                        "parent": n["parent"],
                        "kind": n["kind"],
                        "branch": n.get("branch"),
                        "summary": n["summary"],
                    }
                    for n in result["history"]
                ],
                "head": result["head"],
            },
            indent=2,
        )
    )
