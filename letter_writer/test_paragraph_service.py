"""Paragraph flow helpers: splitting, focus filtering, prompt inputs and output parsing."""

import pytest

from letter_writer.feedback_checks import PHASED_FEEDBACK_TOPIC_KEYS, run_feedback_topic
from letter_writer.letter_generation import (
    parse_paragraph_continue_output,
    regenerate_paragraph,
    split_letter_paragraphs,
)
from letter_writer.paragraph_service import filter_items_to_focus, format_regenerate_feedback


class _Client:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls = []

    def call(self, model_role, system, user_messages, **kwargs):
        self.calls.append({"role": model_role, "system": system, "user": user_messages, **kwargs})
        return self.reply


def test_split_letter_paragraphs_matches_web_rule():
    text = "  Dear team,\n\nFirst para\nstill first.\n   \nSecond.\n\n\n\nBye  "
    assert split_letter_paragraphs(text) == ["Dear team,", "First para\nstill first.", "Second.", "Bye"]
    assert split_letter_paragraphs("   ") == []


def test_filter_items_to_focus_keeps_overlap_and_flags_unanchored():
    items = [
        {"id": "in", "span_start": 12, "span_end": 20},
        {"id": "edge", "span_start": 5, "span_end": 11},
        {"id": "out", "span_start": 30, "span_end": 40},
        {"id": "none"},
    ]
    kept = filter_items_to_focus(items, 10, 25)
    assert [it["id"] for it in kept] == ["in", "edge", "none"]
    assert kept[-1]["whole_letter"] is True
    assert "whole_letter" not in kept[0]
    assert filter_items_to_focus(items, None, None) == items


def test_format_regenerate_feedback_combines_user_and_ai_notes():
    out = format_regenerate_feedback(
        "  Shorter please ",
        [
            {"topic": "precision", "observation": "Vague claim", "quote": "many projects"},
            {"topic": "human", "observation": ""},
            {"observation": "Repetitive"},
        ],
    )
    assert out == 'Shorter please\n- [precision] Vague claim (about: "many projects")\n- Repetitive'


def test_regenerate_paragraph_marks_target_and_strips_markers():
    client = _Client(">>>\nNew middle.\n<<<")
    out = regenerate_paragraph(["A.", "B.", "C."], 1, "", "CV", [], "", "Job", client)
    assert out == "New middle."
    user = client.calls[0]["user"][0]
    assert "A.\n\n>>>\nB.\n<<<\n\nC." in user
    assert "(none given" in user


def test_regenerate_paragraph_rejects_bad_index():
    with pytest.raises(ValueError):
        regenerate_paragraph(["A."], 3, "", "CV", [], "", "Job", _Client("x"))


def test_parse_paragraph_continue_output():
    assert parse_paragraph_continue_output('{"paragraph": " Next. ", "letter_complete": true}') == ("Next.", True)
    assert parse_paragraph_continue_output("Plain prose reply.") == ("Plain prose reply.", False)
    with pytest.raises(ValueError):
        parse_paragraph_continue_output('{"paragraph": ""}')


def test_run_feedback_topic_runs_only_that_check():
    client = _Client('{"items": [{"observation": "Too long", "type": "PLEASE_FIX", "quote": "Hello"}]}')
    items = run_feedback_topic(
        "instruction",
        draft_letter="Hello world.\n\nBye.",
        cv_text="CV",
        company_report="",
        job_text="Job",
        top_docs=[],
        client=client,
    )
    assert len(client.calls) == 1
    assert items and items[0]["observation"] == "Too long"
    assert items[0].get("span_start") == 0
    with pytest.raises(KeyError):
        run_feedback_topic(
            "nope", draft_letter="x", cv_text="", company_report="", job_text="", top_docs=[], client=client
        )
    assert "instruction" in PHASED_FEEDBACK_TOPIC_KEYS


class _FakeSession:
    def __init__(self) -> None:
        self.session_id = "s1"
        self.vendors: dict = {}
        self.selected_top_docs = [{"company_name": "Ex", "job_text": "J", "letter_text": "Example letter.", "score": 9}]
        self.search_result: list = []
        self.metadata: dict = {"common": {"company_name": "Acme"}}
        self.cv_text = "My CV"
        self.job_text = "The job"
        self.style_instructions = "Be brief."


class _CostClient(_Client):
    def __init__(self, replies):
        super().__init__("")
        self.replies = list(replies)
        self.total_cost = 0.0
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def call(self, model_role, system, user_messages, **kwargs):
        super().call(model_role, system, user_messages, **kwargs)
        self.total_cost += 0.01
        reply = self.replies.pop(0)
        return reply(user_messages) if callable(reply) else reply


def _patch_service(monkeypatch, client):
    from letter_writer import paragraph_service

    monkeypatch.setattr(paragraph_service, "_load_session", lambda _sid: _FakeSession())
    monkeypatch.setattr(paragraph_service, "get_client", lambda _vendor: client)
    return paragraph_service


def test_draft_letter_for_paragraphs_end_to_end(monkeypatch, tmp_path):
    from letter_writer.clients.base import ModelRole, ModelVendor

    monkeypatch.chdir(tmp_path)
    client = _CostClient(['{"draft_letter": "Dear Acme,\\n\\nI fit.\\n\\nRegards", "known_weaknesses": []}'])
    svc = _patch_service(monkeypatch, client)
    out = svc.draft_letter_for_paragraphs(session_id="s1", vendor=ModelVendor.OPENAI, user_id=None, company_report_override="Report")
    assert [p["text"] for p in out["paragraphs"]] == ["Dear Acme,", "I fit.", "Regards"]
    assert out["cost"] == pytest.approx(0.01)
    assert out["usage"]["paragraph_draft"]["cost"] == pytest.approx(0.01)
    assert out["timing"]["started_at_ms"] > 0 and "llm" in out["timing"]["stages"]
    call = client.calls[0]
    assert call["role"] == ModelRole.PARAGRAPH
    assert "APPROVED STRATEGIC PLAN" not in call["system"]
    assert "Example letter." in call["system_cache_prefix"] and "Report" in call["system_cache_prefix"]


def test_continue_and_focused_feedback_end_to_end(monkeypatch, tmp_path):
    import re

    from letter_writer.clients.base import ModelRole, ModelVendor

    monkeypatch.chdir(tmp_path)

    def review(user):
        # Reviewer drops any critique whose text says "weak".
        rows = re.findall(r"id=([^:]+): (.*)", user[0])
        return '{"results": [%s]}' % ",".join(
            '{"id": "%s", "keep": %s}' % (oid, "false" if "weak" in obs else "true") for oid, obs in rows
        )

    client = _CostClient(
        [
            '{"paragraph": "Next one.", "letter_complete": true}',
            '{"items": [{"observation": "a", "type": "PLEASE_FIX", "quote": "Opening"},'
            ' {"observation": "b", "type": "PLEASE_FIX", "quote": "Next one"},'
            ' {"observation": "weak c", "type": "PLEASE_FIX", "quote": "Next"}]}',
            review,
        ]
    )
    svc = _patch_service(monkeypatch, client)
    laya_seen = []

    def fake_laya(feedback, letter):
        for items in feedback.values():
            laya_seen.extend(it["observation"] for it in items)
            for it in items:
                it["laya_verdict"] = "invalid" if it["observation"] == "b" else "valid"
        return {"available": True}

    monkeypatch.setattr(svc, "annotate_feedback_validity", fake_laya)
    cont = svc.continue_assembled_letter(session_id="s1", vendor=ModelVendor.MISTRAL, user_id=None, letter_so_far="Opening.", instructions="Short")
    assert cont["paragraph"]["text"] == "Next one." and cont["letter_complete"] is True
    assert "Opening." in client.calls[0]["user"][0] and "Short" in client.calls[0]["user"][0]
    assert cont["usage"]["paragraph_continue"]["cost"] == pytest.approx(0.01)
    assert set(cont["timing"]["stages"]) == {"prepare", "llm"}

    letter = "Opening.\n\nNext one."
    fb = svc.paragraph_feedback_topic(
        session_id="s1",
        vendor=ModelVendor.MISTRAL,
        user_id=None,
        topic="precision",
        letter_text=letter,
        focus_start=letter.index("Next"),
        focus_end=len(letter),
    )
    # Focus filter runs before Laya and review, so "a" is never scored or reviewed.
    assert laya_seen == ["b", "weak c"]
    assert [it["observation"] for it in fb["items"]] == ["b"]
    assert fb["items"][0]["laya_verdict"] == "invalid"
    assert [it["observation"] for it in fb["dropped_items"]] == ["weak c"]
    assert fb["raw_count"] == 3
    assert client.calls[-1]["role"] == ModelRole.FEEDBACK_REVIEW
    assert set(fb["usage"]) == {"paragraph_feedback", "paragraph_feedback_review"}
    assert fb["cost"] == pytest.approx(0.02)
    assert {"prepare", "check", "quote_spans", "laya", "review"} <= set(fb["timing"]["stages"])
    assert fb["timing"]["laya_scored"] == 2 and fb["timing"]["total_ms"] >= 0


def test_feedback_review_failure_keeps_notes(monkeypatch, tmp_path):
    from letter_writer.clients.base import ModelVendor

    monkeypatch.chdir(tmp_path)

    def boom(_user):
        raise RuntimeError("reviewer down")

    client = _CostClient(['{"items": [{"observation": "x", "type": "PLEASE_FIX", "quote": "Hi"}]}', boom])
    svc = _patch_service(monkeypatch, client)
    monkeypatch.setattr(svc, "annotate_feedback_validity", lambda fb, letter: {"available": False})
    fb = svc.paragraph_feedback_topic(session_id="s1", vendor=ModelVendor.OPENAI, user_id=None, topic="accuracy", letter_text="Hi there.")
    assert [it["observation"] for it in fb["items"]] == ["x"]
    assert fb["dropped_items"] == []
    assert "reviewer down" in fb["timing"]["review_error"]


def test_route_timing_event_logged_on_success_and_failure(monkeypatch):
    from fastapi import HTTPException

    from letter_writer_server.api import paragraph as api

    logged = []
    monkeypatch.setattr(api, "append_application_event", logged.append)
    out = api._timed(
        "feedback",
        "openai",
        {"topic": "human", "draft_id": "d1", "paragraph_id": None},
        lambda: {"items": [{"id": "a"}], "dropped_items": [{"id": "b"}], "raw_count": 2, "cost": 0.03, "usage": {}, "timing": {"total_ms": 5.0, "stages": {"check": 4.0}}},
    )
    assert out["timing"]["route_ms"] >= 0 and out["timing"]["stages"] == {"check": 4.0}
    ev = logged[-1]
    assert ev["type"] == "timing" and ev["source"] == "paragraph.feedback"
    assert ev["payload"]["ok"] is True and ev["payload"]["kept_count"] == 1
    assert ev["payload"]["dropped_items"] == [{"id": "b"}] and ev["payload"]["cost"] == 0.03

    def fail():
        raise ValueError("bad index")

    with pytest.raises(HTTPException) as exc:
        api._timed("regenerate", "openai", {"draft_id": "d1"}, fail, bad_request=(ValueError,))
    assert exc.value.status_code == 400
    assert logged[-1]["payload"]["ok"] is False and "bad index" in logged[-1]["payload"]["error"]
