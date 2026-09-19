"""Tests for jevx.py idioms. Transport stubbed; no network."""

import pytest

from jevx import answers as A
from jevx.client import Response
from jevx.py import (
    AmbiguousTruth,
    Choice,
    P,
    Questions,
    Refused,
    Score,
    StaleReplay,
    ask,
    feels,
    gate,
    pick,
    rate,
    record,
    replay,
    route,
)
from typing import Literal


def canned():
    return {
        "u": {"type": "noul", "noul": 0.92},
        "t": {
            "type": "choice", "choice": "billing",
            "probabilities": {"billing": 0.9, "bug": 0.1}, "confidence": 0.85,
        },
        "s": {
            "type": "score", "score": 1.6,
            "legend": {"0": "low", "1": "mid", "2": "high"},
            "probabilities": {"0": 0.1, "1": 0.2, "2": 0.7}, "confidence": 0.6,
        },
    }


class FakeClient:
    def __init__(self, answers=None):
        by_type = answers or canned()
        # accept {qid: answer} (canned) or {"noul":..., "choice":..., "score":...}
        if set(by_type) <= {"noul", "choice", "score"}:
            self.by_type = dict(by_type)
        else:
            self.by_type = {}
            for v in by_type.values():
                self.by_type.setdefault(v["type"], v)
        self.seen = []

    def system_one(self, state, questions, model=None):
        self.seen.append((state, questions))
        out = {k: A.parse_answer(k, self.by_type[q["type"]]) for k, q in questions.items()}
        return Response(answers=out, model="jev-1.13.0", usage={})


def test_p_arithmetic_and_explicit_truth():
    assert (P(0.9) & P(0.5)) == pytest.approx(0.45)
    assert (P(0.9) | P(0.5)) == pytest.approx(0.95)
    assert (~P(0.9)) == pytest.approx(0.1)
    assert (P(0.9) > 0.5) is True
    with pytest.raises(AmbiguousTruth):
        bool(P(0.9))
    with pytest.raises(AmbiguousTruth):
        P(0.9) and True
    with pytest.raises(ValueError):
        P(1.5)
    assert P(0.9).band() == "yes" and P(0.2).band() == "no"


def test_verbs_single_request():
    c = FakeClient()
    assert float(feels("urgent?", "x", client=c)) == 0.92
    ch = pick("team?", "x", {"billing": "...", "bug": "..."}, client=c)
    assert ch.choice == "billing"
    s = rate("sev?", "x", ["low", "mid", "high"], client=c)
    assert float(s) == 1.6 and s.confidence == 0.6
    assert len(c.seen) == 3  # one request per verb call


def test_match_on_choice():
    c = FakeClient()
    match pick("team?", "x", ["billing", "bug"], client=c):
        case Choice(choice="billing", confidence=conf) if conf > 0.9:
            out = "sure-billing"
        case Choice(choice="billing"):
            out = "billing"
        case _:
            out = "other"
    assert out == "billing"


def test_declarative_battery_one_request():
    class Triage(Questions):
        urgent: bool = ask("reply within the hour?")
        team: Literal["billing", "bug"] = ask("which team?")
        sev: Score["low", "mid", "high"] = ask("how severe?")

    c = FakeClient()
    t = Triage(client=c)("ticket!")
    assert len(c.seen) == 1
    assert t.urgent is True and t.team == "billing" and t.sev == 1.6
    assert t.confidence("team") == 0.85
    with pytest.raises(TypeError):
        t.urgent = False
    assert "'urgent': True" in repr(t)


def test_gate_refuses_and_passes():
    @gate("destroys data?", over=0.8, client=FakeClient())  # canned u=0.92
    def wipe(path):
        return f"wiped {path}"

    with pytest.raises(Refused) as e:
        wipe("/tmp/x")
    assert e.value.prob == 0.92

    low = FakeClient({"u": {"type": "noul", "noul": 0.1}})
    ok = gate("destroys data?", over=0.8, client=low)(lambda p: f"wiped {p}")
    assert ok("/tmp/x") == "wiped /tmp/x"


def test_route_dispatch():
    @route({"billing": "...", "bug": "..."}, client=FakeClient())
    def handle(team, ticket):
        return f"{team}:{ticket}"

    assert handle("T!") == "billing:T!"
    assert handle.last_choice.choice == "billing"


def test_record_replay_roundtrip(tmp_path):
    log = str(tmp_path / "run.jsonl")
    c = FakeClient()
    with record(log):
        assert float(feels("urgent?", "hi", client=c)) == 0.92
    with replay(log):
        # no client at all — offline
        assert float(feels("urgent?", "hi", client=None)) == 0.92
    with replay(log):
        with pytest.raises(StaleReplay):
            feels("different question?", "hi", client=None)
