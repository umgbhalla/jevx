"""TypeSafe SDK client exports used by Jevx."""

from __future__ import annotations

from typesafe_sdk import AsyncTypeSafeClient as AsyncClient
from typesafe_sdk import RetryPolicy
from typesafe_sdk import SystemOneResponse as Response
from typesafe_sdk import TypeSafeClient as Client


def evaluate(state, questions, model: str | None = None) -> Response:
    """Make one System One request with a short-lived TypeSafe client."""
    with Client(model=model) as client:
        return client.system_one(state, questions)


__all__ = ["AsyncClient", "Client", "Response", "RetryPolicy", "evaluate"]
