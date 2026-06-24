# ShoulderAngels — Integration Plan

How ShoulderAngels plugs into the wider AutoProjects / Team Brain ecosystem,
and how to embed it in your own pipelines.

## 1. Role in the Organism

ShoulderAngels is a **DEV/BUILD biome** tool. Its job is *deliberate choice*:
at any fork in a build, it forces a structured safe-vs-bold comparison instead
of letting the first idea win by default. It is intentionally small, stdlib-only,
and composable — one decision primitive other tools can call.

```
            ┌─────────────────────────────────────────────┐
   task ───▶│ ShoulderAngels.propose()  → {safe, bold}     │
            │ ShoulderAngels.run(choice) → forecast + log  │
            └───────────────┬─────────────────────────────┘
                            ▼
                  ~/.shoulderangels/history.json   (decision ledger)
```

## 2. Integration surfaces

### a) CLI (shell / CI)
Deterministic, non-interactive via `--choose ... --json`. Pipe the JSON into
`jq`, a build script, or a GitHub Action step output.

```bash
choice=$(shoulderangels "$GOAL" --choose safe --json | jq -r '.chosen_path')
```

### b) Library (Python)
`from shoulderangels import ShoulderAngels`. Inject a `client` (any object with
`.complete(prompt, system="")`) and/or a `chooser` callback. This is how the
Organism's orchestrator drives it without a TTY.

### c) Agent tool
The `LLMClient` shape (`complete(prompt, system)`) matches every other Organism
tool, so a swarm controller can share one client/transport across tools.

## 3. Shared LLM contract

All Organism tools expose the same core so they interoperate:

```python
class LLMClient:
    def complete(self, prompt: str, system: str = "") -> str: ...
```

Anything implementing that Protocol is a drop-in (local model, gateway,
recorded fixture). `extract_json()` is the shared, defensive parser for
structured model output.

## 4. Wiring into Team Brain / BCH

1. **As a pre-commit gate** — before a risky refactor, run with `--choose both`
   and attach the JSON to the PR description as a decision record.
2. **As a Synapse step** — orchestrator calls `run(target, choice=...)` and
   posts `chosen_path` + `predicted_outcomes` to the channel.
3. **As an audit ledger** — `history.json` is an append-only record of forks
   taken; ship it to MEMORY_CORE for longitudinal review.

## 5. Configuration

| Setting            | Source                          | Default            |
|--------------------|---------------------------------|--------------------|
| API key            | `ANTHROPIC_API_KEY`             | (required)         |
| Model              | `--model` / `ANTHROPIC_MODEL`   | `claude-haiku-4-5` |
| Max tokens         | `--max-tokens`                  | 1024               |
| History location   | `ShoulderAngels(store=...)`     | `~/.shoulderangels/history.json` |
| Timeout / retries  | `LLMClient(timeout=, max_retries=)` | 60s / 3        |

## 6. Operational notes

- **Cost**: two model calls per single-path run (propose + forecast); three for
  `--choose both`. Keep `--max-tokens` modest for cheap decisions.
- **Determinism**: not deterministic by design (it's advisory). Pin a model and
  log `history.json` if you need reproducibility of *what was decided*.
- **Safety**: no code is executed and nothing is written outside the history
  file. Secrets are read from env only and never logged.

## 7. Roadmap hooks

- Add a third "pragmatic" angel (config-driven number of voices).
- Pluggable transports (OpenAI-compatible gateway) behind the same `complete()`.
- `--explain` mode that surfaces why each path got its risk/effort labels.
