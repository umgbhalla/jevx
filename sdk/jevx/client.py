"""Stdlib-only sync + async clients with retries baked in."""

from __future__ import annotations

import asyncio
import json
import os
import random
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from . import questions as _q
from .answers import Answer
from .answers import ChoiceAnswer
from .answers import NoulAnswer
from .answers import ScoreAnswer
from .answers import parse_answer
from .errors import AuthError
from .errors import JevError

DEFAULT_BASE_URL = "https://api.typesafe.ai"
DEFAULT_MODEL = "jev-latest"
RETRYABLE = {408, 429, 500, 502, 503, 504, 529}


@dataclass
class RetryPolicy:
    max_retries: int = 2
    backoff_initial: float = 0.5
    backoff_max: float = 5.0
    timeout: float = 30.0
    jitter: float = 0.1

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if self.timeout <= 0:
            raise ValueError("timeout must be > 0")


@dataclass
class Response:
    answers: dict[str, Answer]
    model: str
    usage: dict
    request_id: str | None = None

    def get(self, qid: str) -> Answer | None:
        return self.answers.get(qid)

    def noul(self, qid: str) -> float:
        a = self.answers[qid]
        if not isinstance(a, NoulAnswer):
            raise TypeError(f"{qid!r} is not a Noul answer")
        return a.prob

    def choice(self, qid: str) -> tuple[str, float]:
        a = self.answers[qid]
        if not isinstance(a, ChoiceAnswer):
            raise TypeError(f"{qid!r} is not a Choice answer")
        return a.choice, a.confidence

    def score(self, qid: str) -> float:
        a = self.answers[qid]
        if not isinstance(a, ScoreAnswer):
            raise TypeError(f"{qid!r} is not a Score answer")
        return a.score


def _config(api_key: str | None, base_url: str | None, model: str | None):
    key = api_key or os.environ.get("TYPESAFE_API_KEY", "")
    if not key:
        raise AuthError("missing API key: pass api_key or set TYPESAFE_API_KEY")
    base = (base_url or os.environ.get("TYPESAFE_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
    if not base.startswith("https://"):
        raise AuthError(f"base_url must be https, got {base!r}")
    mdl = model or os.environ.get("TYPESAFE_DEFAULT_MODEL", DEFAULT_MODEL)
    return key, base, mdl


class _Transient(JevError):
    """Network-level failure (DNS, refused, timeout). Always retryable."""

    @property
    def retryable(self) -> bool:
        return True


def _post(url: str, key: str, payload: dict, timeout: float) -> tuple[Any, bytes, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read() or b"{}", r.headers
    except urllib.error.HTTPError as e:
        status = e.code if isinstance(e.code, int) else None
        return status, e.read() or b"{}", e.headers
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise _Transient(f"transport failure: {e}") from e


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


def _payload(state: Any, questions: Mapping[str, Any], model: str) -> dict:
    return {
        "state": state,
        "model": model,
        "questions": {k: _q.to_json(v) for k, v in questions.items()},
    }


def _decode(body: bytes) -> Response:
    try:
        data = json.loads(body or b"{}")
    except ValueError as e:
        raise JevError(f"invalid JSON response: {e}") from e
    if not isinstance(data, dict):
        raise JevError("invalid response envelope")
    answers = {k: parse_answer(k, v) for k, v in data.get("answers", {}).items()}
    usage = data.get("usage", {})
    return Response(
        answers=answers,
        model=str(data.get("model", "")),
        usage=dict(usage) if isinstance(usage, dict) else {},
        request_id=data.get("request_id"),
    )


def _call_with_retry(post, policy: RetryPolicy) -> tuple[int | None, bytes, Mapping[str, str]]:
    wait = policy.backoff_initial
    attempt = 0
    while True:
        try:
            status, body, headers = post()
        except _Transient:
            if attempt >= policy.max_retries:
                raise
            status, body, headers = None, b"{}", {}
        if status is None or status in RETRYABLE:
            if attempt >= policy.max_retries:
                if status is None:
                    raise _Transient("transport failure after retries")
                from .errors import JevError as _JE

                raise _JE.from_status(status, _message(body), None)
            delay = _retry_after(headers) or wait
            delay = min(delay, policy.backoff_max)
            time.sleep(delay + random.uniform(0, delay * policy.jitter))
            wait = min(wait * 2, policy.backoff_max)
            attempt += 1
            continue
        return status, body, headers


def _message(body: bytes) -> str:
    try:
        detail = json.loads(body or b"{}")
    except ValueError:
        return f"HTTP error ({len(body)} bytes)"
    return str(detail.get("message") or detail or "HTTP error")


class Client:
    """Sync client. Reads TYPESAFE_API_KEY / TYPESAFE_BASE_URL / TYPESAFE_DEFAULT_MODEL."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        retry: RetryPolicy | None = None,
    ) -> None:
        self.api_key, self.base_url, self.model = _config(api_key, base_url, model)
        self.retry = retry or RetryPolicy()

    def system_one(
        self,
        state: Any,
        questions: Mapping[str, Any],
        model: str | None = None,
    ) -> Response:
        payload = _payload(state, questions, model or self.model)
        url = f"{self.base_url}/v1/systemone"
        policy = self.retry

        def post():
            return _post(url, self.api_key, payload, policy.timeout)

        status, body, _ = _call_with_retry(post, policy)
        if status is not None and status >= 400:
            from .errors import JevError as _JE

            raise _JE.from_status(status, _message(body), None)
        return _decode(body)

    # Vercel-flavored alias: evaluate(state, questions) in one call.
    def evaluate(
        self, state: Any, questions: Mapping[str, Any], model: str | None = None
    ) -> Response:
        return self.system_one(state, questions, model)

    def close(self) -> None:
        pass

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


class AsyncClient:
    """Async client (stdlib; runs the sync transport in a thread)."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        retry: RetryPolicy | None = None,
    ) -> None:
        self._sync = Client(api_key=api_key, base_url=base_url, model=model, retry=retry)

    async def system_one(
        self, state: Any, questions: Mapping[str, Any], model: str | None = None
    ) -> Response:
        return await asyncio.to_thread(self._sync.system_one, state, questions, model)

    async def evaluate(
        self, state: Any, questions: Mapping[str, Any], model: str | None = None
    ) -> Response:
        return await self.system_one(state, questions, model)

    async def __aenter__(self) -> AsyncClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None


def evaluate(state: Any, questions: Mapping[str, Any], model: str | None = None) -> Response:
    """One-shot: builds a default Client from env and evaluates."""
    return Client().evaluate(state, questions, model)


__all__ = ["AsyncClient", "Client", "Response", "RetryPolicy", "evaluate"]
