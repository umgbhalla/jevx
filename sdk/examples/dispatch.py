"""Union dispatch: one route question fills only the winner's battery.

BillingQs | BugQs | AccountQs as S1-fillable routes, plus a plain callable
route (no second request). Surrogate fast-path included: confident
auto-handling skips the worker; unsure work goes to Codex and logs traces.
"""

from __future__ import annotations

from typing import Literal

from jevx.backends import Backend, Live
from jevx.programs import surrogate
from jevx.py import Questions, Score, ask, choose_from


class BillingQs(Questions):
    """Triage a billing ticket."""

    urgent: bool = ask("reply within the hour?")
    refund_ok: bool = ask("is a no-questions refund within policy?", threshold=0.8)


class BugQs(Questions):
    """Triage a bug report."""

    repro: bool = ask("does the report reproduce the bug?")
    severity: Score["cosmetic", "annoying", "blocking"] = ask("how severe?")


class AccountQs(Questions):
    """Triage an account request."""

    verified: bool = ask("is the requester identity verified?", threshold=0.8)


CALIB: list = []


def _write_reply(state: dict, route: str, filled) -> str:
    return f"[{route}] handled: {filled.as_dict()}"


@surrogate(question="safe to auto-handle without a worker?", reference=_write_reply,
           over=0.85, log=CALIB)
def handle_routed(state: dict, route: str, filled) -> str:
    return f"[{route}] auto: {filled.as_dict()}"


def dispatch(ticket: str, backend: Backend | None = None) -> dict:
    bk = backend or Live()
    name, filled = choose_from(
        ticket,
        {"billing": BillingQs, "bug": BugQs, "account": AccountQs,
         "spam": lambda state: {"action": "drop"}},
        instructions="Which ticket handler does this call for?",
        client=bk.s1(),
    )
    if isinstance(filled, dict):  # plain callable route took it
        return {"route": name, **filled}
    text, info = handle_routed({"ticket": ticket}, name, filled, client=bk.s1())
    return {"route": name, "text": text, "path": info["path"], "filled": filled.as_dict()}
