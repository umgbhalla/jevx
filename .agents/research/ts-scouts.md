# TS wave-1 scout findings (arriving)

## Vercel AI SDK provider (ai-sdk.dev docs)

- Setup: `pnpm add @ai-sdk/typesafe-ai`, `TYPESAFE_API_KEY`. `createTypeSafeAi({apiKey, baseURL (https://api.typesafe.ai/v1), headers, fetch})`.
- `typeSafeAi.evaluationModel('jev-latest')` + `experimental_evaluate({model, state, questions})`. Registry aliases supported; Gateway: `model:'typesafe-ai/jev-latest'`.
- One request, shared state: `choice` (1-255 opts), `score` (2-10 levels, fractional), `boolean`->noul (`probability=P(true)`).
- Rounding: probs/scores rounded 2dp, may sum 0.99; `result.rounding={probabilityDecimals:2,scoreDecimals:2}`.
- Confidence: `result.providerMetadata?.typesafe?.confidence: Record<qid,number>` — Choice/Score only, not selected-prob; boolean prob != confidence.
- Sources: https://ai-sdk.dev/providers/ai-sdk-providers/typesafe-ai, https://ai-sdk.dev/docs/ai-sdk-core/evaluation

## Email triage pair

- GiesN/typesafe-jev-workflow: single `Choice intent` (invoice vs general, "merely mentioning invoices != invoice"), LangGraph `START->detect_intent->handle_invoice/handle_general->END`, `EmailState{email,intent,confidence,probabilities,model,destination}`, 10 mocked emails, fail-closed on API error.
- jnorgren/an-email-classifier: 7 parallel Qs (Choice category + Score priority 0-4 + 5 Noul spam/phishing/reply/action/security_alert), linear CLI parse->evaluate->apply_filters, thresholds override to phishing/spam without re-call, Gmail auto-label + dry-run.

## MCP servers

- itsmostafa/typesafe-mcp (80★, Go binary, better maintained: release-please+CHANGELOG): single `evaluate` tool, `{state, questions, model?}`, batched parallel, retries 429/529, 60s timeout. `evaluate setup mcp/pi`.
- pedroknigge/mcp_jev (TS/Node20, 0★): 5 tools (`ping|list_packs|describe_pack|run_pack|run_questions`), 12 packs (computer_use_step, model_router, skill_router, command_risk, review_diff, code_audit, pr_audit, verify_gap, boundary_check, locale_country, intent_router, i18n_copy). Richer but GitHub-install only.

## Flue + Cloudflare gateway

- matthewp/flue-jev-demo: `POST /api/route` -> direct `askJev` (no chat cost); `SupportAgent` (gpt-4o-mini) + `useJevRouter` exposing `route_with_jev` tool (intent Choice billing|technical|human + isUrgent Noul). `env.AI.run('typesafe/jev',...)` via Workers AI binding, default gateway, no custom caching. Jev model on CF: https://developers.cloudflare.com/ai/models/typesafe/jev/

## Composio TS provider (@composio/typesafe, `next` branch)

- `decide(toolSet, request) -> call|partial|abstain + confidence/judgements`, then `execute(userId, decision, {arguments, confirm})` needs no second TypeSafe call. Closed-set only (enum/bool); `partial`+missing/suggestions, destructive `requiresConfirmation`, `shortlistTools`/`confidenceGate`. Best TS answer to "tool routing with abstain reasons + per-arg confidence."

## @typesafe-ai/sdk (JS) surface

- `npm i @typesafe-ai/sdk` (node>=20). `new TypeSafeClient({apiKey, baseURL, defaultModel, timeout, retry, fetch, dangerouslyAllowBrowser})`, env fallback.
- `client.systemOne({state, questions, model?})` -> typed `answers` via `const Q extends Questions` generics. Helpers: `noul(instr, {true,false})`, `choice(instr, {label: desc|null})` (map!), `score(instr, [d0,d1..])` (>=2 list).
- Retry: 10s/attempt, maxRetries 2, 500->5000ms backoff, 408/429/5xx, Retry-After<=60s. ESM+CJS dual.

## Adblock (DOM classification pattern)

- realZachi/typesafe-adblock (MV3, BYOK): DOM candidates -> compact JSON state (tag/classes/shape/text<=220ch/link_hosts, numbers->words since Jev weak on numbers), 1 Noul/candidate (`ad_i`, >=0.70 remove), batches<=30, 600ms debounce, ~25-60ms amortized/element. Textbook "code pre-filters, Jev judges" split.

## Vercel provider internals

- `typesafe-ai-evaluation-model.ts`: `boolean->{noul}` on POST `${baseURL}/systemone`; response `noul` -> `boolean:{probability}`; choice/score passthrough. Eval-only (language/embedding/image throw `NoSuchModelError`). choice<=255 / score<=10 enforced client-side. `providerOptions.typesafe.*` -> unsupported warnings; errors via `APICallError`. Examples: basic/registry/error-handling/structured-rubrics.

## LangChainJS provider

- `TypeSafeClassifier extends Runnable`, no middleware in JS (unlike Python). `serializeState` zod (Date->ISO, circular throws); `renderMessage` any-depth (human->user, ai->assistant, tool calls/refusals inline). `new TypeSafeClassifier({questions, model, apiKey, baseUrl, timeout 30s, maxRetries 2})`.

## ts-browser-agent loop

- `Decision(operation, target, confidence)`, ops CLICK|TYPE_TEXT|SELECT|SCROLL|WAIT|DONE|BLOCKED. `build_classifier(snapshot)`: Choice operation + per-op target Choices (speculative fan-out, 1 req/step). State `{goal, page, elements[], recent_actions[-10:]}`. Tiny gpt-5-mini only for TYPE_TEXT strings. Wiki game: rules as snapshot filter, goal `Start at <url>` last.

## jev-ultrafast detail

- 1 req/step + Qs `{operation, click_target, type_text_target, select_target}`; 2nd chat call only for TYPE_TEXT fill. 7.073s / 17 reqs / median 178ms; 9.45s->7.09s, browser calls 1092->101.

## Voice browser loop

- moritzkremb/jev-voice-browser: transcript+page+elements(<=100) as state, ONE systemOne per partial (~250-350ms, ~$0.0002). intent/site/target/tab_direction Choice; complete/is_command/destructive Noul; scroll_amount Score; spans Choice over regex candidates. Gates: is_command>=0.5, intent>=0.55, complete>=0.6|900ms silence. MAX_INFLIGHT=2, abort stale.

## Mobile loop

- droidrun/mobile-jev: operation Choice + speculative targets; StaleObservationError retry<=3; 400ms settle poll. Phone = Mobilerun cloud Android, brain = Jev. Uber demo ~21s/9 actions (device-bound, not Jev-bound).

## Computer-use numbers

- awlevin/typesafe-computer-use: screencapture + Vision OCR + tile-diff cache + AX walk; state `{goal, app, tab, focused_field, prev_actions[-8:], screen_items[]}`. kind Choice (12 ops) + item/site/offscreen Choices + type_text Noul; stop if conf<0.4. Jev $0.0002 vs Opus $0.032 (**155x**); 0.13-0.38s vs 5.2s (14-40x).

## oh-my-pi Judge (why native beats LLM-judge)

- `TypeSafeJudge.judge()` verbatim-forwards `{state, model, questions}`. True distributions vs one-hot; no prompt-render/keyword-parse; retry-after backoff; `GET /v1/models` probe. `providers.judgmentProvider: auto|typesafe|llm` + failover.

## WrongStack dual classifier

- Stage-1 keywords settle most of ~75 roles; only ambiguous reaches stage-2. TypeSafe: Choice over candidates + Noul "does any fit", honest null decline (LLM always conf 1). Fallback on: no account, transport/timeout/malformed/off-list/<2 candidates.

## Foreman (supervisor pattern)

- thruwire/foreman: Codex worker loop + foreman watcher (debounce 5s/30s). Jev owns 9 parallel Nouls (complete/tests/requirements/verify/finish + progress/stuck/off-track/needs_human), NO tools. Code owns `FactoryPolicy` -> 8 actions, thresholds (finish .85, stuck .80). Uncertain estimator + deterministic controller.

## jev-review pipeline

- devagrawal09/jev-review: per-file Noul risk matrix (0.7, top-8) -> Choice category + Score priority -> Choice evidence hunk (>=0.55) -> Choice mechanism + Score severity -> conditional owner; request_changes if >=2. Dashboard :4317.

## neo4jev (graph traversal)

- jexp/neo4jev: node state `{current_node, path_so_far, hop_index, goal, graph_schema}` (vectors dropped, text 200ch). 1 systemOne/hop: Choice next_edge (cap 255) + Noul goal_reached. Beam width 4, max_depth 4, max_calls 24.

## blink (probabilistic BFS search)

- ellipsis-dev/blink: chunk = dir listing; Choice "which entry most relevant"; rank by probabilities[name]. BFS largest-remainder walker allocation. Minimal TS search-as-routing ref.

## Model-router template (asymmetric bars)

- davila7: 1 req, 3 Qs (tier Choice, effort Score 0-3, risky Noul). Upgrade conf 0.3, downgrade 0.6; risky>0.7 forces deep. Fail-closed.

## inbox-zero mapping (canonical yesNo<->noul)

- `yesNo`->`noul` on request, back on response; zod discriminatedUnion; 30s abort; 429 throws.

## advocaat (minimal TS DX)

- pithings/advocaat: `ask(state, {k: question})` one batch; `ask.if/choice/score/switch` tagged templates; zero-dep, `Askable` thenable, `skills/advocaat/SKILL.md`. Best tiny TS ref.

## Driving sims (sensor encoding)

- kavehmz demo02: 4 cameras + radar/TTC + blind-spot + signs/peds as structured state (no pixels). 5 parallel Qs (lane, left/right_speed, collision Noul, attention). ~800ms loop, stale>1.8s discard.
- standardagents/jevpilot: full sim -> compact state (tables factored shared+varying, RDP boundaries); motion{drive,stop} + vector{v0..} + conditional route; 250ms/650ms adaptive (4Hz danger, 1.5Hz cruise); single-eligible resolved locally (no call); code owns sampling/geometry/safety veto; server holds key at /api/decide.

## Duels harness (eval discipline)

- JYeswak/jev_playground: 5-rung kill-ladder, ~10x cost/rung, authors can't grade own. Probes live-vs-replay; framing-leak note; ensemble only if low error-phi.

## dabit3/jev-experiments (20 dirs, one line each)

- agent-assist (intent/churn/flags+macro) · commit-sentry (per-hunk block/warn) · inbox-blitz (NL label vs 500 emails) · jev-ax-pilot (macOS AX UI) · jev-dispatch (7Q triage) · jev-firehose (6 Nouls+lang) · jev-instant-search (30 Score re-rank/keystroke) · jev-launcher (candidate/action intent) · jev-lint (line Nouls+severity) · jev-shell-guard (run/confirm/refuse) · jev-swarm (move/boost/target per agent/400ms) · jev-tower (ATC instruction) · jev-voice-turn (turn_complete/barge-in) · judge-sheets (300-row fill) · live-minutes (actions/decisions/risks) · log-sentinel (severity vs regex) · modstream (pre-publish mod) · nl-palette (66 commands re-rank) · send-guard (10+Qs block/warn/send) · turbo-rerank (50 Score to #1).

## TS starters top-10 (curated)

- hamakyo/jev-starter (confidence-gated + evals) · romaluev/jev-ego (indexed-action, no Chrome) · Ying-Kai-Liao/jev-browser (LLM plans, Jev steps; lib/CLI/MCP) · yusukebe/hono-jev-router (request->Choice->handler) · tamaratran/fast-jev-compaction (prune/truncate verbatim) · kitze/unclutter (clutter Noul->hide-rule) · jomatsu/zod-jev (Zod->semantic gate) · typesafe-sdk-js (official base) · smithersai/smithers (plan/run/review + session-checker) · vercel-labs/fx (act->permission-review loop).

## Weak / failed scouts

- superagents-lab/jev-search: repo NOT FOUND (scout reconstructed from docs + parallel.ai blog) — treat pipeline notes as unverified.
- ElizaOS: scout looked at local disk instead of GitHub — needs redo if Eliza matters.
