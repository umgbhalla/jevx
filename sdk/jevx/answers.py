"""Typed System One answers from the official TypeSafe SDK."""

from __future__ import annotations

import json
from collections.abc import Mapping

from typesafe_sdk import Answer
from typesafe_sdk import ChoiceAnswer
from typesafe_sdk import NoulAnswer
from typesafe_sdk import ScoreAnswer


def parse_answer(qid: str, raw: Mapping) -> Answer:
    """Validate a scripted or replayed answer with the upstream answer model."""
    try:
        kind = raw["type"]
    except KeyError:
        raise ValueError(f"answer {qid!r} missing 'type'") from None
    models = {"noul": NoulAnswer, "choice": ChoiceAnswer, "score": ScoreAnswer}
    try:
        model = models[kind]
    except (KeyError, TypeError):
        raise ValueError(f"answer {qid!r} has unknown type {kind!r}") from None
    return model.model_validate_json(json.dumps(raw))


__all__ = ["Answer", "ChoiceAnswer", "NoulAnswer", "ScoreAnswer", "parse_answer"]
