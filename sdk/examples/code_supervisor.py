"""Code supervisor: S1 scopes, approves, and judges; S2 (Codex) implements.

Loop is algebraic: complexity Score routes trivial/complex, plan Nouls approve,
diff Nouls + severity Score judge each turn, bounded retries with hysteresis.
S2 never decides done — S1 declares FINISH.
"""

from __future__ import annotations

from jevx.backends import Backend
from jevx.backends import Live
from jevx.contracts import ensure
from jevx.py import case
from jevx.py import noul
from jevx.py import score
from jevx.py import vector

SCOPE = vector(
    complexity=score("how big is this task?", ("trivial", "small", "large")),
    testable=noul("can the result be checked by running tests?"),
)


PLAN_CHECK = vector(
    scoped=noul("is the plan confined to the task?"),
    has_tests=noul("does the plan include running tests?"),
)


DIFF_CHECK = vector(
    correct=noul("does the diff address the task?"),
    risky=noul("does the diff touch auth, migrations, or deletes?"),
    severity=score("how severe are remaining issues?", ("cosmetic", "notable", "blocking")),
)


@ensure(
    lambda *a, result=None, **k: result is not None and result["action"] in ("FINISH", "ESCALATE"),
    msg="known supervise action",
)
def supervise(task: str, backend: Backend | None = None, max_fixes: int = 3) -> dict:
    bk = backend or Live()
    s1, s2 = bk.s1(), bk.s2()
    sc = SCOPE.ask(task, client=s1)  # 1 request
    if sc.complexity <= 0.5 and sc.testable >= 0.5:
        out = s2.ask(f"Do it, then run tests. Task: {task}")
        d = DIFF_CHECK.ask({"task": task, "diff": out}, client=s1)  # 1 request
        return case[
            d.correct >= 0.5 and d.risky < 0.35 and abs(2 * d.correct - 1) >= 0.2 : {
                "action": "FINISH",
                "mode": "trivial",
                "output": out,
            },
            ... : {"action": "ESCALATE", "why": "trivial path failed checks", "output": out},
        ].ask({})

    plan = s2.ask(f"Propose a short numbered plan only, no code. Task: {task}")
    pc = PLAN_CHECK.ask({"task": task, "plan": plan}, client=s1)  # 1 request
    plan_ok = case[
        (pc.scoped >= 0.5) & (pc.has_tests >= 0.5) : True,
        ...:False,
    ].ask({})
    if not plan_ok:
        return {"action": "ESCALATE", "why": "plan rejected", "plan": plan}

    out = ""
    for i in range(max_fixes):
        out = s2.ask(f"Step {i}: implement per plan, run tests, show diff.\nPlan: {plan}")
        d = DIFF_CHECK.ask({"task": task, "diff": out}, client=s1)  # 1 request/turn
        decision = case[
            d.correct >= 0.5 and d.risky < 0.35 and abs(2 * d.correct - 1) >= 0.2 : {
                "action": "FINISH",
                "mode": "planned",
                "turns": i + 1,
                "output": out,
            },
            d.severity >= 1.5 : {
                "action": "ESCALATE",
                "why": "blocking issues remain",
                "output": out,
            },
            ...:None,
        ].ask({})
        if decision is not None:
            return decision
    return {"action": "ESCALATE", "why": "fix budget exhausted", "output": out}
