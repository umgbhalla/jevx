"""Stdlib-only sync + async clients with retries baked in."""

from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Mapping

from . import questions as _q
from .answers import Answer, parse_answer
from .errors import (
    AuthError,
    JevError,
    OverloadedError,
    RateLimitError,
    ServerError,
    ValidationError,
)

DEFAULT_BASE_URL = "https://api.typesafe.ai"
DEFAULT_MODEL = "jev-latest"
RETRYABLE = {408, 429, 500, 502, 503, 504, 529}


@dataclass
class RetryPolicy:
    max_retries: int = 2
    backoff_initial: float = 0.5
    backoff_max: float = 5.0
    timeout: float = 30.0


@dataclass
class Response:
    answers: dict[str, Answer]
    model: str
    usage: dict
    request_id: str | None = None

    def noul(self, qid: str) -> float:
        a = self.answers[qid]
        assert hasattr(a, "prob"), f"{qid!r} is not a Noul answer"
        return a.prob  # type: ignore[attr-defined]


def _config(api_key: str | None, base_url: str | None, model: str | None):
    key = api_key or os.environ.get("TYPESAFE_API_KEY", "")
    if not key:
        raise AuthError("missing API key: pass api_key or set TYPESAFE_API_KEY")
    base = (base_url or os.environ.get("TYPESAFE_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
    mdl = model or os.environ.get("TYPESAFE_DEFAULT_MODEL", DEFAULT_MODEL)
    return key, base, mdl


def _error(status: int | None, body: bytes) -> JevError:
    try:
        detail = json.loads(body or b"{}")
    except ValueError:
        detail = {}
    msg = str(detail.get("message") or detail or f"HTTP {status}")
    if status in (401, 403):
        return AuthError(msg, status=status)
    if status == 422:
        return ValidationError(msg, status=status)
    if status == 429:
        return RateLimitError(msg, status=status)
    if status == 529:
        return OverloadedError(msg, status=status)
    if status and status >= 500:
        return ServerError(msg, status=status)
    return JevError(msg, status=status)


def _post(url: str, key: str, payload: dict, timeout: float) -> tuple[int, dict, Mapping[str, str]]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}"), r.headers
    except urllib.error.HTTPError as e:
        return e.code, {}, e.headers


def _retry_after(headers: Mapping[str, str]) -> float | None:
    for name in ("retry-after", "Retry-After", "retry-after-ms"):
        v = headers.get(name)
        if v is None:
            continue
        try:
            f = float(v)
        except ValueError:
            continue
        return f / 1000.0 if name.endswith("-ms") else f
    return None


class Client:
    """Sync client. Reads TYPESAFE_API_KEY / TYPESAFE_BASE_URL / TYPESAFE_DEFAULT_MODEL."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        retry: RetryPolicy | None = None,
    ):
        self.api_key, self.base_url, self.model = _config(api_key, base_url, model)
        self.retry = retry or RetryPolicy()

    def system_one(
        self,
        state: Any,
        questions: Mapping[str, Any],
        model: str | None = None,
    ) -> Response:
        payload = {
            "state": state,
            "model": model or self.model,
            "questions": {k: _q.to_json(v) for k, v in questions.items()},
        }
        url = f"{self.base_url}/v1/systemone"
        policy = self.retry
        wait = policy.backoff_initial
        attempt = 0
        while True:
            status, body, headers = _post(url, self.api_key, payload, policy.timeout)
            if status is not None and status not in RETRYABLE:
                if status >= 400:
                    raise _error(status, json.dumps(body).encode())
                break
            if attempt >= policy.max_retries:
                raise _error(status, json.dumps(body).encode())
            delay = _retry_after(headers) or wait
            time.sleep(min(delay, policy.backoff_max))
            wait = min(wait * 2, policy.backoff_max)
            attempt += 1
        answers = {k: parse_answer(k, v) for k, v in body.get("answers", {}).items()}
        return Response(
            answers=answers,
            model=str(body.get("model", "")),
            usage=dict(body.get("usage", {})),
            request_id=body.get("request_id"),
        )

    # Vercel-flavored alias: evaluate(state, questions) in one call.
    def evaluate(self, state: Any, questions: Mapping[str, Any], model: str | None = None) -> Response:
        return self.system_one(state, questions, model)

    def close(self) -> None:
        pass

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


class AsyncClient:
    """Async client (stdlib; runs the sync transport in a thread)."""

    def __init__(self, **kwargs: Any):
        self._sync = Client(**kwargs)

    async def system_one(self, state: Any, questions: Mapping[str, Any], model: str | None = None) -> Response:
        return await asyncio.to_thread(self._sync.system_one, state, questions, model)

    async def evaluate(self, state: Any, questions: Mapping[str, Any], model: str | None = None) -> Response:
        return await self.system_one(state, questions, model)

    async def __aenter__(self) -> "AsyncClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None


def evaluate(state: Any, questions: Mapping[str, Any], model: str | None = None) -> Response:
    """One-shot: builds a default Client from env and evaluates."""
    return Client().evaluate(state, questions, model)


__all__ = ["AsyncClient", "Client", "Response", "RetryPolicy", "evaluate", "field"]
