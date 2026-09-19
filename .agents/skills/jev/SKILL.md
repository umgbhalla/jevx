---
name: jev
description: Fast structured decisions with Jev (TypeSafe System One). Use when routing, gating tool calls, reranking, scoring, or any yes-no / pick-one / rate-it judgment inside an agent loop. Replaces per-decision LLM calls.
---

# Jev skill

Jev is not an LLM: no text generation. `state` in, typed probabilities out.
Endpoint `POST https://api.typesafe.ai/v1/systemone` (base `https://api.typesafe.ai`),
auth `Bearer $TYPESAFE_API_KEY`. Env: `TYPESAFE_API_KEY` (required),
`TYPESAFE_BASE_URL`, `TYPESAFE_DEFAULT_MODEL` (default `jev-latest`).
Response: `{answers, model, usage, request_id?}`.

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
3. Threshold in code: `P.over(0.5)` default; `band(review_at=0.35, act_at=0.70)` for
   triage; `@gate over=0.8`, destructive needs >0.9. Scale bars with risk.
4. Decompose broad judgments into atomic questions, combine with weights in code (composite scoring).
5. Jev is text-only, English-best, weak on raw numbers (spell out sizes/dates). Never send secrets.

## Snippets

Raw HTTP (no SDK):
```bash
curl https://api.typesafe.ai/v1/systemone \
  -H "Authorization: Bearer $TYPESAFE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"jev-latest","state":"deploy failed twice, 500s",
       "questions":{"urgent":{"type":"noul","instructions":"needs attention now?"}}}'
```

Python (`sdk/` here, stdlib-only; or `pip install typesafe-sdk` for official):
```python
from jevx import Client, Noul
r = Client().system_one(state="...", questions={"u": Noul(instructions="Urgent?")})
r.noul("u")  # prob; NoulAnswer.prob. Choice: r.choice("t") -> (choice, conf)
```

Idiomatic layer (`sdk/jevx/py.py`):
```python
from jevx.py import feels, pick, Questions, ask
from jevx.backends import Sim, Live
if feels("urgent?", ticket, client=Sim({...}).s1()).over(0.8): ...
```

TS lives outside this repo (`@typesafe-ai/sdk`, Vercel `@ai-sdk/typesafe-ai`).
Here, `Client.evaluate(state, questions)` is the one-call equivalent.

## Loop patterns (details in .agents/research/)

- Route: Choice over handlers/models, confidence-gated fallback to capable model
- Gate: Noul risk check before each tool call; refuse, don't ask
- Filter/rerank: Noul per candidate, sort desc; Choice over <=255 candidates
- Supervise: batch N Nouls estimating worker state in one call; deterministic policy acts
