# Confidence + State + Patterns (condensed)

Source: https://docs.typesafe.ai/confidence, /concepts/state, /patterns*, /concepts/how-to-build-with-system-one

## Confidence
- Only on Choice/Score. Derived from `probabilities` shape (concentrated = confident). Noul has no confidence — prob is the answer.
- Don't lock to vendor formula: full distribution returned, compute your own if needed.
- Pattern: 3 bands
  - high -> act automatically
  - medium -> confirm / flag / gather more
  - low (<0.5 default floor) -> route to human, don't guess
- Thresholds scale with risk: read-only low bar, destructive high bar (e.g. `approve_transfer` needs >0.9 + explicit confirm).
- Start conservative, tune on your own labeled traffic.

## State
- One state per request, all questions see it.
- string = single message/passage. object = named fields + related records + policy/rules together (preferred). array = sequences/chat logs.
- Put comparison material together: `{ticket.messages, order.charges, refund_policy}` then ask `did_customer_request_refund?` + `does_policy_support?`.
- Text only. English best; CJK/other lower accuracy — watch confidence.
- LangChain `TypeSafeClassifier.invoke()` accepts str | JSON | BaseMessage | sequence of messages (auto-converted to role/content JSON).

## How to build
- Code stays in control; Jev gets narrow structured decisions (smart if-statements).
- Decompose broad judgment -> atomic questions, combine with weights in code (composite scoring).
- Don't use Noul 0.5 as "medium" — 0.5 = even split yes/no. Use Score for spectrums.
- Write questions about the *idea*, not keywords ("is amd tracking nvidia" matches without word overlap). Don't name after params ("Which resolution?").

## Patterns
1. **Speculative fan-out** (`/patterns/fan-out`): pack many (even speculative) questions in one call, let code ignore irrelevants. Cheap.
2. **Confidence-gated routing** (`/patterns/confidence-routing`): answer = what, confidence = whether to act.
3. **Composite scoring**: atomic Scores + code weights instead of one mega-judgment.
4. **Intent routing**: Jev classifies -> deterministic logic | specialist LLM | human.

## Cookbooks worth stealing
- **Guardrails** (`/cookbooks/llm_guardrails`): 4x Noul (jailbreak, harmful_request, medical_advice, self_harm) + Severity Score (0-3). Policies: `{review_threshold, action_threshold, severity_block}` e.g. strict `{0.35, 0.70, 2.0}`. HAZARD_ACTION maps hazard->block/review/support. Severity can escalate review->block. Run on BOTH input and output. `novelist_poison` passes (fiction != intent), `good_refusal` passes.
- **Function calling** (`/cookbooks/function_calling`): closed-set args only. `Literal` -> Choice, `list[Literal]` -> Noul per member (`Does user want {}?`), `bool` -> flag. `stated?` Noul per optional arg decides omit vs fill (else model forced to guess). `__tool__` Choice picks fn. Call confidence = min(judgment confidences). 54 questions/command in demo, one request.
- Others: rerank (1 Q per query-candidate), line-by-line search (218 line-ids in one Choice!), hierarchical classification (beam search over Choice probs), citation_check, classifying_rag_passages (drop prompt injections), SDE cascade (mini->verify->reasoning).
