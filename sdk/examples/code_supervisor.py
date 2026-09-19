"""Code supervisor: S1 scopes, approves, and judges; S2 (Codex) implements.

Loop is algebraic: complexity Score routes trivial/complex, plan Nouls approve,
diff Nouls + severity Score judge each turn, bounded retries with hysteresis.
S2 never decides done — S1 declares FINISH.
"""

from __future__ import annotations

from typing import Any, Literal

from jevx.client import Client
from jevx.py import Questions, Score, ask, feels
from jevx.s2 import CodexSystem2, System2


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


def supervise(task: str, s1: Client | None = None, s2: System2 | None = None,
              max_fixes: int = 3) -> dict:
    s2 = s2 or CodexSystem2()
    sc = Scope(client=s1)(task)  # 1 request
    if sc.complexity <= 0.5:
        out = s2.ask(f"Do it, then run tests. Task: {task}")
        d = DiffCheck(client=s1)({"task": task, "diff": out})  # 1 request
        if d.correct and d.risky is False:
            return {"action": "FINISH", "mode": "trivial", "output": out}
        return {"action": "ESCALATE", "why": "trivial path failed checks", "output": out}

    plan = s2.ask(f"Propose a short numbered plan only, no code. Task: {task}")
    pc = PlanCheck(client=s1)({"task": task, "plan": plan})  # 1 request
    if not (pc.scoped and pc.has_tests):
        return {"action": "ESCALATE", "why": "plan rejected", "plan": plan}

    out = ""
    for i in range(max_fixes + 1):
        out = s2.ask(f"Step {i}: implement per plan, run tests, show diff.\nPlan: {plan}")
        d = DiffCheck(client=s1)({"task": task, "diff": out})  # 1 request/turn
        if d.correct and d.risky is False:
            return {"action": "FINISH", "mode": "planned", "turns": i, "output": out}
        if d.severity >= 1.5:
            return {"action": "ESCALATE", "why": "blocking issues remain", "output": out}
    return {"action": "ESCALATE", "why": "fix budget exhausted", "output": out}
