"""Question models from the official TypeSafe SDK."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel
from typesafe_sdk import Choice
from typesafe_sdk import JSONContent
from typesafe_sdk import Noul
from typesafe_sdk import Question
from typesafe_sdk import Score


def to_json(question: Question | Mapping[str, Any]) -> dict[str, Any]:
    """Return the wire mapping accepted by TypeSafe and Jevx effect drivers."""
    if isinstance(question, Mapping):
        return dict(question)
    if isinstance(question, BaseModel):
        return question.model_dump(mode="json", exclude_none=True)
    raise TypeError(f"unsupported question model: {type(question).__name__}")


__all__ = ["Choice", "JSONContent", "Noul", "Question", "Score", "to_json"]
