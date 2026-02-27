"""Tests for generation helpers (e.g. core skill normalization)."""
import pytest
from letter_writer.skill_utils import core_skill_name


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
