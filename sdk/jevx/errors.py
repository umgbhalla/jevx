"""Typed errors."""


class JevError(Exception):
    """Base error. Carries HTTP status and TypeSafe request id when known."""

    def __init__(self, message: str, *, status: int | None = None, request_id: str | None = None):
        super().__init__(message)
        self.status = status
        self.request_id = request_id


class AuthError(JevError):
    """401/403 — missing or invalid API key."""


class ValidationError(JevError):
    """422 — request failed validation (also raised client-side by builders)."""


class RateLimitError(JevError):
    """429 — over rate limits. Retry after backoff."""


class OverloadedError(JevError):
    """529 — temporarily overloaded. Retry after backoff."""


class ServerError(JevError):
    """5xx — server failure."""
