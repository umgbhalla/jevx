"""Calibration sweeps: one evaluator expands into a variant graph, run over gold.

Hamilton-style parameterize (one declaration -> many nodes) + DSPy-style
discipline (trainset + metric + compiled winner). Tunes the numbers code
owns: thresholds, bands, bars — never the model's weights.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from typing import Any


def variants(**axes: list) -> list[dict]:
    """Cartesian product of parameter axes: variants(threshold=[.5,.7], k=[1,3])."""
    names = list(axes)
    return [dict(zip(names, combo)) for combo in itertools.product(*(axes[n] for n in names))]


def sweep(
    run: Callable[[dict, dict], Any],
    gold: list[dict],
    metric: Callable[[Any, dict], float],
    **axes: list,
) -> dict:
    """run(variant, case) -> output; metric(output, case) -> score. Best variant wins.

    Ties break deterministically on the variant mapping. Reports mean, stdev,
    and min so a high-mean/high-variance bar doesn't silently win.
    """
    import statistics as _st

    if not gold:
        raise ValueError("sweep() needs a non-empty gold set")
    rows: list[dict[str, Any]] = []
    for v in variants(**axes):
        scores = [metric(run(v, case), case) for case in gold]
        mean = sum(scores) / len(scores)
        rows.append(
            {
                "variant": v,
                "mean": mean,
                "stdev": _st.pstdev(scores) if len(scores) > 1 else 0.0,
                "min": min(scores),
                "n": len(scores),
            }
        )
    rows.sort(
        key=lambda r: (-float(r["mean"]), sorted((str(k), str(v)) for k, v in r["variant"].items()))
    )
    return {"best": rows[0], "rows": rows}
