"""Tests for quote-to-span resolution and quote fields on feedback items."""
from letter_writer.feedback_checks import normalize_parsed_feedback_items
from letter_writer.quote_span import apply_span_to_item, attach_quote_span, resolve_quote_span, resolve_quote_span_multi


LETTER = (
    "Dear team,\n"
    "I enjoy working with cats in the lab.\n"
    "I also build payment systems for dogs.\n"
    "Kind regards"
)


def test_empty_quote_is_none():
    assert resolve_quote_span(LETTER, "") is None
    assert resolve_quote_span(LETTER, "   ") is None


def test_exact_span():
    span = resolve_quote_span(LETTER, "working with cats")
    assert span is not None
    assert span.method == "exact"
    assert LETTER[span.start : span.end] == "working with cats"


def test_normalized_whitespace_and_case():
    span = resolve_quote_span(LETTER, "WORKING   with   CATS")
    assert span is not None
    assert span.method == "normalized"
    assert "cats" in span.matched_text.lower()


def _dog_vs_cat_embed(texts):
    def vec(t):
        low = (t or "").lower()
        return [
            1.0 if ("dog" in low or "canine" in low or "payment" in low) else 0.0,
            1.0 if "cat" in low else 0.0,
        ]

    return [vec(t) for t in texts]


def test_vector_fallback_picks_closer_span():
    span = resolve_quote_span(
        LETTER,
        "canine payment platforms",
        embed_fn=_dog_vs_cat_embed,
    )
    assert span is not None
    assert span.method == "vector"
    assert "dog" in span.matched_text.lower() or "payment" in span.matched_text.lower()
    assert "cats" not in span.matched_text.lower()


def test_multi_draft_picks_matching_vendor():
    drafts = {
        "openai": "We love astronomy and telescopes.",
        "anthropic": "I ship payment systems for dogs every week.",
    }
    span = resolve_quote_span_multi(
        drafts,
        "payment systems for dogs",
        embed_fn=_dog_vs_cat_embed,
    )
    assert span is not None
    assert span.draft_vendor == "anthropic"
    assert span.method == "exact"


def test_normalize_parsed_keeps_quote():
    items = normalize_parsed_feedback_items(
        {
            "items": [
                {
                    "observation": "Too vague",
                    "type": "PLEASE_FIX",
                    "quote": "working with cats",
                }
            ]
        },
        allowed_context_sources=frozenset({"CV", "LETTER"}),
    )
    assert len(items) == 1
    assert items[0]["quote"] == "working with cats"
    assert items[0]["matched_text"] == ""


def test_attach_span_like_agentic_comment():
    comment = {"quote": "working with cats", "matched_text": ""}
    span = resolve_quote_span_multi(
        {"openai": LETTER},
        "working with cats",
        embed_fn=_dog_vs_cat_embed,
    )
    apply_span_to_item(comment, span)
    assert comment["matched_text"] == "working with cats"
    assert comment["draft_vendor"] == "openai"


def test_blank_quote_stays_unanchored():
    item = {"quote": "", "observation": "Overall tone is fine."}
    attach_quote_span(item, LETTER, embed_fn=_dog_vs_cat_embed)
    assert item["quote"] == ""
    assert item["matched_text"] == ""
