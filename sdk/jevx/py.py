"""Idiomatic Jev: judgments as Python grammar.

``feels`` asks yes/no, ``pick`` chooses, ``rate`` scores. ``noul`` builds a
lazy predicate tree: ``urgent & ~unsafe`` batches both leaves in one request.
Pattern-match typed answers, declare typed batteries, and keep policy in Python.

    from jevx.py import feels, pick, Questions, ask, gate, noul
    from jevx.answers import ChoiceAnswer
    from jevx.py import Score
    from typing import Literal

    safety = noul("is this urgent?") & ~noul("does this expose private data?")
    match safety.ask(ticket).band(review_at=0.35, act_at=0.8):
        case "yes":
            escalate(ticket)
        case "review":
            ask_human(ticket)
        case "no":
            continue_normally(ticket)

    match pick("which team?", ticket, {"billing": "...", "bug": "..."}):
        case ChoiceAnswer(choice="billing", confidence=c) if c > 0.9:
            bill(ticket)
        case ChoiceAnswer(choice="bug", confidence=c) if c > 0.9:
            debug(ticket)
        case ChoiceAnswer(choice=team):
            triage(team, ticket)

    class Triage(Questions):
        urgent: bool = ask("reply within the hour?")
        team: Literal["billing", "bug"] = ask("which team owns it?")
        sev: Score[Literal["low", "high"]] = ask("how severe?")

    t = Triage().ask(ticket)   # one request; t.urgent is bool, t.team is str

"""

from __future__ import annotations

import contextlib
import functools
import hashlib
import inspect
import json
import sys as _sys
import typing as _typing
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from typing import Literal
from typing import cast
from typing import get_args
from typing import get_origin

from . import fx as _fx
from .answers import ChoiceAnswer
from .client import Client
from .questions import Choice as _ChoiceQ
from .questions import Noul as _NoulQ
from .questions import Score as _ScoreQ

__all__ = [
    "AmbiguousTruth",
    "ChoiceAnswer",
    "P",
    "Predicate",
    "Questions",
    "Refused",
    "Result",
    "Score",
    "StaleReplay",
    "ask",
    "choose_from",
    "feels",
    "gate",
    "pick",
    "noul",
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
    """An evaluated fuzzy degree. ``&`` is product; ``|`` is probabilistic sum."""

    def __new__(cls, v: float) -> P:
        f = float(v)
        if not 0.0 <= f <= 1.0:
            raise ValueError(f"P must be within 0..1, got {v!r}")
        return super().__new__(cls, f)

    def __and__(self, o: float) -> P:
        if not isinstance(o, (int, float)):
            return NotImplemented
        return P(float(self) * float(o))

    def __rand__(self, o: float) -> P:
        return self.__and__(o)

    def __or__(self, o: float) -> P:
        if not isinstance(o, (int, float)):
            return NotImplemented
        a, b = float(self), float(o)
        return P(a + b - a * b)

    def __ror__(self, o: float) -> P:
        return self.__or__(o)

    def __invert__(self) -> P:
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


@dataclass(frozen=True)
class Predicate[StateT]:
    """Lazy Noul expression. Operators build a tree; ``ask`` batches its leaves.

    The generic state type helps check the state passed to ``ask``. Operators
    compose fuzzy degrees; they do not claim statistical independence.
    """

    op: str
    question: _NoulQ | None = None
    left: Predicate[Any] | None = None
    right: Predicate[Any] | None = None

    def __post_init__(self) -> None:
        valid = (
            self.op == "leaf"
            and self.question is not None
            and self.left is None
            and self.right is None
        ) or (
            self.op == "not"
            and self.question is None
            and self.left is not None
            and self.right is None
        ) or (
            self.op in ("and", "or")
            and self.question is None
            and self.left is not None
            and self.right is not None
        )
        if not valid:
            raise ValueError(f"invalid predicate node {self.op!r}")

    def __and__(self, other: Predicate[StateT]) -> Predicate[StateT]:
        if not isinstance(other, Predicate):
            return NotImplemented
        return Predicate("and", left=self, right=other)

    def __rand__(self, other: Predicate[StateT]) -> Predicate[StateT]:
        return self.__and__(other)

    def __or__(self, other: Predicate[StateT]) -> Predicate[StateT]:
        if not isinstance(other, Predicate):
            return NotImplemented
        return Predicate("or", left=self, right=other)

    def __ror__(self, other: Predicate[StateT]) -> Predicate[StateT]:
        return self.__or__(other)

    def __invert__(self) -> Predicate[StateT]:
        return Predicate("not", left=self)

    def __bool__(self) -> bool:
        raise AmbiguousTruth("a predicate is unevaluated; call .ask(state).over(threshold)")

    def ask(self, state: StateT, *, client: Client | None = None) -> P:
        """Evaluate every leaf in one request, then apply the fuzzy operators."""
        ids: dict[_NoulQ, str] = {}

        def collect(node: Predicate[Any]) -> None:
            if node.op == "leaf":
                assert node.question is not None
                ids.setdefault(node.question, f"q{len(ids)}")
            else:
                if node.left is not None:
                    collect(node.left)
                if node.right is not None:
                    collect(node.right)

        collect(self)
        questions = {qid: question for question, qid in ids.items()}
        raw = _decide(state, questions, client)

        def evaluate(node: Predicate[Any]) -> P:
            if node.op == "leaf":
                assert node.question is not None
                return P(raw[ids[node.question]].prob)
            if node.op == "not":
                assert node.left is not None
                return ~evaluate(node.left)
            assert node.left is not None and node.right is not None
            if node.op == "and":
                return evaluate(node.left) & evaluate(node.right)
            if node.op == "or":
                return evaluate(node.left) | evaluate(node.right)
            raise ValueError(f"unknown predicate operation {node.op!r}")

        return evaluate(self)


def noul(
    instructions: str, *, true: str | None = None, false: str | None = None
) -> Predicate[Any]:
    """Build a lazy yes/no expression. Combine with ``&``, ``|``, and ``~``."""
    return Predicate("leaf", question=_NoulQ(instructions, true, false))


class Score[LevelT: str](float):
    """A spectrum position with its confidence attached."""

    confidence: float
    legend: tuple[LevelT, ...]

    def __new__(cls, value: float, *, confidence: float, legend: tuple) -> Score:
        obj = super().__new__(cls, value)
        obj.confidence = confidence
        obj.legend = legend
        return obj

    def level(self) -> int:
        return int(round(float(self)))

def _score_levels(ann: Any) -> tuple[str, ...] | None:
    if get_origin(ann) is not Score:
        return None
    (levels,) = get_args(ann)
    if get_origin(levels) is not Literal:
        raise TypeError("Score needs Literal['low', 'high', ...] levels")
    values = get_args(levels)
    if len(values) < 2 or any(not isinstance(v, str) or not v for v in values):
        raise TypeError("Score needs at least two non-empty string levels")
    return values


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
    driver = _fx.current()
    if driver is not None:
        if client is not None and not isinstance(driver, _fx.LiveDriver):
            import warnings as _w

            _w.warn(
                "explicit client ignored: a driver is on the stack "
                "(record/replay needs to see calls)"
            )
        return driver.answer(state, payload)
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
    """Evaluate one yes/no question. Use ``noul`` to batch expressions."""
    (a,) = _decide(state, {"p": _NoulQ(question, true, false)}, client).values()
    return P(a.prob)


def pick[ChoiceT: str](
    question: str,
    state: Any,
    options: Mapping[ChoiceT, str | None] | Sequence[ChoiceT],
    *,
    client: Client | None = None,
) -> ChoiceAnswer[ChoiceT]:
    """One pick-one judgment -> matchable Choice. Match on it."""
    if not isinstance(options, Mapping):
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


def ask(question: str, *, threshold: float = 0.5) -> Any:
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


class Questions[ResultT]:
    """Declarative battery. Annotations decide the question kind; one request.

    bool -> Noul (threshold per field via ask(..., threshold=))
    Literal[...] -> Choice
    Score[Literal[...]] -> Score (raw float position)
    """

    _fields_: dict[str, _Field] = {}

    def __init_subclass__(cls) -> None:
        cls._fields_ = {k: v for k, v in cls.__dict__.items() if isinstance(v, _Field)}
        raw = getattr(cls, "__annotations__", {})
        for name in cls._fields_:
            if name not in raw:
                raise TypeError(f"{cls.__name__}.{name} needs an annotation")
        import typing as _t

        resolved = _hints(cls)
        cls.Result = _t.NamedTuple(
            f"{cls.__name__}Result",
            [(n, _pytype(resolved[n])) for n in cls._fields_],  # ty: ignore[invalid-named-tuple]
        )

    def __init__(self, client: Client | None = None):
        self._client = client

    def ask(self, state: Any) -> ResultT:
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
            elif (levels := _score_levels(ann)) is not None:
                values[name] = Score(a.score, confidence=a.confidence, legend=levels)
            else:
                raise TypeError(f"unsupported annotation for {name}: {ann!r}")
            meta[name] = a
        return cast(Any, Result(values, meta, self._fields_))


def _pytype(ann: Any) -> type:
    """Annotation -> runtime value type: bool | str | float."""
    if ann is bool:
        return bool
    if get_origin(ann) is Literal:
        return str
    if get_origin(ann) is Score:
        return float
    raise TypeError(f"unsupported annotation: {ann!r}")


def _build(question: str, ann: Any) -> Any:
    if ann is bool:
        return _NoulQ(question)
    if get_origin(ann) is Literal:
        return _ChoiceQ(question, {str(o): None for o in get_args(ann)})
    if (levels := _score_levels(ann)) is not None:
        return _ScoreQ(question, list(levels))
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
        c = getattr(a, "confidence", None)
        if c is not None:
            return c
        p = getattr(a, "prob", None)  # Noul: margin from coin-flip as confidence
        return abs(p - 0.5) * 2 if p is not None else None

    def __repr__(self) -> str:
        return f"Result({object.__getattribute__(self, '_values')!r})"

    def as_tuple(self) -> tuple:
        """Destructure values in field order: urgent, team, sev = t.as_tuple()."""
        v = object.__getattribute__(self, "_values")
        return tuple(v[k] for k in v)

    def as_dict(self) -> dict:
        return dict(object.__getattribute__(self, "_values"))

    def as_named(self, nt_cls: type) -> Any:
        """Pack into a NamedTuple class (e.g. Triage.Result): t.as_named(Triage.Result)."""
        return nt_cls(**self.as_dict())


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
            bound = sig.bind_partial(*args, **kwargs)
            if "state" in bound.arguments:
                state = bound.arguments["state"]
            elif args:
                state = args[0]
            else:
                state = ""
            call = f"{fn.__name__}{sig}: {args} {kwargs}".strip()
            p = feels(question, {"call": call, "state": state}, client=client)
            wrapper.last_prob = float(p)  # ty: ignore[unresolved-attribute]
            if p.over(over):
                raise Refused(f"{fn.__name__} refused: {question} P={float(p):.2f}", prob=float(p))
            return fn(*args, **kwargs)

        wrapper.last_prob = 0.0  # ty: ignore[unresolved-attribute]
        return wrapper

    return deco


def route(
    options: Mapping[str, str | None],
    *,
    instructions: str = "Which route?",
    client: Client | None = None,
):
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
            wrapper.last_choice = c  # ty: ignore[unresolved-attribute]
            return fn(c.choice, *args, **kwargs)

        wrapper.last_choice = None  # ty: ignore[unresolved-attribute]
        return wrapper

    return deco


# ---------------------------------------------------------------- replay


@contextlib.contextmanager
def record(path: str):
    """Log every decision (state, questions, answers) as JSONL. Probably-style."""
    with _fx.use(_fx.RecordDriver(path)):
        yield path


@contextlib.contextmanager
def replay(path: str):
    """Re-run offline: serve logged answers in order, no network. Mismatch -> StaleReplay."""
    with _fx.use(_fx.ReplayDriver(path)):
        yield path


def choose_from(
    state: Any,
    routes: dict[str, Any],
    *,
    instructions: str = "Which route does this call for?",
    client: Client | None = None,
) -> tuple[str, Any]:
    """Union dispatch: one route question, then fill only the winner.

    routes: name -> Questions subclass (filled in a second request with only
    its questions) | callable(state) (run directly, no second request).
    Returns (name, filled Result | callable return).
    """
    c = pick(
        instructions,
        state,
        {n: getattr(r, "__doc__", None) or n for n, r in routes.items()},
        client=client,
    )
    winner = routes[c.choice]
    if isinstance(winner, type) and issubclass(winner, Questions):
        return c.choice, winner(client=client).ask(state)
    return c.choice, winner(state)


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
