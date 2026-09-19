"""A bounded, branching incident investigation with replayable context.

Each Jev turn and S2 proposal is a node in one task tree. Candidate causes
fork from the same route decision. Code selects the branch and the next state.
Run this file for an offline demo of the complete path.
"""

from __future__ import annotations

import json
import time
from typing import Any
from typing import Literal
from typing import TypedDict

from jevx.answers import ChoiceAnswer
from jevx.backends import Backend
from jevx.backends import Sim
from jevx.fx import ScriptDriver
from jevx.fx import TraceDriver
from jevx.fx import use
from jevx.programs import assess_due
from jevx.programs import band
from jevx.programs import joint
from jevx.programs import session
from jevx.programs import stuck
from jevx.programs import tail
from jevx.programs import topk
from jevx.programs import verify_each
from jevx.py import Predicate
from jevx.py import feels
from jevx.py import noul
from jevx.py import pick

Cause = Literal["database_pool", "recent_deploy", "upstream"]

CAUSES: dict[Cause, str] = {
    "database_pool": "connection pool exhaustion or database locks",
    "recent_deploy": "a recent deploy changed request or retry behavior",
    "upstream": "an external service is slow or unavailable",
}


class CandidateState(TypedDict):
    task: str
    evidence: str
    cause: str
    ancestor_ids: list[int]
    event_tail: str
    event_count: int


def _append(history: list[dict], parent: int | None, kind: str, **data: Any) -> int:
    node_id = len(history)
    history.append({"id": node_id, "parent": parent, "kind": kind, **data})
    return node_id


def _path(history: list[dict], head: int) -> list[dict]:
    by_id = {node["id"]: node for node in history}
    path = []
    while head is not None:
        node = by_id[head]
        path.append(node)
        head = node["parent"]
    return list(reversed(path))


def _context(history: list[dict], head: int) -> dict:
    path = _path(history, head)
    lines = [f"{node['kind']}: {node.get('summary', '')}" for node in path]
    return {"ancestor_ids": [node["id"] for node in path], **tail(lines, n=8, chars=3000)}


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
    """Choose a likely cause, fork and verify candidates, then verify a plan.

    Jev answers rank and verify. S2 drafts a plan only for a supported branch.
    This example does not execute the plan or change external systems.
    """
    s1, s2 = session(backend)
    history: list[dict] = []
    root = _append(history, None, "task", summary=task, evidence=evidence)
    observations = list(prior_observations or [])
    if stuck(observations, window=3):
        return {"action": "ESCALATE", "why": "three observations show no change", "history": history}

    clock = time.monotonic() if now is None else now
    if not assess_due(
        dirty=dirty,
        force=force,
        last=last_assessed,
        min_interval=0.0,
        periodic=60.0,
        now=clock,
    ):
        return {"action": "WAIT", "history": history}

    route_state = {"task": task, "evidence": evidence, **_context(history, root)}
    route = pick("which cause best explains the evidence?", route_state, CAUSES, client=s1)
    match route:
        case ChoiceAnswer(choice="database_pool", confidence=conf) if conf >= 0.75:
            route_summary = f"matched database route at {conf:.2f}"
        case ChoiceAnswer(choice=cause, confidence=conf):
            route_summary = f"matched {cause} at {conf:.2f}"

    route_node = _append(
        history,
        root,
        "jev.route",
        summary=route_summary,
        input_state=route_state,
        question="which cause best explains the evidence?",
        options=CAUSES,
        answer={"choice": route.choice, "probabilities": route.probabilities,
                "confidence": route.confidence},
    )

    candidates = topk(
        [(prob, cause) for cause, prob in route.probabilities.items()], k=2, floor=0.2
    )
    scores: dict[Cause, float] = {}
    candidate_states: dict[Cause, CandidateState] = {}
    candidate_questions: dict[Cause, tuple[str, str]] = {}

    def supported(cause: Cause):
        context = _context(history, route_node)
        state: CandidateState = {
            "task": task,
            "evidence": evidence,
            "cause": CAUSES[cause],
            "ancestor_ids": context["ancestor_ids"],
            "event_tail": context["event_tail"],
            "event_count": context["event_count"],
        }
        candidate_states[cause] = state
        support_question = f"does the evidence support cause '{cause}'?"
        contradiction_question = f"does the evidence contradict cause '{cause}'?"
        candidate_questions[cause] = (support_question, contradiction_question)
        rule: Predicate[CandidateState] = (
            noul(support_question) & ~noul(contradiction_question)
        )
        p = rule.ask(state, client=s1)
        scores[cause] = float(p)
        return p

    accepted, rejected = verify_each(candidates, supported, over=0.5)
    branch_nodes: dict[Cause, int] = {}
    for cause in candidates:
        branch_nodes[cause] = _append(
            history,
            route_node,
            "jev.candidate",
            branch=cause,
            summary=f"support probability {scores[cause]:.2f}",
            input_state=candidate_states[cause],
            questions=list(candidate_questions[cause]),
            answer={"probability": scores[cause], "accepted": cause in accepted},
        )
    if not accepted:
        return {"action": "ESCALATE", "why": "no candidate passed verification",
                "rejected": rejected, "history": history}

    best = topk([(scores[cause], cause) for cause in accepted], k=1)[0]
    confidence = joint(route.confidence, scores[best])
    decision = band(confidence, act_at=0.75, review_at=0.5)
    selected = branch_nodes[best]
    if decision != "act":
        return {"action": "HUMAN_REVIEW" if decision == "review" else "ESCALATE",
                "cause": best, "confidence": confidence, "history": history}

    prompt_context = _context(history, selected)
    prompt = (
        f"Give a short investigation plan. Task: {task}. Cause: {CAUSES[best]}. "
        f"Evidence: {evidence}. Prior task events: {prompt_context['event_tail']}"
    )
    proposal = s2.ask(prompt)
    proposal_node = _append(
        history,
        selected,
        "s2.proposal",
        summary=proposal,
        prompt=prompt,
        state_ref={"task": task, "evidence": evidence, "context_head": selected},
    )
    verify_state = {
        "task": task,
        "cause": best,
        "proposal": proposal,
        **_context(history, proposal_node),
    }
    verify_question = "does this plan address the task using the selected supported cause?"
    verified = feels(
        verify_question,
        verify_state,
        client=s1,
    )
    verify_node = _append(
        history,
        proposal_node,
        "jev.verify",
        summary=f"plan verification probability {float(verified):.2f}",
        input_state=verify_state,
        question=verify_question,
        answer={"probability": float(verified)},
    )
    observations.append({"page_changed": float(verified) >= 0.75})
    if float(verified) < 0.75:
        return {"action": "ESCALATE", "why": "plan did not pass verification",
                "cause": best, "history": history, "head": verify_node}
    return {"action": "PLAN_READY", "cause": best, "confidence": confidence,
            "plan": proposal, "history": history, "head": verify_node}


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
        "c": [{"type": "choice", "choice": "database_pool",
               "probabilities": {"database_pool": 0.65, "recent_deploy": 0.30,
                                  "upstream": 0.05}, "confidence": 0.82}],
        "q0": [{"type": "noul", "noul": 0.85},
               {"type": "noul", "noul": 0.35}],
        "q1": [{"type": "noul", "noul": 0.10},
               {"type": "noul", "noul": 0.90}],
        "p": [{"type": "noul", "noul": 0.90}],
    }
    result = investigate(
        "Reduce intermittent request timeouts",
        "Timeouts rise with database connection count; no deploy occurred.",
        Sim(s1_script=script, s2_texts=["Inspect pool limits, then test a lower cap."]),
        now=1.0,
    )
    assert result["action"] == "PLAN_READY"
    branches = [n for n in result["history"] if n["kind"] == "jev.candidate"]
    assert len(branches) == 2
    assert branches[0]["parent"] == branches[1]["parent"]
    assert result["head"] == result["history"][-1]["id"]
    assert investigate(
        "no progress",
        "unchanged",
        Sim(),
        prior_observations=[{"page_changed": False}] * 3,
        now=1.0,
    )["action"] == "ESCALATE"
    assert investigate(
        "not due yet",
        "unchanged",
        Sim(),
        dirty=False,
        last_assessed=100.0,
        now=101.0,
    )["action"] == "WAIT"
    return result


if __name__ == "__main__":
    result = demo()
    print(json.dumps({
        "action": result["action"],
        "cause": result["cause"],
        "confidence": result["confidence"],
        "plan": result["plan"],
        "history": [
            {"id": n["id"], "parent": n["parent"], "kind": n["kind"],
             "branch": n.get("branch"), "summary": n["summary"]}
            for n in result["history"]
        ],
        "head": result["head"],
    }, indent=2))
