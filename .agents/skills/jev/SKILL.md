---
name: jev
description: Fast structured decisions with Jev (TypeSafe System One). Use when routing, gating tool calls, reranking, scoring, or any yes-no / pick-one / rate-it judgment inside an agent loop. Replaces per-decision LLM calls.
---

# Jev skill

Jev is not an LLM: no text generation. `state` in, typed probabilities out.
Endpoint `POST https://api.typesafe.ai/v1/systemone`, auth `Bearer $TYPESAFE_API_KEY`.

## The one request shape

```json
{
  "model": "jev-latest",
  "state": "string | object | array",
  "questions": {
    "is_urgent": {"type": "noul", "instructions": "...", "criteria": {"true": "...", "false": "..."}},
    "team": {"type": "choice", "instructions": "...", "criteria": {"a": "rubric", "b": null}},
    "sev": {"type": "score", "instructions": "...", "criteria": ["low", "mid", "high"]}
  }
}
```

Answers keyed by your IDs. All questions evaluate in parallel — pack every
question about one state into a single call.

## Which type

- `noul` -> `{"noul": 0..1}` P(yes). No confidence field. `0.5` = undecided, NOT medium. Use for `if` branches.
- `choice` -> `{"choice", "probabilities" (sum 1), "confidence"}`. Max 255 options. Use when options map to code paths. Always add an escape option (`other`/`none`) for open worlds.
- `score` -> `{"score" (weighted float), "legend", "probabilities", "confidence"}`. Ordered levels, min 2 max 10. Use for spectrums (severity, relevance). If you read a Noul 0.5 as "medium", you wanted Score.

## Rules

1. One predicate per question; describe situations, not degrees.
2. State holds facts (object preferred: `{ticket, order, policy}`); questions hold judgments. Never put the question inside the state.
3. Threshold in code: high -> act, medium -> confirm/flag, low (<0.5 default floor) -> human. Scale bars with risk (destructive needs >0.9).
4. Decompose broad judgments into atomic questions, combine with weights in code (composite scoring).
5. Jev is text-only, English-best, weak on raw numbers (spell out sizes/dates). Never send secrets.

## Snippets

Python (`pip install typesafe-sdk`):
```python
from typesafe_sdk import Noul, TypeSafeClient
r = TypeSafeClient().system_one(state="...", questions={"u": Noul(instructions="Urgent?")})
r.answers["u"].noul
```

TS (`npm i @typesafe-ai/sdk`, or Vercel `@ai-sdk/typesafe-ai` + `experimental_evaluate`):
```ts
const r = await client.systemOne({state, questions:{team: choice("Which team?", {billing: "...", other: null})}});
r.answers.team.choice
```

## Loop patterns (details in .agents/research/)

- Route: Choice over handlers/models, confidence-gated fallback to capable model
- Gate: Noul risk check before each tool call; refuse, don't ask
- Filter/rerank: Noul per candidate, sort desc; Choice over <=255 candidates
- Supervise: 9 parallel Nouls estimating worker state; deterministic policy acts
