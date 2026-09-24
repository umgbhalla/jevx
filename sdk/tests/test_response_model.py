"""The Pydantic declaration surface compiles to one exact TypeSafe request."""

import asyncio
import json
from types import SimpleNamespace

import httpx2
import pytest
from pydantic import BaseModel
from pydantic import computed_field

import jevx as j
from jevx.model import questions_for


class TicketTriage(BaseModel):
    severity: j.ScoreAnswer = (
        j.ask("How severe is the bug?")
        | j.level("Cosmetic")
        | j.level("Degraded with workaround")
        | j.level("Blocked without workaround")
    )
    frustration: j.ScoreAnswer = (
        j.ask("How frustrated is the customer?")
        | j.level("Calm")
        | j.level("Frustrated")
        | j.level("Very angry")
    )
    route: j.ChoiceAnswer = (
        j.ask({"question": "Which team?", "inspect": ["ticket.message"]})
        | j.option("billing", {"what": "Payment issues", "not_for": "Bugs"})
        | j.option("support", {"what": "Product bugs"})
        | j.option("other", None)
    )
    resolved: j.NoulAnswer = (
        j.ask("Does the reply resolve the ticket?")
        | j.yes({"what": "The user can finish the task"})
        | j.no("A necessary step is missing")
    )

    @computed_field
    @property
    def priority(self) -> float:
        return 0.6 * self.severity.score / 2 + 0.4 * self.frustration.score / 2


ANSWERS = {
    "severity": {
        "type": "score", "score": 1.5, "confidence": 0.5,
        "legend": {
            "0": "Cosmetic", "1": "Degraded with workaround", "2": "Blocked without workaround",
        },
        "probabilities": {"0": 0, "1": 0.5, "2": 0.5},
    },
    "frustration": {
        "type": "score", "score": 1.0, "confidence": 1.0,
        "legend": {"0": "Calm", "1": "Frustrated", "2": "Very angry"},
        "probabilities": {"0": 0, "1": 1, "2": 0},
    },
    "route": {
        "type": "choice", "choice": "support", "confidence": 0.7,
        "probabilities": {"billing": 0.1, "support": 0.8, "other": 0.1},
    },
    "resolved": {"type": "noul", "noul": 0.9},
}


class StubClient(j.Client):
    def __init__(self):
        self.calls = []

    def system_one(self, state, questions, *, model=None):
        self.calls.append((state, questions, model))
        return SimpleNamespace(answers=ANSWERS)


def test_response_model_batches_questions_and_keeps_full_answers():
    client = StubClient()
    state = {"ticket": {"message": "PDF export hangs"}}
    result = client.create(response_model=TicketTriage, state=state, model="jev-latest")

    assert isinstance(result, TicketTriage)
    assert result.priority == pytest.approx(0.65)
    assert result.route.choice == "support"
    assert result.route.probabilities["billing"] == 0.1
    assert result.severity.probabilities[2] == 0.5
    assert result.resolved.noul == 0.9
    assert len(client.calls) == 1
    sent_state, questions, model = client.calls[0]
    assert sent_state == state and model == "jev-latest"
    assert set(questions) == {"severity", "frustration", "route", "resolved"}
    assert questions["severity"].criteria == [
        "Cosmetic", "Degraded with workaround", "Blocked without workaround",
    ]
    assert questions["route"].instructions == {
        "question": "Which team?", "inspect": ["ticket.message"],
    }
    assert questions["route"].criteria["billing"] == {
        "what": "Payment issues", "not_for": "Bugs",
    }
    assert questions["resolved"].criteria == {
        "true": {"what": "The user can finish the task"},
        "false": "A necessary step is missing",
    }


def test_invalid_declarations_fail_before_an_api_call():
    with pytest.raises(TypeError, match="cannot mix"):
        j.ask("question") | j.level("low") | j.option("x")
    with pytest.raises(ValueError, match="duplicate"):
        j.ask("question") | j.option("x") | j.option("x")

    class TooFew(BaseModel):
        score: j.ScoreAnswer = j.ask("How much?") | j.level("only level")

    with pytest.raises(ValueError, match="2 to 10"):
        questions_for(TooFew)

    class WrongType(BaseModel):
        answer: str = j.ask("Which?") | j.option("a") | j.option("b")

    with pytest.raises(TypeError, match="annotate"):
        questions_for(WrongType)

    class MissingField(BaseModel):
        answer: j.NoulAnswer

    with pytest.raises(TypeError, match="j.ask"):
        questions_for(MissingField)


def test_undeclared_choice_response_is_rejected():
    bad = {**ANSWERS, "route": {**ANSWERS["route"], "choice": "unknown"}}
    client = StubClient()
    client.system_one = lambda *args, **kwargs: SimpleNamespace(answers=bad)
    with pytest.raises(ValueError, match="outside the declared options"):
        client.create(response_model=TicketTriage, state="ticket")


def test_async_client_uses_the_same_compiler_and_model():
    class StubAsyncClient(j.AsyncClient):
        def __init__(self):
            pass

        async def system_one(self, state, questions, *, model=None):
            assert state == "ticket"
            assert set(questions) == set(TicketTriage.model_fields)
            return SimpleNamespace(answers=ANSWERS)

    result = asyncio.run(
        StubAsyncClient().create(response_model=TicketTriage, state="ticket")
    )
    assert isinstance(result, TicketTriage)
    assert result.priority == pytest.approx(0.65)


def test_real_client_serializes_one_request_with_shared_state():
    sent = []

    def handle(request):
        sent.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "model": "jev-1.13.0",
                "answers": ANSWERS,
                "usage": {"input_tokens": 30, "output_tokens": 15},
            },
        )

    state = {"ticket": {"message": "PDF export hangs"}}
    with j.Client(api_key="unused", transport=httpx2.MockTransport(handle)) as client:
        result = client.create(response_model=TicketTriage, state=state)

    assert result.route.choice == "support"
    assert len(sent) == 1
    assert sent[0]["state"] == state
    assert sent[0]["model"] == "jev-latest"
    assert sent[0]["questions"]["route"] == {
        "type": "choice",
        "instructions": {"question": "Which team?", "inspect": ["ticket.message"]},
        "criteria": {
            "billing": {"what": "Payment issues", "not_for": "Bugs"},
            "support": {"what": "Product bugs"},
            "other": None,
        },
    }
