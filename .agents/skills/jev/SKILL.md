---
name: jev
description: Use the jevx Python SDK for TypeSafe Jev judgments. Apply when routing, gating, scoring, triaging, or batching Noul, Choice, and Score questions over a shared state in a Pydantic response model.
---

# Jev with jevx

Use the Pydantic `response_model` interface in `sdk/README.md`. Jev evaluates
questions about supplied `state`; it does not generate arbitrary prose. Split
a complex judgment into focused questions and combine their returned scores
and probabilities with local Python policy.

## Declare one batch

```python
from pydantic import BaseModel, computed_field
import jevx as j

class Review(BaseModel):
    resolved: j.NoulAnswer = (
        j.ask("Does the reply resolve the request?")
        | j.yes("The user can complete the requested task")
        | j.no("A necessary answer or step is missing")
    )
    route: j.ChoiceAnswer = (
        j.ask({"question": "Who owns the primary issue?", "focus": "Classify the problem"})
        | j.option("billing", {"what": "Charges, payments, refunds"})
        | j.option("support", {"what": "Product bugs and troubleshooting"})
        | j.option("human", {"what": "Requires a person's decision"})
    )
    severity: j.ScoreAnswer = (
        j.ask("How severe is the impact?")
        | j.level("Minor inconvenience")
        | j.level("Work impaired; workaround exists")
        | j.level("Blocked with no workaround")
    )

    @computed_field
    @property
    def send(self) -> bool:
        return self.resolved.noul >= 0.8 and self.severity.score < 1.5

with j.Client() as client:
    result = client.create(
        response_model=Review,
        state={"request": request, "reply": reply, "account": account},
    )
```

The call sends one `{model, state, questions}` request. Field names become
question IDs; `j.ask` becomes each question's `instructions`; `j.yes`/`j.no`,
`j.option`, and ordered `j.level` entries become its `criteria`. Preserve the
full rubric, using JSON objects or arrays for instructions and descriptions
when useful. Keep facts in the shared state. Independent questions in one
model are evaluated together. Computed fields and validators run locally.

Noul returns a degree of yes (`.noul`); Choice returns `.choice`,
`.probabilities`, and `.confidence`; Score returns `.score`, `.legend`,
`.probabilities`, and `.confidence`. Choice supports at most 255 options; Score
requires 2–10 ordered levels. Use `j.AsyncClient().create(...)` for async code.

Do not mistake a Noul value around 0.5 for medium severity: use Score for an
ordered scale. Provide a meaningful escape Choice option when categories are
not exhaustive. Put action thresholds and weighted combinations in Python.
Avoid sending secrets in state.

For exact payload mapping and runnable examples, read `sdk/README.md` and
`sdk/examples/`.
