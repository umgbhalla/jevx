# Repository guidance

`sdk/` is the Python uv project. The supported public API is the Pydantic
`response_model` surface documented in `sdk/README.md`. Keep examples and
tests on that interface; avoid reviving the earlier algebra, flow, relational,
or task wrappers.

## Layout

- `sdk/jevx/` — question declarations, answer parsing, Pydantic compiler,
  and sync/async TypeSafe clients.
- `sdk/examples/` — small live examples using a Pydantic `BaseModel`.
- `sdk/tests/` — compiler, validation, and request serialization tests.
- `.agents/skills/jev/SKILL.md` — condensed Jev usage instructions.
- `.agents/research/` — historical research notes, not SDK API documentation.

## API invariants

- Compile `client.create(response_model=Model, state=state, model="jev-latest")`
  into one `{model, state, questions}` request. All declared fields judge the
  same state in parallel.
- A Pydantic field's name is the question ID; its `NoulAnswer`,
  `ChoiceAnswer`, or `ScoreAnswer` annotation chooses the primitive.
- `j.ask(instructions)` starts a question. `| j.yes(...) | j.no(...)`,
  `| j.option(name, description)`, or `| j.level(description)` constructs its
  complete criteria. Preserve structured JSON in instructions and criteria.
- Parse the full upstream answer into the same Pydantic model. Computed fields
  and validators are local; do not submit them as questions.
- Keep the request state as supplied by the caller. Do not embed it into field
  descriptions or silently drop model configuration.

Run `uv run pytest` and `uv run ruff check .` from `sdk/`. Live examples need
`TYPESAFE_API_KEY`; offline tests must not need network access.
