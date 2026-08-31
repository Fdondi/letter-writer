"""Tests for generation helpers (e.g. core skill normalization)."""
from unittest.mock import MagicMock

import pytest
from letter_writer.skill_utils import core_skill_name
from letter_writer.generation import (
    _format_letter_examples,
    _job_extraction_cache_prefix,
    _letter_generation_context,
    EXTRACTION_SYSTEM,
)
from letter_writer.letter_generation import generate_letter


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("German", "German"),
        ("Fluent German", "German"),
        ("German language proficiency", "German"),
        ("fluent German", "German"),
        ("german language proficiency", "german"),
        ("C++", "C++"),
        ("git", "git"),
        ("Proficient in Python", "Python"),
        ("basic Spanish", "Spanish"),
        ("English language", "English"),
        ("communication skills", "communication"),
        ("working knowledge of French", "French"),
        ("", ""),
        ("  Python  ", "Python"),
    ],
)
def test_core_skill_name_strips_modifiers(raw: str, expected: str) -> None:
    assert core_skill_name(raw) == expected


def test_job_text_cache_prefix_is_stable():
    job = "Senior Engineer at Acme"
    prefix = _job_extraction_cache_prefix(job)
    assert EXTRACTION_SYSTEM.split()[0] in prefix
    assert job in prefix


def test_letter_generation_context_shared_by_plan_and_draft():
    examples = _format_letter_examples(
        [{"company_name": "Acme", "job_text": "Dev", "letter_text": "Dear hiring manager..."}]
    )
    ctx = _letter_generation_context(
        cv_text="CV body",
        examples_formatted=examples,
        company_report="Research",
        job_text="Job posting",
        hire_problem="Scale the platform",
    )
    assert "========== User CV:\nCV body\n==========" in ctx
    assert "========== Examples:\n" in ctx
    assert "Dear hiring manager" in ctx
    assert "========== Company Report:\nResearch\n==========" in ctx
    assert "========== Target Job Description:\nJob posting\n==========" in ctx
    assert "Scale the platform" in ctx


def test_letter_generation_context_omits_hire_goal_when_empty():
    ctx = _letter_generation_context(
        cv_text="CV",
        examples_formatted="(none)",
        company_report="Co",
        job_text="Job",
        hire_problem="",
    )
    assert "Hire goal" not in ctx


def test_generate_letter_fails_fast_on_billing_error(tmp_path):
    client = MagicMock()
    client.call.side_effect = RuntimeError(
        "Your credit balance is too low to access the Anthropic API"
    )
    with pytest.raises(RuntimeError, match="Draft letter generation failed:"):
        generate_letter(
            cv_text="CV body",
            examples=[],
            company_report="Co",
            job_text="Job",
            client=client,
            trace_dir=tmp_path,
            style_instructions="Be concise.",
            max_retries=3,
        )
    assert client.call.call_count == 1


def test_strip_page_html_drops_script_and_caps():
    from letter_writer.job_extraction import strip_page_html

    html = "<html><script>alert(1)</script><p>Hello</p><style>x{}</style></html>"
    out = strip_page_html(html)
    assert "alert" not in out
    assert "Hello" in out
    assert "x{}" not in out


def test_extract_job_page_metadata_parses_cleaned_job_text(tmp_path):
    from letter_writer.job_extraction import extract_job_page_metadata

    client = MagicMock()
    client.call.return_value = (
        '{"job_text":"Zürich sucht eine Entwicklerin für das Zahlungs-Team.",'
        '"company_name":"Acme","job_title":"Engineerin","location":"Zürich",'
        '"language":"German","salary":null,"point_of_contact":null}'
    )
    result = extract_job_page_metadata(
        "Cookie accept\nRelated jobs\nZürich sucht eine Entwicklerin\nApply now",
        client,
        html="<html><nav>Menu</nav><main>Zürich sucht eine Entwicklerin</main></html>",
        source_url="https://jobs.example/acme",
        trace_dir=tmp_path,
    )
    assert result["job_text"].startswith("Zürich")
    assert result["company_name"] == "Acme"
    assert result["job_title"] == "Engineerin"
    assert "Cookie" not in result["job_text"]
    prompt_sent = client.call.call_args.kwargs.get("system_cache_prefix") or ""
    if not prompt_sent:
        prompt_sent = str(client.call.call_args)
    assert "ä" in result["job_text"] or "Zürich" in result["job_text"]
