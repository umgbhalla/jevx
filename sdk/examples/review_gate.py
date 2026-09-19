"""Staged PR review funnel: screen -> profile -> locate -> mechanism -> severity -> route.

Ports: verbatim 5-Noul screen, category Choice + priority Score, evidence-hunk
Choice with noMatch exit, per-dimension mechanism with noIssue exit, severity
Score, conditional owner route. Thresholds 0.70 / 0.55 / 1.5 / 2.0.
Findings are review prompts, not proof of defect — S2 fixes, S1 re-checks.
"""

from __future__ import annotations

from jevx.backends import Backend
from jevx.backends import Live
from jevx.contracts import ensure
from jevx.py import choice
from jevx.py import feels
from jevx.py import noul
from jevx.py import score
from jevx.py import vector

SCREEN_AT, LOCATE_AT, ROUTE_SEV, BLOCK_SEV = 0.70, 0.55, 1.5, 2.0
MAX_FOLLOW_UPS, MAX_PROFILES, MAX_ROUNDS, HUNKS_PER_ROUND = 8, 5, 3, 8
SEC_PATHS = ("auth", "crypto", "secrets")
FIX_AT = 0.80


def _is_sec(path: str) -> bool:
    return any(s in path.split("/") for s in SEC_PATHS)


SCREEN = vector(
    correctness=noul(
        "Does the patch directly support that this change likely introduces incorrect runtime behavior?"
    ),
    security=noul(
        "Does the patch directly support that this change introduces or weakens a security boundary?"
    ),
    reliability=noul(
        "Does the patch directly support that this change can crash, race, leak, deadlock, or recover poorly?"
    ),
    compatibility=noul(
        "Does the patch directly support that this change can break an existing caller, format, protocol, or public behavior?"
    ),
    test_gap=noul(
        "Does the patch change important behavior without adequate targeted evidence in changed tests?"
    ),
)

PROFILE = vector(
    category=choice(
        "Which category best describes the patch?",
        {
            "behavior": "Changes runtime behavior or business logic.",
            "interface": "Changes a public API, protocol, or data format.",
            "infrastructure": "Changes build, deployment, storage, or runtime foundations.",
            "observability": "Changes logs, metrics, traces, or diagnostics.",
            "refactor": "Changes structure without intended behavior changes.",
            "routine": "Documentation, formatting, or another low-risk maintenance edit.",
        },
    ),
    priority=score(
        "Rate how closely a human should review the patch.",
        (
            {"summary": "low", "signals": ["routine", "isolated", "easy to revert"]},
            {"summary": "notable", "signals": ["multiple callers", "behavior changes"]},
            {"summary": "high", "signals": ["security", "data integrity", "concurrency"]},
            {"summary": "urgent", "signals": ["production outage", "irreversible impact"]},
        ),
    ),
)

FINDING = vector(
    mechanism=choice(
        "Which mechanism best describes the suspected concern supported by the selected evidence?",
        (
            "authorization",
            "injection",
            "exposure",
            "unsafe_default",
            "logic",
            "race",
            "leak",
            "no_issue",
        ),
    ),
    severity=score(
        "Assuming the evidence exhibits the concern, rate the likely production impact.",
        (
            {"summary": "cosmetic", "signals": ["no user-visible effect"]},
            {"summary": "notable", "signals": ["limited degradation"]},
            {"summary": "high", "signals": ["service failure", "data exposure"]},
            {"summary": "blocking", "signals": ["severe or broad production harm"]},
        ),
    ),
    owner=choice(
        "Which reviewer is best suited to investigate this concern?",
        ("security", "api", "runtime", "testing", "maintainer"),
    ),
)


def _pick(prompt: str, state: dict, options: dict, s1) -> tuple[str, float]:
    from jevx.py import pick

    c = pick(prompt, state, options, client=s1)
    return c.choice, c.confidence


@ensure(
    lambda *a, result=None, **k: result["action"] in ("approve", "comment", "request_changes"),
    msg="known review action",
)
def review(pr: dict, backend: Backend | None = None) -> dict:
    bk = backend or Live()
    s1, s2 = bk.s1(), bk.s2()
    """pr: {files: [{path, patch, hunks: [ids], changed_tests: [...]}, ...]}."""
    from jevx.prompts import render

    findings, followed, profiled = [], 0, 0
    for f in pr["files"]:
        if followed >= MAX_FOLLOW_UPS or profiled >= MAX_PROFILES:
            break
        m = SCREEN.ask(
            {"patch": f["patch"][:3000], "changed_tests": f.get("changed_tests", [])},
            client=s1,
        )  # 1 req
        if not any(value >= SCREEN_AT for value in m.as_dict().values()):
            continue
        followed += 1
        p = PROFILE.ask({"patch": f["patch"][:3000]}, client=s1)  # 1 req
        prio = float(p.priority) + (0.5 if _is_sec(f["path"]) else 0.0)
        if prio < 1.0:
            continue
        profiled += 1
        for hunk in f.get("hunks", [])[:HUNKS_PER_ROUND]:
            ev, ev_conf = _pick(
                "Which candidate hunk provides the strongest direct evidence "
                "for the suspected concern?",
                {"hunk": hunk, "patch": f["patch"][:3000]},
                {"hunk": "this hunk", "noMatch": "no hunk shows it"},
                s1,
            )
            if ev == "noMatch" or ev_conf < LOCATE_AT:
                continue
            fin = FINDING.ask({"hunk": hunk, "path": f["path"]}, client=s1)  # 1 req
            if fin.mechanism.choice == "no_issue":
                continue
            sev = float(fin.severity)
            findings.append(
                {
                    "file": f["path"],
                    "hunk": hunk,
                    "mechanism": fin.mechanism.choice,
                    "severity": sev,
                    "owner": (
                        "security"
                        if (_is_sec(f["path"]) and sev >= ROUTE_SEV)
                        else fin.owner.choice
                    ),
                }
            )

    blocking = [x for x in findings if x["severity"] >= BLOCK_SEV]
    if not blocking:
        return {"action": "comment" if findings else "approve", "findings": findings}
    prior = ""
    for _ in range(MAX_ROUNDS):
        worst = max(blocking, key=lambda x: x["severity"])
        fix = s2.ask(
            render(
                "fix",
                file=worst["file"],
                hunk=worst["hunk"],
                mechanism=worst["mechanism"],
                severity=f"{worst['severity']:.1f}",
            )
            + (f"\nPrior attempt failed, do not repeat it: {prior}" if prior else "")
        )
        ok = feels(
            "does this fix resolve the finding with a regression test?",
            {"finding": worst, "fix": fix},
            client=s1,
        )
        if ok.over(FIX_AT):
            blocking = [
                b
                for b in blocking
                if not (b["file"] == worst["file"] and b["hunk"] == worst["hunk"])
            ]
            findings = [
                x
                for x in findings
                if not (x["file"] == worst["file"] and x["hunk"] == worst["hunk"])
            ]
            if not blocking:
                return {"action": "approve", "findings": findings}
        prior = fix[:500]
    return {"action": "request_changes", "blocking": blocking, "findings": findings}
