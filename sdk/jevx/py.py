"""Idiomatic Jev: judgments as Python grammar.

``feels`` asks yes/no, ``pick`` chooses, ``rate`` scores — all in ONE request
per state when batched. Pattern-match answers, combine probabilities with
operators, declare batteries as classes, gate functions, replay runs offline.

    from jevx.py import feels, pick, Questions, ask, gate

    if feels("is this urgent?", ticket).over(0.8):
        escalate(ticket)

    match pick("which team?", ticket, {"billing": "...", "bug": "..."}):
        case Choice(choice="billing", confidence=c) if c > 0.9:
            bill(ticket)
        case Choice(choice=team):
            triage(team, ticket)

    class Triage(Questions):
        urgent: bool = ask("reply within the hour?")
        team: Literal["billing", "bug"] = ask("which team owns it?")
        sev: Score["low", "high"] = ask("how severe?")

    t = Triage()(ticket)   # one request; t.urgent is bool, t.team is str
"""

from __future__ import annotations

import contextlib
import functools
import hashlib
import inspect
import json
import sys as _sys
import typing as _typing
from typing import Annotated, Any, Literal, Mapping, get_args, get_origin

from .answers import ChoiceAnswer as Choice
from .answers import parse_answer
from .client import Client, Response
from .questions import Choice as _ChoiceQ
from .questions import Noul as _NoulQ
from .questions import Score as _ScoreQ

__all__ = [
    "AmbiguousTruth",
    "Choice",
    "P",
    "Questions",
    "Refused",
    "Score",
    "StaleReplay",
    "ask",
    "feels",
    "gate",
    "pick",
    "rate",
    "record",
    "replay",
    "route",
]


class AmbiguousTruth(TypeError):
    """Raised by bool(P): collapse uncertainty explicitly (.over/.under/band)."""


class Refused(Exception):
    """A @gate decorator refused the call."""

    def __init__(self, message: str, *, prob: float):
        super().__init__(message)
        self.prob = prob


class StaleReplay(Exception):
    """Replay log doesn't match the questions being asked."""


class P(float):
    """A probability 0..1. Fuzzy &, |, ~. Comparisons return bool.
    Bare bool() raises — pandas-style, ambiguity must be explicit."""

    def __new__(cls, v: float) -> "P":
        f = float(v)
        if not 0.0 <= f <= 1.0:
            raise ValueError(f"P must be within 0..1, got {v!r}")
        return super().__new__(cls, f)

    def __and__(self, o: float) -> "P":
        return P(float(self) * float(o))

    def __or__(self, o: float) -> "P":
        a, b = float(self), float(o)
        return P(a + b - a * b)

    def __invert__(self) -> "P":
        return P(1.0 - float(self))

    def __bool__(self) -> bool:
        raise AmbiguousTruth(
            f"bool({float(self)!r}) is ambiguous — use .over(t), .under(t) or .band()"
        )

    def over(self, t: float = 0.5) -> bool:
        return float(self) >= t

    def under(self, t: float = 0.5) -> bool:
        return float(self) < t

    def band(self, review_at: float = 0.35, act_at: float = 0.70) -> str:
        if float(self) >= act_at:
            return "yes"
        if float(self) >= review_at:
            return "review"
        return "no"


class Score(float):
    """A spectrum position with its confidence attached."""

    confidence: float
    legend: tuple

    def __new__(cls, value: float, *, confidence: float, legend: tuple) -> "Score":
        obj = super().__new__(cls, value)
        obj.confidence = confidence
        obj.legend = legend
        return obj

    def level(self) -> int:
        return int(round(float(self)))

    @classmethod
    def __class_getitem__(cls, levels) -> "_Levels":
        if isinstance(levels, str):
            levels = (levels,)
        return _Levels(tuple(levels))


class _Levels:
    """Score["low", "high"] in a Questions annotation."""

    def __init__(self, levels: tuple):
        if len(levels) < 2:
            raise ValueError("Score needs >= 2 levels")
        self.levels = levels


# ---------------------------------------------------------------- internals

_Hooks: list = []  # pre/post hooks for record/replay


class _Serve(Exception):
    def __init__(self, answers: dict):
        self.answers = answers


def _sha(state: Any, questions: dict) -> str:
    return hashlib.sha256(
        json.dumps({"s": state, "q": questions}, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]


def _decide(state: Any, questions: dict, client: Client | None) -> dict[str, Any]:
    payload = {k: (v.to_json() if hasattr(v, "to_json") else v) for k, v in questions.items()}
    for hook in _Hooks:
        if r := hook("pre", state, payload):
            return r
    resp = (client or Client()).system_one(state, payload)
    out = {k: resp.answers[k] for k in questions}
    for hook in _Hooks:
        hook("post", state, payload, out)
    return out


# ---------------------------------------------------------------- verbs


def feels(
    question: str,
    state: Any,
    *,
    true: str | None = None,
    false: str | None = None,
    client: Client | None = None,
) -> P:
    """One yes/no judgment -> P. Combine: feels(a) & ~feels(b)."""
    (a,) = _decide(state, {"p": _NoulQ(question, true, false)}, client).values()
    return P(a.prob)


def pick(
    question: str,
    state: Any,
    options: Mapping[str, str | None] | list | tuple,
    *,
    client: Client | None = None,
) -> Choice:
    """One pick-one judgment -> matchable Choice. Match on it."""
    if isinstance(options, (list, tuple)):
        options = {o: None for o in options}
    (a,) = _decide(state, {"c": _ChoiceQ(question, dict(options))}, client).values()
    return a


def rate(
    question: str,
    state: Any,
    levels: list | tuple,
    *,
    client: Client | None = None,
) -> Score:
    """One spectrum judgment -> Score float with .confidence."""
    (a,) = _decide(state, {"s": _ScoreQ(question, list(levels))}, client).values()
    return Score(a.score, confidence=a.confidence, legend=tuple(levels))


def ask(question: str, *, threshold: float = 0.5) -> "_Field":
    """Declare a battery field inside a Questions class (descriptor)."""
    return _Field(question, threshold)


def _hints(cls: type) -> dict[str, Any]:
    """Resolved annotations (class bodies are strings under `from __future__`)."""
    ns = dict(vars(_sys.modules[__name__]))  # SDK names first (base-class annotations)
    ns.update(vars(_sys.modules[cls.__module__]))
    ns.setdefault("Literal", Literal)
    ns.setdefault("Score", Score)
    ns.setdefault("bool", bool)
    out = _typing.get_type_hints(cls, globalns=ns)
    out.pop("_fields_", None)
    out.pop("_client", None)
    return out


class _Field:
    def __init__(self, question: str, threshold: float):
        self.question = question
        self.threshold = threshold
        self.name = ""

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name


class Questions:
    """Declarative battery. Annotations decide the question kind; one request.

    bool -> Noul (threshold per field via ask(..., threshold=))
    Literal[...] -> Choice
    Score["low", ...] -> Score (raw float position)
    """

    _fields_: dict[str, _Field] = {}

    def __init_subclass__(cls) -> None:
        cls._fields_ = {
            k: v for k, v in cls.__dict__.items() if isinstance(v, _Field)
        }
        hints = getattr(cls, "__annotations__", {})
        for name, f in cls._fields_.items():
            if name not in hints:
                raise TypeError(f"{cls.__name__}.{name} needs an annotation (bool/Literal/Score[...])")

    def __init__(self, client: Client | None = None):
        self._client = client

    def __call__(self, state: Any) -> "Result":
        hints = _hints(self.__class__)
        qs: dict[str, Any] = {}
        for name, f in self._fields_.items():
            ann = hints[name]
            qs[name] = _build(f.question, ann)
        raw = _decide(state, qs, self._client)
        values, meta = {}, {}
        for name, f in self._fields_.items():
            ann = hints[name]
            a = raw[name]
            if ann is bool:
                values[name] = a.prob >= f.threshold
            elif get_origin(ann) is Literal:
                values[name] = a.choice
            elif isinstance(ann, _Levels):
                values[name] = float(
                    Score(a.score, confidence=a.confidence, legend=ann.levels)
                )
            else:
                raise TypeError(f"unsupported annotation for {name}: {ann!r}")
            meta[name] = a
        return Result(values, meta, self._fields_)


def _build(question: str, ann: Any) -> Any:
    if ann is bool:
        return _NoulQ(question)
    if get_origin(ann) is Literal:
        return _ChoiceQ(question, {str(o): None for o in get_args(ann)})
    if isinstance(ann, _Levels):
        return _ScoreQ(question, list(ann.levels))
    raise TypeError(f"unsupported annotation: {ann!r}")


class Result:
    """Typed namespace over one battery evaluation. attribute access + .meta."""

    def __init__(self, values: dict, meta: dict, fields: dict):
        object.__setattr__(self, "_values", values)
        object.__setattr__(self, "_meta", meta)

    def __getattr__(self, name: str) -> Any:
        try:
            return object.__getattribute__(self, "_values")[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name: str, value: Any) -> None:
        raise TypeError("Result is immutable — re-evaluate instead")

    @property
    def answers(self) -> dict:
        return object.__getattribute__(self, "_meta")

    def confidence(self, name: str) -> float | None:
        a = self.answers[name]
        return getattr(a, "confidence", None)

    def __repr__(self) -> str:
        return f"Result({object.__getattribute__(self, '_values')!r})"


# ---------------------------------------------------------------- control


def gate(question: str, *, over: float = 0.8, client: Client | None = None):
    """Refuse the call when P(question about the call) >= over.

    The first positional arg (or state= kw) is the judged material;
    everything else passes through. Raises Refused.
    """

    def deco(fn):
        sig = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any):
            state = kwargs.pop("state", args[0] if args else "")
            rest = args[1:] if "state" not in kwargs and args else args
            call = f"{fn.__name__}{sig}: {rest} {kwargs}".strip()
            p = feels(question, {"call": call, "state": state}, client=client)
            wrapper.last_prob = float(p)
            if p.over(over):
                raise Refused(f"{fn.__name__} refused: {question} P={float(p):.2f}", prob=float(p))
            return fn(*args, **kwargs)

        wrapper.last_prob = 0.0
        return wrapper

    return deco


def route(options: Mapping[str, str | None], *, instructions: str = "Which route?", client: Client | None = None):
    """Fill the first declared parameter with Jev's pick; judge the first arg.

    @route({"billing": "...", "bug": "..."})
    def handle(team, ticket): ...
    handle(ticket)  # team chosen by Jev; ticket judged AND passed through
    """

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any):
            state = kwargs.get("state", args[0] if args else "")
            c = pick(instructions, state, dict(options), client=client)
            wrapper.last_choice = c
            return fn(c.choice, *args, **kwargs)

        wrapper.last_choice = None
        return wrapper

    return deco


# ---------------------------------------------------------------- replay


@contextlib.contextmanager
def record(path: str):
    """Log every decision (state, questions, answers) as JSONL. Probably-style."""
    def hook(phase: str, state: Any, questions: dict, out: dict | None = None):
        if phase == "post":
            with open(path, "a") as fh:
                fh.write(json.dumps({
                    "sha": _sha(state, questions),
                    "state": state,
                    "questions": questions,
                    "answers": {k: _freeze(v) for k, v in out.items()},
                }, default=str) + "\n")

    _Hooks.append(hook)
    try:
        yield path
    finally:
        _Hooks.remove(hook)


@contextlib.contextmanager
def replay(path: str):
    """Re-run offline: serve logged answers in order, no network. Mismatch -> StaleReplay."""
    rows = [json.loads(line) for line in open(path) if line.strip()]
    idx = {"n": 0}

    def hook(phase: str, state: Any, questions: dict, out: dict | None = None):
        if phase != "pre":
            return None
        if idx["n"] >= len(rows):
            raise StaleReplay("replay log exhausted")
        row = rows[idx["n"]]
        idx["n"] += 1
        if row["sha"] != _sha(state, questions):
            raise StaleReplay(f"question mismatch at step {idx['n']}")
        return {k: parse_answer(k, v) for k, v in row["answers"].items()}

    _Hooks.append(hook)
    try:
        yield path
    finally:
        _Hooks.remove(hook)


def _freeze(answer: Any) -> dict:
    if hasattr(answer, "prob"):
        return {"type": "noul", "noul": answer.prob}
    if hasattr(answer, "choice"):
        return {
            "type": "choice",
            "choice": answer.choice,
            "probabilities": dict(answer.probabilities),
            "confidence": answer.confidence,
        }
    return {
        "type": "score",
        "score": float(answer),
        "legend": {str(i): v for i, v in enumerate(getattr(answer, "legend", ()))},
        "probabilities": dict(getattr(answer, "probabilities", {})),
        "confidence": getattr(answer, "confidence", 0.0),
    }
