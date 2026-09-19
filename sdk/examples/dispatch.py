"""Union dispatch: one route question fills only the winner's battery.

Billing, bug, and account vectors are S1-fillable routes, plus a plain callable
route (no second request). Surrogate fast-path included: confident
auto-handling skips the worker; unsure work goes to Codex and logs traces.
"""

from __future__ import annotations

from jevx.backends import Backend
from jevx.backends import Live
from jevx.contracts import ensure
from jevx.programs import surrogate
from jevx.py import choose_from
from jevx.py import noul
from jevx.py import score
from jevx.py import vector

ROUTES = {
    "billing": vector(
        urgent=noul("Reply within the hour?") >= 0.5,
        refund_ok=noul("Is a no-questions refund within policy?") >= 0.8,
    ),
    "bug": vector(
        repro=noul("Does the report reproduce the bug?"),
        severity=score("How severe?", ("cosmetic", "annoying", "blocking")),
    ),
    "account": vector(
        verified=noul("Is the requester identity verified?") >= 0.8,
    ),
    "spam": lambda state: {"action": "drop"},
}
ROUTE_DESCRIPTIONS = {
    "billing": "Charges, invoices, refunds, and subscriptions.",
    "bug": "Crashes, defects, and unexpected behavior.",
    "account": "Login, profile, and account access.",
    "spam": "Spam or irrelevant messages.",
}

CALIB: list = []
CALIB_MAX = 1000


def _write_reply(state: dict, route: str, filled) -> str:
    return f"[{route}] handled: {filled.as_dict()}"


@surrogate(
    question="safe to auto-handle without a worker?", reference=_write_reply, over=0.85, log=CALIB
)
def handle_routed(state: dict, route: str, filled) -> str:
    return f"[{route}] auto: {filled.as_dict()}"


@ensure(
    lambda *a, result=None, **k: result is not None
    and result["route"] in ("billing", "bug", "account", "spam"),
    msg="known route",
)
def dispatch(ticket: str, backend: Backend | None = None) -> dict:
    bk = backend or Live()
    name, filled = choose_from(
        ticket,
        ROUTES,
        descriptions=ROUTE_DESCRIPTIONS,
        instructions="Which ticket handler does this call for?",
        client=bk.s1(),
    )
    match (name, filled):
        case ("spam", {"action": action}):  # plain callable route took it
            return {"route": name, "action": action}
        case ("billing" | "bug" | "account", _):
            pass
        case _:
            raise AssertionError(f"route {name!r} returned an unexpected result")
    full_state = {"ticket": ticket, "route": name, "filled": filled.as_dict()}
    text, info = handle_routed(full_state, name, filled, client=bk.s1())
    if len(CALIB) > CALIB_MAX:
        del CALIB[: len(CALIB) - CALIB_MAX]
    return {"route": name, "text": text, "path": info["path"], "filled": filled.as_dict()}
