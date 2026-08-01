"""Tests for generation helpers (e.g. core skill normalization)."""
import pytest
from letter_writer.skill_utils import core_skill_name
from letter_writer.generation import (
    _format_letter_examples,
    _job_extraction_cache_prefix,
    _letter_generation_context,
    EXTRACTION_SYSTEM,
)


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
