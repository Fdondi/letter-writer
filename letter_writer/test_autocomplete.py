"""Tests for autocomplete stop rules and model resolution."""

import pytest

from letter_writer.autocomplete_core import (
    build_all_sections_plan_user_prompt,
    build_autocomplete_cache_prefix,
    build_autocomplete_draft_prefix,
    build_section_plan_user_prompt,
    context_summary_max_chars,
    finalize_plan_context_summary,
    format_autocomplete_top_docs,
    parse_autocomplete_plan_batch_json,
    get_autocomplete_plan_role_defaults,
    get_autocomplete_role_defaults,
    next_model_in_cycle,
    resolve_autocomplete_model,
    resolve_autocomplete_plan_model,
    sections_to_body_text,
    finalize_autocomplete_suggestion,
    parse_autocomplete_section_plan_response,
    should_extend_autocomplete_cache,
    slice_next_autocomplete_chunk,
    strip_autocomplete_continuation_overlap,
    truncate_autocomplete_suggestion,
)


def test_strip_autocomplete_continuation_overlap():
    out, stripped = strip_autocomplete_continuation_overlap("world today", "Hello ")
    assert stripped is False
    assert out == "world today"

    out, stripped = strip_autocomplete_continuation_overlap("Hello world", "Hello ")
    assert stripped is True
    assert out == "world"

    out, stripped = strip_autocomplete_continuation_overlap("Hello world", "Hello world")
    assert stripped is True
    assert out == ""


def test_finalize_autocomplete_suggestion_overlap_warning():
    out, reason, warnings = finalize_autocomplete_suggestion(
        "Hello world",
        max_words=20,
        stop_on_period=False,
        text_before_cursor="Hello ",
    )
    assert out == "world"
    assert reason is None
    assert warnings == []

    out, reason, warnings = finalize_autocomplete_suggestion(
        "Hello world",
        max_words=20,
        stop_on_period=False,
        text_before_cursor="Hello world",
    )
    assert out == ""
    assert reason is None
    assert "continuation_only_repeated_existing_text" in warnings


@pytest.mark.parametrize(
    "raw,max_words,stop_on_period,expected,truncated",
    [
        ("hello world foo", 2, False, "hello world", "max_words"),
        ("one two. three", 20, True, "one two.", "period"),
        ("", 20, True, "", None),
        ("word", 20, False, "word", None),
    ],
)
def test_truncate_autocomplete_suggestion(raw, max_words, stop_on_period, expected, truncated):
    out, reason = truncate_autocomplete_suggestion(
        raw, max_words=max_words, stop_on_period=stop_on_period
    )
    assert out == expected
    if truncated:
        assert reason is not None
        assert truncated in (reason or "")
    else:
        assert reason is None


def test_resolve_autocomplete_model_explicit():
    user_data = {"models": {"value": ["openai", "gemini"]}}
    assert resolve_autocomplete_model(user_data, explicit_model="mistral") == "mistral/mistral-small-2506"


def test_resolve_autocomplete_model_ctrl_letter():
    user_data = {
        "autocomplete_models": {"value": ["gemini/gemini-2.5-flash-lite"]},
    }
    assert resolve_autocomplete_model(user_data, ctrl_letter="g") == "gemini/gemini-2.5-flash-lite"


def test_derive_ctrl_letter_map_collisions():
    from letter_writer.autocomplete_core import derive_ctrl_letter_map_from_models

    models = ["gemini/gemini-2.5-flash-lite", "grok/grok-4-1-fast-non-reasoning"]
    mapped = derive_ctrl_letter_map_from_models(models)
    assert mapped["G"] == "gemini/gemini-2.5-flash-lite"
    assert mapped["H"] == "grok/grok-4-1-fast-non-reasoning"


def test_merge_ctrl_letter_map_honors_stored_override():
    from letter_writer.autocomplete_core import merge_ctrl_letter_map

    models = ["openai/gpt-realtime-mini", "gemini/gemini-2.5-flash-lite"]
    stored = {"M": "gemini/gemini-2.5-flash-lite"}
    merged = merge_ctrl_letter_map(models, stored)
    assert merged["O"] == "openai/gpt-realtime-mini"
    assert merged["M"] == "gemini/gemini-2.5-flash-lite"


def test_get_autocomplete_ctrl_letter_map_reads_stored():
    from letter_writer.personal_data_sections import get_autocomplete_ctrl_letter_map

    user_data = {
        "autocomplete_models": {
            "value": ["openai/gpt-realtime-mini", "gemini/gemini-2.5-flash-lite"],
        },
        "autocomplete_ctrl_letter_map": {
            "value": {"M": "gemini/gemini-2.5-flash-lite"},
        },
    }
    mapped = get_autocomplete_ctrl_letter_map(user_data)
    assert mapped["M"] == "gemini/gemini-2.5-flash-lite"
    assert mapped["O"] == "openai/gpt-realtime-mini"


def test_resolve_autocomplete_model_legacy_shift_letter():
    user_data = {
        "autocomplete_models": {"value": ["gemini/gemini-2.5-flash-lite"]},
    }
    assert resolve_autocomplete_model(user_data, shift_letter="g") == "gemini/gemini-2.5-flash-lite"


def test_next_model_in_cycle():
    user_data = {
        "autocomplete_models": {
            "value": ["openai/gpt-realtime-mini", "gemini/gemini-2.5-flash-lite", "mistral/mistral-small-latest"],
        }
    }
    assert next_model_in_cycle("openai/gpt-realtime-mini", user_data) == "gemini/gemini-2.5-flash-lite"
    assert next_model_in_cycle("mistral/mistral-small-latest", user_data) == "openai/gpt-realtime-mini"


def test_get_autocomplete_role_defaults_includes_vendors():
    defaults = get_autocomplete_role_defaults()
    assert "openai" in defaults
    assert defaults["openai"].startswith("openai/")


def test_format_autocomplete_top_docs_skips_empty_letters():
    docs = [
        {"company_name": "Acme", "score": 8, "job_text": "Dev", "letter_text": "Dear hiring manager"},
        {"company_name": "Empty", "score": 5, "job_text": "X", "letter_text": ""},
    ]
    out = format_autocomplete_top_docs(docs)
    assert "Acme" in out
    assert "Dear hiring manager" in out
    assert "Empty" not in out


def test_build_autocomplete_draft_prefix_stops_at_active_cursor():
    sections = [
        {"title": "You are great", "description": "Why them", "body": "Dear team,"},
        {"title": "I am great", "description": "Why me", "body": "I built systems"},
        {"title": "Together", "description": "Fit", "body": "Future"},
    ]
    prefix = build_autocomplete_draft_prefix(sections, active_index=1, cursor_in_section=3)
    assert "Please continue:" in prefix
    assert "# You are great" in prefix
    assert "## Why them" in prefix
    assert "Dear team," in prefix
    assert "# I am great" in prefix
    assert "I b" in prefix
    assert "built" not in prefix
    assert "Together" not in prefix


def test_sections_to_body_text_omits_metadata():
    sections = [
        {"title": "A", "description": "meta", "body": "Para one"},
        {"title": "B", "description": "meta2", "body": "Para two"},
        {"title": "C", "description": "meta3", "body": ""},
    ]
    assert sections_to_body_text(sections) == "Para one\n\nPara two"


def test_get_autocomplete_plan_role_defaults_includes_vendors():
    defaults = get_autocomplete_plan_role_defaults()
    assert "openai" in defaults
    assert defaults["openai"].startswith("openai/")


def test_resolve_autocomplete_plan_model_explicit():
    user_data = {}
    resolved = resolve_autocomplete_plan_model(user_data, explicit_model="gemini")
    assert resolved.startswith("gemini/")


def test_build_section_plan_user_prompt_includes_goal_and_sibling_plans():
    sections = [
        {
            "title": "You are great",
            "description": "Why the company",
            "body": "",
            "plan": "- Mention product\n- Culture fit",
        },
        {"title": "I am great", "description": "Why me — SQL and C++", "body": "Partial"},
        {
            "title": "Together",
            "description": "Fit",
            "body": "",
            "plan": "- Joint impact",
        },
    ]
    prompt = build_section_plan_user_prompt(sections=sections, section_index=1)
    assert "I am great" in prompt
    assert "SQL" in prompt
    assert "Other sections" in prompt
    assert "Mention product" in prompt
    assert "Joint impact" in prompt
    assert "Together" in prompt
    assert "bullet" in prompt.lower()
    assert "section goal" in prompt.lower() or "Section goal" in prompt


def test_build_all_sections_plan_user_prompt_lists_goals_and_json():
    sections = [
        {"title": "You are great", "description": "Why them", "body": ""},
        {"title": "I am great", "description": "Why me", "body": ""},
    ]
    prompt = build_all_sections_plan_user_prompt(sections=sections)
    assert "non-overlapping" in prompt.lower()
    assert "Why them" in prompt
    assert "Why me" in prompt
    assert '"plans"' in prompt
    assert '"context_summary"' in prompt
    assert "coherent letter" in prompt.lower() or "complete" in prompt.lower()


def test_parse_autocomplete_plan_batch_json():
    raw = (
        '{"plans": {"0": "- A", "1": "- B"}, "proposals": {"0": "Draft A.", "1": "Draft B."}, '
        '"context_summary": "Python role, 8 years backend."}'
    )
    plans, proposals, summary = parse_autocomplete_plan_batch_json(raw, expected_count=2)
    assert plans == {"0": "- A", "1": "- B"}
    assert proposals == {"0": "Draft A.", "1": "Draft B."}
    assert summary == "Python role, 8 years backend."


def test_parse_autocomplete_plan_batch_json_rejects_missing_section():
    raw = (
        '{"plans": {"0": "- A"}, "proposals": {"0": "Draft A."}, '
        '"context_summary": "Summary."}'
    )
    with pytest.raises(ValueError, match="missing sections"):
        parse_autocomplete_plan_batch_json(raw, expected_count=2)


def test_parse_autocomplete_plan_batch_json_requires_context_summary():
    raw = '{"plans": {"0": "- A"}, "proposals": {"0": "Draft A."}}'
    with pytest.raises(ValueError, match="context_summary"):
        parse_autocomplete_plan_batch_json(raw, expected_count=1)


def test_parse_autocomplete_section_plan_response():
    raw = "## Plan\n- Point one\n- Point two\n\n## Proposal\nI bring ten years of experience."
    plan, proposal = parse_autocomplete_section_plan_response(raw)
    assert "- Point one" in plan
    assert "ten years" in proposal


def test_slice_next_autocomplete_chunk_and_extend_threshold():
    raw = "one two three. four five six. seven eight"
    chunk, offset, reason, has_more = slice_next_autocomplete_chunk(
        raw, 0, max_words=3, stop_on_period=True
    )
    assert chunk == "one two three."
    assert has_more is True
    assert should_extend_autocomplete_cache(offset, len(raw)) is False
    assert should_extend_autocomplete_cache(int(len(raw) * 0.85), len(raw)) is True


def test_build_autocomplete_cache_prefix_includes_section_proposal_stale_note():
    prefix = build_autocomplete_cache_prefix(
        cv_text="CV",
        job_text="Job",
        style_instructions="Style",
        additional_user_info="",
        additional_company_info="",
        active_section_proposal="I admire your product culture.",
        section_proposal_stale=True,
    )
    assert "draft candidate" in prefix.lower()
    assert "approximate" in prefix
    assert "product culture" in prefix


def test_build_autocomplete_cache_prefix_includes_section_plan():
    prefix = build_autocomplete_cache_prefix(
        cv_text="CV",
        job_text="Job",
        style_instructions="Style",
        additional_user_info="",
        additional_company_info="",
        active_section_plan="- Highlight SQL\n- Bridge C++ to C#",
    )
    assert "Section writing plan" in prefix
    assert "Highlight SQL" in prefix


def test_context_summary_max_chars_and_finalize():
    assert context_summary_max_chars(1000) == 100
    assert context_summary_max_chars(0) == 0
    # Moderate overrun (under 3× target): keep full text, no warning.
    summary, warnings = finalize_plan_context_summary(
        "x" * 150,
        full_context_len=1000,
    )
    assert len(summary) == 150
    assert warnings == []
    # Wild overrun (>3× target): truncate to target and warn.
    summary2, warnings2 = finalize_plan_context_summary(
        "x" * 350,
        full_context_len=1000,
    )
    assert len(summary2) == 100
    assert any("exceeded_max_length" in w for w in warnings2)


def test_build_autocomplete_cache_prefix_uses_plan_summary_instead_of_cv():
    full = build_autocomplete_cache_prefix(
        cv_text="Very long CV " * 50,
        job_text="Job " * 50,
        style_instructions="Style",
        additional_user_info="",
        additional_company_info="",
        plan_context_summary="Relevant: Python role, 8 years backend.",
    )
    assert "plan-relevant summary" in full
    assert "Relevant: Python" in full
    assert "User CV" not in full
    assert "Target Job Description" not in full
    assert "Style instructions" in full


def test_build_autocomplete_cache_prefix_includes_vendor_context():
    prefix = build_autocomplete_cache_prefix(
        cv_text="CV body",
        job_text="Job offer",
        style_instructions="Write warmly",
        structure_instructions="Three paragraphs",
        additional_user_info="Side project",
        additional_company_info="Startup culture",
        company_report="Company facts",
        top_docs=[{"company_name": "Ex", "score": 9, "job_text": "Role", "letter_text": "Hello"}],
        company_name="TargetCo",
        job_title="Engineer",
        competences={"Python": {"need": "required", "level": "strong"}},
    )
    assert "User CV" in prefix
    assert "Examples" in prefix
    assert "Company Report" in prefix
    assert "TargetCo" in prefix
    assert "Python" in prefix
    assert "Target Job Description" in prefix
    assert "Structure instructions" in prefix
    assert "Style instructions" in prefix
