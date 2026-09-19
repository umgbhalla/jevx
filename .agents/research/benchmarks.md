# Benchmarks & evals (Jev)

Most numbers are first-party (TypeSafe) + reproducible cookbooks + 2 independent GitHub evals. No third-party GPT-6 vs Jev accuracy leaderboard outside `evals.typesafe.ai` as of 2026-09-19.

## Official claims

- Home https://typesafe.ai: **193.6x faster, 444.6x cheaper** (footnote: workflows for System One tasks), hero `TypeSafe $0.000081 / 0.114s` vs `LLMs $0.013880 / 8.566s`, `$42/BTok in, output FREE` (238x lower than Claude Fable 5.1), `70-500ms` vs frontier `3-329s` (https://llm-benchmarks.diegoromero.es/) = 40-200x.
- Launch blog https://typesafe.ai/blog/introducing-system-one-models-and-jev — method: same workflow for all, reference = avg `GPT-6 Astra + Claude Fable 5.1` high-thinking, others default reasoning, LLMs via https://github.com/typesafe-ai/system-one-adapter-python. Admits 193x/444x is high-end; capability-team workflows (bias possible); Astra+Fable ref biases toward OpenAI/Anthropic. Side-by-side vs `GPT-5.6 Terra`, only disagreement `Churn likelihood`. Playground share: https://console.typesafe.ai/playground?share=shr_13a74b495fb786c4bd7964f11597301e7c9
- Models https://docs.typesafe.ai/models.md: `jev-latest -> jev-1.13.0`, `$0.042/MTok in, $0 out`, `250k tok/s, 1200 req/min`, `64k/req, 32k state+longest Q`.

## evals.typesafe.ai

https://evals.typesafe.ai — same workflow for all, consensus labels, equal-weight mean over 4 workflows. Up-left = better.

Mean (acc / cost / time):
- Jev workflow `67.8% $0.0004 0.4s`
- opus 5 workflow `73.1% $0.1761 37.8s` / prompt `64.8% $0.3417 70.5s`
- sol workflow `74.1% $0.0836 23.3s` / prompt `63.4% $0.2005 48.6s`
- sonnet 5 workflow `67.8% $0.1174 78.1s`, terra workflow `67.9% $0.0304 10.1s`, luna workflow `66.8% $0.0033 12.9s`
- DS v4 flash `64.4% $0.0059 51.9s`, DS v4 pro `65.5% $0.0413 86.5s`, haiku 4.5 workflow `53.6% $0.0195 12.5s` / prompt `18.1%`
- Every model: workflow > prompt.

Per-workflow (Jev): security_incidents `61.7% $0.0001 0.3s` (https://evals.typesafe.ai/security_incidents.html), agent_trace `71.6% $0.0003 0.5s`, invoice `61.8% $0.0011 0.5s` (weakest vs sol 79.1%), customer_service `76.0% $0.0001 0.4s` (best relative). Legend: opus/sonnet/haiku = Anthropic, DS = DeepSeek, luna/sol/terra = GPT-5.x, Astra = GPT-6, Fable 5.1 = Claude (refs).

## Calibration / consistency (reproducible cookbooks)

- https://docs.typesafe.ai/confidence.md — confidence from probs shape; `<0.5 human, high-stakes >0.9`.
- consistency_noul https://docs.typesafe.ai/cookbooks/consistency_noul_cookbook.md — 14 Nouls x15, mean std `0.0102` (lowest of all), `111ms $0.000043` vs haiku `1780ms $0.0018 (16x/42x)`, gpt-5.5-reasoning `11125ms $0.033 (100x/778x)`, opus `13886ms $0.034 (125x/805x)`.
- consistency_choice https://docs.typesafe.ai/cookbooks/consistency_choice_cookbook.md — mean prob-std `0.0098`; with `<0.60 -> uncertain`, `99.2%` agreement, `74.2%` auto / `25.8%` uncertain.
- classification_using_confidence https://docs.typesafe.ai/cookbooks/classification_using_confidence.md — 60 10-Ks -> 75 SIC groups, cutoff `0.9`: sure `27/30 (90%)`, unsure `12/30 (40%)`, back-off to division `48/60 useful`.
- parallel_questions https://docs.typesafe.ai/cookbooks/parallel_questions.md — 13Q GDPR batched `$0.000497 0.27s` vs 13 calls `$0.00609 2.71s` = **12.2x cheaper, 10x faster**, identical answers.
- Jaggedness https://docs.typesafe.ai/model-jaggedness/jev-1.13.md — 9 known failures: literal reading, math/counting, dates, indirection, large-state distractors, adversarial, contradictory criteria, no structural invariants (`P(refund)=0.72 + P(not)=0.47 = 1.19`), no generation.

## Independent GitHub benchmarks

- https://github.com/browser-use/jev-ultrafast (5991★) — `docs/performance.md`: Zurich->London flights `7.073s` (17 Jev reqs, median Jev `178ms`), matched pairs `9.45s -> 7.09s (-25%)`, browser calls `1092 -> 101`, reqs `22 -> 17`. Wiki Godel `2.798s`, hotel `1.896s`. 6 alternating runs, `jev-1.13.0` + `inception/mercury-2.5`.
- https://github.com/kyotofin/tax-doc-classifier (154★) — strict = wrong OR conf<0.95: TaxCalcBench `314pp 0 wrong ($0.36)`, IRS blanks `753pp 0 wrong 38 low-conf 5% ($0.86)`; vs Sonnet `$0.039 -> $0.00115 (34x)`, `3.3s -> 0.5s (6x)`, `30 -> 261 forms`. Repro `pnpm eval`.
- https://github.com/typesafe-ai/system-one-adapter-python (128★) — drop-in LLM-backed `system_one` for apples-to-apples; what evals.typesafe.ai uses for LLM arms.
- https://github.com/tamaratran/fast-jev-compaction (3515★) — 2 Nouls/call (`keepCall/keepResult`, 0.5), `maxState 25k`, never rewrites text (stability anecdote, no acc #s).
- https://github.com/anisselbd/jev-phishing-bench — Jev vs Haiku 4.5 on 2000 phishing emails (acc/calibration/latency/cost).
- https://github.com/WiktorB2004/llama-index-jev — Jev Score rerank, nfcorpus nDCG `0.340 -> 0.396 ~$0.0003/q`.
- https://github.com/DanRWilloughby/snifftest — 10x Boolean @0.7, 182ms median, 1/54 clean flagged vs 37 Haiku 4.5.
- https://github.com/CodeAlive-AI/mastra-jev-moderation — block 9/9 hostile, 0/49 real, ~0.4s median, ~4x cheaper.
- https://github.com/awlevin/typesafe-computer-use — OCR+Jev click, `~$0.0002/step`, 155x cheaper than Opus 5, ~20x faster.
