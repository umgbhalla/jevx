"""Incident loop: S1 monitors, hypothesizes, verifies; S2 debugs and fixes.

`while feels(...).over()` is the whole control plane: symptom Nouls open the
loop, a Choice picks the hypothesis, verification Nouls close it. Bounded, so
an unsure S1 escalates instead of spinning.
"""

from __future__ import annotations

from jevx.backends import Backend
from jevx.backends import Live
from jevx.contracts import ensure
from jevx.py import Questions
from jevx.py import ask
from jevx.redact import scrub


class Symptoms(Questions):
    down: bool = ask("is the service down or erroring?")
    user_facing: bool = ask("are users affected?")
    data_risk: bool = ask("is data loss or corruption plausible?", threshold=0.35)


class Verify(Questions):
    gone: bool = ask("are the reported symptoms gone from these logs?", threshold=0.8)
    caused: bool = ask("does the fix address the root cause, not just symptoms?", threshold=0.7)


HYPOTHESES = {
    "bad_deploy": "a recent deploy broke it; check deploys and roll back",
    "db": "database slowness, locks, or connection exhaustion",
    "traffic": "traffic spike or hot keys overwhelming capacity",
    "external": "a third-party dependency is degraded",
}

RISKY_HYPOTHESES = {"bad_deploy", "db"}


@ensure(
    lambda *a, result=None, **k: result["action"] in ("NOOP", "ESCALATE", "RESOLVED", "APPROVAL"),
    msg="known incident action",
)
def respond(
    logs: str, backend: Backend | None = None, max_rounds: int = 4, fetch_logs=None, approve=None
) -> dict:
    """fetch_logs() -> fresh logs from monitoring (independent of S2).
    approve(hypothesis, fix) -> bool for risky hypotheses. Both injectable."""
    bk = backend or Live()
    s1 = bk.s1()
    logs = scrub(logs)
    sym = Symptoms(client=s1)(logs)  # 1 request
    if sym.down is False:
        return {"action": "NOOP", "why": "no outage in logs"}
    if sym.data_risk:
        return {
            "action": "ESCALATE",
            "why": "possible data risk — human first",
            "sev": "SEV-1" if sym.user_facing else "SEV-2",
        }
    sev = "SEV-1" if sym.user_facing else "SEV-2"

    s2 = bk.s2()
    from jevx.py import pick

    for rnd in range(max_rounds):
        h = pick("most likely cause?", {"logs": logs[-4000:], "round": rnd}, HYPOTHESES, client=s1)
        if h.confidence < 0.5:
            return {"action": "ESCALATE", "why": "hypothesis unsure", "round": rnd}
        if h.choice in RISKY_HYPOTHESES and approve is not None and not approve(h.choice, None):
            return {"action": "APPROVAL", "why": f"{h.choice} needs approval", "round": rnd}
        fix = s2.ask(
            f"Investigate and fix. Hypothesis: {h.choice} ({HYPOTHESES[h.choice]}). "
            f"Logs: {scrub(logs[-4000:])}"
        )
        new_logs = scrub(
            fetch_logs()
            if fetch_logs
            else s2.ask("Show fresh logs/errors after the fix attempt above.")
        )
        v = Verify(client=s1)({"logs": new_logs[-4000:], "fix": fix})  # 1 request
        if v.gone and v.caused:
            return {"action": "RESOLVED", "rounds": rnd, "hypothesis": h.choice, "sev": sev}
        logs = (logs + "\n" + new_logs)[-8000:]
    return {"action": "ESCALATE", "why": "rounds exhausted", "rounds": max_rounds}
