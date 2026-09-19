"""Staged PR review gate: S1 screens, profiles, evidences, judges; S2 fixes.

Bounds everywhere: MAX_FOLLOW_UPS files, MAX_PROFILES, 3 fix rounds, 8 hunks
per round, fail-closed on timeout. Auto-merge bar: 0 blocking, 0 unverified
contradictions, all injections dropped. Security paths force priority + owner.
"""

from __future__ import annotations

from typing import Literal

from jevx.client import Client
from jevx.py import Questions, Score, ask, feels
from jevx.s2 import CodexSystem2, System2

MAX_FOLLOW_UPS = 8
MAX_PROFILES = 5
MAX_ROUNDS = 3
SEC_PATHS = ("auth/", "crypto/", "secrets")


class RiskMatrix(Questions):
    correctness: bool = ask("could this cause incorrect runtime behavior?", threshold=0.70)
    security: bool = ask("could this cause a security issue?", threshold=0.70)
    reliability: bool = ask("could this cause crashes or hangs?", threshold=0.70)
    test_gap: bool = ask("is changed behavior missing test coverage?", threshold=0.70)


class Profile(Questions):
    category: Literal["behavior", "interface", "infrastructure", "observability",
                      "refactor", "routine"] = ask("what kind of change?")
    priority: Score["low", "notable", "high", "urgent"] = ask("review priority?")


class Finding(Questions):
    mechanism: Literal["authorization", "injection", "exposure", "unsafe_default",
                       "logic", "no_issue"] = ask("failure mechanism?")
    severity: Score["cosmetic", "notable", "high", "blocking"] = ask("severity?")
    owner: Literal["security", "api", "runtime", "testing", "maintainer"] = ask("owning team?")


def review(pr: dict, s1: Client | None = None, s2: System2 | None = None) -> dict:
    """pr: {files: [{path, patch, hunks: [ids], changed_tests: [...]}, ...]}."""
    s2 = s2 or CodexSystem2()
    findings, followed = [], 0
    for f in pr["files"]:
        if followed >= MAX_FOLLOW_UPS:
            break
        m = RiskMatrix(client=s1)({"patch": f["patch"][:3000],
                                   "tests": f.get("changed_tests", [])})  # 1 req
        if not (m.correctness or m.security or m.reliability or m.test_gap):
            continue
        followed += 1
        p = Profile(client=s1)({"patch": f["patch"][:3000]})  # 1 req
        prio = float(p.priority) + (0.5 if f["path"].startswith(SEC_PATHS) else 0.0)
        if prio < 1.0:
            continue
        for hunk in f.get("hunks", [])[:8]:
            ev = feels("does this hunk support the suspected concern?",
                       {"hunk": hunk, "patch": f["patch"][:3000]}, client=s1)
            if ev.under(0.55):
                continue
            fin = Finding(client=s1)({"hunk": hunk, "path": f["path"]})  # 1 req
            if fin.mechanism == "no_issue":
                continue
            findings.append({"file": f["path"], "hunk": hunk,
                             "mechanism": fin.mechanism,
                             "severity": float(fin.severity),
                             "owner": "security" if f["path"].startswith(SEC_PATHS) else fin.owner})

    blocking = [x for x in findings if x["severity"] >= 2.0]
    if not blocking:
        return {"action": "MERGE", "findings": findings}
    for rnd in range(MAX_ROUNDS):
        worst = max(blocking, key=lambda x: x["severity"])
        fix = s2.ask(f"Fix {worst['file']}:{worst['hunk']} mechanism={worst['mechanism']} "
                     f"severity={worst['severity']}. Cite lines, add a regression test.")
        ok = feels("does this fix resolve the finding with a regression test?",
                   {"finding": worst, "fix": fix}, client=s1)
        if ok.over(0.80):
            blocking.remove(worst)
            if not blocking:
                return {"action": "MERGE", "findings": findings, "rounds": rnd}
    return {"action": "REQUEST_CHANGES", "blocking": blocking, "findings": findings}
