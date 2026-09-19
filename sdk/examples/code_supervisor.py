"""Code supervisor: S1 scopes, approves, and judges; S2 (Codex) implements.

Loop is algebraic: complexity Score routes trivial/complex, plan Nouls approve,
diff Nouls + severity Score judge each turn, bounded retries with hysteresis.
S2 never decides done — S1 declares FINISH.
"""

from __future__ import annotations

from jevx.backends import Backend
from jevx.backends import Live
from jevx.contracts import ensure
from jevx.py import Questions
from jevx.py import Score
from jevx.py import ask


class Scope(Questions):
    complexity: Score["trivial", "small", "large"] = ask("how big is this task?")
    testable: bool = ask("can the result be checked by running tests?")


class PlanCheck(Questions):
    scoped: bool = ask("is the plan confined to the task?")
    has_tests: bool = ask("does the plan include running tests?")


class DiffCheck(Questions):
    correct: bool = ask("does the diff address the task?")
    risky: bool = ask("does the diff touch auth, migrations, or deletes?", threshold=0.35)
    severity: Score["cosmetic", "notable", "blocking"] = ask("how severe are remaining issues?")


@ensure(
    lambda *a, result=None, **k: result["action"] in ("FINISH", "ESCALATE"),
    msg="known supervise action",
)
def supervise(task: str, backend: Backend | None = None, max_fixes: int = 3) -> dict:
    bk = backend or Live()
    s1, s2 = bk.s1(), bk.s2()
    sc = Scope(client=s1)(task)  # 1 request
    if sc.complexity <= 0.5 and sc.testable:
        out = s2.ask(f"Do it, then run tests. Task: {task}")
        d = DiffCheck(client=s1)({"task": task, "diff": out})  # 1 request
        if d.correct and d.risky is False and d.confidence("correct") >= 0.2:
            return {"action": "FINISH", "mode": "trivial", "output": out}
        return {"action": "ESCALATE", "why": "trivial path failed checks", "output": out}

    plan = s2.ask(f"Propose a short numbered plan only, no code. Task: {task}")
    pc = PlanCheck(client=s1)({"task": task, "plan": plan})  # 1 request
    if not (pc.scoped and pc.has_tests):
        return {"action": "ESCALATE", "why": "plan rejected", "plan": plan}

    out = ""
    for i in range(max_fixes):
        out = s2.ask(f"Step {i}: implement per plan, run tests, show diff.\nPlan: {plan}")
        d = DiffCheck(client=s1)({"task": task, "diff": out})  # 1 request/turn
        if d.correct and d.risky is False and d.confidence("correct") >= 0.2:
            return {"action": "FINISH", "mode": "planned", "turns": i + 1, "output": out}
        if d.severity >= 1.5:
            return {"action": "ESCALATE", "why": "blocking issues remain", "output": out}
    return {"action": "ESCALATE", "why": "fix budget exhausted", "output": out}
