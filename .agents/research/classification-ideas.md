# Classification restatements (community ideas)

Source: Adam Wathan thread "interesting problems restated as classification for Jev?" (Sep 18 2026) + replies. Community claims, not verified.

## The ideas

1. **Graph extraction** (@yoheinakajima) — score every word 1-5 semantic significance + tag IDs, keep high scorers, emit graph. Extraction as per-token Score + dedup in code.
2. **NPC AI** (@Cephalization) — game state every few frames -> Jev dispatches goblin actions (run away, etc.). Real-time loop classification; matches Doom-demo shape.
3. **Component rendering** (@cjwestland, json-render.dev) — Jev decides which component to render. UI dispatch as Choice.
4. **Receipt budgeting** (@techenby) — Walmart/Target receipt line-by-line -> budget categories. Line-item Choice, like semantic_find pattern.
5. **Search filtering** (@kentcdodds, kody.codes) — vector search returns noisy candidates, Jev filters noise. Rerank/gate pattern (cf. classifying_rag_passages cookbook).
6. **Codebase audit crawler** (@marckohlbrugge) — options = file paths / "next chunk" / "mark reviewed". Navigation as Choice loop.
7. **Live sports camera selection** (@vamonke) — pick 1 of N cameras. Classic high-cardinality Choice.
8. **Code quality judgement** (@MrCollison) — senior-flavor architectural checks as many cheap checks. Composite scoring over PRs.
9. **State-graph exploration** (@owickstrom, Bombadil) — reweigh Markov chains w/ user goals. Routing-as-reweighing.
10. **Robot litter picker** (@CraigSmitham) — open Q: Jev is text-only (no images yet), so vision must be pre-processed to text state.

## Pattern behind all of them

State (richer than you think: game frames, DOM, receipts, file trees, camera feeds-as-text) + one narrow question per step + code owns the loop. If it smells like "pick one / score this / yes-no per item," it's Jev-shaped even when it doesn't look like ML.
