# jevxperiments

Experiments with Jev (TypeSafe AI System One model) + LangChain harness patterns.

## What is Jev?

Not an LLM. No text generation. `unstructured state in -> typed probabilistic decisions out`.

- Endpoint: `POST https://api.typesafe.ai/v1/systemone`
- Auth: `Authorization: Bearer $TYPESAFE_API_KEY`
- Model: `jev-latest` -> currently `jev-1.13.0`
- Price: $0.042 / MTok input, output FREE
- Speed: 70-500ms (claimed 40-200x faster, up to 193.6x / 444.6x cheaper on workflow evals)
- Limits: 64k total (32k state + longest question), 250k tok/sec, 1200 req/min
- Text-only, English best. No fine-tune per customer — shape via state + instructions/criteria.

From: https://typesafe.ai/blog/introducing-system-one-models-and-jev
Training: RLCD (Reinforcement Learning for Calibrated Decisions), vs RLHF/RLVR.

## API core

```json
{
  "state": "string | object | array",
  "model": "jev-latest",
  "questions": {
    "is_urgent": {"type": "noul", "instructions": "...", "criteria": {"true": "...", "false": "..."}},
    "department": {"type": "choice", "instructions": "...", "criteria": {"billing": "...", "technical": "..."}},
    "frustration": {"type": "score", "instructions": "...", "criteria": ["Calm", "Frustrated", "Very angry"]}
  }
}
```

Answers keyed by same IDs:
- `noul`: `{type, noul: 0..1}` — no confidence (prob IS answer)
- `choice`: `{type, choice, probabilities{}, confidence}`
- `score`: `{type, score (weighted, can land between), legend, probabilities{}, confidence}`

All questions in one request evaluated in parallel — batch aggressively. See `docs/api-spec.md`.

Key mental models in `docs/`:
- `confidence.md` — confidence = shape of distribution, 3-tier routing (act / review / block), thresholds scale with risk
- `state.md` — string for simple, object for real work (conversation + records + policy together)
- `patterns.md` — fan-out, confidence-gated routing, composite scoring, intent routing
- `cookbooks.md` — guardrails (Noul battery + Severity Score -> pass/review/block/support), function-calling (Choice per closed-set arg + Noul `stated?` for optional)

## LangChain integration

`pip install langchain-typesafe` (+ `[experimental]` for middleware)

```python
from langchain_typesafe import Noul, TypeSafeClassifier
clf = TypeSafeClassifier(questions={"urgent": Noul(instructions="Does this need attention now?")})
resp = clf.invoke("deploy failed twice, 500s...")
resp.nouls["urgent"].noul
```

Middleware (`langchain_typesafe.experimental.middleware`):
- `ModelRouterMiddleware(choices={fast: ModelChoice(...), powerful: ModelChoice(...)})` — classifies latest human message, picks model for run
- `AutoModeMiddleware(tools=[...])` — `wrap_tool_call`, Noul risk check, returns error ToolMessage instead of running

See: https://docs.langchain.com/oss/python/integrations/providers/typesafe
Blog: https://www.langchain.com/blog/building-a-harness-with-jev

## SDKs

- Python: `pip install typesafe-sdk` -> `TypeSafeClient().system_one(state=..., questions={...})`
- JS: `@typesafe-ai/sdk`
- Skill: `npx skills add typesafe-ai/skills --skill typesafe-ai` / Claude Code plugin `typesafe@typesafe-ai`

## Ideas to try here

1. `01-routing/` — intent router: Jev Choice -> deterministic fn vs small LLM vs big LLM
2. `02-guardrails/` — port guardrails cookbook: 4x Noul + Severity Score, strict vs permissive policies
3. `03-function-calling/` — closed-set dispatcher: `__tool__` Choice + per-arg Choice + `stated?` Noul
4. `04-automode/` — LangChain AutoMode clone without LangChain: intercept tool calls, Jev risk gate
5. `05-fanout/` — 50+ question single-request benchmark: latency vs LLM sequential

## Sources

- Quickstart: https://docs.typesafe.ai/introduction/quickstart
- API ref: https://docs.typesafe.ai/api
- Models/pricing/limits: https://docs.typesafe.ai/models
- Confidence: https://docs.typesafe.ai/confidence
- State: https://docs.typesafe.ai/concepts/state
- Full index: https://docs.typesafe.ai/llms.txt
- LangChain provider: https://docs.langchain.com/oss/python/integrations/providers/typesafe
- Launch blog: https://typesafe.ai/blog/introducing-system-one-models-and-jev
- LangChain harness blog: https://www.langchain.com/blog/building-a-harness-with-jev
- Evals: https://evals.typesafe.ai/
