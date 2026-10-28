"""Alert parsers on synthetic mails that copy each sender's plain-text layout."""
import json
from pathlib import Path

import pytest

from experimental.email.alert_parsing import parse_alert, parser_for
from letter_writer.opportunity_store import canonical_key, clean_url

ALERTS = Path(__file__).resolve().parents[1] / "fixtures"


def mail(name):
    return json.loads((ALERTS / name).read_text(encoding="utf-8"))


def test_jobs_ch_recommendations():
    result = parse_alert(mail("jobs_ch_recommendations.json"))
    assert result.parser == "jobs.ch"
    assert [(p.title, p.company, p.location) for p in result.proposals] == [
        ("Professional/Senior Software Engineer", "Fixture Appliances AG", "Zug"),
        ("Software Engineer – Industrial HMI, Control & Infrastructure (Rust/NixOS) (m/w/d)", "Example Tech AG", "Immensee"),
    ]
    first = result.proposals[0]
    assert canonical_key(first.url) == "jobs.ch:11111111-2222-4333-8444-555555555555"
    # HTML entities are unescaped, so tracking parameters are recognised and dropped.
    assert clean_url(first.url) == "https://www.jobs.ch/de/stellenangebote/detail/11111111-2222-4333-8444-555555555555"
    assert result.events == []


def test_linkedin_digest_lists_every_alert_and_dedupes():
    result = parse_alert(mail("linkedin_alert_digest.json"))
    assert result.parser == "linkedin"
    assert [(p.title, p.company, p.location) for p in result.proposals] == [
        ("Senior C++ Engineer (Robotics)", "Fixture Robotics AG", "Zurich"),
        ("Traineeprogramm Data & Analytics (m/w/d) / 100% / Bern oder Zürich - per 01.04.2027", "Example Authority FINMA-like", "Zurich"),
        ("Junior Data Scientist", "Example Hiring & Partners", "United Kingdom"),
    ]
    assert [canonical_key(p.url) for p in result.proposals] == ["linkedin:4100000001", "linkedin:4100000002", "linkedin:4100000003"]


def test_linkedin_application_confirmation_is_an_applied_signal_not_a_proposal():
    result = parse_alert(mail("linkedin_applied.json"))
    assert result.parser == "linkedin_applied"
    assert result.proposals == []
    assert len(result.events) == 1
    event = result.events[0]
    assert event.kind == "applied"
    assert event.company == "Example Compass"
    assert event.job_title == "Artificial Intelligence Engineer"
    assert canonical_key(event.job_url) == "linkedin:4100000010"


def test_linkedin_viewed_notice_is_an_event():
    m = mail("linkedin_applied.json")
    m["subject"] = "Your application was viewed by Example Compass"
    m["body"] = m["body"].replace("Your application was sent to Example Compass", "Your application was viewed by Example Compass")
    result = parse_alert(m)
    assert result.parser == "linkedin_viewed"
    assert [(e.kind, e.company, canonical_key(e.job_url)) for e in result.events] == [("viewed", "Example Compass", "linkedin:4100000010")]


def test_linkedin_jobs_mail_without_application_lists_jobs():
    m = mail("linkedin_applied.json")
    m["subject"] = "Example Chips is hiring"
    m["body"] = m["body"].replace("Your application was sent to Example Compass", "Apply to your saved jobs.")
    result = parse_alert(m)
    assert result.parser == "linkedin_jobs"
    assert [canonical_key(p.url) for p in result.proposals] == ["linkedin:4100000010", "linkedin:4100000011"]


def test_swissdevjobs_alert():
    result = parse_alert(mail("swissdevjobs_alert.json"))
    assert [(canonical_key(p.url), p.title, p.company, p.location) for p in result.proposals] == [
        ("swissdevjobs:fixture-systems-ag-senior-cpp-developer", "Senior C++ Developer", "Fixture Systems AG", "Zurich"),
        ("swissdevjobs:example-devices-embedded-engineer", "Embedded Engineer", "Example Devices", "Bern"),
    ]


def test_unknown_sender_is_unparsed_never_guessed():
    result = parse_alert(mail("unknown_sender.json"))
    assert result.unparsed
    assert result.proposals == [] and result.events == []
    assert "newsletter@example.com" in result.reason


@pytest.mark.parametrize(
    "sender,expected",
    [
        ("LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>", "parse_linkedin_alert"),
        ("JOBS-NOREPLY@LINKEDIN.COM", "parse_linkedin_jobs_mail"),
        ("jobs.ch <info@jobs.ch>", "parse_jobs_ch"),
        ("someone@linkedin.com.evil.example", None),
        ("info@jobs.ch.example", None),
    ],
)
def test_sender_routing_is_exact(sender, expected):
    parser = parser_for(sender)
    assert (parser.__name__ if parser else None) == expected


def test_malformed_mail_is_unparsed_not_raised():
    result = parse_alert({"message_id": "x", "sender": "info@jobs.ch", "body": None})
    assert result.parser in ("jobs.ch", "unparsed")
    assert result.proposals == []


def test_linkedin_application_update_reads_the_kind_from_its_marker():
    body = "Your update from Navique\n\n------\nLearn why: https://www.linkedin.com/help?lipi=urn%3Ali%3Apage%3Aemail_email_jobs_application_rejected_01%3BX&trk=eml-email_jobs_application_rejected_01-SecurityHelp"
    result = parse_alert({"message_id": "u1", "sender": "jobs-noreply@linkedin.com",
                          "subject": "Your application to Agentic AI Engineer 80-100 % (m/w/d) at Navique", "body": body})
    assert result.parser == "linkedin_rejection"
    assert [(e.kind, e.company, e.job_title) for e in result.events] == [("rejection", "Navique", "Agentic AI Engineer 80-100 % (m/w/d)")]
    unknown = parse_alert({"message_id": "u2", "sender": "jobs-noreply@linkedin.com", "subject": "Your application to X at Y", "body": "Your update from Y"})
    assert unknown.unparsed and unknown.proposals == []


def test_job_board_mail_about_an_application_goes_to_the_classifier():
    result = parse_alert({"message_id": "s1", "sender": "app@swissdevjobs.ch", "subject": "Your application at Scalera AG",
                          "body": "Thanks for applying https://swissdevjobs.ch/jobs/Scalera-AG-Engineer"})
    assert result.unparsed and result.proposals == []

