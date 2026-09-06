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
The `Completer` shape (`complete(prompt, system)`) matches every other Organism
tool, so a swarm controller can share one client/transport across tools.
Anthropic is optional — inject `CallableClient`, `CommandClient`, or any duck.

## 3. Shared LLM contract

All Organism tools expose the same core so they interoperate:

```python
class Completer(Protocol):
    def complete(self, prompt: str, system: str = "") -> str: ...
```

Shipped backends:

| Backend | Class | When to use |
|---------|-------|-------------|
| Anthropic Messages API | `LLMClient` / `AnthropicClient` | default CLI; needs `ANTHROPIC_API_KEY` |
| Host callable | `CallableClient` | in-process agent / Grok Bot / tests |
| External command | `CommandClient` | CLI `--backend command`; stdin/stdout JSON |

Anything implementing that Protocol is a drop-in (local model, gateway,
recorded fixture). `extract_json()` is the shared, defensive parser for
structured model output.

**Command protocol:** the child reads one JSON object
`{"prompt": "...", "system": "..."}` on stdin and writes either
`{"text": "..."}` or raw text on stdout. Non-zero exit, empty output, or
timeout → `LLMError`.

## 3b. Grok Bot / agent host

The Python tool owns schema validation, choose/forecast orchestration, and
history. The host LLM only supplies completions — **no Anthropic key**.

**In-process (library):** wrap the host's generate function:

```python
from shoulderangels import ShoulderAngels, CallableClient

def host_complete(prompt: str, system: str = "") -> str:
    return grok_or_subagent.generate(prompt, system=system)

tool = ShoulderAngels(client=CallableClient(host_complete), store=history_path)
result = tool.run(task, choice="safe")          # propose + forecast + record
# or persist a decision the host already finished:
tool.record(result)
```

**CLI (subprocess):** point `--complete-cmd` at a shim that talks to the host:

```bash
shoulderangels "Add rate limiting" --choose safe --json \
  --backend command \
  --complete-cmd "python examples/fake_completer.py"
# or: export SHOULDERANGELS_BACKEND=command
#      export SHOULDERANGELS_COMPLETE_CMD='python /path/to/host_completer.py'
```

A production Grok / Cursor shim uses the same stdin/stdout contract as
`examples/fake_completer.py`, replacing the canned JSON with a live model call.

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
| Backend            | `--backend` / `SHOULDERANGELS_BACKEND` | `anthropic` |
| Completer command  | `--complete-cmd` / `SHOULDERANGELS_COMPLETE_CMD` | (required if backend=`command`) |
| API key            | `ANTHROPIC_API_KEY`             | required **only** for `--backend anthropic` |
| Model              | `--model` / `ANTHROPIC_MODEL`   | `claude-haiku-4-5` |
| Max tokens         | `--max-tokens`                  | 1024               |
| History location   | `ShoulderAngels(store=...)`     | `~/.shoulderangels/history.json` |
| Timeout / retries  | `LLMClient` / `CommandClient(timeout=)` | 60s / 3 (Anthropic) |

## 6. Operational notes

- **Cost**: two model calls per single-path run (propose + forecast); three for
  `--choose both`. Keep `--max-tokens` modest for cheap decisions.
- **Determinism**: not deterministic by design (it's advisory). Pin a model and
  log `history.json` if you need reproducibility of *what was decided*.
- **Safety**: no code is executed and nothing is written outside the history
  file. Secrets are read from env only and never logged.

## 7. Roadmap hooks

- Add a third "pragmatic" angel (config-driven number of voices).
- `--explain` mode that surfaces why each path got its risk/effort labels.
- Extra HTTP gateways can sit behind `CallableClient` / `CommandClient`
  without new runtime dependencies.
