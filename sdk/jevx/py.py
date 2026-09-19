"""Algebraic judgments and ordered policy expressions.

Python's overloaded operators build the expression tree. ``.ask(state)``
collects its distinct question leaves into one TypeSafe request, then computes
the arithmetic, thresholds, and first matching case locally.

    from jevx import case, noul

    answered = noul("does the draft answer the ticket?")
    leaks = noul("does it expose private information?")
    ready = (answered >= 0.75) & (leaks <= 0.05)

    policy = case[
        ready: "send",
        answered >= 0.35: "human-review",
        ...: "revise",
    ]
    decision = policy.ask({"ticket": ticket, "draft": draft})

The expression tree compiles to one batched question request per ``ask``.
It does not compile an entire Python workflow or execute its side effects.
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
from numbers import Real
from operator import add
from operator import ge
from operator import gt
from operator import le
from operator import lt
from operator import mul
from operator import neg
from operator import pow as power
from operator import sub
from operator import truediv
from typing import Any
from typing import Literal
from typing import cast
from typing import get_args
from typing import get_origin

from . import fx as _fx
from .answers import ChoiceAnswer
from .client import Client
from .questions import Choice as _ChoiceQ
from .questions import JSONContent
from .questions import Noul as _NoulQ
from .questions import Score as _ScoreQ
from .questions import to_json as _question_json

__all__ = [
    "AmbiguousTruth",
    "Case",
    "ChoiceAnswer",
    "Expr",
    "JSONContent",
    "Rule",
    "P",
    "Predicate",
    "Questions",
    "Refused",
    "Result",
    "Score",
    "StaleReplay",
    "ask",
    "case",
    "choice",
    "choose_from",
    "feels",
    "gate",
    "pick",
    "noul",
    "rate",
    "record",
    "replay",
    "route",
    "score",
    "vector",
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


@dataclass(frozen=True, eq=False)
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
            (
                self.op == "leaf"
                and self.question is not None
                and self.left is None
                and self.right is None
            )
            or (
                self.op == "not"
                and self.question is None
                and self.left is not None
                and self.right is None
            )
            or (
                self.op in ("and", "or")
                and self.question is None
                and self.left is not None
                and self.right is not None
            )
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

    def __add__(self, other: Real | Expr) -> Expr:
        return _expr(self) + other

    def __radd__(self, other: Real | Expr) -> Expr:
        return _expr(self).__radd__(other)

    def __sub__(self, other: Real | Expr) -> Expr:
        return _expr(self) - other

    def __rsub__(self, other: Real | Expr) -> Expr:
        return _expr(self).__rsub__(other)

    def __mul__(self, other: Real | Expr) -> Expr:
        return _expr(self) * other

    def __rmul__(self, other: Real | Expr) -> Expr:
        return _expr(self).__rmul__(other)

    def __truediv__(self, other: Real | Expr) -> Expr:
        return _expr(self) / other

    def __rtruediv__(self, other: Real | Expr) -> Expr:
        return _expr(self).__rtruediv__(other)

    def __pow__(self, other: Real | Expr) -> Expr:
        return _expr(self) ** other

    def __rpow__(self, other: Real | Expr) -> Expr:
        return _expr(self).__rpow__(other)

    def __neg__(self) -> Expr:
        return -_expr(self)

    def __abs__(self) -> Expr:
        return abs(_expr(self))

    def __lt__(self, other: Real | Expr) -> Rule:
        return _expr(self) < other

    def __le__(self, other: Real | Expr) -> Rule:
        return _expr(self) <= other

    def __gt__(self, other: Real | Expr) -> Rule:
        return _expr(self) > other

    def __ge__(self, other: Real | Expr) -> Rule:
        return _expr(self) >= other

    def __bool__(self) -> bool:
        raise AmbiguousTruth("a predicate is unevaluated; call .ask(state).over(threshold)")

    def ask(self, state: StateT, *, client: Client | None = None) -> P:
        """Evaluate every leaf in one request, then apply the fuzzy operators."""
        return _evaluate(self, state, client)


@dataclass(frozen=True, eq=False)
class Expr:
    """Lazy numeric expression over Noul questions and ordinary numbers."""

    op: str
    left: Any
    right: Any = None

    def _binary(self, op: str, other: Real | Expr) -> Expr:
        return Expr(op, self, _numeric(other))

    def __add__(self, other: Real | Expr) -> Expr:
        return self._binary("add", other)

    def __radd__(self, other: Real | Expr) -> Expr:
        return _expr(other) + self

    def __sub__(self, other: Real | Expr) -> Expr:
        return self._binary("sub", other)

    def __rsub__(self, other: Real | Expr) -> Expr:
        return _expr(other) - self

    def __mul__(self, other: Real | Expr) -> Expr:
        return self._binary("mul", other)

    def __rmul__(self, other: Real | Expr) -> Expr:
        return _expr(other) * self

    def __truediv__(self, other: Real | Expr) -> Expr:
        return self._binary("div", other)

    def __rtruediv__(self, other: Real | Expr) -> Expr:
        return _expr(other) / self

    def __pow__(self, other: Real | Expr) -> Expr:
        return self._binary("pow", other)

    def __rpow__(self, other: Real | Expr) -> Expr:
        return _expr(other) ** self

    def __neg__(self) -> Expr:
        return Expr("neg", self)

    def __abs__(self) -> Expr:
        return Expr("abs", self)

    def __lt__(self, other: Real | Expr) -> Rule:
        return Rule("lt", self, _numeric(other))

    def __le__(self, other: Real | Expr) -> Rule:
        return Rule("le", self, _numeric(other))

    def __gt__(self, other: Real | Expr) -> Rule:
        return Rule("gt", self, _numeric(other))

    def __ge__(self, other: Real | Expr) -> Rule:
        return Rule("ge", self, _numeric(other))

    def __bool__(self) -> bool:
        raise AmbiguousTruth("a lazy expression has no value yet; call .ask(state)")

    def ask(self, state: Any, *, client: Client | None = None) -> float:
        return _evaluate(self, state, client)


@dataclass(frozen=True)
class Rule:
    """Hard threshold policy. Unlike Predicate, `&` means both rules pass."""

    op: str
    left: Any
    right: Any = None

    def __and__(self, other: Rule) -> Rule:
        if not isinstance(other, Rule):
            return NotImplemented
        return Rule("and", self, other)

    def __or__(self, other: Rule) -> Rule:
        if not isinstance(other, Rule):
            return NotImplemented
        return Rule("or", self, other)

    def __invert__(self) -> Rule:
        return Rule("not", self)

    def __bool__(self) -> bool:
        raise AmbiguousTruth("a lazy rule has no result yet; call .ask(state)")

    def ask(self, state: Any, *, client: Client | None = None) -> bool:
        return _evaluate(self, state, client)


def _numeric(value: object) -> Expr | float:
    if isinstance(value, (Predicate, Expr)):
        return _expr(value)
    if isinstance(value, Real):
        return float(value)
    raise TypeError(f"expected a numeric expression, got {type(value).__name__}")


def _expr(value: Predicate | Expr | Real) -> Expr:
    return value if isinstance(value, Expr) else Expr("value", value)


def _evaluate(root: Any, state: Any, client: Client | None) -> Any:
    ids: dict[int, str] = {}
    signatures: dict[str, str] = {}
    questions: dict[str, _NoulQ] = {}

    def register(question: Any) -> None:
        key = id(question)
        if key in ids:
            return
        signature = json.dumps(_question_json(question), sort_keys=True)
        qid = signatures.get(signature)
        if qid is None:
            qid = f"q{len(questions)}"
            signatures[signature] = qid
            questions[qid] = question
        ids[key] = qid

    def collect(node: Any) -> None:
        if isinstance(node, Predicate):
            if node.op == "leaf":
                assert node.question is not None
                register(node.question)
            else:
                if node.left is not None:
                    collect(node.left)
                if node.right is not None:
                    collect(node.right)
        elif isinstance(node, Expr):
            collect(node.left)
            if node.right is not None:
                collect(node.right)
        elif isinstance(node, Rule):
            collect(node.left)
            if node.right is not None:
                collect(node.right)
        elif isinstance(node, (_NoulQ, _ChoiceQ, _ScoreQ)):
            register(node)
        elif isinstance(node, Mapping):
            for child in node.values():
                collect(child)

    collect(root)
    raw = _decide(state, questions, client) if questions else {}

    def evaluate(node: Any) -> Any:
        if isinstance(node, Predicate):
            if node.op == "leaf":
                assert node.question is not None
                return P(raw[ids[id(node.question)]].noul)
            if node.op == "not":
                assert node.left is not None
                return ~evaluate(node.left)
            assert node.left is not None and node.right is not None
            if node.op == "and":
                return evaluate(node.left) & evaluate(node.right)
            if node.op == "or":
                return evaluate(node.left) | evaluate(node.right)
            raise ValueError(f"unknown predicate operation {node.op!r}")
        if isinstance(node, Expr):
            if node.op == "value":
                return evaluate(node.left)
            if node.op == "neg":
                return neg(evaluate(node.left))
            if node.op == "abs":
                return abs(evaluate(node.left))
            left = evaluate(node.left)
            right = evaluate(node.right)
            return {
                "add": add,
                "sub": sub,
                "mul": mul,
                "div": truediv,
                "pow": power,
            }[node.op](left, right)
        if isinstance(node, Rule):
            if node.op == "and":
                return evaluate(node.left) and evaluate(node.right)
            if node.op == "or":
                return evaluate(node.left) or evaluate(node.right)
            if node.op == "not":
                return not evaluate(node.left)
            return {
                "lt": lt,
                "le": le,
                "gt": gt,
                "ge": ge,
            }[node.op](evaluate(node.left), evaluate(node.right))
        if isinstance(node, (_NoulQ, _ChoiceQ, _ScoreQ)):
            answer = raw[ids[id(node)]]
            if isinstance(node, _NoulQ):
                return P(answer.noul)
            if isinstance(node, _ChoiceQ):
                return answer
            levels = tuple(answer.legend[key] for key in sorted(answer.legend))
            return Score(
                answer.score,
                confidence=answer.confidence,
                legend=levels,
                probabilities=answer.probabilities,
            )
        if isinstance(node, Mapping):
            return {key: evaluate(value) for key, value in node.items()}
        return node

    return evaluate(root)


def noul(
    instructions: JSONContent,
    *,
    true: JSONContent | None = None,
    false: JSONContent | None = None,
) -> Predicate[Any]:
    """Build a lazy Noul expression; instructions and outcome rubrics may be JSON."""
    criteria = {"true": true, "false": false} if true is not None or false is not None else None
    return Predicate("leaf", question=_NoulQ(instructions=instructions, criteria=criteria))


class Score[LevelT: str](float):
    """A spectrum position with its confidence attached."""

    confidence: float
    legend: tuple[LevelT, ...]
    probabilities: dict[int, float]

    def __new__(
        cls,
        value: float,
        *,
        confidence: float,
        legend: tuple,
        probabilities: Mapping[int, float] | None = None,
    ) -> Score:
        obj = super().__new__(cls, value)
        obj.confidence = confidence
        obj.legend = legend
        obj.probabilities = dict(probabilities or {})
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
    payload = {k: _question_json(v) for k, v in questions.items()}
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
    live_questions = {k: getattr(v, "_b", v) for k, v in questions.items()}
    resp = (client or Client()).system_one(state, live_questions)
    out = {k: resp.answers[k] for k in questions}
    for hook in _Hooks:
        hook("post", state, payload, out)
    return out


# ---------------------------------------------------------------- verbs


def feels(
    question: JSONContent,
    state: Any,
    *,
    true: JSONContent | None = None,
    false: JSONContent | None = None,
    client: Client | None = None,
) -> P:
    """Evaluate one yes/no question. Use ``noul`` to batch expressions."""
    criteria = {"true": true, "false": false} if true is not None or false is not None else None
    (a,) = _decide(state, {"p": _NoulQ(instructions=question, criteria=criteria)}, client).values()
    return P(a.noul)


def pick[ChoiceT: str](
    question: JSONContent,
    state: Any,
    options: Mapping[ChoiceT, JSONContent | None] | Sequence[ChoiceT],
    *,
    client: Client | None = None,
) -> ChoiceAnswer:
    """One pick-one judgment -> matchable Choice. Match on it."""
    criteria: Mapping[str, JSONContent | None]
    if isinstance(options, Mapping):
        criteria = {str(k): v for k, v in options.items()}
    else:
        criteria = {str(option): None for option in options}
    (a,) = _decide(
        state,
        {"c": _ChoiceQ(instructions=question, criteria=criteria)},
        client,
    ).values()
    return a


def rate(
    question: JSONContent,
    state: Any,
    levels: Sequence[JSONContent],
    *,
    client: Client | None = None,
) -> Score:
    """One spectrum judgment -> Score float with .confidence."""
    (a,) = _decide(
        state, {"s": _ScoreQ(instructions=question, criteria=list(levels))}, client
    ).values()
    return Score(
        a.score,
        confidence=a.confidence,
        legend=tuple(levels),
        probabilities=a.probabilities,
    )


def ask(
    question: JSONContent,
    *,
    threshold: float = 0.5,
    criteria: Mapping[str, JSONContent | None] | Sequence[JSONContent] | None = None,
) -> Any:
    """Declare a battery field inside a Questions class (descriptor)."""
    return _Field(question, threshold, criteria)


def choice(
    instructions: JSONContent,
    options: Mapping[str, JSONContent | None] | Sequence[str],
) -> _ChoiceQ:
    """Build an upstream choice question for a named vector field."""
    criteria = (
        {str(key): value for key, value in options.items()}
        if isinstance(options, Mapping)
        else {str(option): None for option in options}
    )
    return _ChoiceQ(instructions=instructions, criteria=criteria)


def score(instructions: JSONContent, levels: Sequence[JSONContent]) -> _ScoreQ:
    """Build an upstream score question for a named vector field."""
    return _ScoreQ(instructions=instructions, criteria=list(levels))


class Vector:
    """Named scalar judgments, batched against one shared state."""

    def __init__(self, fields: Mapping[str, Any]):
        if not fields:
            raise ValueError("vector needs at least one field")
        invalid = [
            name
            for name in fields
            if not name.isidentifier() or name.startswith("_") or name in {"ask", "fields"}
        ]
        if invalid:
            raise ValueError(f"invalid or reserved vector field(s): {invalid}")
        self.fields = dict(fields)

    def __getattr__(self, name: str) -> Any:
        try:
            return self.fields[name]
        except KeyError:
            raise AttributeError(name) from None

    def ask(self, state: Any, *, client: Client | None = None) -> Result:
        values = _evaluate(self.fields, state, client)
        return Result(values, values, self.fields)


def vector(**fields: Any) -> Vector:
    """Group named questions or lazy expressions into one request."""
    return Vector(fields)


@dataclass(frozen=True)
class Case:
    """Ordered, first-match routing over lazy rules; actions are returned, not run."""

    arms: tuple[tuple[Rule | Any, Any], ...]

    def ask(self, state: Any, *, client: Client | None = None) -> Any:
        rules = {str(i): rule for i, (rule, _) in enumerate(self.arms) if rule is not Ellipsis}
        results = _evaluate(rules, state, client) if rules else {}
        for i, (rule, action) in enumerate(self.arms):
            if rule is Ellipsis:
                return action
            if results[str(i)]:
                return action
        raise LookupError("no case matched and no default arm was declared")


class _CaseBuilder:
    def __getitem__(self, arms: slice | tuple[slice, ...]) -> Case:
        rows = arms if isinstance(arms, tuple) else (arms,)
        parsed = []
        for row in rows:
            if not isinstance(row, slice) or row.step is not None:
                raise TypeError("case arms use `condition: action` syntax")
            condition, action = row.start, row.stop
            if condition is not Ellipsis and not isinstance(condition, Rule | bool):
                raise TypeError("case conditions must be lazy rules or booleans")
            parsed.append((condition, action))
        if any(rule is Ellipsis for rule, _ in parsed[:-1]):
            raise ValueError("the default case must be last")
        if sum(rule is Ellipsis for rule, _ in parsed) > 1:
            raise ValueError("only one default case is allowed")
        return Case(tuple(parsed))


case = _CaseBuilder()


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
    def __init__(
        self,
        question: JSONContent,
        threshold: float,
        criteria: Mapping[str, JSONContent | None] | Sequence[JSONContent] | None,
    ):
        self.question = question
        self.threshold = threshold
        self.criteria = criteria
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
            qs[name] = _build(f, ann)
        raw = _decide(state, qs, self._client)
        values, meta = {}, {}
        for name, f in self._fields_.items():
            ann = hints[name]
            a = raw[name]
            if ann is bool:
                values[name] = a.noul >= f.threshold
            elif get_origin(ann) is Literal:
                values[name] = a.choice
            elif (levels := _score_levels(ann)) is not None:
                values[name] = Score(
                    a.score,
                    confidence=a.confidence,
                    legend=levels,
                    probabilities=a.probabilities,
                )
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


def _build(field: _Field, ann: Any) -> Any:
    if ann is bool:
        return _NoulQ(instructions=field.question, criteria=field.criteria)
    if get_origin(ann) is Literal:
        options = tuple(str(option) for option in get_args(ann))
        criteria = (
            field.criteria if field.criteria is not None else {option: None for option in options}
        )
        if not isinstance(criteria, Mapping) or set(criteria) != set(options):
            raise ValueError(f"{field.name}: choice criteria keys must match {options!r}")
        return _ChoiceQ(
            instructions=field.question,
            criteria=criteria,
        )
    if (levels := _score_levels(ann)) is not None:
        criteria = field.criteria if field.criteria is not None else levels
        if isinstance(criteria, (str, bytes, Mapping)) or len(criteria) != len(levels):
            raise ValueError(f"{field.name}: score criteria need {len(levels)} ordered levels")
        return _ScoreQ(instructions=field.question, criteria=list(criteria))
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
        p = float(a) if isinstance(a, P) else getattr(a, "noul", None)
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


def gate(question: JSONContent, *, over: float = 0.8, client: Client | None = None):
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
    options: Mapping[str, JSONContent | None],
    *,
    instructions: JSONContent = "Which route?",
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
    instructions: JSONContent = "Which route does this call for?",
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
    if hasattr(answer, "noul"):
        return {"type": "noul", "noul": answer.noul}
    if hasattr(answer, "choice"):
        return {
            "type": "choice",
            "choice": answer.choice,
            "probabilities": dict(answer.probabilities),
            "confidence": answer.confidence,
        }
    return {
        "type": "score",
        "score": answer.score,
        "legend": {str(i): v for i, v in answer.legend.items()},
        "probabilities": {str(i): v for i, v in answer.probabilities.items()},
        "confidence": getattr(answer, "confidence", 0.0),
    }
