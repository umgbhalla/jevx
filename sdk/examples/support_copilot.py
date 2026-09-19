"""Support copilot: System 1 triages, routes, and verifies; System 2 drafts.

Redact first, batch each judgment battery, and keep the send threshold in code.
A failed first check gets one rewrite; only a passing verification can send.
"""

from __future__ import annotations

import jevx as j
from jevx.backends import Backend
from jevx.backends import Live
from jevx.contracts import ensure

x = j.x

TRIAGE = j.vector(
    urgent=j.noul("Does this need a reply within the hour?"),
    team=j.choice(
        "Which team owns this ticket?",
        {"billing": "charges and refunds", "bug": "product defects", "account": "access"},
    ),
    autoreply_ok=j.noul("Is it safe to auto-reply with a template?"),
)

VERIFY = j.vector(
    answered=j.noul("Does the draft answer the ticket?"),
    leaks=j.noul("Does it reveal secrets or internal details?"),
    overpromises=j.noul("Does it promise something we cannot do?"),
)

TEMPLATES = {
    "billing": "Thanks — we've flagged the charge for review and will update you within a day.",
    "bug": "Thanks — we've reproduced this and filed it; a fix is queued.",
    "account": "Thanks — check your inbox for a reset link, valid 24h.",
}
HUMAN = "route:human"


def redact(ticket: str) -> str:
    from jevx.redact import scrub

    return scrub(ticket)


def _template(team: str) -> str:
    return TEMPLATES[team]


@j.s2
def draft(ticket: str, team: str) -> str:
    """Draft a short customer reply for the selected team. Use only this ticket."""


@j.s2
def revise(ticket: str, draft: str, checks: dict) -> str:
    """Revise the customer reply to fix these checks. Do not add unsupported promises."""


_READY = (
    (x.check.answered >= 0.70)
    & (x.check.leaks <= 0.30)
    & (x.check.overpromises <= 0.30)
)
_REVISED_READY = (
    (x.recheck.answered >= 0.70)
    & (x.recheck.leaks <= 0.30)
    & (x.recheck.overpromises <= 0.30)
)

SUPPORT = (
    j.input(ticket=x)
    | j.keep(clean=j.compute(redact, x.ticket))
    | j.keep(triage=TRIAGE.on({"ticket": x.clean}))
    | j.case[
        (x.triage.team.confidence < 0.60)
        | ((x.triage.urgent >= 0.35) & (x.triage.urgent <= 0.70)):
            j.stop(HUMAN, why="low triage confidence"),
        x.triage.autoreply_ok >= 0.75:
            j.stop(
                "send-template",
                text=j.compute(_template, x.triage.team.choice),
                triage=x.triage,
            ),
        ...: j.pass_,
    ]
    | j.keep(draft=draft(x.clean, x.triage.team.choice))
    | j.keep(check=VERIFY.on({"ticket": x.clean, "draft": x.draft}))
    | j.case[
        _READY: j.stop("send-draft", text=x.draft, triage=x.triage),
        ...: j.pass_,
    ]
    | j.keep(
        revised=revise(
            x.clean,
            x.draft,
            {
                "answered": x.check.answered,
                "leaks": x.check.leaks,
                "overpromises": x.check.overpromises,
            },
        )
    )
    | j.keep(recheck=VERIFY.on({"ticket": x.clean, "draft": x.revised}))
    | j.case[
        _REVISED_READY:
            j.stop("send-draft", text=x.revised, triage=x.triage),
        ...: j.stop(HUMAN, why="verification failed", draft=x.revised),
    ]
)


@ensure(
    lambda *a, result=None, **k: (
        result is not None and result["action"] in ("send-template", "send-draft", HUMAN)
    ),
    msg="known support action",
)
def handle(ticket: str, backend: Backend | None = None) -> dict:
    return SUPPORT.run(ticket=ticket, backend=backend or Live())
