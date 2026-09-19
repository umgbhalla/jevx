"""A bounded incident workflow with typed decisions and task history.

The task scope binds S1 and S2, batches each battery into one S1 call, and
keeps a parent-linked record of judgments and work. Control flow stays Python.
"""

from __future__ import annotations

import json
from typing import Any

import jevx as j
from jevx import Backend
from jevx import Live
from jevx import ensure
from jevx import task
from jevx.redact import scrub

x = j.x

SYMPTOMS = j.vector(
    down=j.noul("is the service down or erroring?"),
    user_facing=j.noul("are users affected?"),
    data_risk=j.noul("is data loss or corruption plausible?"),
)

VERIFIED = (j.noul("are the reported symptoms gone from these logs?") >= 0.8) & (
    j.noul("does the fix address the root cause, not just symptoms?") >= 0.7
)

SYMPTOM_POLICY = (
    j.input(symptoms=x)
    | j.case[
        x.symptoms.down < 0.5: j.stop("NOOP", why="no outage in logs"),
        x.symptoms.data_risk >= 0.35: j.stop(
            "ESCALATE",
            why="possible data risk - human first",
            sev=j.compute(
                lambda user_facing: "SEV-1" if user_facing >= 0.5 else "SEV-2",
                x.symptoms.user_facing,
            ),
        ),
        ...: j.stop("CONTINUE"),
    ]
)


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
        symptoms = run.ask(SYMPTOMS, logs)
        stop = SYMPTOM_POLICY.run(symptoms=symptoms)
        if stop["action"] != "CONTINUE":
            return _result(run, **{key: value for key, value in stop.items() if key != "action"}, action=stop["action"])
        severity = "SEV-1" if symptoms.user_facing >= 0.5 else "SEV-2"
        for round_no in range(max_rounds):
            h = run.pick(
                "most likely cause?",
                {**run.context(), "logs": logs[-4000:], "round": round_no},
                HYPOTHESES,
            )
            selection = j.case[
                h.confidence < 0.5: "uncertain",
                ...: "selected",
            ].ask({})
            if selection == "uncertain":
                return _result(run, action="ESCALATE", why="hypothesis unsure", round=round_no)
            cause = h.choice
            if cause in RISKY_HYPOTHESES and approve is not None and not approve(cause, None):
                return _result(run, action="APPROVAL", why=f"{cause} needs approval", round=round_no)

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
                verified = run.ask(VERIFIED, {"logs": new_logs[-4000:], "fix": fix})
                if verified:
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
                "q0": [
                    {"type": "noul", "noul": 0.99},
                    {"type": "noul", "noul": 0.2},
                    {"type": "noul", "noul": 0.95},
                ],
                "q1": [
                    {"type": "noul", "noul": 0.92},
                    {"type": "noul", "noul": 0.5},
                    {"type": "noul", "noul": 0.9},
                ],
                "q2": [{"type": "noul", "noul": 0.08}],
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
