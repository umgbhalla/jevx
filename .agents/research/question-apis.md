# Question APIs: Noul vs Choice vs Score (+ SDK surfaces)

Yes — three question types. Same endpoint `POST /v1/systemone` (`{state, model, questions}` -> `{model, answers, usage}`), same `model: jev-latest -> jev-1.13.0`. Keys are yours, not sent to model. All questions in one req evaluated in parallel.

## Noul (yes/no -> P(yes))

Schema: `{"type":"noul","instructions":"...","criteria":{"true":"...","false":"..."}}` (criteria optional). -> `{"type":"noul","noul":0.92}`. NO confidence field — value IS the answer. `0.5` = even split, NOT medium.
Use when code branches on `if`. Phrase so high=yes; one predicate per Q; define vague terms ("urgent", "strong in Python") or probs are uninterpretable. `Noul(instructions, criteria=NoulCriteria(true,false))`.
Production: threshold bands, e.g. `<0.30 no / 0.30-0.70 uncertain->human / >0.70 yes` (illustrative — tune on labeled data). Self-consistency run: mean std `0.0102` (lowest of all LLM conditions).
Guardrail battery: 4 Nouls (jailbreak, harmful_request, medical_advice, self_harm) + Severity Score, `route()` with `HAZARD_ACTION` + `POLICIES strict{0.35,0.70,2.0}/permissive{0.35,0.85,2.0}` -> pass/review/block/support. Run on input AND output.
Sources: https://docs.typesafe.ai/primitives/noul.md, https://docs.typesafe.ai/cookbooks/consistency_noul_cookbook.md, https://docs.typesafe.ai/cookbooks/llm_guardrails.md

## Choice (pick one of N -> distribution + confidence)

Schema: `{"type":"choice","instructions":"...","criteria":{"opt":"rubric or null"}}` (criteria required). -> `{"choice":"technical","probabilities":{...sum 1},"confidence":0.82}`.
Use when options map to code paths. Up to **255 options**/Q; larger = 2-stage rank->rerank (182 skills proven: Choice over 182 + gate Nouls, top-3 reread with full text + `fits?` Nouls; wrong loads `16.8% -> 7.3%`). Token budget ~32k shared state+Qs. Structured criteria for confusables (`{what, not_for, examples}`). Hierarchical: one Choice per sibling set, beam K=3 (`prod(edge)^(1/decisions)`) beats greedy 4/4 vs 2/4. Threshold e.g. `top<0.60 -> uncertain` gives 99.2% agreement, 74% auto.
Sources: https://docs.typesafe.ai/primitives/choice.md, https://docs.typesafe.ai/cookbooks/skill_suggestion.md, https://docs.typesafe.ai/cookbooks/hierarchical_classification.md, https://docs.typesafe.ai/cookbooks/consistency_choice_cookbook.md

## Score (spectrum position -> weighted float + confidence)

Schema: `{"type":"score","instructions":"...","criteria":["level0","level1",...]}` (ordered low->high, min 2, max 10). -> `{"score":1.6,"legend":{...},"probabilities":{...},"confidence":0.78}`. `score = sum(level*P)`, floats between levels.
Use for severity/happiness/relevance — anything where Noul 0.5 would be misread as "medium". Rules: situations not degrees (`Broken w/ workaround` > `Moderately severe`), one dimension per Q, rare extreme gets own top level, structured levels need same fields + realistic examples.
Composite scoring: atomic Scores -> normalize (`score/(len-1)`) -> weighted sum in code (e.g. `0.6*sev+0.3*frust+0.1*quality`), all in one req. Classification w/ confidence: `conf>=0.9 report group else parent division` (sure 90% vs unsure 40% -> 70% after back-off).
Sources: https://docs.typesafe.ai/primitives/score.md, https://docs.typesafe.ai/patterns/composite-scoring.md, https://docs.typesafe.ai/cookbooks/classification_using_confidence.md

## SDK surfaces (all hit same backend)

| | raw HTTP | Python `typesafe-sdk` | JS `@typesafe-ai/sdk` | LangChain `langchain-typesafe` |
|---|---|---|---|---|
| install | — | `pip install typesafe-sdk` | `npm i @typesafe-ai/sdk` (node>=20) | `pip install langchain-typesafe` (`[experimental]` for middleware) |
| auth | `Authorization: Bearer` | `TYPESAFE_API_KEY` (+`BASE_URL`/`DEFAULT_MODEL`/`LOG_LEVEL`) | same 4 via ENV/config | `TYPESAFE_API_KEY` (+optional `BASE_URL`) |
| sync/async | yours | `TypeSafeClient` + `AsyncTypeSafeClient` | async-only `systemOne()` | Runnable `invoke/ainvoke/batch` + agent middleware |
| state | str/object/array | str/dict/list or raw dicts | EntryType(+null), `noul()/choice()/score()` helpers | + LangChain messages auto->role/content JSON |
| retries | manual (429/529 backoff) | auto RetryPolicy (2 retries, 0.5->5s, 408/429/5xx, 30s budget) | same, ms (10s/attempt, 60s Retry-After cap) | inherited |
| LangSmith | no | no | no | yes |
| list models | `GET /v1/models` | `client.models.list()` | `client.models.list()` | — |

## Cookbook index (all official, https://docs.typesafe.ai/llms.txt)

- parallel_questions (13Q GDPR: 12.2x cheaper, 10x faster, identical): https://docs.typesafe.ai/cookbooks/parallel_questions.md
- rerank (BM25->Jev top-1 5%->18%, top-10 38%->62%): https://docs.typesafe.ai/cookbooks/rerank_typesafe.md
- semantic_find (218 lines, 1 Choice<=255 + exists Noul): https://docs.typesafe.ai/cookbooks/semantic_find.md
- autoformat (28->17 blocks, 2 reqs, $0.0003): https://docs.typesafe.ai/cookbooks/autoformat.md
- function_calling (54Q/cmd, closed_sets + `stated?` Noul + `__tool__` Choice): https://docs.typesafe.ai/cookbooks/function_calling.md
- skill_suggestion, entity_alignment (Score route=round), classifying_rag_passages (injection>0.70 drop), citation_check (Choice supports/contradicts/says_nothing, conf>=0.8 auto), sde_cascade (mini->Jev verify->reasoning Pareto frontier), date_extraction (7 Choices + assemble(), 6/6), hierarchical_classification, autoresearch (RMSE 3.09->1.77), pre_parsed_value_extraction (regex over-find + Choice pick).
- LLM compare harness: https://github.com/typesafe-ai/system-one-adapter-python
