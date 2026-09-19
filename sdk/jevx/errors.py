"""Typed errors."""

from __future__ import annotations


class JevError(Exception):
    """Base error. Carries HTTP status and TypeSafe request id when known."""

    def __init__(self, message: str, *, status: int | None = None, request_id: str | None = None):
        super().__init__(message)
        self.status = status
        self.request_id = request_id

    @property
    def retryable(self) -> bool:
        return self.status in {408, 429, 500, 502, 503, 504, 529}

    @staticmethod
    def from_status(status: int | None, message: str, request_id: str | None = None) -> JevError:
        if status in (401, 403):
            return AuthError(message, status=status, request_id=request_id)
        if status == 422:
            return ValidationError(message, status=status, request_id=request_id)
        if status == 429:
            return RateLimitError(message, status=status, request_id=request_id)
        if status == 529:
            return OverloadedError(message, status=status, request_id=request_id)
        if status is not None and status >= 500:
            return ServerError(message, status=status, request_id=request_id)
        return JevError(message, status=status, request_id=request_id)


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
