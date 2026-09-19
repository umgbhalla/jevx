# AGENTS.md

Research repo for Jev (TypeSafe AI System One model): API notes, benchmarks,
community experiments, and agent-loop patterns. Read-only research — no app code.

## Layout

- `00-quickstart.py` — raw HTTP + SDK hello-world (needs `TYPESAFE_API_KEY`)
- `.agents/skills/jev/SKILL.md` — condensed Jev usage for agents (start here)
- `.agents/research/` — deep notes, one topic per file:
  - `api-spec.md` — endpoint, Noul/Choice/Score schemas, errors, limits
  - `question-apis.md` — per-type deep dives + SDK surface comparison + cookbook index
  - `patterns.md` — fan-out, confidence gating, composite scoring, intent routing
  - `langchain.md` — TypeSafeClassifier, ModelRouterMiddleware, AutoModeMiddleware
  - `benchmarks.md` — evals.typesafe.ai + consistency numbers + independent GH benchmarks
  - `community.md` — what people build (browser/trading/email/guardrails/games)
  - `ts-scouts.md` — TypeScript ecosystem findings (Vercel provider, loops, starters)
  - `classification-ideas.md` — community "restate it as classification" ideas
- `README.md` — human overview

## Setup

```bash
export TYPESAFE_API_KEY=...   # from https://console.typesafe.ai/
python3 00-quickstart.py       # raw HTTP; USE_SDK=1 for typesafe-sdk path
```

## Jev essentials (see SKILL.md for full)

- `POST https://api.typesafe.ai/v1/systemone`, `{state, model: "jev-latest", questions}` -> `{model, answers, usage}`
- Three question types: `noul` (P yes, no confidence), `choice` (<=255 opts + confidence), `score` (2-10 ordered levels + confidence)
- All questions in one request evaluate in parallel — batch aggressively
- Code owns decisions: threshold probs/confidence in your code, never in the model
- Text-only state (string | object | array); English best; never send secrets

## Conventions

- New findings go in `.agents/research/<topic>.md` with source links + dates; flag unverified claims
- Keep notes dense: bullets + links + numbers, no essays
- Commit per research batch: `git add -A && git commit -m "<topic>: <what>"`
