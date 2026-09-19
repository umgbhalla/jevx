"""Calibration sweeps: one evaluator expands into a variant graph, run over gold.

Hamilton-style parameterize (one declaration -> many nodes) + DSPy-style
discipline (trainset + metric + compiled winner). Tunes the numbers code
owns: thresholds, bands, bars — never the model's weights.
"""

from __future__ import annotations

import itertools
from typing import Any, Callable


def variants(**axes: list) -> list[dict]:
    """Cartesian product of parameter axes: variants(threshold=[.5,.7], k=[1,3])."""
    names = list(axes)
    return [dict(zip(names, combo)) for combo in itertools.product(*(axes[n] for n in names))]


def sweep(run: Callable[[dict, dict], Any], gold: list[dict],
          metric: Callable[[Any, dict], float], **axes: list) -> dict:
    """run(variant, case) -> output; metric(output, case) -> score. Best variant wins."""
    rows = []
    for v in variants(**axes):
        scores = [metric(run(v, case), case) for case in gold]
        rows.append({"variant": v, "mean": sum(scores) / len(scores), "n": len(scores)})
    rows.sort(key=lambda r: -r["mean"])
    return {"best": rows[0], "rows": rows}
