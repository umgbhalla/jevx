"""Offline lint for TypeSafe question payloads, including structured entries."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from collections.abc import Sequence


def lint(questions: Mapping[str, Mapping]) -> list[str]:
    """Check question shapes and rubrics before a request."""
    out = []
    if not questions:
        return ["empty: no questions in request"]
    for qid, question in questions.items():
        if not isinstance(question, Mapping):
            out.append(f"{qid}: not an object")
            continue
        kind = question.get("type")
        if kind not in ("noul", "choice", "score"):
            out.append(f"{qid}: unknown type {kind!r}")
            continue

        instructions = question.get("instructions")
        if not _content(instructions):
            out.append(f"{qid}: instructions must be a string, object, or array")
        elif not _nonempty(instructions):
            out.append(f"{qid}: empty instructions")
        elif (
            isinstance(instructions, str)
            and not instructions.strip().endswith("?")
            and len(instructions.split()) < 3
        ):
            out.append(f"{qid}: instructions too short to be a judgment")
        if param := _mentions_param(" ".join(_strings(instructions))):
            out.append(f"{qid}: instructions name a parameter ({param}), describe the idea instead")

        criteria = question.get("criteria")
        if kind == "choice":
            if not isinstance(criteria, Mapping) or not criteria:
                out.append(f"{qid}: choice needs a non-empty criteria map")
            else:
                if len(criteria) > 255:
                    out.append(f"{qid}: {len(criteria)} options exceeds 255 cap")
                if (
                    len([value for value in criteria.values() if value is None]) == len(criteria)
                    and len(criteria) > 4
                ):
                    out.append(
                        f"{qid}: all {len(criteria)} options undescribed; confusables need rubrics"
                    )
                for key, value in criteria.items():
                    if not isinstance(key, str):
                        out.append(f"{qid}: choice option names must be strings")
                        continue
                    if value is not None and (not _content(value) or not _nonempty(value)):
                        out.append(f"{qid}.{key}: invalid or empty option description")
                    if (
                        isinstance(value, str)
                        and len(key) > 2
                        and key.lower() in value.lower()
                        and len(value.split()) < 4
                    ):
                        out.append(f"{qid}.{key}: rubric restates the name, add detail")
        elif kind == "score":
            if not isinstance(criteria, list) or len(criteria) < 2:
                out.append(f"{qid}: score needs >= 2 ordered levels")
            else:
                if len(criteria) > 10:
                    out.append(f"{qid}: {len(criteria)} levels exceeds 10 cap")
                if any(not _content(level) or not _nonempty(level) for level in criteria):
                    out.append(f"{qid}: score levels must be non-empty strings, objects, or arrays")
                keys = [
                    json.dumps(level, sort_keys=True, separators=(",", ":"), default=str)
                    if _content(level)
                    else repr(level)
                    for level in criteria
                ]
                if len(set(keys)) != len(keys):
                    out.append(f"{qid}: duplicate level descriptions")
        elif criteria is not None:
            if not isinstance(criteria, Mapping):
                out.append(f"{qid}: noul criteria must be an object")
            else:
                if set(criteria) - {"true", "false"}:
                    out.append(f"{qid}: noul criteria only accepts true/false")
                for outcome, description in criteria.items():
                    if description is not None and (
                        not _content(description) or not _nonempty(description)
                    ):
                        out.append(f"{qid}.criteria.{outcome}: invalid or empty description")
    return out


def _mentions_param(instructions: str) -> str | None:
    match = re.search(r"\b(which|what)\s+([a-z_]+)\?", instructions, re.I)
    if match and match.group(2).lower() in (
        "resolution",
        "option",
        "value",
        "choice",
        "format",
        "type",
    ):
        return match.group(0)
    return None


def _json_value(value) -> bool:
    if value is None or isinstance(value, (str, int, bool)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_json_value(item) for item in value)
    if isinstance(value, Mapping):
        return all(isinstance(key, str) and _json_value(item) for key, item in value.items())
    return False


def _content(value) -> bool:
    return (
        value is None
        or isinstance(value, str)
        or (isinstance(value, (Mapping, list)) and _json_value(value))
    )


def _nonempty(value) -> bool:
    return bool(value.strip()) if isinstance(value, str) else bool(value)


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            yield from _strings(item)
