# ShoulderAngels — Examples

Worked, copy-pasteable examples. Each assumes `ANTHROPIC_API_KEY` is exported.
Unit tests mock the model (no cost); the examples below make **real** calls.

---

## 1. Interactive (the intended human flow)

```bash
shoulderangels "Add rate limiting to a Flask API"
```

You'll see both paths and a prompt:

```
🔰 SAFE PATH: Use Flask-Limiter with a Redis backend...
   effort=low risk=low upside=Battle-tested, minimal code changes

⚡ BOLD PATH: Hand-roll a sliding-window limiter in middleware...
   effort=high risk=high upside=Zero deps, fully customizable

Choose [safe/bold/both]: bold

✅ Chosen path: bold
— Predicted outcomes (bold) —
1. ...
2. ...
3. ...
```

---

## 2. Non-interactive / pipeline (the CI flow)

Force a path so nothing ever blocks:

```bash
shoulderangels "Migrate the monolith to microservices" --choose safe --json
```

```json
{
  "target": "Migrate the monolith to microservices",
  "chosen_path": "safe",
  "strategy": {
    "description": "Strangler-fig: extract one bounded context at a time...",
    "effort": "medium",
    "risk": "low",
    "upside": "Incremental, reversible, low blast radius"
  },
  "predicted_outcomes": {
    "safe": "1. ...\n2. ...\n3. ..."
  },
  "safe_risk": "low",
  "bold_upside": "...",
  "timestamp": "2026-06-24T15:40:10.595892+00:00"
}
```

---

## 3. Forecast BOTH paths

Useful when you want the contrast on paper before deciding:

```bash
shoulderangels "Replace REST with GraphQL" --choose both --json | jq '.predicted_outcomes'
```

---

## 4. Read the task from a file

```bash
cat > task.md <<'EOF'
We need to cut cold-start latency on our Lambda functions below 300ms.
Constraints: Python runtime, no container images, keep deploy under 2 min.
EOF

shoulderangels task.md --choose safe --json
```

The tool detects that the argument is an existing file and uses its contents.

---

## 5. Use as a library

```python
from shoulderangels import ShoulderAngels

tool = ShoulderAngels()
result = tool.run("Introduce feature flags", choice="bold")
print(result["strategy"]["description"])
print(result["predicted_outcomes"]["bold"])
```

Inject a custom chooser (e.g. a GUI or a policy function):

```python
def policy(strategies):
    # auto-pick bold only when its risk is acceptable
    return "bold" if strategies["bold"]["risk"] != "high" else "safe"

tool.run("Adopt event sourcing", chooser=policy)
```

Swap in a fake client for tests (no network, no cost):

```python
from shoulderangels import ShoulderAngels

class Fake:
    def complete(self, prompt, system=""):
        return '{"safe": {"description": "x"}, "bold": {"description": "y"}}'

tool = ShoulderAngels(client=Fake())
assert tool.propose("anything")["safe"]["description"] == "x"
```

---

## 6. Decision history

Every non-`--no-store` run is appended to `~/.shoulderangels/history.json`.

```bash
shoulderangels --history
# 3 decision(s) recorded
#   • [safe] Add rate limiting to a Flask API
#   • [bold] Migrate the monolith to microservices
#   • [both] Replace REST with GraphQL

shoulderangels --history --json | jq '.[].chosen_path'
```

---

## 7. Override model / token budget

```bash
shoulderangels "Design a plugin system" \
  --model claude-haiku-4-5 \
  --max-tokens 2048 \
  --choose both --json
```

---

## Error handling you can rely on

| Situation                  | What happens                                            |
|----------------------------|---------------------------------------------------------|
| `ANTHROPIC_API_KEY` unset  | exits 1 with a clear "export your key" message          |
| Network down / timeout     | retries with backoff, then exits 1 with the reason      |
| 429 / 5xx from the API     | retried up to 3× with backoff                           |
| Model returns non-JSON     | gracefully normalized; you still get safe/bold objects  |
| Piped input, no `--choose` | defaults to `safe`, never hangs waiting on stdin        |
