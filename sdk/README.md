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
collects its distinct question leaves, sends them together, evaluates the
math and thresholds locally, then selects the first matching case. It does not
compile a whole application workflow or execute the selected action.

For inline batteries, `vector()` names each question once and sends them in one
request. Noul fields are numeric `P` values, choices retain their distribution,
and score fields retain confidence and level probabilities:

```python
from jevx import choice, noul, score, vector

triage = vector(
    safe=noul("Is the response safe?"),
    team=choice("Which team owns it?", ("billing", "bug", "account")),
    severity=score("How severe is it?", ("low", "medium", "high")),
)
result = triage.ask(ticket)

destination = case[
    (result.safe >= 0.9) & (result.team.confidence >= 0.6): result.team.choice,
    ...: "human-review",
].ask({})
handlers[destination](ticket)  # Only the selected external action runs.
```

`vector()` is a named battery over one shared state. It does not map over
collections; use an explicit loop when every row needs its own state.

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

Question batteries use `.ask(state)`. Type choice answers with `Literal` when
static checkers need to narrow their value. Use ordinary Python for effects
such as sending a message; the expression DSL returns a decision value.

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

Use a rule for explicit thresholds and arithmetic for a weighted score. A
weighted score is not automatically a calibrated probability.

Use `case[...]` for ordered policy results. Keep Python unions when actions
have distinct domain data, and compose indexed handoffs with `>>`. The
[algebraic flow example](examples/algebraic_flow.py) shows typed outcomes and
handoffs. This follows the same type-algebra idea as
[Instructor's union and iterable response models](https://python.useinstructor.com/concepts/iterable/),
while Jevx keeps decision thresholds and branch policy in Python.

```python
type Outcome = Allowed | HumanReview | Retry

flow = start("ticket", "judged", judge) >> classify
outcome, context = flow(ticket)

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
from jevx import task

with task("incident", backend) as run:
    triage = run.ask(Triage, logs)
    cause = run.pick("likely cause?", {**run.context(), "logs": logs}, causes)
    with run.branch(cause.choice, restore=False):
        fix = run.s2.ask("Investigate and fix...")
        verified = run.ask(Verify, {"logs": fresh_logs, "fix": fix})
```

This keeps decisions in Python. The history is ordinary data, so an example can
return it, save it, or pass only the bounded `run.context()` to a later turn.
