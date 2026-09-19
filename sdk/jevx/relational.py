"""Relational judgments: WHERE / ORDER BY / GROUP BY over rows, no database.

Ports pg-jev semantics to pure Python: rows become state, sha1(row) caches
answers per (question, kind, options), batches of 20 share one request,
threshold/sort/aggregate reuse cached judgments for free.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping
from collections.abc import Sequence
from typing import Any

from .client import Client
from .py import P
from .py import _decide
from .questions import Choice
from .questions import JSONContent
from .questions import Noul
from .questions import Score
from .questions import to_json

BATCH = 20


def _key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _h(row: dict) -> str:
    return hashlib.sha1(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()


class Table:
    """rows: list of JSON-able dicts. Judgments cached by (question, kind, options, row-hash)."""

    def __init__(self, rows: list[dict], client: Client | None = None, *, context: Any = None):
        self.rows = rows
        self._client = client
        self.context = context
        self._cache: dict = {}
        self.stats = {"requests": 0, "judged": 0, "cache_hits": 0}

    def _batch(self, items: list[tuple[int, dict, Any]]) -> None:
        if not items:
            return
        for i in range(0, len(items), BATCH):
            chunk = items[i : i + BATCH]
            qs = {f"r{j}": q._b for j, (_, _, q) in enumerate(chunk)}
            state = {"batch_size": len(chunk)}
            if self.context is not None:
                state["context"] = self.context
            answers = _decide(state, qs, self._client)
            self.stats["requests"] += 1
            for j, (idx, row, q) in enumerate(chunk):
                self._cache[(q.key, _h(row))] = answers[f"r{j}"]
                self.stats["judged"] += 1

    def _hits(self, key: tuple, rows: list[dict]) -> int:
        n = sum(1 for r in rows if (key, _h(r)) in self._cache)
        self.stats["cache_hits"] += n
        return n

    def where(self, condition: JSONContent, threshold: float = 0.5) -> list[dict]:
        """[r for r in rows if P(condition about r) >= threshold]. One batched pass."""
        scores = self.noul(condition)
        return [row for row, score in zip(self.rows, scores, strict=True) if score >= threshold]

    def noul(
        self,
        instructions: JSONContent,
        *,
        true: JSONContent | None = None,
        false: JSONContent | None = None,
    ) -> list[P]:
        """Judge each row once, embedding that row in its question, in batches."""
        key = ("noul", _key((instructions, true, false, self.context)))
        criteria = {"true": true, "false": false} if true is not None or false is not None else None
        missing = [
            (
                i,
                r,
                _Q(
                    key,
                    Noul(
                        instructions={
                            "question": "Does this record satisfy the condition?",
                            "condition": instructions,
                            "record": r,
                        },
                        criteria=criteria,
                    ),
                ),
            )
            for i, r in enumerate(self.rows)
            if (key, _h(r)) not in self._cache
        ]
        self._batch(missing)
        self._hits(key, self.rows)
        return [P(self._cache[(key, _h(r))].noul) for r in self.rows]

    def order_by(
        self,
        question: JSONContent,
        levels: Sequence[JSONContent],
        limit: int = 0,
        descending: bool = True,
    ) -> list[dict]:
        """Score every row once, sort by score. (No early-stop: all rows judged.)"""
        key = ("score", _key((question, levels, self.context)))
        missing = [
            (
                i,
                r,
                    _Q(
                        key,
                        Score(
                            instructions={
                                "question": "Score this record against the requested criterion.",
                                "criterion": question,
                                "record": r,
                            },
                            criteria=list(levels),
                        ),
                    ),
            )
            for i, r in enumerate(self.rows)
            if (key, _h(r)) not in self._cache
        ]
        self._batch(missing)
        self._hits(key, self.rows)
        ranked = sorted(
            self.rows, key=lambda r: self._cache[(key, _h(r))].score, reverse=descending
        )
        return ranked[:limit] if limit else ranked

    def group_by(
        self,
        question: JSONContent,
        options: Mapping[str, JSONContent | None],
    ) -> dict[str, list[dict]]:
        """Choice per row, grouped. Must score all rows — no early-stop."""
        key = ("choice", _key((question, options, self.context)))
        missing = [
            (
                i,
                r,
                _Q(
                    key,
                    Choice(
                        instructions={
                            "question": "Classify this record using the requested categories.",
                            "question_context": question,
                            "record": r,
                        },
                        criteria=dict(options),
                    ),
                ),
            )
            for i, r in enumerate(self.rows)
            if (key, _h(r)) not in self._cache
        ]
        self._batch(missing)
        self._hits(key, self.rows)
        out: dict[str, list[dict]] = defaultdict(list)
        for r in self.rows:
            out[self._cache[(key, _h(r))].choice].append(r)
        return dict(out)


class _Q:
    """Cache-key carrier around a builder."""

    def __init__(self, key: tuple, builder):
        self.key = key
        self._b = builder

    def to_json(self) -> dict:
        return to_json(self._b)
