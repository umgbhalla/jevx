# Jev API spec (condensed from https://docs.typesafe.ai/api)

## Endpoint
```
POST https://api.typesafe.ai/v1/systemone
Authorization: Bearer <API_KEY>
Content-Type: application/json
GET https://api.typesafe.ai/v1/models  -> list aliases
```

## Request
- `state: string | object | array` (required) — content to evaluate. Object preferred: `{ticket:{...}, order:{...}, policy:...}`. Array for sequences.
- `model: string` (required) — `jev-latest` (default in SDKs), `jev-preview`, or pinned `jev-1.13.0`. Response echoes resolved versioned ID.
- `questions: map<string, Question>` (required) — key is yours, not sent to model, answers keyed same.

### Noul
```json
{"type": "noul", "instructions": "Does this convey urgency?", "criteria": {"true": "Explicitly time-sensitive", "false": "No urgency"}}
```
-> `{"type":"noul","noul":0.92}`

### Choice
```json
{"type": "choice", "instructions": "Which team?", "criteria": {"billing": "Payments...", "technical": "Bugs..."}}
```
-> `{"type":"choice","choice":"technical","probabilities":{"billing":0.08,"technical":0.85},"confidence":0.82}`
- cardinality up to 255 (higher = 2-stage score-then-choose internally)
- `criteria` values can be null for no detail

### Score
```json
{"type": "score", "instructions": "How frustrated?", "criteria": ["Calm","Frustrated","Very angry"]}
```
-> `{"type":"score","score":1.6,"legend":{"0":"Calm","1":"Frustrated","2":"Very angry"},"probabilities":{"0":0.05,"1":0.3,"2":0.65},"confidence":0.78}`
- min 2 levels, ordered. Score is probability-weighted, floats between levels.

`instructions`/`criteria` accept string | object | array (structured rubrics allowed — see primitives/advanced).

## Response
```json
{"model":"jev-1.13.0","answers":{...},"usage":{"input_tokens":312,"output_tokens":48}}
```

## Errors
- 401 invalid key
- 422 validation (body names offending field)
- 429 rate limit / 529 overloaded -> exponential backoff, honor `retry-after`. SDKs retry by default.

## Operational notes
- Parallel: all questions see same state, evaluated independently in one call. Extra questions ~ free latency, cheap tokens.
- Context: 64k state + all questions; 32k state + longest single question.
- Output tokens free (too cheap to meter).
- No type errors by construction; can't hallucinate strings (no strings).
- Pin versioned ID if you tuned thresholds against it; alias can move.
