"""Gemma 4, Claude Sonnet 5.5, Gemini JSON Schema pass-through, and superseded-model grouping."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from letter_writer.clients.anthropic import ClaudeClient, anthropic_json_request_kwargs
from letter_writer.clients.base import BaseClient, ModelRole
from letter_writer.clients.deepseeek import DeepSeekClient
from letter_writer.clients.gemini import GeminiClient
from letter_writer.clients.model_override import thinking_config_for_vendor
from letter_writer.clients.prompt_cache import anthropic_min_cache_tokens
from letter_writer.cost_tracker import _validated_successor, get_all_model_pricing

_CLIENTS_DIR = Path(__file__).resolve().parent / "clients"

# Later model costs the same or less on both input and output.
_EXPECTED_SUPERSEDED = {
    "claude-sonnet-4-5": "claude-sonnet-5-5",
    "claude-sonnet-4-6": "claude-sonnet-5-5",
    "claude-sonnet-5": "claude-sonnet-5-5",
    "claude-opus-4-5": "claude-opus-5-5",
    "claude-opus-4-6": "claude-opus-5-5",
    "claude-opus-4-7": "claude-opus-5-5",
    "claude-opus-4-8": "claude-opus-5-5",
    "claude-fable-5": "claude-fable-5-1",
    "gpt-5.6-luna": "gpt-6-luna",
    "gpt-5.6-terra": "gpt-6.1-sol",
    "gpt-5.6-sol": "gpt-6.1-sol",
    "gpt-5.5": "gpt-6.1-sol",
    "gpt-6-sol": "gpt-6.1-sol",
    "gpt-5.4-nano": "gpt-6-luna",
    "gpt-5.4-pro": "gpt-5.5-pro",
    "grok-4.6": "grok-4.7",
    "grok-4.5": "grok-4.7",
    "grok-4.20-0309-non-reasoning": "grok-4.3",
    "grok-4.20-0309-reasoning": "grok-4.3",
    "gemini-3.5-flash": "gemini-3.8-flash",
}

# Successor costs more on at least one rate, so the older model stays top level.
_STAYS_TOP_LEVEL = (
    "claude-sonnet-5-5",
    "claude-fable-5-1",
    "gpt-6.1-sol",
    "gpt-5.5-pro",
    "gpt-6-astra",
    "gpt-4o-mini",
    "grok-4.7",
    "grok-4.3",
    "grok-4.20-multi-agent-0309",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-3-flash-preview",
    "mistral-medium-3-5",
    "mistral-large-latest",
    "mistral-small-latest",
    "deepseek-flash",
    "deepseek-v4-pro",
)


def _bare(cls):
    client = cls.__new__(cls)
    BaseClient.__init__(client)
    return client


def _picker_by_id():
    return {m["id"]: m for models in get_all_model_pricing().values() for m in models}


def _gemini_capture(client):
    usage = SimpleNamespace(
        prompt_token_count=10, candidates_token_count=5, thoughts_token_count=0, cached_content_token_count=0
    )
    captured = {}

    def _generate_content(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(usage_metadata=usage, text="{}", candidates=[])

    client.client = SimpleNamespace(models=SimpleNamespace(generate_content=_generate_content))
    return captured


def test_gemini_sends_additional_properties_via_response_json_schema():
    client = _bare(GeminiClient)
    captured = _gemini_capture(client)
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "minLength": 1, "maxLength": 20},
            "votes": {"type": "object", "additionalProperties": {"type": "string"}},
        },
        "required": ["name"],
        "additionalProperties": False,
    }
    client.call(
        "gemini-2.5-flash-lite",
        "system",
        ["user"],
        response_format={"type": "json_schema", "json_schema": {"name": "x", "schema": schema}},
    )
    config = captured["config"]
    assert config.response_schema is None
    sent = config.response_json_schema
    assert sent["additionalProperties"] is False
    assert sent["properties"]["votes"]["additionalProperties"] == {"type": "string"}
    assert sent["properties"]["name"] == {"type": "string"}


def test_gemma_catalog_is_free_tier_only_without_search():
    by_id = _picker_by_id()
    for model in ("gemma-4-31b-it", "gemma-4-26b-a4b-it"):
        entry = by_id[model]
        assert entry["vendor_key"] == "gemini"
        assert entry["input"] == 0.0
        assert entry["output"] == 0.0
        assert entry["free_tier_only"] is True
        assert entry["supports_search"] is False
        assert entry["reasoning_efforts"] == ["Minimal", "High"]
        assert entry["superseded_by"] is None
    assert by_id["gemini-2.5-flash-lite"]["free_tier_only"] is False


def test_gemma_minimal_thinking_level_reaches_api():
    assert thinking_config_for_vendor("gemini", "minimal") == {"thinking_level": "Minimal"}
    client = _bare(GeminiClient)
    captured = _gemini_capture(client)
    client.call("gemma-4-26b-a4b-it@Minimal", "system", ["user"])
    assert captured["model"] == "gemma-4-26b-a4b-it"
    assert captured["config"].thinking_config.thinking_level.value == "MINIMAL"
    assert client.total_cost == 0.0


def test_sonnet_55_price_cache_and_json():
    client = _bare(ClaudeClient)
    costs = client.get_model_cost("claude-sonnet-5-5")
    assert costs["input"] == 2.0
    assert costs["output"] == 10.0
    assert costs["input_cached_mult"] == 0.10
    client.track_cost("claude-sonnet-5-5", input_tokens=1_000_000, output_tokens=0, cache_read_tokens=1_000_000)
    assert client.total_cost == pytest.approx(0.20)
    assert anthropic_min_cache_tokens("claude-sonnet-5-5") == 512
    assert anthropic_min_cache_tokens("claude-sonnet-5") == 1024
    schema = {"type": "object", "properties": {"draft_letter": {"type": "string"}}}
    kwargs = anthropic_json_request_kwargs("claude-sonnet-5-5", schema, "draft_letter_output")
    assert kwargs["output_config"]["format"]["type"] == "json_schema"


def test_sonnet_55_thinking_on_is_adaptive_and_off_is_between_tools():
    on = ClaudeClient._thinking_request_kwargs("claude-sonnet-5-5", True, 8000, {"effort": "xhigh"})
    assert on == {"thinking": {"type": "adaptive"}, "output_config": {"effort": "xhigh"}}
    off = ClaudeClient._thinking_request_kwargs("claude-sonnet-5-5", False, 8000, {})
    assert off == {"thinking": {"type": "between_tools"}}
    assert ClaudeClient._thinking_request_kwargs("claude-sonnet-5", False, 8000, {}) == {}
    assert ClaudeClient._thinking_request_kwargs("claude-opus-5-5", False, 8000, {}) == {}
    assert _picker_by_id()["claude-sonnet-5-5"]["reasoning_efforts"] == [
        "off", "low", "medium", "high", "xhigh", "max",
    ]


def test_anthropic_sonnet_roles_moved_to_sonnet_55():
    client = _bare(ClaudeClient)
    for role in (
        ModelRole.RAG_RANKER,
        ModelRole.COMPANY_RESEARCH,
        ModelRole.LETTER_PLAN,
        ModelRole.LETTER_DRAFT,
        ModelRole.LETTER_REFINE,
    ):
        assert client.get_model_for_role(role) == "claude-sonnet-5-5"


def test_picker_groups_exactly_the_dominated_models():
    by_id = _picker_by_id()
    superseded = {mid: m["superseded_by"] for mid, m in by_id.items() if m["superseded_by"]}
    assert superseded == _EXPECTED_SUPERSEDED
    for model in _STAYS_TOP_LEVEL:
        assert by_id[model]["superseded_by"] is None


def test_every_catalog_superseded_claim_is_same_price_or_cheaper():
    for path in sorted(_CLIENTS_DIR.glob("*.json")):
        models = json.loads(path.read_text(encoding="utf-8")).get("models", {})
        for model_id, cfg in models.items():
            if isinstance(cfg, dict) and cfg.get("superseded_by"):
                assert _validated_successor(path.stem, model_id, cfg, models) == cfg["superseded_by"], (
                    f"{path.name}: {model_id} -> {cfg['superseded_by']} costs more on input or output"
                )


def test_role_defaults_never_use_superseded_models():
    for path in sorted(_CLIENTS_DIR.glob("*.json")):
        cfg = json.loads(path.read_text(encoding="utf-8"))
        models = cfg.get("models", {})
        for role, entry in (cfg.get("roles") or {}).items():
            model = entry.get("model") if isinstance(entry, dict) else entry
            assert not (models.get(model) or {}).get("superseded_by"), f"{path.name}: {role} uses {model}"


def test_deepseek_v41_flash_price_effort_and_cache_hits():
    by_id = _picker_by_id()
    flash = by_id["deepseek-flash"]
    pro = by_id["deepseek-v4-pro"]
    assert flash["input"] == 0.15
    assert flash["output"] == 0.60
    assert pro["input"] == 0.66
    assert pro["output"] == 1.98
    assert flash["reasoning_efforts"] == ["none", "low", "high", "max"]
    assert "deepseek-chat" not in by_id
    assert "deepseek-v4-flash" not in by_id

    client = _bare(DeepSeekClient)
    captured = {}
    usage = SimpleNamespace(
        prompt_tokens=100, completion_tokens=20, prompt_cache_hit_tokens=40
    )

    def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            usage=usage,
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
        )

    client.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    client.call("deepseek-flash@low", "system", ["user"])
    assert captured["model"] == "deepseek-flash"
    assert captured["reasoning_effort"] == "low"
    assert captured["extra_body"] == {"thinking": {"type": "enabled"}}
    assert client.total_cached_tokens == 40
    assert client.total_cost == pytest.approx((60 / 1_000_000) * 0.15 + (40 / 1_000_000) * 0.15 * 0.02 + (20 / 1_000_000) * 0.60)

    captured.clear()
    client.call("deepseek-flash@none", "system", ["user"])
    assert "reasoning_effort" not in captured
    assert captured["extra_body"] == {"thinking": {"type": "disabled"}}


def test_mistral_keeps_large_medium_small_at_current_prices():
    by_id = _picker_by_id()
    assert by_id["mistral-small-latest"]["input"] == 0.15
    assert by_id["mistral-small-latest"]["output"] == 0.60
    assert by_id["mistral-medium-3-5"]["input"] == 1.50
    assert by_id["mistral-medium-3-5"]["output"] == 7.50
    assert by_id["mistral-large-latest"]["input"] == 0.50
    assert by_id["mistral-large-latest"]["output"] == 1.50
    assert by_id["mistral-medium-3-5"]["superseded_by"] is None
    assert "mistral-small-2506" not in by_id
    assert "open-mixtral-8x7b" not in by_id


def test_unbacked_superseded_claim_is_ignored():
    models = {
        "old": {"input": 2.0, "output": 10.0, "superseded_by": "pricier"},
        "pricier": {"input": 3.0, "output": 8.0},
        "tie": {"input": 2.0, "output": 10.0},
        "sol": {"input": 2.0, "output": 10.0},
    }
    assert _validated_successor("x", "old", models["old"], models) is None
    assert _validated_successor("x", "old", {"input": 1, "output": 1, "superseded_by": "missing"}, models) is None
    assert _validated_successor(
        "x", "old", {"input": 2.0, "output": 10.0, "superseded_by": "tie"}, models
    ) == "tie"
    assert _validated_successor(
        "x", "terra", {"input": 2.0, "output": 12.0, "superseded_by": "sol"}, models
    ) == "sol"
