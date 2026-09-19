"""Staged PR review funnel: screen -> profile -> locate -> mechanism -> severity -> route.

Ports: verbatim 5-Noul screen, category Choice + priority Score, evidence-hunk
Choice with noMatch exit, per-dimension mechanism with noIssue exit, severity
Score, conditional owner route. Thresholds 0.70 / 0.55 / 1.5 / 2.0.
Findings are review prompts, not proof of defect — S2 fixes, S1 re-checks.
"""

from __future__ import annotations

from typing import Literal

from jevx.py import Questions, Score, ask, feels
from jevx.backends import Backend, Live

SCREEN_AT, LOCATE_AT, ROUTE_SEV, BLOCK_SEV = 0.70, 0.55, 1.5, 2.0
MAX_FOLLOW_UPS, MAX_PROFILES, MAX_ROUNDS, HUNKS_PER_ROUND = 8, 5, 3, 8
SEC_PATHS = ("auth/", "crypto/", "secrets")


class Screen(Questions):
    correctness: bool = ask("Does the patch directly support that this change likely introduces incorrect runtime behavior?", threshold=SCREEN_AT)
    security: bool = ask("Does the patch directly support that this change introduces or weakens a security boundary?", threshold=SCREEN_AT)
    reliability: bool = ask("Does the patch directly support that this change can crash, race, leak, deadlock, or recover poorly?", threshold=SCREEN_AT)
    compatibility: bool = ask("Does the patch directly support that this change can break an existing caller, format, protocol, or public behavior?", threshold=SCREEN_AT)
    test_gap: bool = ask("Does the patch change important behavior without adequate targeted evidence in changed tests?", threshold=SCREEN_AT)


class Profile(Questions):
    category: Literal["behavior", "interface", "infrastructure", "observability",
                      "refactor", "routine"] = ask("Which category best describes the patch?")
    priority: Score["low", "notable", "high", "urgent"] = ask("Rate how closely a human should review the patch.")


class Finding(Questions):
    mechanism: Literal["authorization", "injection", "exposure", "unsafe_default",
                       "logic", "race", "leak", "no_issue"] = ask("Which mechanism best describes the suspected concern supported by the selected evidence?")
    severity: Score["cosmetic", "notable", "high", "blocking"] = ask("Assuming the evidence exhibits the concern, rate the likely production impact.")
    owner: Literal["security", "api", "runtime", "testing", "maintainer"] = ask("Which reviewer is best suited to investigate this concern?")


def _pick(prompt: str, state: dict, options: dict, s1) -> tuple[str, float]:
    from jevx.py import pick
    c = pick(prompt, state, options, client=s1)
    return c.choice, c.confidence


def review(pr: dict, backend: Backend | None = None) -> dict:
    bk = backend or Live()
    s1, s2 = bk.s1(), bk.s2()
    """pr: {files: [{path, patch, hunks: [ids], changed_tests: [...]}, ...]}."""
    from jevx.prompts import render
    findings, followed, profiled = [], 0, 0
    for f in pr["files"]:
        if followed >= MAX_FOLLOW_UPS or profiled >= MAX_PROFILES:
            break
        m = Screen(client=s1)({"patch": f["patch"][:3000],
                               "changed_tests": f.get("changed_tests", [])})  # 1 req
        if not (m.correctness or m.security or m.reliability or m.compatibility or m.test_gap):
            continue
        followed += 1
        p = Profile(client=s1)({"patch": f["patch"][:3000]})  # 1 req
        prio = float(p.priority) + (0.5 if f["path"].startswith(SEC_PATHS) else 0.0)
        if prio < 1.0:
            continue
        profiled += 1
        for hunk in f.get("hunks", [])[:HUNKS_PER_ROUND]:
            ev, ev_conf = _pick("Which candidate hunk provides the strongest direct evidence "
                                "for the suspected concern?",
                                {"hunk": hunk, "patch": f["patch"][:3000]},
                                {"hunk": "this hunk", "noMatch": "no hunk shows it"}, s1)
            if ev == "noMatch" or ev_conf < LOCATE_AT:
                continue
            fin = Finding(client=s1)({"hunk": hunk, "path": f["path"]})  # 1 req
            if fin.mechanism == "no_issue":
                continue
            findings.append({"file": f["path"], "hunk": hunk, "mechanism": fin.mechanism,
                             "severity": float(fin.severity),
                             "owner": "security" if f["path"].startswith(SEC_PATHS) else fin.owner})

    blocking = [x for x in findings if x["severity"] >= BLOCK_SEV]
    if not blocking:
        return {"action": "comment" if findings else "approve", "findings": findings}
    for _ in range(MAX_ROUNDS):
        worst = max(blocking, key=lambda x: x["severity"])
        fix = s2.ask(render("fix", file=worst["file"], hunk=worst["hunk"],
                            mechanism=worst["mechanism"], severity=f"{worst['severity']:.1f}"))
        ok = feels("does this fix resolve the finding with a regression test?",
                   {"finding": worst, "fix": fix}, client=s1)
        if ok.over(0.80):
            blocking = [b for b in blocking if not (
                b["file"] == worst["file"] and b["hunk"] == worst["hunk"])]
            if not blocking:
                return {"action": "approve", "findings": findings}
    return {"action": "request_changes", "blocking": blocking, "findings": findings}
