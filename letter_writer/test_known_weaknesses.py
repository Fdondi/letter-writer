"""Tests for known_weaknesses normalization."""
from letter_writer.generation import normalize_known_weaknesses, parse_draft_letter_output


def test_normalize_known_weaknesses_from_weaknesses_key() -> None:
    data = {
        "weaknesses": [
            {"requirement": "Fluent German", "gap": "Applicant has B2 German"},
            {"requirement": "AWS certification", "gap": "No AWS cert on CV"},
        ]
    }
    out = normalize_known_weaknesses(data)
    assert len(out) == 2
    assert out[0]["requirement"] == "Fluent German"
    assert out[0]["gap"] == "Applicant has B2 German"
    assert out[0]["id"]


def test_normalize_known_weaknesses_dedupes() -> None:
    data = {
        "weaknesses": [
            {"requirement": "Fluent German", "gap": "B2 level"},
            {"requirement": "fluent german", "gap": "b2 level"},
        ]
    }
    out = normalize_known_weaknesses(data)
    assert len(out) == 1


def test_normalize_known_weaknesses_empty() -> None:
    assert normalize_known_weaknesses({"weaknesses": []}) == []
    assert normalize_known_weaknesses({}) == []


def test_parse_draft_letter_output() -> None:
    letter, weaknesses = parse_draft_letter_output(
        {
            "draft_letter": "Dear hiring manager,\n\nI am a great fit.",
            "known_weaknesses": [
                {"requirement": "Fluent German", "gap": "B2 level documented"},
            ],
        }
    )
    assert "great fit" in letter
    assert len(weaknesses) == 1
    assert weaknesses[0]["requirement"] == "Fluent German"
