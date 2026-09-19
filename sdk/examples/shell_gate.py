"""Shell gate: typed questions before execution, routine cmds free.

Ports the jev-axi shape: an allowlist classifies routine commands locally
with zero requests; everything else fans out per-command questions (risk
Score + secrets/behavior/leftovers Nouls) plus a diff-focus Score, then a
CRAP-style verdict. Refuse / review / run.
"""

from __future__ import annotations

import re
import shlex

import jevx as j
from jevx.backends import Backend
from jevx.backends import Live
from jevx.contracts import ensure
from jevx.risk import blast_of
from jevx.risk import risk
from jevx.risk import verdict

x = j.x

ROUTINE = {
    "ls",
    "pwd",
    "echo",
    "cat",
    "head",
    "tail",
    "wc",
    "date",
    "whoami",
    "git status",
    "git diff",
    "git log",
    "pytest --collect-only",
}

_SAFE_ARG = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-/]*$")


def is_routine(cmd: str) -> bool:
    """Exact-match or bare read-only binary with safe args. Any metachar -> False."""
    import re as _re

    if _re.search(r"[;&|><`$()#\n]", cmd):
        return False
    if cmd.strip() in ROUTINE:
        return True
    try:
        parts = shlex.split(cmd)
    except ValueError:
        return False
    return (
        bool(parts)
        and parts[0] in ("ls", "pwd", "true")
        and all(_SAFE_ARG.match(a) for a in parts[1:])
    )


CHECK = j.vector(
    risk_level=j.score(
        "How risky is this command to run without extra review? Judge blast radius and reversibility, not size.",
        (
            "cosmetic or isolated: formatting, comments, docs, tests only",
            "moderate: one code path, limited callers, easy revert",
            "high: auth, payments, migration, concurrency, secrets, deletion, shared interface",
        ),
    ),
    secrets=j.noul("Does this expose a credential, token, key, password, or connection string?"),
    behavior=j.noul("Does this change runtime state, as opposed to only reading?"),
    leftovers=j.noul("Is this a leftover, placeholder, or TODO rather than a real command?"),
)


def _assessment(risk_level, secrets, behavior, leftovers):
    has_secrets = secrets >= 0.5
    changes_state = behavior >= 0.5
    has_leftovers = leftovers >= 0.7
    blast = blast_of(
        0.9 if has_secrets else 0.0,
        0.7 if changes_state else 0.1,
        0.5 if float(risk_level) >= 1.5 else 0.1,
    )
    confidence = 1.0 - (float(risk_level) / 2.0) * 0.5 - (0.3 if has_secrets else 0.0)
    status = verdict(risk(blast, max(0.0, min(1.0, confidence))), review_at=1.5, refuse_at=4.0)
    return {
        "secrets": 1.0 if has_secrets else 0.0,
        "leftovers": 1.0 if has_leftovers else 0.0,
        "status": status,
    }


POLICY = (
    j.input(command=x)
    | j.keep(check=CHECK.on(x.command))
    | j.keep(
        assessment=j.compute(
            _assessment,
            x.check.risk_level,
            x.check.secrets,
            x.check.behavior,
            x.check.leftovers,
        )
    )
    | j.case[
        (x.assessment.secrets >= 1.0) | (x.assessment.status == "refuse"):
            j.stop("refuse", verdict="refuse", risk=x.assessment.status),
        (x.assessment.status == "review") | (x.assessment.leftovers >= 1.0):
            j.stop("review", verdict="review", risk=x.assessment.status),
        ...: j.stop("run", verdict="run", risk=x.assessment.status),
    ]
)


@ensure(
    lambda *a, result=None, **k: (
        result is not None and result["verdict"] in ("run", "review", "refuse")
    ),
    msg="known gate verdict",
)
def gate(cmd: str, backend: Backend | None = None) -> dict:
    if is_routine(cmd):
        return {"verdict": "run", "why": "routine-local", "requests": 0}
    result = POLICY.run(command=cmd, backend=backend or Live())
    return {key: value for key, value in result.items() if key != "action"}
