"""Tests for ShoulderAngels.

The embedded LLM is always mocked here: the suite is deterministic, free, and
offline. A single live end-to-end smoke test lives outside pytest (see
EXAMPLES.md / `python shoulderangels.py "..." --json`).
"""
from __future__ import annotations

import hashlib
import inspect
import json
import sys
from pathlib import Path

import pytest

from shoulderangels import (
    AnthropicClient,
    CallableClient,
    CommandClient,
    Completer,
    LLMClient,
    LLMError,
    ShoulderAngels,
    extract_json,
    main,
)

FAKE_COMPLETER = Path(__file__).resolve().parent / "examples" / "fake_completer.py"

SAFE_BOLD = json.dumps(
    {
        "safe": {"description": "Refactor incrementally", "effort": "low",
                 "risk": "low", "upside": "stable"},
        "bold": {"description": "Rewrite in Rust", "effort": "high",
                 "risk": "high", "upside": "10x perf"},
    }
)


class FakeClient:
    """Stand-in for LLMClient that returns scripted responses, no network."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def complete(self, prompt, system=""):
        self.calls.append((prompt, system))
        return self._responses.pop(0) if self._responses else "{}"


def make_tool(tmp_path, responses):
    return ShoulderAngels(store=tmp_path / "h.json", client=FakeClient(responses))


# -- structural contract (kept from the scaffold) --------------------------- #
def test_has_engine():
    t = ShoulderAngels(client=FakeClient([]))
    assert hasattr(t, "run") and hasattr(t, "_ask")


def test_embeds_llm():
    src = inspect.getsource(ShoulderAngels._ask)
    assert "complete" in src, "core mechanism must call the embedded LLM"


# -- JSON extraction -------------------------------------------------------- #
@pytest.mark.parametrize(
    "text,expected",
    [
        ('{"a": 1}', {"a": 1}),
        ('```json\n{"a": 2}\n```', {"a": 2}),
        ('Here you go:\n{"a": 3}\nThanks!', {"a": 3}),
        ("[1, 2, 3]", [1, 2, 3]),
    ],
)
def test_extract_json_variants(text, expected):
    assert extract_json(text) == expected


def test_extract_json_raises_on_garbage():
    with pytest.raises(ValueError):
        extract_json("no json here at all")


# -- proposal normalization ------------------------------------------------- #
def test_propose_parses_both_paths(tmp_path):
    tool = make_tool(tmp_path, [SAFE_BOLD])
    strategies = tool.propose("ship a feature")
    assert strategies["safe"]["description"] == "Refactor incrementally"
    assert strategies["bold"]["risk"] == "high"


def test_propose_fills_defaults_on_garbage(tmp_path):
    tool = make_tool(tmp_path, ["totally not json"])
    strategies = tool.propose("x")
    assert set(strategies) == {"safe", "bold"}
    assert strategies["safe"]["effort"] == "unknown"


# -- run / choice ----------------------------------------------------------- #
def test_run_safe_default_is_noninteractive(tmp_path):
    tool = make_tool(tmp_path, [SAFE_BOLD, "outcome text"])
    result = tool.run("task")
    assert result["chosen_path"] == "safe"
    assert "safe" in result["predicted_outcomes"]


def test_run_both_forecasts_each(tmp_path):
    tool = make_tool(tmp_path, [SAFE_BOLD, "safe outcome", "bold outcome"])
    result = tool.run("task", choice="both")
    assert set(result["predicted_outcomes"]) == {"safe", "bold"}


def test_run_invalid_choice_falls_back_to_safe(tmp_path):
    tool = make_tool(tmp_path, [SAFE_BOLD, "outcome"])
    result = tool.run("task", choice="banana")
    assert result["chosen_path"] == "safe"


def test_chooser_is_used_when_no_choice(tmp_path):
    tool = make_tool(tmp_path, [SAFE_BOLD, "outcome"])
    result = tool.run("task", chooser=lambda s: "bold")
    assert result["chosen_path"] == "bold"


# -- target coercion -------------------------------------------------------- #
def test_coerce_target_reads_file(tmp_path):
    f = tmp_path / "task.txt"
    f.write_text("build the thing", encoding="utf-8")
    assert ShoulderAngels._coerce_target(str(f)) == "build the thing"


def test_coerce_target_accepts_dict():
    assert ShoulderAngels._coerce_target({"task": "do x"}) == "do x"


def test_run_file_subject_digest_is_file_bytes_not_stripped_text(tmp_path):
    """SA2 gap: size+sha must be of the file bytes, never the stripped prompt."""
    f = tmp_path / "task.md"
    raw = b"build the thing\n\n"
    f.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    tool = make_tool(tmp_path, [SAFE_BOLD, "outcome"])
    result = tool.run(str(f), choice="safe", store=False)
    assert result["target"] == "build the thing"
    assert result["subject_kind"] == "file"
    assert result["subject_size"] == len(raw)
    assert result["subject_sha256"] == digest
    assert result["subject_sha16"] == digest[:16]
    assert result["subject_path"].endswith("task.md")


def test_run_text_subject_digest_is_utf8_bytes(tmp_path):
    text = "plain task"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    tool = make_tool(tmp_path, [SAFE_BOLD, "outcome"])
    result = tool.run(text, choice="safe", store=False)
    assert result["subject_kind"] == "text"
    assert result["subject_size"] == len(text.encode("utf-8"))
    assert result["subject_sha256"] == digest
    assert "subject_path" not in result


# -- history persistence ---------------------------------------------------- #
def test_history_is_recorded_and_loaded(tmp_path):
    tool = make_tool(tmp_path, [SAFE_BOLD, "outcome"])
    tool.run("first task")
    assert len(tool.load_history()) == 1
    assert tool.load_history()[0]["target"] == "first task"


def test_no_store_skips_history(tmp_path):
    tool = make_tool(tmp_path, [SAFE_BOLD, "outcome"])
    tool.run("task", store=False)
    assert tool.load_history() == []


def test_corrupt_history_returns_empty(tmp_path):
    store = tmp_path / "h.json"
    store.write_text("{not json", encoding="utf-8")
    tool = ShoulderAngels(store=store, client=FakeClient([]))
    assert tool.load_history() == []


# -- LLM client error handling (no network) --------------------------------- #
def test_api_key_missing_raises(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    client = LLMClient(api_key=None)
    with pytest.raises(LLMError):
        _ = client.api_key


def test_extract_text_rejects_empty():
    with pytest.raises(LLMError):
        LLMClient._extract_text({"content": []})


# -- CLI -------------------------------------------------------------------- #
def test_cli_history_empty(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert main(["--history"]) == 0
    assert "0 decision" in capsys.readouterr().out


def test_cli_requires_target(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    with pytest.raises(SystemExit):
        main([])


# -- Completer contract / public record ------------------------------------ #
def test_anthropic_alias_and_protocol():
    assert AnthropicClient is LLMClient
    assert isinstance(LLMClient(api_key="x"), Completer)
    assert isinstance(CallableClient(lambda p, s: "ok"), Completer)


def test_record_appends_without_propose(tmp_path):
    tool = ShoulderAngels(store=tmp_path / "h.json", client=FakeClient([]))
    tool.record({"target": "hosted decision", "chosen_path": "bold"})
    history = tool.load_history()
    assert len(history) == 1
    assert history[0]["target"] == "hosted decision"
    assert history[0]["chosen_path"] == "bold"


def test_record_rejects_non_dict(tmp_path):
    tool = ShoulderAngels(store=tmp_path / "h.json", client=FakeClient([]))
    with pytest.raises(TypeError):
        tool.record("not a result")  # type: ignore[arg-type]


# -- CallableClient -------------------------------------------------------- #
def test_callable_client_forwards_prompt_and_system():
    seen = {}

    def fn(prompt, system):
        seen["prompt"] = prompt
        seen["system"] = system
        return "hello from host"

    client = CallableClient(fn)
    assert client.complete("p", system="s") == "hello from host"
    assert seen == {"prompt": "p", "system": "s"}


def test_callable_client_empty_raises():
    with pytest.raises(LLMError, match="empty"):
        CallableClient(lambda p, s: "   ").complete("x")


def test_run_with_callable_client(tmp_path):
    replies = [SAFE_BOLD, "callable forecast"]

    def fn(prompt, system):
        return replies.pop(0)

    tool = ShoulderAngels(store=tmp_path / "h.json", client=CallableClient(fn))
    result = tool.run("task", choice="safe")
    assert result["predicted_outcomes"]["safe"] == "callable forecast"


# -- CommandClient (scripted subprocess, no network) ----------------------- #
def test_command_client_json_text(tmp_path):
    script = tmp_path / "ok.py"
    script.write_text(
        "import json,sys\n"
        "req=json.load(sys.stdin)\n"
        "assert 'prompt' in req and 'system' in req\n"
        "json.dump({'text': 'from-json:'+req['prompt']}, sys.stdout)\n",
        encoding="utf-8",
    )
    client = CommandClient([sys.executable, str(script)])
    assert client.complete("hello", system="sys") == "from-json:hello"


def test_command_client_raw_text(tmp_path):
    script = tmp_path / "raw.py"
    script.write_text("import sys; sys.stdout.write('plain text')\n", encoding="utf-8")
    client = CommandClient([sys.executable, str(script)])
    assert client.complete("p") == "plain text"


def test_command_client_nonzero_exit(tmp_path):
    script = tmp_path / "fail.py"
    script.write_text("import sys; sys.stderr.write('boom'); sys.exit(3)\n", encoding="utf-8")
    with pytest.raises(LLMError, match="exited 3"):
        CommandClient([sys.executable, str(script)]).complete("p")


def test_command_client_empty_output(tmp_path):
    script = tmp_path / "empty.py"
    script.write_text("import sys; sys.stdin.read()\n", encoding="utf-8")
    with pytest.raises(LLMError, match="empty"):
        CommandClient([sys.executable, str(script)]).complete("p")


def test_command_client_empty_text_field(tmp_path):
    script = tmp_path / "empty_text.py"
    script.write_text("print('{\"text\": \"  \"}')\n", encoding="utf-8")
    with pytest.raises(LLMError, match="empty"):
        CommandClient([sys.executable, str(script)]).complete("p")


def test_command_client_timeout(tmp_path):
    script = tmp_path / "slow.py"
    script.write_text("import time; time.sleep(30)\n", encoding="utf-8")
    with pytest.raises(LLMError, match="timed out"):
        CommandClient([sys.executable, str(script)], timeout=0.2).complete("p")


def test_command_client_empty_command_raises():
    with pytest.raises(LLMError, match="empty"):
        CommandClient("   ")


def test_command_client_missing_binary():
    with pytest.raises(LLMError, match="failed to run"):
        CommandClient(["/definitely/not/a/real/completer-bin"]).complete("p")


# -- CLI command backend --------------------------------------------------- #
def _isolate_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("SHOULDERANGELS_COMPLETE_CMD", raising=False)


def test_cli_command_backend_e2e(tmp_path, monkeypatch, capsys):
    _isolate_home(monkeypatch, tmp_path)
    cmd = f"{sys.executable} {FAKE_COMPLETER}"
    rc = main([
        "ship a feature",
        "--choose", "safe",
        "--json",
        "--backend", "command",
        "--complete-cmd", cmd,
        "--no-store",
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["chosen_path"] == "safe"
    assert out["strategy"]["description"] == "Ship the smallest reversible change"
    assert "The change ships" in out["predicted_outcomes"]["safe"]


def test_cli_command_backend_env_complete_cmd(tmp_path, monkeypatch, capsys):
    _isolate_home(monkeypatch, tmp_path)
    monkeypatch.setenv("SHOULDERANGELS_BACKEND", "command")
    monkeypatch.setenv(
        "SHOULDERANGELS_COMPLETE_CMD",
        f"{sys.executable} {FAKE_COMPLETER}",
    )
    rc = main(["env-driven", "--choose", "bold", "--json", "--no-store"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["chosen_path"] == "bold"


def test_cli_command_backend_requires_cmd(tmp_path, monkeypatch):
    _isolate_home(monkeypatch, tmp_path)
    with pytest.raises(SystemExit):
        main(["task", "--backend", "command", "--choose", "safe"])


def test_cli_command_backend_no_anthropic_key(tmp_path, monkeypatch, capsys):
    _isolate_home(monkeypatch, tmp_path)
    rc = main([
        "no key",
        "--choose", "safe",
        "--json",
        "--backend", "command",
        "--complete-cmd", f"{sys.executable} {FAKE_COMPLETER}",
        "--no-store",
    ])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["target"] == "no key"

