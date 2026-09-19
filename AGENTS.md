# AGENTS.md

Jev (TypeSafe System One) research + Python SDK where S1 (Jev, algebraic)
drives S2 (Codex, organic). Examples run on scripted backends; live needs keys.

## Layout

- `sdk/` — uv project (`uv run pytest`, `uv lock`)
- `sdk/jevx/` — client, idiomatic `py` layer, `relational`, `lint`, `prompts`,
  `s2` backends, `risk`
- `sdk/examples/` — 18 flows: support_copilot, code_supervisor, incident_loop,
  invoice_cascade, rag_guard, browser_loop, review_gate, conteval,
  floor_supervisor, skill_router, context_compact, model_router, graph_nav,
  trader_loop, game_loop, test_select, shell_gate, robot_loop
- `.agents/skills/jev/SKILL.md` — condensed Jev usage for agents (start here)
- `.agents/research/` — deep notes, one topic per file (see dir)

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
