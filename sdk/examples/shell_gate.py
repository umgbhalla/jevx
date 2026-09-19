"""Shell gate: typed questions before execution, routine cmds free.

Ports the jev-axi shape: an allowlist classifies routine commands locally
with zero requests; everything else fans out per-command questions (risk
Score + secrets/behavior/leftovers Nouls) plus a diff-focus Score, then a
CRAP-style verdict. Refuse / review / run.
"""

from __future__ import annotations

import shlex

from jevx.client import Client
from jevx.py import Questions, Score, ask
from jevx.risk import blast_of, risk, verdict

ROUTINE = {"ls", "pwd", "echo", "cat", "head", "tail", "wc", "date", "whoami",
           "git status", "git diff", "git log", "pytest --collect-only"}


def is_routine(cmd: str) -> bool:
    try:
        parts = shlex.split(cmd)
    except ValueError:
        return False
    return cmd.strip() in ROUTINE or (parts and parts[0] in ("ls", "echo", "pwd", "true"))


class CmdCheck(Questions):
    risk_level: Score["cosmetic or isolated: formatting, comments, docs, tests only",
                      "moderate: one code path, limited callers, easy revert",
                      "high: auth, payments, migration, concurrency, secrets, deletion, shared interface"] = \
        ask("How risky is this command to run without extra review? Judge blast radius and reversibility, not size.")
    secrets: bool = ask("Does this expose a credential, token, key, password, or connection string?")
    behavior: bool = ask("Does this change runtime state, as opposed to only reading?")
    leftovers: bool = ask("Is this a leftover, placeholder, or TODO rather than a real command?", threshold=0.7)


def gate(cmd: str, s1: Client | None = None) -> dict:
    if is_routine(cmd):
        return {"verdict": "run", "why": "routine-local", "requests": 0}
    c = CmdCheck(client=s1)({"command": cmd})  # 1 request
    blast = blast_of(0.9 if c.secrets else 0.0, 0.7 if c.behavior else 0.1,
                     0.5 if float(c.risk_level) >= 1.5 else 0.1)
    conf = 1.0 - (float(c.risk_level) / 2.0) * 0.5 - (0.3 if c.secrets else 0.0)
    v = verdict(risk(blast, max(0.0, min(1.0, conf))), review_at=1.5, refuse_at=4.0)
    if c.secrets or v == "refuse":
        return {"verdict": "refuse", "risk": v}
    if v == "review" or c.leftovers:
        return {"verdict": "review", "risk": v}
    return {"verdict": "run", "risk": v}
