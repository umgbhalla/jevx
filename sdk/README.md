# jevx SDK

Define TypeSafe Jev questions as fields of a Pydantic model. `Client.create`
compiles the model into one request and returns a validated instance of the
same model.

## Install and run

```sh
uv sync
export TYPESAFE_API_KEY=...  # or put it in .env and use uv run --env-file .env
uv run --env-file .env python examples/pydantic_triage.py
uv run pytest
```

## Define questions

```python
from pydantic import BaseModel, computed_field
import jevx as j

class TicketReview(BaseModel):
    resolved: j.NoulAnswer = (
        j.ask("Does the reply resolve the user's request?")
        | j.yes("Addresses the requested outcome with usable detail")
        | j.no("Misses a necessary step or gives an unusable answer")
    )
    route: j.ChoiceAnswer = (
        j.ask({"question": "Who owns the primary issue?", "focus": "Classify the problem, not the tone"})
        | j.option("billing", {"what": "Charges, invoices, payments, or refunds"})
        | j.option("support", {"what": "Product bugs or troubleshooting"})
        | j.option("human", {"what": "Needs a person's decision or exception"})
    )
    impact: j.ScoreAnswer = (
        j.ask("How serious is the customer's current impact?")
        | j.level("Minor inconvenience; work continues")
        | j.level("Important workflow impaired; workaround exists")
        | j.level("Critical workflow blocked or material loss occurring")
    )

    @computed_field
    @property
    def send(self) -> bool:
        return self.resolved.noul >= 0.8 and self.impact.score < 1.5

with j.Client() as client:
    result: TicketReview = client.create(
        response_model=TicketReview,
        state={"request": request, "reply": reply, "account": account},
        model="jev-latest",
    )

print(result.route.choice, result.route.probabilities, result.impact.confidence)
```

`j.ask` starts a declaration. `| j.yes(...) | j.no(...)` defines a Noul
rubric; `| j.option(key, description)` adds Choice outcomes; `| j.level(...)`
adds ordered Score levels. Each field must be annotated `j.NoulAnswer`,
`j.ChoiceAnswer`, or `j.ScoreAnswer` to match its criteria. These are the
returned answer types: `NoulAnswer.noul` is the degree of yes;
`ChoiceAnswer.choice`, `.probabilities`, and `.confidence` describe the selected
outcome; `ScoreAnswer.score`, `.legend`, `.probabilities`, and `.confidence`
describe a weighted position on its ordered scale. Choice allows up to 255
options; Score requires 2–10 levels.

The model is an ordinary Pydantic `BaseModel`. Validators and computed fields
run after the TypeSafe response is parsed; they do not create model questions.
Use regular Python comparisons and arithmetic to combine answers, such as a
weighted priority calculated from several Score fields. See
[`pydantic_triage.py`](examples/pydantic_triage.py).

## Payload mapping

The call above sends a single `POST /v1/systemone` request:

```json
{
  "model": "jev-latest",
  "state": {"request": "...", "reply": "...", "account": {"...": "..."}},
  "questions": {
    "resolved": {
      "type": "noul",
      "instructions": "Does the reply resolve the user's request?",
      "criteria": {
        "true": "Addresses the requested outcome with usable detail",
        "false": "Misses a necessary step or gives an unusable answer"
      }
    },
    "route": {
      "type": "choice",
      "instructions": {"question": "Who owns the primary issue?", "focus": "Classify the problem, not the tone"},
      "criteria": {
        "billing": {"what": "Charges, invoices, payments, or refunds"},
        "support": {"what": "Product bugs or troubleshooting"},
        "human": {"what": "Needs a person's decision or exception"}
      }
    },
    "impact": {
      "type": "score",
      "instructions": "How serious is the customer's current impact?",
      "criteria": [
        "Minor inconvenience; work continues",
        "Important workflow impaired; workaround exists",
        "Critical workflow blocked or material loss occurring"
      ]
    }
  }
}
```

`state` is the shared evidence, separate from the questions. Field names become
question IDs, answer annotations select the primitive, `j.ask(...)` supplies
`instructions`, and the chained alternatives become `criteria`. Instructions
and descriptions accept JSON-compatible text, objects, and arrays. The SDK
validates declarations before sending the request, including incompatible
answer types, duplicate Choice labels, and the Choice/Score size limits. It
also checks returned Choice distributions and Score legends against the
declared rubric. A Pydantic `BaseModel` may be passed as `state`; the client
serializes it with `model_dump(mode="json")`. Extra request options passed to
`create`, such as transport-supported timeout or retry options, are forwarded
to the underlying TypeSafe `system_one` call.

Use `j.AsyncClient().create(...)` with `await` for asynchronous calls. The
async client uses the same model and payload compilation. See the
[response model tests](tests/test_response_model.py) for an HTTP transport
example that asserts the exact request body.
