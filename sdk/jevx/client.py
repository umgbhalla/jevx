"""TypeSafe SDK client exports used by Jevx."""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel
from typesafe_sdk import AsyncTypeSafeClient
from typesafe_sdk import RetryPolicy
from typesafe_sdk import SystemOneResponse as Response
from typesafe_sdk import TypeSafeClient

from .model import questions_for
from .model import validate_answers
from .questions import JSONContent

ModelT = TypeVar("ModelT", bound=BaseModel)


class Client(TypeSafeClient):
    """TypeSafe client with Pydantic ``response_model`` compilation."""

    def create(
        self,
        *,
        response_model: type[ModelT],
        state: JSONContent | BaseModel,
        model: str | None = None,
        **request_options,
    ) -> ModelT:
        questions = questions_for(response_model)
        kwargs = {"model": model} if model is not None else {}
        payload_state = state.model_dump(mode="json") if isinstance(state, BaseModel) else state
        response = self.system_one(
            state=payload_state, questions=questions, **kwargs, **request_options
        )
        return validate_answers(response_model, response.answers)


class AsyncClient(AsyncTypeSafeClient):
    """Async counterpart to ``Client.create``."""

    async def create(
        self,
        *,
        response_model: type[ModelT],
        state: JSONContent | BaseModel,
        model: str | None = None,
        **request_options,
    ) -> ModelT:
        questions = questions_for(response_model)
        kwargs = {"model": model} if model is not None else {}
        payload_state = state.model_dump(mode="json") if isinstance(state, BaseModel) else state
        response = await self.system_one(
            state=payload_state, questions=questions, **kwargs, **request_options
        )
        return validate_answers(response_model, response.answers)


def evaluate(state, questions, model: str | None = None) -> Response:
    """Make one System One request with a short-lived TypeSafe client."""
    with Client(model=model) as client:
        return client.system_one(state, questions)


__all__ = ["AsyncClient", "Client", "Response", "RetryPolicy", "evaluate"]
