"""Offline lint for question sets: validate before paying for a request.

Ports the jevkit idea: a battery of cheap structural checks that catch
malformed instructions/criteria/options without any model call. Returns a
list of findings; empty means clean.
"""

from __future__ import annotations


def lint(questions: dict[str, dict]) -> list[str]:
    """questions: {qid: question-json}. Findings read like compiler errors."""
    out = []
    if not questions:
        return ["empty: no questions in request"]
    for qid, q in questions.items():
        if not isinstance(q, dict):
            out.append(f"{qid}: not an object")
            continue
        kind = q.get("type")
        if kind not in ("noul", "choice", "score"):
            out.append(f"{qid}: unknown type {kind!r}")
            continue
        ins = q.get("instructions", "")
        if not isinstance(ins, str) or not ins.strip():
            out.append(f"{qid}: empty instructions")
        elif ins.strip().endswith("?") is False and len(ins.split()) < 3:
            out.append(f"{qid}: instructions too short to be a judgment")
        if _mentions_param(ins):
            out.append(
                f"{qid}: instructions name a parameter ({_mentions_param(ins)}), "
                "describe the idea instead"
            )
        crit = q.get("criteria")
        if kind == "choice":
            if not isinstance(crit, dict) or not crit:
                out.append(f"{qid}: choice needs a non-empty criteria map")
            else:
                if len(crit) > 255:
                    out.append(f"{qid}: {len(crit)} options exceeds 255 cap")
                nulls = [k for k, v in crit.items() if v is None]
                if len(nulls) == len(crit) and len(crit) > 4:
                    out.append(
                        f"{qid}: all {len(crit)} options undescribed; confusables need rubrics"
                    )
                for k, v in crit.items():
                    if (
                        isinstance(v, str)
                        and len(k) > 2
                        and k.lower() in v.lower()
                        and len(v.split()) < 4
                    ):
                        out.append(f"{qid}.{k}: rubric restates the name, add detail")
        if kind == "score":
            if not isinstance(crit, list) or len(crit) < 2:
                out.append(f"{qid}: score needs >= 2 ordered levels")
            elif len(crit) > 10:
                out.append(f"{qid}: {len(crit)} levels exceeds 10 cap")
            elif len({str(c).lower() for c in crit}) != len(crit):
                out.append(f"{qid}: duplicate level descriptions")
        if kind == "noul" and isinstance(crit, dict):
            if set(crit) - {"true", "false"}:
                out.append(f"{qid}: noul criteria only accepts true/false")
    return out


def _mentions_param(ins: str) -> str | None:
    import re

    m = re.search(r"\b(which|what)\s+([a-z_]+)\?", ins, re.I)
    if m and m.group(2).lower() in ("resolution", "option", "value", "choice", "format", "type"):
        return m.group(0)
    return None
