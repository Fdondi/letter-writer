"""GPT-6, Grok 4.6/4.7 and Gemini 3.8 Flash: catalog prices and request wiring."""

import json
from types import SimpleNamespace

import pytest
from xai_sdk.proto import chat_pb2

from letter_writer.clients.base import BaseClient, ModelRole
from letter_writer.clients.gemini import GeminiClient
from letter_writer.clients.grok import GrokClient, _xai_response_format
from letter_writer.clients.openai import OpenAIClient
from letter_writer.cost_tracker import get_all_model_pricing

_RETIRED_OPENAI = (
    "gpt-4o-search-preview",
    "o1-mini",
    "o1",
    "o3-mini",
    "o4-mini",
    "gpt-4.1-nano",
    "gpt-5",
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-5-pro",
    "o3",
    "o3-pro",
)
_RETIRED_GROK = ("grok-4-1-fast-reasoning", "grok-4-1-fast-non-reasoning")
_RETIRED_GEMINI = ("gemini-3-pro-preview",)


def _bare(cls):
    client = cls.__new__(cls)
    BaseClient.__init__(client)
    return client


def _role_models(client) -> set:
    return {client.get_model_for_role(role) for role in ModelRole if role.value in client.config["roles"]}


def test_gpt6_list_prices():
    client = _bare(OpenAIClient)
    expected = {"gpt-6-astra": (10.0, 50.0), "gpt-6-sol": (2.0, 10.0), "gpt-6-luna": (0.10, 0.50)}
    for model, (inp, out) in expected.items():
        costs = client.get_model_cost(model)
        assert costs["input"] == inp
        assert costs["output"] == out
        assert costs["input_cached_mult"] == 0.10
        assert costs["cache_write_mult"] == 1.25
    sol = client.get_model_cost("gpt-6.1-sol")
    assert sol["input"] == 2.0
    assert sol["output"] == 10.0
    assert sol["input_cached_mult"] == 0.05
    assert sol["cache_write_mult"] == 1.25


def test_gpt6_luna_cache_read_and_write_costs():
    client = _bare(OpenAIClient)
    client.track_cost(
        "gpt-6-luna",
        input_tokens=1_000_000,
        output_tokens=0,
        cached_tokens=500_000,
        cache_write_tokens=500_000,
    )
    # 0.5M reads at 10% + 0.5M writes at 125% of $0.10/1M
    assert client.total_cost == pytest.approx(0.005 + 0.0625)


def test_openai_sends_none_effort_only_where_model_lists_it():
    client = _bare(OpenAIClient)
    assert client._accepts_none_effort("gpt-6-luna")
    assert client._accepts_none_effort("gpt-6-sol")
    assert not client._accepts_none_effort("gpt-6-astra")
    assert not client._accepts_none_effort("gpt-6.1-sol")
    assert not client._accepts_none_effort("gpt-4o")


def test_openai_roles_and_catalog_drop_retired_models():
    client = _bare(OpenAIClient)
    models = client.config["models"]
    for model in _RETIRED_OPENAI:
        assert model not in models
    for model in _role_models(client):
        assert model in models
    assert client.get_model_for_role(ModelRole.EXTRACTION) == "gpt-6-luna"
    assert client.get_thinking_config(ModelRole.EXTRACTION) == {"reasoning_effort": "none"}


def test_grok_46_47_prices_and_cache_discount():
    client = _bare(GrokClient)
    for model in ("grok-4.6", "grok-4.7"):
        costs = client.get_model_cost(model)
        assert costs["input"] == 2.0
        assert costs["output"] == 6.0
        assert costs["input_cached_mult"] == 0.25
    client.track_cost("grok-4.7", input_tokens=1_000_000, output_tokens=0, cached_tokens=1_000_000)
    assert client.total_cost == pytest.approx(0.50)


def test_grok_roles_and_catalog_drop_retired_models():
    client = _bare(GrokClient)
    models = client.config["models"]
    for model in _RETIRED_GROK:
        assert model not in models
    for model in _role_models(client):
        assert model in models
    assert client.get_model_for_role(ModelRole.LETTER_DRAFT) == "grok-4.7"


def test_xai_response_format_mapping():
    schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
    fmt = _xai_response_format({"type": "json_schema", "json_schema": {"name": "x", "schema": schema}})
    assert fmt.format_type == chat_pb2.FormatType.FORMAT_TYPE_JSON_SCHEMA
    assert json.loads(fmt.schema) == schema
    assert _xai_response_format({"type": "json_object"}) == "json_object"
    assert _xai_response_format(None) is None


class _FakeXaiChat:
    def __init__(self, response):
        self.messages = []
        self._response = response

    def append(self, message):
        self.messages.append(message)

    def sample(self):
        return self._response


def test_grok_call_passes_reasoning_effort_structured_output_and_cache_usage():
    client = _bare(GrokClient)
    usage = SimpleNamespace(prompt_tokens=1_000_000, completion_tokens=0, cached_prompt_text_tokens=1_000_000)
    response = SimpleNamespace(usage=usage, content=' {"a": "b"} ', server_side_tool_usage=None)
    captured = {}

    def _create(**kwargs):
        captured.update(kwargs)
        return _FakeXaiChat(response)

    client.client = SimpleNamespace(chat=SimpleNamespace(create=_create))
    schema = {"type": "object", "properties": {"a": {"type": "string"}}}
    out = client.call(
        "grok-4.7@xhigh",
        "system",
        ["user"],
        response_format={"type": "json_schema", "json_schema": {"name": "x", "schema": schema}},
    )
    assert out == '{"a": "b"}'
    assert captured["model"] == "grok-4.7"
    assert captured["reasoning_effort"] == "xhigh"
    assert captured["response_format"].format_type == chat_pb2.FormatType.FORMAT_TYPE_JSON_SCHEMA
    assert client.total_cached_tokens == 1_000_000
    assert client.total_cost == pytest.approx(0.50)


def test_gemini_38_flash_price_and_cached_input():
    client = _bare(GeminiClient)
    pricing = client._get_gemini_pricing("gemini-3.8-flash")
    assert pricing["low_input"] == 0.75
    assert pricing["low_output"] == 3.75
    assert pricing["search"] == 14.0
    assert pricing["cached_mult"] == 0.10
    client.track_cost("gemini-3.8-flash", input_tokens=1_000_000, output_tokens=0, cached_tokens=1_000_000)
    assert client.total_cost == pytest.approx(0.075)
    assert client._get_gemini_pricing("gemini-3.1-pro-preview")["high_output"] == 18.0


def test_gemini_roles_and_catalog_drop_retired_models():
    client = _bare(GeminiClient)
    models = client.config["models"]
    for model in _RETIRED_GEMINI:
        assert model not in models
    for model in _role_models(client):
        assert model in models
    assert client.get_model_for_role(ModelRole.RAG_RANKER) == "gemini-3.8-flash"


def test_gemini_call_sends_thinking_level_and_tracks_cache():
    client = _bare(GeminiClient)
    usage = SimpleNamespace(
        prompt_token_count=1_000_000,
        candidates_token_count=0,
        thoughts_token_count=0,
        cached_content_token_count=1_000_000,
    )
    captured = {}

    def _generate_content(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(usage_metadata=usage, text="ok", candidates=[])

    client.client = SimpleNamespace(models=SimpleNamespace(generate_content=_generate_content))
    assert client.call("gemini-3.8-flash@Medium", "system", ["user"]) == "ok"
    thinking = captured["config"].thinking_config
    assert thinking.thinking_level.value == "MEDIUM"
    assert thinking.thinking_budget is None
    assert client.total_cost == pytest.approx(0.075)


def test_model_picker_exposes_new_models_and_reasoning_efforts():
    pricing = get_all_model_pricing()
    by_id = {m["id"]: m for models in pricing.values() for m in models}
    assert by_id["grok-4.7"]["reasoning_efforts"] == ["low", "medium", "high", "xhigh"]
    assert by_id["gpt-6-astra"]["reasoning_efforts"] == ["low", "medium", "high", "xhigh", "max"]
    assert by_id["gpt-6-luna"]["input"] == 0.1
    assert by_id["gemini-3.8-flash"]["supports_search"] is True
    for model in _RETIRED_OPENAI + _RETIRED_GROK + _RETIRED_GEMINI:
        assert model not in by_id
