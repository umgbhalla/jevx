"""Code supervisor: S1 scopes, approves, and judges; S2 (Codex) implements.

Loop is algebraic: complexity Score routes trivial/complex, plan Nouls approve,
diff Nouls + severity Score judge each turn, bounded retries with hysteresis.
S2 never decides done — S1 declares FINISH.
"""

from __future__ import annotations

import jevx as j
from jevx.backends import Backend
from jevx.backends import Live
from jevx.contracts import ensure

x = j.x

SCOPE = j.vector(
    complexity=j.score("how big is this task?", ("trivial", "small", "large")),
    testable=j.noul("can the result be checked by running tests?"),
)


PLAN_CHECK = j.vector(
    scoped=j.noul("is the plan confined to the task?"),
    has_tests=j.noul("does the plan include running tests?"),
)


DIFF_CHECK = j.vector(
    correct=j.noul("does the diff address the task?"),
    risky=j.noul("does the diff touch auth, migrations, or deletes?"),
    severity=j.score("how severe are remaining issues?", ("cosmetic", "notable", "blocking")),
)

PLAN = (
    j.input(task=x, plan=x)
    | j.keep(check=PLAN_CHECK.on({"task": x.task, "plan": x.plan}))
    | j.case[
        (x.check.scoped >= 0.5) & (x.check.has_tests >= 0.5): j.stop("ACCEPT"),
        ...: j.stop("ESCALATE"),
    ]
)

DIFF = (
    j.input(task=x, diff=x, mode=x, turns=x)
    | j.keep(check=DIFF_CHECK.on({"task": x.task, "diff": x.diff}))
    | j.case[
        (x.check.correct >= 0.5)
        & (x.check.risky < 0.35)
        & (abs(2 * x.check.correct - 1) >= 0.2): j.stop(
            "FINISH", mode=x.mode, turns=x.turns, output=x.diff
        ),
        x.check.severity >= 1.5: j.stop("ESCALATE", why="blocking issues remain", output=x.diff),
        x.mode == "trivial": j.stop(
            "ESCALATE", why="trivial path failed checks", output=x.diff
        ),
        ...: j.stop("RETRY"),
    ]
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
        return DIFF.run(task=task, diff=out, mode="trivial", turns=1, client=s1)

    plan = s2.ask(f"Propose a short numbered plan only, no code. Task: {task}")
    accepted = PLAN.run(task=task, plan=plan, client=s1)
    if accepted["action"] != "ACCEPT":
        return {"action": "ESCALATE", "why": "plan rejected", "plan": plan}

    out = ""
    for i in range(max_fixes):
        out = s2.ask(f"Step {i}: implement per plan, run tests, show diff.\nPlan: {plan}")
        decision = DIFF.run(task=task, diff=out, mode="planned", turns=i + 1, client=s1)
        if decision["action"] != "RETRY":
            return decision
    return {"action": "ESCALATE", "why": "fix budget exhausted", "output": out}
