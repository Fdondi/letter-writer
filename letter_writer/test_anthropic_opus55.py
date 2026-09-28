"""Claude Opus 5.5 catalog price and request shape."""

import pytest

from letter_writer.clients.anthropic import ClaudeClient, anthropic_json_request_kwargs
from letter_writer.clients.base import BaseClient, ModelRole
from letter_writer.clients.prompt_cache import anthropic_min_cache_tokens


def _client() -> ClaudeClient:
    client = ClaudeClient.__new__(ClaudeClient)
    BaseClient.__init__(client)
    return client


def test_autocomplete_plan_uses_opus_55_list_price():
    client = _client()
    assert client.get_model_for_role(ModelRole.AUTOCOMPLETE_PLAN) == "claude-opus-5-5"
    costs = client.get_model_cost("claude-opus-5-5")
    assert costs["input"] == 4.0
    assert costs["output"] == 20.0
    assert costs["input_cached_mult"] == 0.05


def test_opus_55_cache_read_is_five_percent_of_input():
    client = _client()
    client.track_cost(
        "claude-opus-5-5",
        input_tokens=1_000_000,
        output_tokens=0,
        cache_read_tokens=1_000_000,
    )
    assert client.total_cost == 0.20

    older = _client()
    older.track_cost(
        "claude-opus-4-7",
        input_tokens=1_000_000,
        output_tokens=0,
        cache_read_tokens=1_000_000,
    )
    assert older.total_cost == 0.50


def test_opus_55_thinking_is_adaptive():
    kwargs = ClaudeClient._thinking_request_kwargs(
        "claude-opus-5-5",
        True,
        8000,
        {"effort": "high"},
    )
    assert kwargs["thinking"] == {"type": "adaptive"}
    assert kwargs["output_config"] == {"effort": "high"}
    assert ClaudeClient._thinking_request_kwargs("claude-opus-5-5", False, 8000, {}) == {}
    assert anthropic_min_cache_tokens("claude-opus-5-5") == 512
    assert anthropic_min_cache_tokens("claude-opus-4-7-20250514") == 2048
    assert anthropic_min_cache_tokens("claude-sonnet-4-6") == 1024


def test_opus_55_json_uses_output_config_format():
    schema = {
        "type": "object",
        "properties": {"draft_letter": {"type": "string"}},
        "required": ["draft_letter"],
    }
    kwargs = anthropic_json_request_kwargs("claude-opus-5-5", schema, "draft_letter_output")
    fmt = kwargs["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["schema"]["additionalProperties"] is False
    assert "tools" not in kwargs


def test_supported_models_use_output_config_format():
    schema = {"type": "object", "properties": {"draft_letter": {"type": "string"}}}
    for model in ("claude-opus-5-5", "claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5", "claude-fable-5"):
        kwargs = anthropic_json_request_kwargs(model, schema, "draft_letter_output")
        assert kwargs["output_config"]["format"]["type"] == "json_schema"
        assert "tools" not in kwargs


def test_map_schema_is_rejected_on_structured_output_models():
    schema = {
        "type": "object",
        "properties": {
            "votes": {
                "type": "object",
                "additionalProperties": {"type": "string"},
            }
        },
    }
    for model in ("claude-opus-5-5", "claude-haiku-4-5", "claude-sonnet-4-6"):
        with pytest.raises(ValueError, match="output_config.format"):
            anthropic_json_request_kwargs(model, schema, "votes")
