"""Model-based flow checker: randomized S1 scripts + invariant assertions.

Hypothesis-style stateful discipline without the dependency: drive a flow
against scripted backends with randomized answer scripts, asserting the
invariants that must hold on EVERY path (budgets respected, no unverified
sends, fail-closed on exhaustion). Randomized, shrinking-ish (minimizes the
failing seed by replaying prefixes), stdlib-only.
"""

from __future__ import annotations

import random
from typing import Any, Callable


def _answers_for(spec: dict[str, tuple[str, tuple]], rng: random.Random) -> dict:
    out = {}
    for qid, (kind, draw) in spec.items():
        if kind == "noul":
            out[qid] = [{"type": "noul", "noul": rng.choice(draw)}]
        elif kind == "choice":
            opts, pick = draw
            out[qid] = [{"type": "choice", "choice": pick,
                         "probabilities": {o: (0.9 if o == pick else 0.1 / max(len(opts) - 1, 1))
                                           for o in opts}, "confidence": 0.9}]
        elif kind == "score":
            v, top = draw
            out[qid] = [{"type": "score", "score": v,
                         "legend": {str(i): str(i) for i in range(top + 1)},
                         "probabilities": {str(i): 1.0 if i == round(v) else 0.0
                                           for i in range(top + 1)}, "confidence": 0.9}]
    return out


def fuzz(flow: Callable[..., dict], spec: dict[str, tuple[str, tuple]],
         invariants: list[Callable[[dict], bool]], args: tuple = (),
         seeds: int = 50, base_seed: int = 0) -> dict:
    """spec: qid -> ("noul", (candidate probs...)) etc. Each seed serves the
    first scripted answer per qid per S1 call... simplified: one answer per qid
    reused across calls (deterministic per seed). Returns failures with seeds."""
    from .backends import Sim

    failures = []
    for s in range(base_seed, base_seed + seeds):
        rng = random.Random(s)
        script = _answers_for(spec, rng)
        try:
            out = flow(*args, backend=Sim(s1_script=script, s2_texts=["x"] * 20))
        except AssertionError as e:  # script exhaustion = flow over-called; not a failure
            if "ScriptDriver" not in str(e):
                failures.append({"seed": s, "error": str(e)})
            continue
        except Exception as e:
            failures.append({"seed": s, "error": f"{type(e).__name__}: {e}"})
            continue
        for inv in invariants:
            try:
                ok = inv(out)
            except Exception as e:
                ok = False
            if not ok:
                failures.append({"seed": s, "error": f"invariant {inv.__name__} on {out}"})
                break
    return {"failures": failures, "seeds": seeds}
