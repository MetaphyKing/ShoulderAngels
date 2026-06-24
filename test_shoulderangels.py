"""Tests for ShoulderAngels.

The embedded LLM is always mocked here: the suite is deterministic, free, and
offline. A single live end-to-end smoke test lives outside pytest (see
EXAMPLES.md / `python shoulderangels.py "..." --json`).
"""
from __future__ import annotations

import inspect
import json

import pytest

from shoulderangels import (
    LLMClient,
    LLMError,
    ShoulderAngels,
    extract_json,
    main,
)

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
