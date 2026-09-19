# Algebraic SDK redesign: status and TODO

Date: 2026-09-19

## Accepted contract

- Python operator syntax builds Jevx expression objects; no custom parser is needed.
- `Predicate`, `Expr`, `Rule`, `Vector`, and `Case` are the expression layer in
  `sdk/jevx/py.py`. One `.ask(state)` collects distinct leaves and submits one
  TypeSafe question batch. Dependent calls remain separate evaluation waves.
- `case[condition: value, ...: fallback]` is ordered and lazy about selecting
  its returned value. It does not execute the value or a side effect.
- Python keeps control of thresholds, retries, budgets, and external effects.
- Each judgment must receive its own row. `Table` now places row identity in
  that question's structured instructions and uses shared state for common
  context. Batches remain capped at 20.
- Official TypeSafe question models and `JSONContent` own wire validation and
  serialization. Do not stringify structured instructions or criteria.

## Done and verified

- Official `typesafe-sdk` dependency and client delegation:
  `sdk/pyproject.toml`, `sdk/jevx/client.py`, `questions.py`, `answers.py`.
- Lazy probability math, hard threshold rules, named vectors, ordered cases:
  `sdk/jevx/py.py`; coverage in `sdk/tests/test_algebra.py`.
- Structured question entries and payload lint:
  `sdk/jevx/questions.py`, `py.py`, `lint.py`; invoice example in
  `sdk/examples/invoice_cascade.py`.
- `Table.noul()` embeds each row in its own question and keeps shared context in
  request state. Score and Choice row calls use the same row binding.
  `sdk/tests/test_relational.py` covers row association, a 21-row split, cache
  reuse, and context invalidation.
- Browser fan-out, preference review, test selection, line filtering, and context
  compaction use public vector/table APIs; examples no longer call private
  `_decide` or inspect raw `.answers` payloads.
- `TaskRun.ask()` records vectors and rules with compact summaries. The incident
  example uses a vector for triage and a lazy threshold rule for verification.
- Field-local Choice/Score metadata replaced `.confidence(name)` in examples,
  except `flow_class.py`, which still demonstrates the class-battery surface.

## Remaining work, ordered

1. **Compile complete dataflow graphs, not only expressions.** Existing `_evaluate`
   compiles one expression to a request batch; `Ix` composes executable typed
   stages separately. Decide whether one graph IR should cover both. Acceptance:
   construction makes no calls; independent question nodes share a request;
   dependent nodes execute in later waves; repeated pure nodes deduplicate;
   unselected case effects do not run; traces show nodes and request waves.
2. **Finish example review and migration.** Re-read every file in
   `sdk/examples/` against its actual job. `dispatch.py` still uses three
   `Questions` classes; decide if route-local vectors preserve the union lesson.
   `flow_class.py` intentionally shows `Questions` and `Uses`, but still exposes
   `.confidence(name)`; either modernize it or label this as the explicit
   class-battery example. Review `eval_harness.py`, `graph_nav.py`, and remaining
   Python branches only where they hide model policy. Keep Python loops,
   budgets, validation, and side-effect control explicit. Acceptance: example
   model calls use public SDK APIs, preserve thresholds and request counts, and
   have a scripted path or a stated live-only reason.
3. **Keep request/result types honest.** Noul probabilities are not model
   confidence. Choice and Score retain their supplied confidence and
   distributions. Acceptance: public examples use field-local metadata and
   never imply a Noul confidence exists.
4. **Final repo-wide proof and push.** `uv run ruff check jevx examples tests`,
   `uv run pytest -q`, `uv run ty check jevx`, compile all examples, run key
   scripted machines, verify `uv lock --check`, then verify the live
   `--env-file .env` example and remote commit.
