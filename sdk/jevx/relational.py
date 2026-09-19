"""Relational judgments: WHERE / ORDER BY / GROUP BY over rows, no database.

Ports pg-jev semantics to pure Python: rows become state, sha1(row) caches
answers per (question, kind, options), batches of 20 share one request,
threshold/sort/aggregate reuse cached judgments for free.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any

from .client import Client
from .questions import Choice
from .questions import Noul
from .questions import Score

BATCH = 20


def _h(row: dict) -> str:
    return hashlib.sha1(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()


class Table:
    """rows: list of JSON-able dicts. Judgments cached by (question, kind, options, row-hash)."""

    def __init__(self, rows: list[dict], client: Client | None = None):
        self.rows = rows
        self._client = client
        self._cache: dict = {}
        self.stats = {"requests": 0, "judged": 0, "cache_hits": 0}

    def _batch(self, items: list[tuple[int, dict, Any]]) -> None:
        if not items:
            return
        c = self._client or Client()
        for i in range(0, len(items), BATCH):
            chunk = items[i : i + BATCH]
            qs = {f"r{j}": q for j, (_, _, q) in enumerate(chunk)}
            resp = c.system_one({"rows": [row for _, row, _ in chunk]}, qs)
            self.stats["requests"] += 1
            for j, (idx, row, q) in enumerate(chunk):
                a = resp.answers[f"r{j}"]
                self._cache[(q.key, _h(row))] = a
                self.stats["judged"] += 1

    def _hits(self, key: tuple, rows: list[dict]) -> int:
        n = sum(1 for r in rows if (key, _h(r)) in self._cache)
        self.stats["cache_hits"] += n
        return n

    def where(self, condition: str, threshold: float = 0.5) -> list[dict]:
        """[r for r in rows if P(condition about r) >= threshold]. One batched pass."""
        key = ("noul", condition)
        missing = [
            (i, r, _Q(key, Noul(f"Does this record satisfy: {condition}?")))
            for i, r in enumerate(self.rows)
            if (key, _h(r)) not in self._cache
        ]
        self._batch(missing)
        self._hits(key, self.rows)
        return [r for r in self.rows if self._cache[(key, _h(r))].prob >= threshold]

    def order_by(
        self, question: str, levels: list[str], limit: int = 0, descending: bool = True
    ) -> list[dict]:
        """Score every row once, sort by score. (No early-stop: all rows judged.)"""
        key = ("score", question, tuple(levels))
        missing = [
            (i, r, _Q(key, Score(f"{question}?", list(levels))))
            for i, r in enumerate(self.rows)
            if (key, _h(r)) not in self._cache
        ]
        self._batch(missing)
        self._hits(key, self.rows)
        ranked = sorted(
            self.rows, key=lambda r: self._cache[(key, _h(r))].score, reverse=descending
        )
        return ranked[:limit] if limit else ranked

    def group_by(self, question: str, options: dict) -> dict[str, list[dict]]:
        """Choice per row, grouped. Must score all rows — no early-stop."""
        key = ("choice", question, tuple(sorted((k, v or "") for k, v in options.items())))
        missing = [
            (i, r, _Q(key, Choice(f"{question}?", dict(options))))
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
        return self._b.to_json()
