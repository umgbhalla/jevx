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
from jevx.py import feels


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
    run, skip, review = [], [], []
    for t in tests:
        q = (
            "No code changes detected. Could this test still be affected by any latent issue?"
            if not diff.strip()
            else f"Could the current code change affect behavior verified by "
            f"{t.get('framework', 'the')} test at {t['path']}?"
        )
        p = float(feels(q, {"diff": diff[:4000], "test": t}, client=s1))
        if p < skip_at:
            skip.append({**t, "p_affected": p})
        elif p < review_at:
            review.append({**t, "p_affected": p})
        else:
            run.append({**t, "p_affected": p})
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
