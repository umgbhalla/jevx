# Jevx

Python SDK for TypeSafe System One. TypeSafe's official SDK owns HTTP,
question schemas, retries, and typed responses. Jevx adds lazy algebra,
policy, effect drivers, and task orchestration.

## Setup

```sh
uv sync
cp .env.example .env
```

Set `TYPESAFE_API_KEY` in `.env` for live calls. Keep `.env` local. Run live
commands with `uv run --env-file .env ...`. The scripted examples need no key:

```sh
uv run python examples/task_tree.py
uv run python examples/cases_machine.py
```

## Pydantic response models

Declare a batch of focused System One questions as fields of an ordinary
Pydantic model. `j.ask(...)` carries the question instructions; `| j.level(...)`
appends ordered Score criteria, `| j.option(name, description)` adds Choice
options, and `| j.yes(...) | j.no(...)` describes Noul outcomes. Descriptions
and instructions can be strings or structured JSON objects/arrays.

```python
from pydantic import BaseModel, computed_field
import jevx as j

class Triage(BaseModel):
    severity: j.ScoreAnswer = (
        j.ask("How severe is the issue?")
        | j.level("Cosmetic; no functional impact")
        | j.level("Degraded; a workaround exists")
        | j.level("Blocked; no workaround exists")
    )
    owner: j.ChoiceAnswer = (
        j.ask({"question": "Who owns this?", "focus": "The primary issue"})
        | j.option("billing", {"what": "Payment issues"})
        | j.option("support", {"what": "Product issues"})
    )

    @computed_field
    @property
    def urgent(self) -> bool:
        return self.severity.score >= 1.5

with j.Client() as client:
    result: Triage = client.create(
        response_model=Triage,
        state={"ticket": ticket, "account": account},
    )
print(result.owner.choice, result.owner.probabilities, result.urgent)
```

The client sends **one request** with the shared `state`, the configured model,
and named questions derived from the Pydantic fields. Returned fields retain
the upstream answer models: `NoulAnswer.noul`, `ChoiceAnswer.choice`/
`probabilities`/`confidence`, and `ScoreAnswer.score`/`legend`/
`probabilities`/`confidence`. Computed fields and validators are local Pydantic
logic; they do not create additional model questions. `j.AsyncClient.create`
offers the same API asynchronously. See
[`examples/pydantic_triage.py`](examples/pydantic_triage.py) for three Scores
normalized and weighted in a computed field.

The existing `j.Noul`, `j.Choice`, and `j.Score` exports remain the upstream
question constructors. Annotate response fields with their `*Answer` types.

Run the small state machine against the live API with the local key:

```sh
uv run --env-file .env python examples/cases_machine.py --live
```

## Compose judgments

`noul()` builds a lazy yes/no expression. `&`, `|`, and `~` compose the
expression before evaluation, so all distinct leaves go in one request.

```python
from jevx import case, noul

answered = noul("does this answer the request?")
private = noul("does it reveal private data?")

policy = case[
    (answered >= 0.8) & (private <= 0.05): "send",
    answered >= 0.35: "review",
    ...: "keep-draft",
]

decision = policy.ask(ticket)  # One request for both question leaves.
```

`P` combines evaluated degrees. `Predicate` combines questions. Its `&` uses
the product t-norm, `|` uses the probabilistic-sum t-conorm, and `~` uses
complement. These are fuzzy degrees, not calibrated joint probabilities.

This is Python operator syntax building a Jevx expression tree. `.ask(state)`
collects its distinct question leaves, sends them together, evaluates the math
and thresholds locally, then selects the first matching case. `case` returns
values; it does not run handlers or other side effects.

For inline batteries, `vector()` names each question once and sends them in one
request. Noul fields are numeric `P` values, choices retain their distribution,
and score fields retain confidence and level probabilities:

```python
import jevx as j

triage = j.vector(
    safe=j.noul("Is the response safe?"),
    team=j.choice("Which team owns it?", ("billing", "bug", "account")),
    severity=j.score("How severe is it?", ("low", "medium", "high")),
)
result = triage.ask(ticket)

destination = j.case[
    (result.safe >= 0.9) & (result.team.confidence >= 0.6): result.team.choice,
    ...: "human-review",
].ask({})
handlers[destination](ticket)  # Only the selected external action runs.
```

`vector()` is a named battery over one shared state. For row-wise judgments,
use `Table`: it binds each row to its own question, puts shared context in the
request state, batches up to 20 rows per request, and caches results for
threshold filtering.

```python
from jevx import Table

rows = Table(tests, client=s1, context={"diff": diff[:4000]})
affected = rows.noul({"question": "Could this diff affect behavior verified by this test?"})
must_run = rows.where(
    {"question": "Could this diff affect behavior verified by this test?"},
    threshold=0.30,
)  # Reuses `affected`; it does not ask again.
review = [
    test for test, p in zip(tests, affected, strict=True) if 0.30 <= p < 0.70
]
```

Question instructions, option descriptions, score levels, and Noul outcomes can
be JSON objects or arrays. Keep their parts labeled instead of flattening them
into prompt strings. Jevx passes these values through the official TypeSafe
question models:

```python
from jevx import choice, noul, score

same_invoice = noul(
    {"question": "Is this the same invoice?", "compare": ["vendor", "number", "amount"]},
    true={"what": "All three fields match the ledger entry."},
    false={"what": "One or more fields differ."},
)
owner = choice(
    {"question": "Which team owns the request?", "focus": "Choose the primary need."},
    {
        "billing": {"what": "Charges and refunds", "not_for": "Delivery status"},
        "orders": {"what": "Tracking, delivery, and returns"},
    },
)
impact = score(
    {"question": "How severe is the issue?", "judge": "User impact, not patch size."},
    [{"summary": "low", "signals": ["cosmetic"]}, {"summary": "high", "signals": ["data loss"]}],
)
```

See the [TypeSafe structured-entry guide](https://docs.typesafe.ai/primitives/advanced)
and the [invoice cascade](examples/invoice_cascade.py) for a full battery.

Use `vector()` to name independent questions about one state. It sends one
request and returns a named result. Use ordinary Python for effects such as
sending a message; the expression DSL returns a decision value.

Question probabilities also support lazy arithmetic. Comparisons create hard
rules, where `&` means every threshold must pass. These differ from fuzzy
predicate composition:

```python
from jevx import case, noul

useful = noul("Does it answer the request?")
leaks = noul("Does it expose private information?")
quality = 0.7 * useful + 0.3 * ~leaks
publish = (useful >= 0.75) & (leaks <= 0.05)

decision = case[
    publish: "send",
    ...: "review",
].ask(draft)  # One request for both leaves; thresholds run locally.
```

## Compose workflows with `|`

Use `j.x` to select values from the current record, `j.input()` to name run
inputs, and `j.keep()` to add computed values. Building a flow does not call a
model. `.run()` executes its stages in order. Judgments in one vector or one
record update share a request; a later update that depends on that result is a
later request wave.

```python
import jevx as j

x = j.x
verify = j.vector(
    answered=j.noul("Does the draft answer the ticket?"),
    leaks=j.noul("Does it expose internal information?"),
)

SEND = (
    j.input(ticket=x, draft=x)
    | j.keep(check=verify.on({"ticket": x.ticket.text, "draft": x.draft.text}))
    | j.case[
        (x.check.answered >= 0.75) & (x.check.leaks <= 0.05): j.stop("SEND"),
        ...: j.stop("HUMAN_REVIEW"),
    ]
)

result = SEND.run(ticket=ticket, draft=draft)
```

`j.stop()` returns a terminal result. `j.pass_` continues to the next stage.
`j.when(rule, action)` runs only when its hard rule passes, and `j.require()`
checks data before later stages. `j.compute(fn, ...)` defers a pure local
calculation; `j.min()` and `j.max()` let that calculation stay in the same
expression. `@j.s2` declares an inert System 2 prompt. It runs only when the
selected stage needs it. Pass `backend=...` to `.run()` to use the same live or
scripted S1/S2 bundle.

`|` builds a linear workflow schedule. Independent Noul, Choice, and Score
questions should be grouped in a `j.vector()` so they share one request.
Dependent stages run in later waves. Python still owns loops, retries, budgets,
validation, and external actions.

Use a rule for explicit thresholds and arithmetic for a weighted score. A
weighted score is not automatically a calibrated probability.

Use `case[...]` for ordered policy results. Keep Python unions when actions
have distinct domain data. The [algebraic flow example](examples/algebraic_flow.py)
shows a lazy judgment piped into a typed outcome. This follows the same
type-algebra idea as
[Instructor's union and iterable response models](https://python.useinstructor.com/concepts/iterable/),
while Jevx keeps decision thresholds and branch policy in Python.

```python
type Outcome = Allowed | HumanReview | Retry

flow = j.flow(safety_expression) | classify
outcome = flow.run(ticket)

match outcome:
    case Allowed(confidence=p): send_reply(p)
    case HumanReview(confidence=p): ask_operator(p)
    case Retry(confidence=p): try_again(p)
```

For multi-turn work, `task()` binds both backends and records a parent-linked
history. `run.context()` gives the current branch a short ancestor summary;
`run.branch()` restores the parent on exit for sibling exploration. Use
`restore=False` to keep a selected branch as the active path across turns.

```python
import jevx as j
from jevx import task

with task("incident", backend) as run:
    triage = run.ask(j.vector(
        urgent=j.noul("Does this incident need immediate action?"),
    ), logs)
    cause = run.pick(
        "likely cause?",
        {**run.context(), "logs": logs},
        ("deploy", "database", "dependency", "unknown"),
    )
    with run.branch(cause.choice, restore=False):
        fix = run.s2.ask("Investigate and fix...")
        verified = run.ask(j.vector(
            symptoms_gone=j.noul("Are the original symptoms gone?"),
            root_cause_addressed=j.noul("Does the change address the root cause?"),
        ), {"logs": fresh_logs, "fix": fix})
```

This keeps decisions in Python. The history is ordinary data, so an example can
return it, save it, or pass only the bounded `run.context()` to a later turn.
