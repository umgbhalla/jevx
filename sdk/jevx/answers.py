"""Typed answers with decision helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NoulAnswer:
    prob: float  # P(yes); 0.5 = undecided

    def __post_init__(self) -> None:
        _prob("noul", self.prob)

    def is_yes(self, threshold: float = 0.5) -> bool:
        return self.prob >= threshold

    def band(self, review_at: float = 0.35, act_at: float = 0.70) -> str:
        """no | review | yes — tune thresholds on your own labeled data."""
        if self.prob >= act_at:
            return "yes"
        if self.prob >= review_at:
            return "review"
        return "no"


@dataclass(frozen=True)
class ChoiceAnswer:
    choice: str
    probabilities: dict[str, float]
    confidence: float
    __match_args__ = ("choice", "probabilities", "confidence")

    def __post_init__(self) -> None:
        _prob("confidence", self.confidence)
        for k, v in self.probabilities.items():
            _prob(f"probabilities[{k!r}]", v)
        if self.choice not in self.probabilities:
            from .errors import ValidationError as _VE

            raise _VE(f"choice {self.choice!r} not in probabilities")

    def top(self, n: int = 3) -> list[tuple[str, float]]:
        return sorted(self.probabilities.items(), key=lambda kv: -kv[1])[:n]

    def is_sure(self, threshold: float = 0.6) -> bool:
        return self.probabilities.get(self.choice, 0.0) >= threshold


@dataclass(frozen=True)
class ScoreAnswer:
    score: float  # weighted position; may land between levels
    legend: dict[str, str]
    probabilities: dict[str, float]
    confidence: float

    def __post_init__(self) -> None:
        _prob("confidence", self.confidence)
        for k, v in self.probabilities.items():
            _prob(f"probabilities[{k!r}]", v)

    def level(self) -> int:
        return int(round(self.score))

    def normalized(self) -> float:
        top = max(len(self.legend) - 1, 1)
        return self.score / top


Answer = NoulAnswer | ChoiceAnswer | ScoreAnswer


def _prob(name: str, v: Any) -> float:
    from .errors import ValidationError as _VE

    try:
        f = float(v)
    except (TypeError, ValueError):
        raise _VE(f"{name} is not a number: {v!r}") from None
    if not 0.0 <= f <= 1.0:
        raise _VE(f"{name} out of 0..1: {v!r}")
    return f


def parse_answer(qid: str, raw: dict) -> Answer:
    from .errors import ValidationError as _VE

    if not isinstance(raw, dict):
        raise _VE(f"answer {qid!r} is not an object")
    try:
        kind = raw["type"]
    except KeyError:
        raise _VE(f"answer {qid!r} missing 'type'") from None
    if kind == "noul":
        return NoulAnswer(prob=float(raw["noul"]))
    if kind == "choice":
        return ChoiceAnswer(
            choice=str(raw["choice"]),
            probabilities={k: float(v) for k, v in raw["probabilities"].items()},
            confidence=float(raw["confidence"]),
        )
    if kind == "score":
        return ScoreAnswer(
            score=float(raw["score"]),
            legend={str(k): str(v) for k, v in raw["legend"].items()},
            probabilities={str(k): float(v) for k, v in raw["probabilities"].items()},
            confidence=float(raw["confidence"]),
        )
    raise ValueError(f"answer {qid!r} has unknown type {kind!r}")
