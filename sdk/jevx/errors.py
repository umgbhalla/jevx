"""TypeSafe SDK errors exposed through Jevx."""

from typesafe_sdk import TypeSafeAuthenticationError as AuthError
from typesafe_sdk import TypeSafeError as JevError
from typesafe_sdk import TypeSafeInternalServerError as ServerError
from typesafe_sdk import TypeSafeRateLimitError as RateLimitError
from typesafe_sdk import TypeSafeUnprocessableEntityError as ValidationError

__all__ = ["AuthError", "JevError", "RateLimitError", "ServerError", "ValidationError"]
