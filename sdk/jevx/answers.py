"""Typed answers with decision helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NoulAnswer:
    prob: float  # P(yes); 0.5 = undecided

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
    __match_args__ = ("choice", "confidence")

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

    def level(self) -> int:
        return int(round(self.score))

    def normalized(self) -> float:
        top = max(len(self.legend) - 1, 1)
        return self.score / top


Answer = NoulAnswer | ChoiceAnswer | ScoreAnswer


def parse_answer(qid: str, raw: dict) -> Answer:
    try:
        kind = raw["type"]
    except KeyError:
        raise ValueError(f"answer {qid!r} missing 'type'") from None
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
