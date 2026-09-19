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
    from jevx.py import _decide
    from jevx.questions import Noul
    import hashlib as _h

    s1 = (backend or Live()).s1()
    qs, keys = {}, []
    for rname, rule in prefs.items():
        for h in hunks:
            tag = _h.sha1(f"{rname}\n{h['file']}\n{h['hunk']}".encode()).hexdigest()[:8]
            qid = f"{rname}::{h['file']}::{tag}"
            qs[qid] = Noul(f"Does this hunk violate the rule: {rule}?")
            keys.append((qid, rname, h))
    out = _decide({"rules": prefs}, qs, s1)
    violations = [
        {"rule": r, "file": h["file"], "hunk": h["hunk"][:500], "prob": float(out[q].prob)}
        for q, r, h in keys
        if float(out[q].prob) >= bar
    ]
    return {
        "violations": violations,
        "action": "block" if violations else "pass",
        "checked": len(keys),
    }
