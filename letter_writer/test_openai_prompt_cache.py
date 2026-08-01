"""Tests for OpenAI prompt-cache message layout."""

from letter_writer.clients.openai_prompt_cache import (
    build_openai_messages,
    is_gpt_56_family,
    prompt_cache_key,
)


def test_is_gpt_56_family():
    assert is_gpt_56_family("gpt-5.6")
    assert is_gpt_56_family("gpt-5.6-sol")
    assert is_gpt_56_family("gpt-5.6-terra")
    assert is_gpt_56_family("gpt-5.6-luna")
    assert not is_gpt_56_family("gpt-5.5")
    assert not is_gpt_56_family("gpt-5.4")


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


def test_legacy_openai_merges_prefixes_into_system():
    messages, key, explicit = build_openai_messages(
        "Instructions",
        ["User task"],
        system_cache_prefix="Cached docs",
        cache_prefix="Job text",
        model="gpt-5.4",
    )
    assert explicit is False
    assert key is None
    assert "Cached docs" in messages[0]["content"]
    assert "Job text" in messages[0]["content"]
    assert messages[1]["content"] == "User task"
