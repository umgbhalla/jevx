"""Secret scrubbing before model calls. No secrets in state — ever."""

from __future__ import annotations

import re

_PATTERNS = (
    (re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*\S+"), r"\1=[REDACTED]"),
    (re.compile(r"\b[A-Za-z0-9_-]{32,}\b"), "[REDACTED]"),
)


def scrub(text: str) -> str:
    """Redact secret-shaped material. Idempotent, cheap, no model involved."""
    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text)
    return text
