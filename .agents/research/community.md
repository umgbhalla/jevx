# Community experiments (GitHub + X, Sept 2026)

Verified 2026-09-19 via `gh search repos jev` + code search + raw fetch. Launch HN: https://news.ycombinator.com/item?id=49717558 (~496 comments).

## Browser agents

- https://github.com/browser-use/jev-ultrafast (5991★) — Jev picks operation+DOM target in one req, LLM only for TYPE_TEXT. See benchmarks.md for numbers. `jev_ultrafast/agent.py`, `docs/performance.md`.
- https://x.com/kylejeong/status/2100622054945095934 (Kyle Jeong, Browserbase) — Stagehand+Jev, a11y-tree as state, `~$0.001`/task near-instant.
- https://github.com/ndrezn/ts-browser-agent — `langchain-typesafe` agent, Jev picks `{CLICK, TYPE_TEXT, DONE}` + target/step. Wiki-Game demo `examples/wiki_game.py`, `src/ts_browser_agent/decision.py`, `docs/wiki_game.mp4`.
- https://github.com/moritzkremb/jev-voice-browser — voice -> intent+target ~300ms/word. https://x.com/moritzkremb/status/2100715237267660873
- https://github.com/droidrun/mobile-jev — mobile variant.
- https://github.com/superagents-lab/jev-search — Jev web search: source selection, query understanding, rerank.

## Trading

- https://github.com/jarrodwatts/jev-trader (931★) — one Jev buy/sell per Monad ~300ms block on Kuru MON-USDC, post-only 1-tick-inside, mock default. p50 read 18ms, loop 100ms, decision `81ms $0.000004`, gas ~0.0357 MON/tx. https://x.com/jarrodwatts/status/2100356151468585346
- https://github.com/aowang-ai/jev-trade — Hyperliquid long/short loop. https://github.com/unicodeveloper/jevocks — 30-day higher? via Valyu. https://github.com/sosopop/jev_stock — HK backtest.
- https://github.com/virattt/ai-hedge-fund — `JevLLM` adapter mapping typed answers onto `LLMClient` JSON contract: `hedge_fund/llm/client.py`.

## Email / triage

- Ryan Vogel email-triage-at-scale: NO repo found (name search empty on GH/X/HN). Closest:
- https://github.com/elie222/inbox-zero — `classifyWithTypeSafe()` posts `{model,state,questions}` (yesNo->noul) to `/v1/systemone`, zod-validates: `apps/web/utils/classifier/typesafe.ts`, `typesafe.test.ts`, `classify.ts`.
- https://github.com/GiesN/typesafe-jev-workflow — LangGraph async, Jev `Choice(invoice,general)` routes inbound email, 10 mocked smoke-checks.
- https://github.com/jnorgren/an-email-classifier — CLI email eval via Jev.

## Guardrails / routing / dispatch

- https://github.com/BerriAI/litellm — Jev relevance-compaction guardrail (one yes/no per tool exchange, blanks irrelevant): `litellm/proxy/guardrails/guardrail_hooks/typesafe/typesafe.py`.
- https://github.com/davila7/claude-code-templates — `cli-tool/components/mods/productivity/jev-model-router/README.md`: tier Choice + effort Score + risky Noul, asymmetric upgrade 0.3 / downgrade 0.6.
- https://github.com/Dicklesworthstone/skillranker — Rust CLI ranks agent skills via Jev (structured JSON, abstention, Claude hooks).
- https://github.com/WrongStack/WrongStack — dual classifier (TypeSafe Choice+Noul vs LLM fallback on ambiguous): `packages/cli/src/services/dispatch-classifier.ts`, `docs/fleet-dispatch-classifier.md`.
- https://github.com/Significant-Gravitas/AutoGPT — blocks `choice/route/pick_best/filter/score/yes_no/ask_many`: `autogpt_platform/backend/backend/blocks/typesafe/`.
- https://github.com/can1357/oh-my-pi — native Judge -> `POST /v1/systemone`: `packages/ai/src/judgment/typesafe.ts`.
- https://github.com/matthewp/flue-jev-demo — Flue routing via Cloudflare AI Gateway.

## Games / fun

- Doom demo (official): no public code found. Closest: https://github.com/kavehmz/typesafe-playground (`demo01-03`, driving sims), https://github.com/standardagents/jevpilot (Three.js driving + Jev autopilot), https://github.com/JYeswak/jev_playground (gauntlet/duels harness).
- Wikiracing: `ndrezn/ts-browser-agent` wiki_game above.

## Misc interesting

- https://github.com/jexp/neo4jev — Jev navigates Neo4j graph via classifier over neighbor rels.
- https://github.com/devagrawal09/jev-review (284★) — staged code review + dashboard.
- https://github.com/realZachi/typesafe-adblock (50★) — "is this DOM an ad?" Chrome ext (BYOK).
- https://github.com/giuliosmall/pg_typesafe (76★) — pre-alpha Postgres ext. https://github.com/pithings/advocaat (75★) — ask-AI-about-data. https://github.com/ellipsis-dev/blink (18★) — codebase search.
- https://github.com/TianyuCodings/NanoJev (452★) — nano replica (parallel decisions, dynamic candidates). https://github.com/TheoLeeCJ/SemIf (1652★) — semantic-ifs on 3090 (independent). https://github.com/thruwire/foreman (309★) — factory foreman. https://github.com/dabit3/jev-experiments (254★).
- MCP: https://github.com/itsmostafa/typesafe-mcp (80★), https://github.com/pedroknigge/mcp_jev.
- Providers: vercel/ai `packages/typesafe-ai/`, pydantic-ai `providers/typesafe.py`, rig Rust `rig-typesafeai`, composio, elizaOS `services/typesafe/`.
- Awesome lists: https://github.com/Anil-matcha/awesome-jev-by-typesafe (548★), https://github.com/yibie/awesome-jev (205★), https://github.com/cobanov/awesome-jev (128★), https://github.com/fatwang2/awesome-jev (130★). Note: bulk same-day scaffolds, many unproven.

## Chatter numbers worth stealing

- DuckDB ext ~10s/1000 rows: https://x.com/hamiltonulmer/status/2100370557405667768
- Jev+small LLM 100% WebMCP ~112x cheaper: https://x.com/0xidanlevin/status/2100937437325205568
- CUA-S1-FORMS 706k params 50ms vs 23 turns 39.6s, 99.7% vs Jev 83.6% specialist-only: https://x.com/trycua/status/2101014004927729737
