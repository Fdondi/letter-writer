"""Client restore must not drop vendors that were already saved."""

from letter_writer_server.core.vendor_restore import merge_restored_vendors


def test_empty_incoming_keeps_existing_vendors():
    existing = {
        "gemini": {"draft_letter": "Hallo"},
        "mistral": {"draft_letter": "Bonjour"},
    }
    assert merge_restored_vendors(existing, {}) == existing
    assert merge_restored_vendors(existing, None) == existing


def test_partial_vendor_does_not_erase_other_vendors_or_blank_letters():
    existing = {
        "gemini": {"draft_letter": "Hallo", "letter_plan": "Plan"},
        "mistral": {"draft_letter": "Bonjour"},
        "grok": {"draft_letter": "Hello"},
    }
    incoming = {
        "gemini": {"draft_letter": "", "feedback": {"instruction": []}},
        "deepseek": {"draft_letter": "你好"},
    }
    merged = merge_restored_vendors(existing, incoming)
    assert merged["gemini"]["draft_letter"] == "Hallo"
    assert merged["gemini"]["letter_plan"] == "Plan"
    assert merged["gemini"]["feedback"] == {"instruction": []}
    assert merged["mistral"]["draft_letter"] == "Bonjour"
    assert merged["grok"]["draft_letter"] == "Hello"
    assert merged["deepseek"]["draft_letter"] == "你好"


def test_empty_vendor_object_is_ignored():
    existing = {"gemini": {"draft_letter": "Hallo"}}
    assert merge_restored_vendors(existing, {"gemini": {}})["gemini"]["draft_letter"] == "Hallo"
