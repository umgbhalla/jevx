"""Validated question builders: Noul, Choice, Score."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

MAX_CHOICE_OPTIONS = 255
MIN_SCORE_LEVELS = 2
MAX_SCORE_LEVELS = 10


def _instructions(v: Any) -> str:
    if not isinstance(v, str) or not v.strip():
        raise ValueError("instructions must be a non-empty string")
    return v


@dataclass(frozen=True)
class Noul:
    """Yes/no question. Answer is P(yes); 0.5 = undecided, not medium."""

    instructions: str
    true: str | None = None
    false: str | None = None

    def __post_init__(self) -> None:
        _instructions(self.instructions)

    def to_json(self) -> dict:
        q: dict = {"type": "noul", "instructions": self.instructions}
        if self.true is not None or self.false is not None:
            q["criteria"] = {"true": self.true, "false": self.false}
        return q


@dataclass(frozen=True)
class Choice:
    """Pick-one question. Max 255 options; include an escape option."""

    instructions: str
    criteria: Mapping[str, str | None]

    def __post_init__(self) -> None:
        _instructions(self.instructions)
        opts = dict(self.criteria)
        if not opts:
            raise ValueError("Choice needs at least one option")
        if len(opts) > MAX_CHOICE_OPTIONS:
            raise ValueError(f"Choice supports max {MAX_CHOICE_OPTIONS} options, got {len(opts)}")
        for k in opts:
            if not isinstance(k, str) or not k:
                raise ValueError("Choice option names must be non-empty strings")

    def to_json(self) -> dict:
        return {
            "type": "choice",
            "instructions": self.instructions,
            "criteria": dict(self.criteria),
        }


@dataclass(frozen=True)
class Score:
    """Spectrum question. Ordered levels low->high, 2-10 of them."""

    instructions: str
    criteria: tuple | list

    def __post_init__(self) -> None:
        _instructions(self.instructions)
        levels = list(self.criteria)
        if not (MIN_SCORE_LEVELS <= len(levels) <= MAX_SCORE_LEVELS):
            raise ValueError(
                f"Score needs {MIN_SCORE_LEVELS}-{MAX_SCORE_LEVELS} levels, got {len(levels)}"
            )
        object.__setattr__(self, "criteria", tuple(levels))

    def to_json(self) -> dict:
        return {
            "type": "score",
            "instructions": self.instructions,
            "criteria": list(self.criteria),
        }


Question = Noul | Choice | Score


def to_json(question: Question | Mapping[str, Any]) -> dict:
    """Accept a builder or a raw dict (forward-compat escape hatch)."""
    if isinstance(question, Mapping):
        return dict(question)
    return question.to_json()
