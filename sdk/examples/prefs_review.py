"""Prefs-as-code review: agent instruction files compiled to rules, diffs judged.

Rules live in a prefs file ({name: rule}); each hunk is checked against each
rule with one Noul per (rule, hunk) pair batched in a single request. Any
violation above bar blocks with the rule name cited. Rules are data, so they
diff, version, and sync like code.
"""

from __future__ import annotations

import json

from jevx.backends import Backend
from jevx.backends import Live
from jevx.contracts import ensure
from jevx.py import noul
from jevx.py import vector


def load_prefs(path: str) -> dict:
    with open(path) as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or not data:
        raise ValueError(f"{path}: prefs must be a non-empty object")
    return data


@ensure(lambda *a, result=None, **k: isinstance(result["violations"], list), msg="violations list")
def review_diff(
    prefs: dict, hunks: list[dict], backend: Backend | None = None, bar: float = 0.70
) -> dict:
    """hunks: [{file, hunk}]. One batched request for all rule x hunk pairs."""
    s1 = (backend or Live()).s1()
    checks, keys = {}, {}
    for rname, rule in prefs.items():
        for h in hunks:
            qid = f"check_{len(keys)}"
            checks[qid] = noul(
                {
                    "question": "Does this diff hunk violate the preference?",
                    "preference": {"name": rname, "rule": rule},
                    "change": {"file": h["file"], "hunk": h["hunk"]},
                },
                true={"what": "The change violates the preference."},
                false={"what": "The change follows the preference."},
            )
            keys[qid] = (rname, h)
    if not checks:
        return {"violations": [], "action": "pass", "checked": 0}
    out = vector(**checks).ask({"task": "Review each diff hunk against its named preference."}, client=s1)
    violations = [
        {"rule": rule, "file": hunk["file"], "hunk": hunk["hunk"][:500], "prob": float(out[qid])}
        for qid, (rule, hunk) in keys.items()
        if out[qid] >= bar
    ]
    return {
        "violations": violations,
        "action": "block" if violations else "pass",
        "checked": len(keys),
    }
