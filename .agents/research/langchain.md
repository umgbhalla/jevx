# LangChain harness notes (from https://docs.langchain.com/oss/python/integrations/providers/typesafe + blog)

## TypeSafeClassifier
- `Runnable`. `questions={id: Noul|Choice|Score}` fixed at construction, `invoke(state)` per call.
- Response: `response.nouls[id].noul`, `response.choices[id].{choice,probabilities,confidence}`, `response.scores[id].{score,legend,probabilities,confidence}` + `model`, `usage`, `request_id`.
- Traced in LangSmith.

## ModelRouterMiddleware
```python
router = ModelRouterMiddleware(
    choices={
        "fast": ModelChoice(model="openai:gpt-5.6-terra", criteria="Direct lookups, extraction..."),
        "powerful": ModelChoice(model="openai:gpt-6-astra", criteria="Architecture, high-stakes..."),
    },
    instructions="Choose the least costly model that can complete the task safely.",
)
agent = create_agent("openai:gpt-5.6-terra", middleware=[router])
# result["model_route"].choice + probs in state
```
- Hook: `before_agent` + `wrap_model_call`. Classifies latest human message.

## AutoModeMiddleware
```python
agent = create_agent("openai:gpt-6-astra", tools=[delete_all_backups],
    middleware=[AutoModeMiddleware(tools=[delete_all_backups])])
```
- Hook: `wrap_tool_call`. Noul risk/insufficient-authorization check. Risky -> error ToolMessage, tool never runs.
- Only listed tools classified (names or objects). Override `instructions` or `criteria=NoulCriteria(true=..., false=...)`.
- Refuses; does NOT request approval. Pair with human-in-the-loop middleware for approvals.
- WARNING: don't put secrets in state sent to TypeSafe.

## Custom middleware sketch
```python
class TriageMiddleware(AgentMiddleware[TriageState]):
    def __init__(self): self.classifier = TypeSafeClassifier(questions={"triage": Choice(...)})
    def before_agent(self, state, runtime): return {"triage": self.classifier.invoke(state["messages"]).choices["triage"]}
```
- `before_model` to reclassify after each tool result, `wrap_tool_call` to gate actions.
