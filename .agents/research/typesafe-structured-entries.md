# TypeSafe structured entries

Date: 2026-09-19

- Official guide: https://docs.typesafe.ai/primitives/advanced
- Index: https://docs.typesafe.ai/llms.txt
- Question fields `instructions`, Choice criteria values, Score criteria entries,
  and Noul true/false criteria accept strings, objects, arrays, or null.
- Installed `typesafe-sdk` question schemas expose `JSONContent`; verified with
  local Pydantic schemas and nested Choice, Score, Noul construction.
- `sdk/jevx/py.py` accepts upstream `JSONContent` values in the Noul, Choice,
  and Score builders. Named `Vector` fields keep the public authoring API small.
- `sdk/jevx/lint.py` validates nested JSON content and duplicate structured
  Score levels without converting rubric objects to strings.
- `sdk/tests/test_algebra.py` verifies request traces preserve nested values.
- Unverified: model quality differences between equivalent string and
  structured instructions. No live quality comparison was run.
