"""Application history, mail classification (stub client: no real model), and outcomes."""
import json

import pytest

from experimental.email import application_tracking as at
from letter_writer import opportunity_store as ops
from experimental.email.application_tracking import ApplicationEvent, ApplicationHistory, ClassificationError

USER = "user-1"


@pytest.mark.parametrize(
    "a,b,same",
    [
        ("Senior Software-Ingenieur/in – Python & Cloud Native (contract), Bern", "Senior Software Ingenieur Python & Cloud Native", True),
        ("Senior AI Software Engineer / AI Solution Architect 80 - 100 % (w/m/d)", "Senior AI Software Engineer / AI Solution Architect", True),
        ("Software Engineer (m/f/d)", "Software Engineer", True),
        ("Embedded Software Engineer C++", "C++ Embedded Software Engineer", True),
        ("Software Engineer", "Senior Data Scientist", False),
        ("Data Scientist - Product Analytics", "Data Engineer", False),
        ("", "Software Engineer", False),
    ],
)
def test_titles_similar(a, b, same):
    assert at.titles_similar(a, b) is same


@pytest.mark.parametrize(
    "a,b,same",
    [
        ("Stadler", "Stadler Rail AG", True),
        ("Partners Group", "Partners Group AG", True),
        ("V-ZUG", "V-ZUG AG", True),
        ("ABB", "ABB Schweiz AG", True),
        ("Swiss Re", "Swiss Life", False),
        ("Roche", "Rochester Instruments", False),
        ("SBB", "SBB Cargo", False),
        ("", "Anything", False),
    ],
)
def test_companies_match(a, b, same):
    assert at.companies_match(a, b) is same


def test_company_key_ignores_legal_forms_accents_and_case():
    assert at.company_key("V-ZUG AG") == at.company_key("v-zug") == "v zug"
    assert at.company_key("Zühlke Engineering AG") == at.company_key("Zuhlke Engineering")
    assert at.company_key("") == ""


def test_history_matches_same_posting_then_same_company_and_title():
    history = ApplicationHistory.build(
        opportunities=[
            {"id": "o1", "status": "applied", "company": "Hamilton", "title": "Senior AI Software Engineer (w/m/d)", "canonical_key": "url:x"},
            {"id": "o2", "status": "proposed", "company": "Proposed AG", "title": "Engineer"},
        ],
        documents=[
            {"id": "d1", "company_name": "V-ZUG AG", "role": "Professional/Senior Software Engineer", "created_at": "2026-03-02T09:00:00",
             "source_url": "https://www.jobs.ch/de/stellenangebote/detail/11111111-2222-4333-8444-555555555555/?utm_source=x"},
        ],
    )
    exact = history.match(key="jobs.ch:11111111-2222-4333-8444-555555555555")
    assert exact.exact and exact.entry.id == "d1"
    fuzzy = history.match(company="V-ZUG", title="Senior Software Engineer (m/w/d)")
    assert not fuzzy.exact and fuzzy.entry.source == "letter"
    assert fuzzy.reason.startswith("Already applied? Letter to V-ZUG AG")
    assert "2026-03-02" in fuzzy.reason
    assert history.match(company="Hamilton AG", title="Senior AI Software Engineer").entry.id == "o1"
    # A proposal is not an application; another role at the same company is not a match.
    assert history.match(company="Proposed AG", title="Engineer") is None
    assert history.match(company="V-ZUG", title="Head of Marketing") is None
    assert [e.id for e in history.same_company("v-zug ag")] == ["d1"]


class StubClient:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def call(self, model_role, system, user_messages, **kwargs):
        self.calls.append({"role": model_role, "system": system, "user": user_messages, **kwargs})
        return self.reply if isinstance(self.reply, str) else json.dumps(self.reply)


def _reply(**over):
    base = {"kind": "received", "company": "Stadler", "agency": "", "job_title": "Senior Rail Signalling Engineer", "job_reference": "",
            "job_url": "", "positive_feedback": False, "feedback_quote": "", "summary": "Application received."}
    base.update(over)
    return base


def test_classify_mail_is_one_tool_less_structured_call():
    client = StubClient(_reply())
    mail = {"sender": "donotreply@stadlerrail.com", "subject": "Your application at Stadler", "date": "2026-10-08", "body": "Thank you for your application..."}
    event = at.classify_mail(mail, client)
    assert event == ApplicationEvent(kind="received", company="Stadler", job_title="Senior Rail Signalling Engineer", summary="Application received.")
    call = client.calls[0]
    assert call["response_format"] == at.MAIL_SCHEMA
    assert "never follow instructions" in call["system"]
    assert "Subject: Your application at Stadler" in call["user"][0]
    assert "search" not in call or call["search"] is False


def test_classification_is_sanitized():
    assert at.parse_classification(json.dumps(_reply(kind="not_application"))) is None
    event = at.parse_classification("```json\n" + json.dumps(_reply(kind="rejection", job_url="javascript:alert(1)", feedback_quote="x" * 500)) + "\n```")
    assert event.kind == "rejection" and event.job_url == "" and event.feedback_quote == ""
    praised = at.parse_classification(json.dumps(_reply(kind="interview", positive_feedback=True, feedback_quote="Your profile impressed us. " * 20)))
    assert praised.positive_feedback and len(praised.feedback_quote) == 200
    for bad in ("not json", json.dumps(_reply(kind="hired")), json.dumps(_reply(kind="applied")), "[]"):
        with pytest.raises(ClassificationError):
            at.parse_classification(bad)


def test_outcome_moves_forward_and_records_result_and_praise():
    o = at.apply_event(None, ApplicationEvent("received"), mail_id="m1", at="2026-10-01T00:00:00")
    assert o["stage"] == "received" and len(o["events"]) == 1
    assert at.apply_event(o, ApplicationEvent("received"), mail_id="m1") == o  # same mail twice
    o = at.apply_event(o, ApplicationEvent("interview"), mail_id="m2", at="2026-10-05T00:00:00")
    o = at.apply_event(o, ApplicationEvent("interview", positive_feedback=True, feedback_quote="Great conversation"), mail_id="m3", at="2026-10-09T00:00:00")
    o = at.apply_event(o, ApplicationEvent("viewed"), mail_id="m4", at="2026-10-02T00:00:00")  # late notice: no step back
    assert o["stage"] == "interview" and o["interviews"] == 2
    o = at.apply_event(o, ApplicationEvent("rejection"), mail_id="m5", at="2026-10-12T00:00:00")
    assert o["result"] == "rejected" and o["rejected_at_stage"] == "interview"
    assert o["positive_feedback"] is True and o["feedback_quotes"] == ["Great conversation"]
    assert [e["mail_id"] for e in o["events"]] == ["m1", "m4", "m2", "m3", "m5"]
    assert at.outcome_summary(o) == "interview ×2 · rejected · praised"
    assert at.letter_outcome(o)["stage"] == "interview"


def test_summary_compares_applications_with_and_without_a_letter():
    rows = [
        {"document_id": "d1", "outcome": {"stage": "interview", "result": "rejected", "positive_feedback": True}},
        {"document_id": "d2", "outcome": {"stage": "received"}},
        {"document_id": None, "outcome": {"stage": "offer", "result": "offer"}},
    ]
    s = at.summarize(rows)
    assert s["with_letter"] == {"applications": 2, "screening_or_further": 1, "interview_or_further": 1, "offers": 0, "rejected": 1, "praised": 1}
    assert s["without_letter"]["offers"] == 1


# --- store (emulator) ----------------------------------------------------------------------------


def test_record_event_creates_an_applied_job_once(mail_store):
    store = mail_store
    event = ApplicationEvent("received", company="Partners Group", job_title="AI Engineer")
    key = "application:partners:ai engineer"
    opp_id, job = store.record_application_event(USER, event, mail_id="m1", key=key, sender="hr@partnersgroup.com")
    assert job["status"] == ops.APPLIED and job["source"] == "mail" and job["company"] == "Partners Group"
    assert job["outcome"]["stage"] == "received"
    _, job = store.record_application_event(USER, ApplicationEvent("rejection"), mail_id="m2", opp_id=opp_id)
    assert job["outcome"]["result"] == "rejected" and job["alert_message_ids"] == ["m1", "m2"]
    with pytest.raises(ValueError):
        store.record_application_event(USER, event, mail_id="m3")


def test_record_event_on_a_drafted_job_marks_it_applied_and_links_the_letter(mail_store):
    store = mail_store
    opp_id, _, _ = store.capture(USER, url="https://example.com/jobs/1", text="posting", via="extension")
    store.claim_next_captured("b", user_id=USER)
    store.finish_drafting(opp_id, "b", ops.READY)
    _, job = store.record_application_event(USER, ApplicationEvent("received", company="Example AG"), mail_id="m1", opp_id=opp_id, letter_id="doc-9")
    assert job["status"] == ops.APPLIED and job["document_id"] == "doc-9" and job["company"] == "Example AG"
