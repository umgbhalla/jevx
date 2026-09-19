"""Model-based flow checker: randomized S1 scripts + invariant assertions.

Hypothesis-style stateful discipline without the dependency: drive a flow
against scripted backends with per-call randomized answers, asserting the
invariants that must hold on EVERY path (budgets respected, no unverified
sends, fail-closed on exhaustion). Script exhaustion is an `overcall`
failure, never a pass. Stdlib-only.
"""

from __future__ import annotations

import random
from collections.abc import Callable


def _draw(kind: str, draw: tuple, rng: random.Random) -> dict:
    if kind == "noul":
        return {"type": "noul", "noul": rng.choice(draw)}
    if kind == "choice":
        opts, pick = draw
        pick = rng.choice(opts) if pick == "?" else pick
        rest = [o for o in opts if o != pick]
        share = 0.1 / max(len(rest), 1)
        return {
            "type": "choice",
            "choice": pick,
            "probabilities": {o: (0.9 if o == pick else share) for o in opts},
            "confidence": 0.9,
        }
    if kind == "score":
        v, top = draw
        v = rng.choice(v) if isinstance(v, (list, tuple)) else v
        return {
            "type": "score",
            "score": v,
            "legend": {str(i): str(i) for i in range(top + 1)},
            "probabilities": {str(i): 1.0 if i == round(v) else 0.0 for i in range(top + 1)},
            "confidence": 0.9,
        }
    raise ValueError(f"unknown answer kind {kind!r}")


class _StreamSim:
    """Backend whose S1 answers draw fresh from the seed stream per call."""

    def __init__(self, spec: dict, seed: int, texts: int = 50):
        self.spec = spec
        self.rng = random.Random(seed)
        self.calls = 0
        self._texts = ["x"] * texts

    def s1(self):
        inner = self

        class _C:
            def system_one(_self, state, questions, model=None):
                from . import answers as _A
                from .client import Response

                inner.calls += 1
                parsed = {
                    k: _A.parse_answer(k, _draw(inner.spec[k][0], inner.spec[k][1], inner.rng))
                    for k in questions
                }
                return Response(
                    parsed,
                    "fuzz",
                    {},
                )

        return _C()

    def s2(self):
        from .s2 import FakeSystem2

        return FakeSystem2(list(self._texts))


def fuzz(
    flow: Callable[..., dict],
    spec: dict[str, tuple[str, tuple]],
    invariants: list[Callable[[dict], bool]],
    args: tuple = (),
    seeds: int = 50,
    base_seed: int = 0,
) -> dict:
    """spec: qid -> ("noul", (candidate probs...)) | ("choice", ((opts), pick|"?""))
    | ("score", (value|[values], top)). Unknown qids fail loudly (spec gap)."""
    failures = []
    for s in range(base_seed, base_seed + seeds):
        sim = _StreamSim(spec, s)
        try:
            out = flow(*args, backend=sim)
        except KeyError as e:
            failures.append({"seed": s, "error": f"spec gap (unknown qid): {e}"})
            continue
        except Exception as e:
            failures.append({"seed": s, "error": f"{type(e).__name__}: {e}"})
            continue
        for inv in invariants:
            try:
                ok = inv(out)
            except Exception:
                ok = False
            if not ok:
                name = getattr(inv, "__name__", type(inv).__name__)
                failures.append({"seed": s, "error": f"invariant {name} on {out}"})
                break
    return {"failures": failures, "seeds": seeds}
