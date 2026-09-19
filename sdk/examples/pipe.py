"""Semdecide: typed judgments over unix pipes + CI gates.

Reads lines (or a diff) from stdin, judges each against a question, prints
KEEP/DROP verdicts. Exit codes for CI: 0 all keep, 1 any drop, 2 on S1 error.
`prog | semdecide "is this line an actionable error?"` composes in shell.
"""

from __future__ import annotations

import sys

from jevx.backends import Backend
from jevx.backends import Live
from jevx.py import case
from jevx.relational import Table


def judge_lines(
    question: str, lines: list[str], backend: Backend | None = None, keep_at: float = 0.5
) -> list[dict]:
    s1 = (backend or Live()).s1()
    rows = [{"line": line, "index": i} for i, line in enumerate(lines)]
    try:
        scores = Table(rows, client=s1).noul(question)
    except Exception as e:
        return [{"error": str(e)}]
    return [
        {
            "line": row["line"],
            "prob": float(score),
            "verdict": case[score >= keep_at: "KEEP", ...: "DROP"].ask({}),
        }
        for row, score in zip(rows, scores, strict=True)
    ]


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print('usage: semdecide "question" [--keep 0.5]', file=sys.stderr)
        return 2
    keep_at = 0.5
    if "--keep" in argv:
        keep_at = float(argv[argv.index("--keep") + 1])
        argv = [a for a in argv if a != "--keep" and a != str(keep_at)]
    lines = [line.rstrip("\n") for line in sys.stdin if line.strip()]
    rows = judge_lines(argv[0], lines, keep_at=keep_at)
    if rows and "error" in rows[0]:
        print(f"S1 error: {rows[0]['error']}", file=sys.stderr)
        return 2
    dropped = 0
    for r in rows:
        print(f"[{r['verdict']}] {r['line']}")
        dropped += r["verdict"] == "DROP"
    return 1 if dropped else 0


if __name__ == "__main__":
    raise SystemExit(main())
