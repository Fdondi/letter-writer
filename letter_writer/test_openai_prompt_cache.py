"""Tests for OpenAI prompt-cache message layout."""

from letter_writer.clients.openai_prompt_cache import (
    build_openai_messages,
    prompt_cache_key,
    supports_explicit_prompt_cache,
)


def test_supports_explicit_prompt_cache():
    assert supports_explicit_prompt_cache("gpt-5.6")
    assert supports_explicit_prompt_cache("gpt-5.6-sol")
    assert supports_explicit_prompt_cache("gpt-5.6-terra")
    assert supports_explicit_prompt_cache("gpt-5.6-luna")
    assert supports_explicit_prompt_cache("gpt-6-astra")
    assert supports_explicit_prompt_cache("gpt-6-sol")
    assert supports_explicit_prompt_cache("gpt-6-luna")
    assert supports_explicit_prompt_cache("gpt-6.1-sol")
    assert not supports_explicit_prompt_cache("gpt-5.5")
    assert not supports_explicit_prompt_cache("gpt-5.4")
    assert not supports_explicit_prompt_cache("gpt-60")


def test_prompt_cache_key_stable():
    a = prompt_cache_key("same", "prefix")
    b = prompt_cache_key("same", "prefix")
    c = prompt_cache_key("other", "prefix")
    assert a == b
    assert a != c
    assert a.startswith("letter-writer:")


def test_gpt_56_explicit_system_cache_breakpoint():
    messages, key, explicit = build_openai_messages(
        "Task instructions",
        ["Do the thing."],
        system_cache_prefix="========== User CV:\n" + ("x" * 2000),
        model="gpt-5.6-terra",
    )
    assert explicit is True
    assert key
    assert messages[0]["role"] == "system"
    blocks = messages[0]["content"]
    assert blocks[0]["prompt_cache_breakpoint"] == {"mode": "explicit"}
    assert "Task instructions" in blocks[1]["text"]


def test_gpt_56_explicit_user_cache_breakpoint():
    messages, key, explicit = build_openai_messages(
        "Extract JSON.",
        ["Task: metadata"],
        cache_prefix="Job description:\n" + ("y" * 2000),
        model="gpt-5.6-luna",
    )
    assert explicit is True
    assert key
    user_blocks = messages[1]["content"]
    assert user_blocks[0]["prompt_cache_breakpoint"] == {"mode": "explicit"}
    assert user_blocks[1]["text"] == "Task: metadata"


def test_gpt_6_explicit_system_cache_breakpoint():
    messages, key, explicit = build_openai_messages(
        "Task instructions",
        ["Do the thing."],
        system_cache_prefix="========== User CV:\n" + ("x" * 5000),
        model="gpt-6-luna",
    )
    assert explicit is True
    assert key
    assert messages[0]["content"][0]["prompt_cache_breakpoint"] == {"mode": "explicit"}


def test_legacy_openai_merges_prefixes_into_system():
    messages, key, explicit = build_openai_messages(
        "Instructions",
        ["User task"],
        system_cache_prefix="Cached docs",
        cache_prefix="Job text",
        model="gpt-5.4",
    )
    assert explicit is False
    assert key == prompt_cache_key("Cached docs\n\nJob text", None)
    assert "Cached docs" in messages[0]["content"]
    assert "Job text" in messages[0]["content"]
    assert messages[1]["content"] == "User task"


def test_legacy_openai_without_prefix_has_no_routing_key():
    _messages, key, explicit = build_openai_messages("Instructions", ["User task"], model="gpt-5.4")
    assert explicit is False
    assert key is None
