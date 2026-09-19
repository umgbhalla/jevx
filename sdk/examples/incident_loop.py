"""A bounded incident workflow with typed decisions and task history.

The task scope binds S1 and S2, batches each battery into one S1 call, and
keeps a parent-linked record of judgments and work. Control flow stays Python.
"""

from __future__ import annotations

import json
from typing import Any

from jevx import Backend
from jevx import ChoiceAnswer
from jevx import Live
from jevx import Questions
from jevx import ask
from jevx import ensure
from jevx import task
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


def _result(run, **result: Any) -> dict[str, Any]:
    return {**result, "history": list(run.history), "head": run.head}


@ensure(
    lambda *a, result=None, **k: result is not None
    and result["action"] in ("NOOP", "ESCALATE", "RESOLVED", "APPROVAL"),
    msg="known incident action",
)
def respond(
    logs: str,
    backend: Backend | None = None,
    max_rounds: int = 4,
    fetch_logs=None,
    approve=None,
) -> dict[str, Any]:
    """Use injected log/approval hooks and a scripted backend for offline runs."""
    logs = scrub(logs)
    with task("incident", backend if backend is not None else Live()) as run:
        symptoms = run.ask(Symptoms, logs)
        if symptoms.down is False:
            return _result(run, action="NOOP", why="no outage in logs")
        if symptoms.data_risk:
            return _result(
                run,
                action="ESCALATE",
                why="possible data risk - human first",
                sev="SEV-1" if symptoms.user_facing else "SEV-2",
            )

        severity = "SEV-1" if symptoms.user_facing else "SEV-2"
        for round_no in range(max_rounds):
            h = run.pick(
                "most likely cause?",
                {**run.context(), "logs": logs[-4000:], "round": round_no},
                HYPOTHESES,
            )
            match h:
                case ChoiceAnswer(confidence=confidence) if confidence < 0.5:
                    return _result(run, action="ESCALATE", why="hypothesis unsure", round=round_no)
                case ChoiceAnswer(choice=cause, confidence=_) if (
                    cause in RISKY_HYPOTHESES
                    and approve is not None
                    and not approve(cause, None)
                ):
                    return _result(
                        run, action="APPROVAL", why=f"{cause} needs approval", round=round_no
                    )
                case ChoiceAnswer(choice=cause):
                    pass

            with run.branch(f"round {round_no}: {cause}", restore=False):
                fix = run.s2.ask(
                    "Investigate and fix this incident.\n"
                    f"Task context: {json.dumps(run.context(), sort_keys=True)}\n"
                    f"Hypothesis: {cause} ({HYPOTHESES[cause]})\n"
                    f"Logs: {scrub(logs[-4000:])}"
                )
                new_logs = scrub(
                    fetch_logs()
                    if fetch_logs
                    else run.s2.ask("Show fresh logs/errors after the fix attempt above.")
                )
                run.record("observation", summary="collected post-fix logs", logs=new_logs[-4000:])
                verified = run.ask(Verify, {"logs": new_logs[-4000:], "fix": fix})
                if verified.gone and verified.caused:
                    return _result(
                        run,
                        action="RESOLVED",
                        rounds=round_no + 1,
                        hypothesis=cause,
                        sev=severity,
                    )

            logs = (logs + "\n" + new_logs)[-8000:]
            run.record("round", summary=f"round {round_no} did not verify")

        return _result(run, action="ESCALATE", why="rounds exhausted", rounds=max_rounds)


if __name__ == "__main__":
    from jevx import Sim

    result = respond(
        "500 errors from the database connection pool",
        Sim(
            s1_script={
                "down": [{"type": "noul", "noul": 0.99}],
                "user_facing": [{"type": "noul", "noul": 0.92}],
                "data_risk": [{"type": "noul", "noul": 0.08}],
                "c": [
                    {
                        "type": "choice",
                        "choice": "db",
                        "probabilities": {"db": 0.9, "bad_deploy": 0.05, "traffic": 0.03, "external": 0.02},
                        "confidence": 0.9,
                    },
                    {
                        "type": "choice",
                        "choice": "db",
                        "probabilities": {"db": 0.9, "bad_deploy": 0.05, "traffic": 0.03, "external": 0.02},
                        "confidence": 0.9,
                    },
                ],
                "gone": [{"type": "noul", "noul": 0.2}, {"type": "noul", "noul": 0.95}],
                "caused": [{"type": "noul", "noul": 0.5}, {"type": "noul", "noul": 0.9}],
            },
            s2_texts=["Checked the pool cap; the errors continue.", "Lowered the pool cap; saturation stopped."],
        ),
        fetch_logs=iter(
            [
                "Database timeouts continue after the first attempt.",
                "No new database timeouts in the last five minutes.",
            ]
        ).__next__,
    )
    assert result["action"] == "RESOLVED"
    assert result["history"][0]["parent"] is None
    assert result["history"][-1]["parent"] == result["history"][-2]["id"]
    branches = [event for event in result["history"] if event["kind"] == "branch"]
    assert len(branches) == 2
    second_pick = [event for event in result["history"] if event["kind"] == "jev.pick"][1]
    assert branches[1]["parent"] == second_pick["id"]
    assert any(event["kind"] == "round" for event in second_pick["state"]["history"])
    print(json.dumps({k: v for k, v in result.items() if k != "history"}, indent=2))
    print(json.dumps(result["history"], indent=2))
