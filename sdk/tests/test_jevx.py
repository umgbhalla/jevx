"""Hermetic tests: no network, transport stubbed."""

import io
import json
import urllib.error
import urllib.request

import pytest

import jevx
from jevx import Choice, Client, Noul, Score


class FakeHeaders(dict):
    pass


class FakeResp:
    def __init__(self, status, payload):
        self.status = status
        self._payload = payload
        self.headers = FakeHeaders()

    def read(self):
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return None


def canned():
    return {
        "model": "jev-1.13.0",
        "answers": {
            "u": {"type": "noul", "noul": 0.92},
            "t": {
                "type": "choice",
                "choice": "infra",
                "probabilities": {"infra": 0.9, "billing": 0.1},
                "confidence": 0.8,
            },
            "s": {
                "type": "score",
                "score": 1.6,
                "legend": {"0": "low", "1": "mid", "2": "high"},
                "probabilities": {"0": 0.1, "1": 0.2, "2": 0.7},
                "confidence": 0.6,
            },
        },
        "usage": {"input_tokens": 10, "output_tokens": 0},
    }


def patch_urlopen(monkeypatch, script):
    """script: list of FakeResp | urllib.error.HTTPError to return in order."""
    calls = {"n": 0, "bodies": []}

    def fake(req, timeout=None):
        calls["n"] += 1
        calls["bodies"].append(json.loads(req.data.decode()))
        item = script[min(calls["n"] - 1, len(script) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return calls


def err(code):
    return urllib.error.HTTPError("url", code, "x", FakeHeaders(), io.BytesIO(b"{}"))


def test_builders_validate():
    with pytest.raises(ValueError):
        Noul(instructions="  ")
    with pytest.raises(ValueError):
        Choice(instructions="x", criteria={})
    with pytest.raises(ValueError):
        Choice(instructions="x", criteria={f"o{i}": None for i in range(256)})
    with pytest.raises(ValueError):
        Score(instructions="x", criteria=["only-one"])
    assert Noul(instructions="q?").to_json()["type"] == "noul"
    assert Choice(instructions="q?", criteria={"a": None}).to_json()["criteria"] == {"a": None}


def test_evaluate_parses_all_types(monkeypatch):
    calls = patch_urlopen(monkeypatch, [FakeResp(200, canned())])
    c = Client(api_key="k")
    r = c.evaluate("deploy failed", {"u": Noul(instructions="urgent?")})
    assert r.model == "jev-1.13.0"
    assert r.noul("u") == 0.92
    assert r.answers["t"].choice == "infra"
    assert r.answers["t"].top(1) == [("infra", 0.9)]
    assert r.answers["s"].level() == 2
    assert r.answers["s"].normalized() == pytest.approx(0.8)
    body = calls["bodies"][0]
    assert body["model"] == "jev-latest"
    assert set(body["questions"]) == {"u"}


def test_retry_then_success(monkeypatch):
    sleeps = []
    monkeypatch.setattr("jevx.client.time.sleep", lambda s: sleeps.append(s))
    patch_urlopen(monkeypatch, [err(429), FakeResp(200, canned())])
    r = Client(api_key="k").evaluate("x", {"u": Noul(instructions="q?")})
    assert r.noul("u") == 0.92
    assert sleeps == [0.5]


def test_retry_exhausted_raises(monkeypatch):
    monkeypatch.setattr("jevx.client.time.sleep", lambda s: None)
    patch_urlopen(monkeypatch, [err(529)])
    with pytest.raises(jevx.OverloadedError):
        Client(api_key="k").evaluate("x", {"u": Noul(instructions="q?")})


def test_auth_and_validation_errors(monkeypatch):
    patch_urlopen(monkeypatch, [err(401)])
    with pytest.raises(jevx.AuthError):
        Client(api_key="bad").evaluate("x", {})
    patch_urlopen(monkeypatch, [err(422)])
    with pytest.raises(jevx.ValidationError):
        Client(api_key="k").evaluate("x", {})


def test_missing_key():
    with pytest.raises(jevx.AuthError):
        Client(api_key="")


def test_bands():
    assert jevx.NoulAnswer(0.9).band() == "yes"
    assert jevx.NoulAnswer(0.5).band() == "review"
    assert jevx.NoulAnswer(0.1).band() == "no"
