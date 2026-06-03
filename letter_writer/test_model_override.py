"""Tests for model picker @thinking suffix parsing."""

from letter_writer.clients.model_override import (
    apply_model_override_thinking,
    split_model_id_and_thinking,
    thinking_config_for_vendor,
    vendor_key_from_model_selector,
)


def test_split_model_id_and_thinking():
    assert split_model_id_and_thinking("gpt-5.5") == ("gpt-5.5", None)
    assert split_model_id_and_thinking("gpt-5.5@high") == ("gpt-5.5", "high")


def test_thinking_config_openai():
    assert thinking_config_for_vendor("openai", "medium") == {"reasoning_effort": "medium"}
    assert thinking_config_for_vendor("openai", None) == {}


def test_thinking_config_gemini():
    assert thinking_config_for_vendor("gemini", "none") == {"thinking_level": None}
    assert thinking_config_for_vendor("gemini", "High") == {"thinking_level": "High"}


def test_thinking_config_anthropic():
    assert thinking_config_for_vendor("anthropic", "off") == {"thinking": False}
    assert thinking_config_for_vendor("anthropic", "high") == {
        "thinking": True,
        "thinking_effort": "high",
    }


def test_apply_model_override_thinking():
    model, cfg = apply_model_override_thinking("openai", "gpt-5.5@low")
    assert model == "gpt-5.5"
    assert cfg == {"reasoning_effort": "low"}


def test_vendor_key_from_model_selector():
    assert vendor_key_from_model_selector("openai") == "openai"
    assert vendor_key_from_model_selector("openai/gpt-5.5@high") == "openai"
