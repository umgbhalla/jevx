"""Instructor-style Pydantic response models for batched System One questions.

``ask(...) | level(...)`` is a Pydantic field declaration, not a model call.
The question's field name supplies its ID; ``create`` supplies the shared state.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from .answers import ChoiceAnswer
from .answers import NoulAnswer
from .answers import ScoreAnswer
from .answers import parse_answer
from .questions import Choice
from .questions import JSONContent
from .questions import Noul
from .questions import Score


@dataclass(frozen=True)
class _Criterion:
    kind: str
    value: JSONContent | None
    name: str | None = None


class QuestionField(FieldInfo):
    """A required Pydantic field carrying one System One question declaration."""

    def __init__(
        self,
        instructions: JSONContent,
        criteria: tuple[_Criterion, ...] = (),
    ) -> None:
        description = instructions if isinstance(instructions, str) else None
        if isinstance(instructions, Mapping):
            question = instructions.get("question")
            description = question if isinstance(question, str) else None
        super().__init__(
            description=description,
            json_schema_extra={
                "jevx": {
                    "instructions": instructions,
                    "criteria": [
                        {"kind": entry.kind, "name": entry.name, "value": entry.value}
                        for entry in criteria
                    ],
                }
            },
        )
        self.instructions = instructions
        self.criteria = criteria

    def __or__(self, other: _Criterion) -> QuestionField:
        if not isinstance(other, _Criterion):
            return NotImplemented
        family = "noul" if other.kind in {"yes", "no"} else other.kind
        existing = self.criteria[0].kind if self.criteria else None
        existing_family = "noul" if existing in {"yes", "no"} else existing
        if existing_family is not None and existing_family != family:
            raise TypeError("one question cannot mix option, level, yes, and no criteria")
        if other.kind in {"option", "yes", "no"} and any(
            entry.name == other.name for entry in self.criteria
        ):
            raise ValueError(f"duplicate criterion {other.name!r}")
        return QuestionField(self.instructions, (*self.criteria, other))


def ask(instructions: JSONContent) -> QuestionField:
    """Begin a field declaration; accepts text or structured instructions."""
    return QuestionField(instructions)


def option(name: str, description: JSONContent | None = None) -> _Criterion:
    """Add a named Choice option, with optional structured guidance."""
    if not isinstance(name, str) or not name:
        raise ValueError("a Choice option needs a nonempty string name")
    return _Criterion("option", description, name)


def level(description: JSONContent) -> _Criterion:
    """Append one ordered Score level."""
    return _Criterion("level", description)


def yes(description: JSONContent) -> _Criterion:
    """Describe what a positive Noul answer means."""
    return _Criterion("yes", description, "true")


def no(description: JSONContent) -> _Criterion:
    """Describe what a negative Noul answer means."""
    return _Criterion("no", description, "false")


_ANSWER_TYPES = {NoulAnswer: "noul", ChoiceAnswer: "choice", ScoreAnswer: "score"}


def questions_for(response_model: type[BaseModel]) -> dict[str, Noul | Choice | Score]:
    """Compile model fields into one named request, rejecting unsupported fields."""
    if not isinstance(response_model, type) or not issubclass(response_model, BaseModel):
        raise TypeError("response_model must be a Pydantic BaseModel subclass")
    if not response_model.model_fields:
        raise ValueError("response_model needs at least one question field")

    questions: dict[str, Noul | Choice | Score] = {}
    for name, field in response_model.model_fields.items():
        if not isinstance(field, QuestionField):
            raise TypeError(f"{name}: use j.ask(...) to declare a question field")
        kind = _ANSWER_TYPES.get(field.annotation)
        if kind is None:
            raise TypeError(
                f"{name}: annotate with NoulAnswer, ChoiceAnswer, or ScoreAnswer"
            )
        entries = field.criteria
        entry_kind = entries[0].kind if entries else None
        if kind == "noul":
            if entry_kind not in {None, "yes", "no"}:
                raise TypeError(f"{name}: Noul accepts only yes/no criteria")
            criteria = {entry.name: entry.value for entry in entries} if entries else None
            questions[name] = Noul(instructions=field.instructions, criteria=criteria)
        elif kind == "choice":
            if entry_kind != "option" or len(entries) < 2:
                raise ValueError(f"{name}: Choice needs at least two options")
            questions[name] = Choice(
                instructions=field.instructions,
                criteria={entry.name: entry.value for entry in entries},
            )
        else:
            if entry_kind != "level" or not 2 <= len(entries) <= 10:
                raise ValueError(f"{name}: Score needs 2 to 10 ordered levels")
            questions[name] = Score(
                instructions=field.instructions,
                criteria=[entry.value for entry in entries],
            )
    return questions


def validate_answers(response_model: type[BaseModel], answers: Mapping[str, Any]) -> BaseModel:
    """Keep upstream distributions and confidence in the returned Pydantic model."""
    questions = questions_for(response_model)
    values = {}
    for name, question in questions.items():
        try:
            answer = answers[name]
        except KeyError:
            raise ValueError(f"missing answer for {name!r}") from None
        if isinstance(answer, BaseModel):
            answer = answer.model_dump(mode="python")
        expected = question.type
        if not isinstance(answer, Mapping) or answer.get("type") != expected:
            raise ValueError(f"{name}: expected a {expected} answer")
        if expected == "choice" and answer.get("choice") not in question.criteria:
            raise ValueError(f"{name}: choice is outside the declared options")
        values[name] = parse_answer(name, answer)
    return response_model.model_validate(values)


__all__ = [
    "QuestionField", "ask", "level", "no", "option", "questions_for", "validate_answers", "yes",
]
