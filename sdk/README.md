# Jevx

Python SDK for TypeSafe System One. The core uses the standard library.

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

## Compose judgments

`noul()` builds a lazy yes/no expression. `&`, `|`, and `~` compose the
expression before evaluation, so all distinct leaves go in one request.

```python
from jevx import noul

safe_to_send = noul("does this answer the request?") & ~noul("does it reveal private data?")
match safe_to_send.ask(ticket).band(review_at=0.35, act_at=0.8):
    case "yes":
        send(ticket)
    case "review":
        ask_for_review(ticket)
    case "no":
        keep_draft(ticket)
```

`P` combines evaluated degrees. `Predicate` combines questions. Its `&` uses
the product t-norm, `|` uses the probabilistic-sum t-conorm, and `~` uses
complement. These are fuzzy degrees, not calibrated joint probabilities.

Question batteries use `.ask(state)`. Type choice answers with `Literal` so
static checkers can narrow their value, then branch with `match`.

`match` also works well on choice answers and on `P.band()` results. The
expression operators compose first; `.ask()` batches the leaves once; `match`
then handles each explicit outcome.

```python
from jevx import ChoiceAnswer, pick

match pick("which team?", ticket, {"billing": "charges", "bug": "defects"}):
    case ChoiceAnswer(choice="billing", confidence=c) if c >= 0.8:
        route_billing(ticket)
    case ChoiceAnswer(choice="bug", confidence=c) if c >= 0.8:
        route_bug(ticket)
    case ChoiceAnswer(choice=team):
        request_human_review(team, ticket)
```

Use Python unions for domain outcomes, match on the selected case, and compose
indexed handoffs with `>>`. The [algebraic flow example](examples/algebraic_flow.py)
shows all three together. This follows the same type-algebra idea as
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
