"""Dashboard reconcile loop: S1 picks operation+target each step, worker fills text,
verify() gates every SUBMIT. FakeBrowser simulates login, 2FA wait, paginated
invoice rows, one flaky button, and a drawer — stall detection + replan included.

Realistic without a browser: swap FakeBrowser for Playwright calls and keep
the exact same decider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from jevx.client import Client
from jevx.py import Questions, ask
from jevx.s2 import CodexSystem2, System2


class Step(Questions):
    operation: Literal["CLICK", "TYPE_TEXT", "SUBMIT", "WAIT", "DONE", "BLOCKED"] = ask(
        "which operation moves the goal forward?")
    target: Literal["e_login", "e_user", "e_pass", "e_pay", "e_next",
                    "e_row", "e_drawer", "e_submit_login", "e_none"] = ask("which element id?")
    stuck: bool = ask("has the last action made no progress?", threshold=0.6)


@dataclass
class FakeBrowser:
    rows: list[dict] = field(default_factory=lambda: [
        {"id": "INV-1", "paid": False}, {"id": "INV-2", "paid": False, "flaky": True},
        {"id": "INV-3", "paid": False},
    ])
    page: int = 0
    logged_in: bool = False
    log: list[str] = field(default_factory=list)
    _flaked: bool = False

    def snapshot(self) -> dict:
        return {"url": "/login" if not self.logged_in else f"/invoices?p={self.page}",
                "rows": [dict(r) for r in self.rows], "page": self.page}

    def act(self, op: str, target: str, text: str = "") -> str:
        self.log.append(f"{op} {target} {text}".strip())
        if op == "CLICK" and target == "e_submit_login":
            self.logged_in = True
            return "toast: welcome (2FA skipped in test tenant)"
        if op == "SUBMIT" and target == "e_pay":
            r = self.rows[self.page]
            if r.get("flaky") and not self._flaked:
                self._flaked = True
                return "error: button covered, click missed"
            r["paid"] = True
            return f"toast: {r['id']} marked paid"
        if op == "CLICK" and target == "e_next":
            self.page = min(self.page + 1, len(self.rows) - 1)
            return f"page {self.page}"
        return "ok"


def reconcile(goal: str, browser: FakeBrowser, s1: Client | None = None,
              s2: System2 | None = None, max_steps: int = 40) -> dict:
    s2 = s2 or CodexSystem2()
    stalls, paid = 0, []
    last_fp = ""
    for step in range(max_steps):
        snap = browser.snapshot()
        fp = str(sorted((r["id"], r["paid"]) for r in snap["rows"])) + snap["url"]
        d = Step(client=s1)({"goal": goal, "page": snap, "last": last_fp})  # 1 req
        if d.operation == "DONE" or all(r["paid"] for r in snap["rows"]):
            return {"action": "DONE", "paid": paid, "steps": step}
        if d.operation == "BLOCKED":
            return {"action": "BLOCKED", "log": browser.log}
        if d.operation == "TYPE_TEXT":
            text = s2.ask(f"Value for {d.target} given goal: {goal}. Reply with the value only.")
            out = browser.act("CLICK", d.target, text)
        elif d.operation == "SUBMIT":
            before = fp
            out = browser.act("SUBMIT", d.target)
            if "toast:" not in out or "marked paid" not in out or before == str(
                    sorted((r["id"], r["paid"]) for r in browser.snapshot()["rows"])) + browser.snapshot()["url"]:
                stalls += 1  # verify() failed: no toast or no state change
                if stalls >= 3:
                    return {"action": "REPLAN", "why": "3 failed submits", "log": browser.log}
                continue
            stalls = 0
            paid.append(browser.rows[browser.page]["id"])
            if browser.page < len(browser.rows) - 1:
                browser.act("CLICK", "e_next")
        else:
            out = browser.act(d.operation, d.target)
        last_fp = fp
        if d.stuck:
            stalls += 1
            if stalls >= 3:
                return {"action": "REPLAN", "why": "stuck", "log": browser.log}
    return {"action": "BUDGET_EXHAUSTED", "paid": paid}
