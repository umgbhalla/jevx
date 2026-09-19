"""Support copilot: System 1 triages, routes, and verifies; System 2 drafts.

S1 owns every decision (one battery per step, confidence-gated). S2 only writes
prose inside a scope S1 chose, and nothing sends without S1 verification.
Tickets are redacted before any model call; drafts send only when the Verify
battery passes WITH confidence.
"""

from __future__ import annotations

from jevx.backends import Backend
from jevx.backends import Live
from jevx.contracts import ensure
from jevx.programs import repair
from jevx.py import choice
from jevx.py import noul
from jevx.py import vector

TRIAGE = vector(
    urgent=noul("reply within the hour?"),
    team=choice(
        "which team owns it?",
        {"billing": "charges and refunds", "bug": "product defects", "account": "access"},
    ),
    autoreply_ok=noul("safe to auto-reply with a template?"),
)


_answers = noul("does the draft answer the ticket?")
_leaks = noul("does the draft leak secrets or internal detail?")
_overpromises = noul("does the draft promise what we can't do?")
_ready_to_send = (_answers >= 0.70) & (_leaks <= 0.30) & (_overpromises <= 0.30)


TEMPLATES = {
    "billing": "Thanks — we've flagged the charge for review and will update you within a day.",
    "bug": "Thanks — we've reproduced this and filed it; a fix is queued.",
    "account": "Thanks — check your inbox for a reset link, valid 24h.",
}

HUMAN = "route:human"


def redact(ticket: str) -> str:
    from jevx.redact import scrub

    return scrub(ticket)


@ensure(
    lambda *a, result=None, **k: (
        result is not None and result["action"] in ("send-template", "send-draft", HUMAN)
    ),
    msg="known support action",
)
def handle(ticket: str, backend: Backend | None = None) -> dict:
    bk = backend or Live()
    s1, s2 = bk.s1(), bk.s2()
    clean = redact(ticket)
    t = TRIAGE.ask(clean, client=s1)  # 1 request: three named judgments
    p_urgent = float(t.urgent)
    if t.team.confidence < 0.6 or 0.35 <= p_urgent <= 0.70:
        return {"action": HUMAN, "why": "low triage confidence"}
    if t.autoreply_ok >= 0.75:
        return {"action": "send-template", "text": TEMPLATES[t.team.choice], "triage": t}

    def check(draft: str) -> tuple[bool, str]:
        ok = _ready_to_send.ask({"ticket": clean, "draft": draft}, client=s1)
        return (
            ok,
            "all three verification thresholds passed" if ok else "verification thresholds failed",
        )

    def revise(draft: str, critique: str) -> str:
        return s2.ask(f"Revise. {critique} Ticket: {clean} Draft: {draft}")

    final, ok = repair(
        lambda: s2.ask(f"Draft a short customer reply. Team: {t.team.choice}. Ticket: {clean}"),
        check,
        revise,
        rounds=1,
        client=s1,
    )
    if ok:
        return {"action": "send-draft", "text": final, "triage": t}
    return {"action": HUMAN, "why": "verification failed", "draft": final}
