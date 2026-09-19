"""Support copilot: System 1 triages, routes, and verifies; System 2 drafts.

S1 owns every decision (one battery per step, confidence-gated). S2 only writes
prose inside a scope S1 chose, and nothing sends without S1 verification.
Tickets are redacted before any model call; drafts send only when the Verify
battery passes WITH confidence.
"""

from __future__ import annotations

from typing import Literal
from typing import Protocol

from jevx.backends import Backend
from jevx.backends import Live
from jevx.contracts import ensure
from jevx.programs import repair
from jevx.py import Questions
from jevx.py import ask


class TriageResult(Protocol):
    urgent: bool
    team: Literal["billing", "bug", "account"]
    autoreply_ok: bool
    answers: dict

    def confidence(self, name: str) -> float | None: ...


class VerifyResult(Protocol):
    answers_q: bool
    leaks: bool
    overpromises: bool
    answers: dict

    def confidence(self, name: str) -> float | None: ...


class Triage(Questions[TriageResult]):
    urgent: bool = ask("reply within the hour?")
    team: Literal["billing", "bug", "account"] = ask("which team owns it?")
    autoreply_ok: bool = ask("safe to auto-reply with a template?", threshold=0.75)


class Verify(Questions[VerifyResult]):
    answers_q: bool = ask("does the draft answer the ticket?")
    leaks: bool = ask("does the draft leak secrets or internal detail?")
    overpromises: bool = ask("does the draft promise what we can't do?")


TEMPLATES = {
    "billing": "Thanks — we've flagged the charge for review and will update you within a day.",
    "bug": "Thanks — we've reproduced this and filed it; a fix is queued.",
    "account": "Thanks — check your inbox for a reset link, valid 24h.",
}

HUMAN = "route:human"
DECISIVE = 0.4  # min |P-0.5|*2 across the battery: every Noul must be decisive


def redact(ticket: str) -> str:
    from jevx.redact import scrub

    return scrub(ticket)


@ensure(
    lambda *a, result=None, **k: result is not None
    and result["action"] in ("send-template", "send-draft", HUMAN),
    msg="known support action",
)
def handle(ticket: str, backend: Backend | None = None) -> dict:
    bk = backend or Live()
    s1, s2 = bk.s1(), bk.s2()
    clean = redact(ticket)
    t = Triage(client=s1).ask(clean)  # 1 request
    p_urgent = t.answers["urgent"].prob
    if (t.confidence("team") or 0.0) < 0.6 or 0.35 <= p_urgent <= 0.70:
        return {"action": HUMAN, "why": "low triage confidence"}
    if t.autoreply_ok and abs(t.answers["autoreply_ok"].prob - 0.5) * 2 >= DECISIVE:
        return {"action": "send-template", "text": TEMPLATES[t.team], "triage": t}

    def check(draft: str) -> tuple[bool, str]:
        v = Verify(client=s1).ask({"ticket": clean, "draft": draft})
        probs = [v.answers[k].prob for k in ("answers_q", "leaks", "overpromises")]
        margin = min(abs(p - 0.5) * 2 for p in probs)  # Nouls carry no confidence
        ok = v.answers_q and v.leaks is False and v.overpromises is False and margin >= DECISIVE
        return ok, (
            f"answers={v.answers_q} leaks={v.leaks} "
            f"overpromises={v.overpromises} margin={margin:.2f}"
        )

    def revise(draft: str, critique: str) -> str:
        return s2.ask(f"Revise. {critique} Ticket: {clean} Draft: {draft}")

    final, ok = repair(
        lambda: s2.ask(f"Draft a short customer reply. Team: {t.team}. Ticket: {clean}"),
        check,
        revise,
        rounds=1,
        client=s1,
    )
    if ok:
        return {"action": "send-draft", "text": final, "triage": t}
    return {"action": HUMAN, "why": "verification failed", "draft": final}
