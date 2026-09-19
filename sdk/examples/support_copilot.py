"""Support copilot: System 1 triages, routes, and verifies; System 2 drafts.

S1 owns every decision (one battery per step, confidence-gated). S2 only writes
prose inside a scope S1 chose, and nothing sends without S1 verification.
"""

from __future__ import annotations

from typing import Any, Literal

from jevx.backends import Backend, Live
from jevx.py import Questions, ask


class Triage(Questions):
    urgent: bool = ask("reply within the hour?")
    team: Literal["billing", "bug", "account"] = ask("which team owns it?")
    autoreply_ok: bool = ask("safe to auto-reply with a template?", threshold=0.75)


class Verify(Questions):
    answers_q: bool = ask("does the draft answer the ticket?")
    leaks: bool = ask("does the draft leak secrets or internal detail?")
    overpromises: bool = ask("does the draft promise what we can't do?")


TEMPLATES = {
    "billing": "Thanks — we've flagged the charge for review and will update you within a day.",
    "bug": "Thanks — we've reproduced this and filed it; a fix is queued.",
    "account": "Thanks — check your inbox for a reset link, valid 24h.",
}

HUMAN = "route:human"


def handle(ticket: str, backend: Backend | None = None) -> dict:
    bk = backend or Live()
    s1, s2 = bk.s1(), bk.s2()
    t = Triage(client=s1)(ticket)  # 1 request
    p_urgent = t.answers["urgent"].prob
    if t.confidence("team") < 0.6 or 0.35 <= p_urgent <= 0.70:
        return {"action": HUMAN, "why": "low triage confidence"}
    if t.autoreply_ok:
        return {"action": "send-template", "text": TEMPLATES[t.team], "triage": t}

    draft = s2.ask(f"Draft a short customer reply. Team: {t.team}. Ticket: {ticket}")
    v = Verify(client=s1)( {"ticket": ticket, "draft": draft} )  # 1 request
    if v.answers_q and v.leaks is False and v.overpromises is False:
        return {"action": "send-draft", "text": draft, "triage": t}
    critique = (
        f"Revise. answers={v.answers_q} leaks={v.leaks} overpromises={v.overpromises}."
    )
    draft2 = s2.ask(f"{critique} Ticket: {ticket} Draft: {draft}")
    v2 = Verify(client=s1)({"ticket": ticket, "draft": draft2})  # 1 request
    if v2.answers_q and v2.leaks is False and v2.overpromises is False:
        return {"action": "send-draft-rev1", "text": draft2, "triage": t}
    return {"action": HUMAN, "why": "verification failed twice", "draft": draft2}
