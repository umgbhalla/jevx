# jevx

An Instructor-style Pydantic interface for TypeSafe Jev. Describe Noul, Choice,
and Score questions as model fields, then send one shared state to all of them
in a single request.

```python
from pydantic import BaseModel, computed_field
import jevx as j

class Triage(BaseModel):
    severity: j.ScoreAnswer = (
        j.ask("How severe is the reported issue?")
        | j.level("Cosmetic; no functional impact")
        | j.level("Degraded feature, but a workaround exists")
        | j.level("Blocking issue; no workaround exists")
    )
    owner: j.ChoiceAnswer = (
        j.ask("Which team owns the primary issue?")
        | j.option("billing", "Charges, payments, or refunds")
        | j.option("support", "Product bugs or troubleshooting")
        | j.option("human", "Requires a person to decide")
    )

    @computed_field
    @property
    def urgent(self) -> bool:
        return self.severity.score >= 1.5

with j.Client() as client:
    result = client.create(
        response_model=Triage,
        state={"ticket": ticket, "account": account},
    )
```

`state` contains the evidence to judge. Each `j.ask(...)` supplies a question's
`instructions`; `j.level(...)`, `j.option(...)`, and `j.yes(...) | j.no(...)`
supply its `criteria`. The field name becomes the question ID. Instructions
and criteria can also contain structured JSON objects or arrays. The returned
model retains the full answers, including Choice and Score probabilities and
confidence. Derived Pydantic fields run locally.

See [setup and the full payload mapping](sdk/README.md), the
[weighted Score example](sdk/examples/pydantic_triage.py), and the
[Choice/Noul example](sdk/examples/review_route.py).

## Source material

- [TypeSafe API](https://docs.typesafe.ai/api) and [primitives](https://docs.typesafe.ai/primitives)
- [Structured entries](https://docs.typesafe.ai/primitives/advanced)
- [Instructor response models](https://python.useinstructor.com/)

The research notes under `.agents/research/` record earlier explorations;
`sdk/README.md` describes the supported jevx API.
