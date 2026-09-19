"""Test selection: judge which tests a diff can skip, run the rest.

Ports the Leanest shape: per-test Noul ("could this change affect behavior
this test verifies?"), skip the safe ones, always run the unsure band,
report savings. Test discovery + diff are injected so CI and local runs
share the same gate.
"""

from __future__ import annotations

from jevx.backends import Backend
from jevx.backends import Live
from jevx.contracts import ensure
from jevx.py import case
from jevx.relational import Table


@ensure(
    lambda *a, result=None, **k: len(result["run"]) + len(result["skip"]) == result["total"],
    msg="run+skip covers all",
)
def select(
    diff: str,
    tests: list[dict],
    backend: Backend | None = None,
    skip_at: float = 0.30,
    review_at: float = 0.70,
) -> dict:
    """tests: [{id, path, framework}]. Returns run/skip/review lists + stats."""
    s1 = (backend or Live()).s1()
    instructions = (
        {
            "question": "Could this test still be affected by a latent issue?",
            "focus": "No code changes were detected in the supplied diff.",
        }
        if not diff.strip()
        else {
            "question": "Could the current code change affect behavior verified by this test?",
            "focus": "Use the test path and framework to identify behavior it verifies.",
        }
    )
    scores = Table(tests, client=s1, context={"diff": diff[:4000]}).noul(instructions)
    buckets = [
        case[
            score < skip_at: "skip",
            score < review_at: "review",
            ...: "run",
        ].ask({})
        for score in scores
    ]
    run = [
        {**test, "p_affected": float(score)}
        for test, score, bucket in zip(tests, scores, buckets, strict=True)
        if bucket == "run"
    ]
    skip = [
        {**test, "p_affected": float(score)}
        for test, score, bucket in zip(tests, scores, buckets, strict=True)
        if bucket == "skip"
    ]
    review = [
        {**test, "p_affected": float(score)}
        for test, score, bucket in zip(tests, scores, buckets, strict=True)
        if bucket == "review"
    ]
    # review band runs too — unsure is not safe to skip
    return {
        "run": run + review,
        "skip": skip,
        "review": review,
        "saved": len(skip),
        "total": len(tests),
    }


def format_github_summary(sel: dict) -> str:
    lines = [f"### Test selection: run {len(sel['run'])}/{sel['total']} (skip {sel['saved']})"]
    for t in sel["run"]:
        lines.append(f"- RUN `{t['id']}` (P={t['p_affected']:.2f})")
    for t in sel["skip"]:
        lines.append(f"- skip `{t['id']}` (P={t['p_affected']:.2f})")
    return "\n".join(lines)
