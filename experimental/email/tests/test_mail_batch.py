"""Mail commands end to end: Firestore emulator, stub classifiers, no real services."""
import json
from pathlib import Path

import pytest

from experimental.email import mail_batch
from experimental.email.application_tracking import ApplicationEvent
from letter_writer import opportunity_store as ops

USER = "100200300400500600700"
ALERTS = Path(__file__).resolve().parents[1] / "fixtures"


def _mail_file(tmp_path, names):
    path = tmp_path / "mail.jsonl"
    path.write_text("\n".join(json.dumps(json.loads((ALERTS / n).read_text(encoding="utf-8"))) for n in names) + "\nnot json\n", encoding="utf-8")
    return path


@pytest.fixture
def no_mail_history(monkeypatch):
    """No saved letters, and a classifier that finds nothing (tests that need one pass their own)."""
    monkeypatch.setattr(mail_batch, "load_letters", lambda user_id, collection=None: [])
    monkeypatch.setattr(mail_batch, "default_classifier", lambda: (lambda mail: None))


def test_propose_creates_jobs_once_and_records_every_mail(mail_store, tmp_path, capsys, monkeypatch, no_mail_history):
    monkeypatch.setenv("LW_USER_ID", USER)
    monkeypatch.setattr(mail_batch, "REVIEW_DIR", tmp_path / "review")
    store = mail_store
    path = _mail_file(tmp_path, ["jobs_ch_recommendations.json", "linkedin_alert_digest.json", "linkedin_applied.json", "unknown_sender.json"])
    assert mail_batch.main(["propose", "--mail-file", str(path)], store=store) == 0
    stats = json.loads(capsys.readouterr().out)
    assert stats == {
        "mails": 4, "skipped_seen": 0, "new": 5, "seen_again": 0, "already_applied": 0,
        "application_events": 1, "ignored": 0, "unparsed": 0, "for_review": 1, "bad_lines": 1,
    }
    # Mail no template knows is kept for manual review, not sent to a model.
    kept = json.loads((tmp_path / "review" / "fixture-unknown.json").read_text(encoding="utf-8"))
    assert kept["sender"] == "newsletter@example.com" and kept["reason"]

    jobs = {j["canonical_key"]: j for j in store.list_for_user(USER)}
    vzug = jobs["jobs.ch:11111111-2222-4333-8444-555555555555"]
    assert (vzug["status"], vzug["title"], vzug["company"], vzug["location"]) == (ops.PROPOSED, "Professional/Senior Software Engineer", "Fixture Appliances AG", "Zug")
    assert vzug["alert_message_ids"] == ["fixture-jobs-ch"]
    assert jobs["linkedin:4100000010"]["status"] == ops.APPLIED
    assert jobs["linkedin:4100000010"]["company"] == "Example Compass"
    assert jobs["linkedin:4100000010"]["outcome"]["stage"] == "applied"
    assert store.alert_processed(USER, "fixture-unknown")

    # Run again (the routine searches the last 3 days): nothing is processed twice.
    mail_batch.main(["propose", "--mail-file", str(path)], store=store)
    again = json.loads(capsys.readouterr().out)
    assert again["skipped_seen"] == 4 and again["new"] == 0


def test_applied_mail_flips_a_proposed_job(mail_store):
    store = mail_store
    opp_id, _ = store.upsert_proposed(USER, url="https://www.linkedin.com/jobs/view/4100000010/", title="AI Engineer")
    applied = json.loads((ALERTS / "linkedin_applied.json").read_text(encoding="utf-8"))
    stats = mail_batch.propose(store, USER, [applied], letters=[])
    assert stats["application_events"] == 1
    assert store.get(opp_id)["status"] == ops.APPLIED


def test_propose_dry_run_touches_nothing(tmp_path, capsys, monkeypatch, no_mail_history):
    monkeypatch.delenv("LW_USER_ID", raising=False)

    class NoStore:
        def __getattr__(self, name):
            raise AssertionError(f"dry run used the store ({name})")

    path = _mail_file(tmp_path, ["jobs_ch_recommendations.json", "linkedin_applied.json", "unknown_sender.json"])
    assert mail_batch.main(["propose", "--mail-file", str(path), "--dry-run"], store=NoStore()) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert sum(r.get("action") == "propose" for r in rows) == 2
    assert sum(r.get("action") == "applied" for r in rows) == 1
    assert sum(r.get("action") == "classify" for r in rows) == 1
    assert rows[-1] == {"mails": 3, "bad_lines": 1, "dry_run": True}


def test_unseen_prints_only_new_message_ids(mail_store, capsys, monkeypatch):
    monkeypatch.setenv("LW_USER_ID", USER)
    mail_store.record_alert(USER, "m-old", parser="jobs.ch", opportunity_ids=[])
    mail_batch.main(["unseen", "m-old", "m-new", "m-new", "m-other"], store=mail_store)
    assert capsys.readouterr().out.split() == ["m-new", "m-other"]




def _alert(message_id, sender, subject, body):
    return {"message_id": message_id, "sender": sender, "subject": subject, "date": "2026-10-20T08:00:00Z", "body": body}


def test_proposals_you_already_applied_to_are_not_proposed_again(mail_store):
    store = mail_store
    uuid_a, uuid_b = "11111111-2222-4333-8444-555555555555", "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    letters = [
        {"id": "doc-exact", "company_name": "Fixture Appliances AG", "role": "Senior Software Engineer",
         "source_url": f"https://www.jobs.ch/de/stellenangebote/detail/{uuid_a}/", "created_at": "2026-05-01T10:00:00"},
        {"id": "doc-fuzzy", "company_name": "Example Tech", "role": "Software Engineer – Industrial HMI, Control & Infrastructure",
         "source_url": "", "created_at": "2026-06-01T10:00:00"},
    ]
    mail = json.loads((ALERTS / "jobs_ch_recommendations.json").read_text(encoding="utf-8"))
    stats = mail_batch.propose(store, USER, [mail], letters=letters, classifier=lambda m: pytest.fail("alerts are parsed, not classified"))
    assert stats["already_applied"] == 2 and stats["new"] == 0
    jobs = {j["canonical_key"]: j for j in store.list_for_user(USER)}
    exact = jobs[f"jobs.ch:{uuid_a}"]
    assert exact["status"] == ops.APPLIED and exact["document_id"] == "doc-exact"
    fuzzy = jobs[f"jobs.ch:{uuid_b}"]
    assert fuzzy["status"] == ops.SKIPPED and fuzzy["auto_skipped"] is True
    assert fuzzy["skip_reason"].startswith("Already applied? Letter to Example Tech")
    # Skipped this way can be restored like any skip.
    store.set_status(fuzzy["id"], ops.PROPOSED, from_states=[ops.SKIPPED], user_id=USER)


def test_another_role_at_a_company_you_applied_to_is_proposed_with_a_note(mail_store):
    store = mail_store
    letters = [{"id": "d1", "company_name": "Fixture Robotics AG", "role": "Head of Sales", "created_at": "2026-04-01T00:00:00"}]
    mail = json.loads((ALERTS / "linkedin_alert_digest.json").read_text(encoding="utf-8"))
    mail_batch.propose(store, USER, [mail], letters=letters)
    job = {j["canonical_key"]: j for j in store.list_for_user(USER)}["linkedin:4100000001"]
    assert job["status"] == ops.PROPOSED
    assert job["history_note"] == "You applied to Fixture Robotics AG before (Head of Sales, 2026-04-01)."


def test_application_mails_update_or_create_jobs_and_outcomes(mail_store, emulator_db):
    import uuid as _uuid

    store = mail_store
    letters_col = emulator_db.collection(f"documents_{_uuid.uuid4().hex[:8]}")
    letters_col.document("doc-hamilton").set({"user_id": USER, "company_name": "Hamilton", "role": "Senior AI Software Engineer", "created_at": "2026-10-10"})
    ready_id, _, _ = store.capture(USER, url="https://example.com/stadler/123", text="posting", via="extension", company="Stadler", title="Senior Rail Signalling Engineer")
    store.claim_next_captured("b", user_id=USER)
    store.finish_drafting(ready_id, "b", ops.READY)

    replies = {
        "pg-1": ApplicationEvent("received", company="Partners Group", job_title="AI Engineer", summary="Received."),
        "pg-2": ApplicationEvent("rejection", company="Partners Group AG", job_title="AI Engineer (16518)", summary="Rejected."),
        "st-1": ApplicationEvent("received", company="Stadler Rail", job_title="Senior Rail Signalling Engineer"),
        "ha-1": ApplicationEvent("interview", company="Hamilton", job_title="Senior AI Software Engineer / AI Solution Architect 80 - 100 % (w/m/d)",
                                 positive_feedback=True, feedback_quote="Your profile convinced the team."),
        "news": None,
    }

    def classify(mail):
        if mail["message_id"] == "boom":
            raise RuntimeError("model unavailable")
        return replies[mail["message_id"]]

    mails = [_alert(mid, "hr@example.com", f"Subject {mid}", "Body") for mid in ["pg-1", "pg-2", "st-1", "ha-1", "news", "boom"]]
    stats = mail_batch.propose(store, USER, mails, letters=mail_batch.load_letters(USER, letters_col), classifier=classify, letters_collection=letters_col)
    assert stats["application_events"] == 4 and stats["ignored"] == 1 and stats["unparsed"] == 1

    jobs = store.list_for_user(USER)
    pg = [j for j in jobs if j.get("company", "").startswith("Partners Group")]
    assert len(pg) == 1, "receipt and rejection are the same application"
    assert pg[0]["status"] == ops.APPLIED and pg[0]["source"] == "mail"
    assert pg[0]["outcome"]["result"] == "rejected" and pg[0]["outcome"]["rejected_at_stage"] == "received"

    stadler = store.get(ready_id)
    assert stadler["status"] == ops.APPLIED and stadler["outcome"]["stage"] == "received"

    hamilton = next(j for j in jobs if j.get("document_id") == "doc-hamilton")
    assert hamilton["outcome"]["stage"] == "interview" and hamilton["outcome"]["positive_feedback"] is True
    letter = letters_col.document("doc-hamilton").get().to_dict()
    assert letter["application_outcome"]["stage"] == "interview"
    assert letter["application_outcome"]["feedback_quotes"] == ["Your profile convinced the team."]

    assert store.alert_processed(USER, "news") and store.alert_processed(USER, "boom")
    # The same mails again change nothing.
    again = mail_batch.propose(store, USER, mails, letters=[], classifier=classify, letters_collection=letters_col)
    assert again["skipped_seen"] == 6 and again["application_events"] == 0


def test_a_proposal_for_a_job_known_from_mail_is_skipped(mail_store):
    store = mail_store
    store.record_application_event(USER, ApplicationEvent("received", company="Example Tech AG", job_title="Software Engineer – Industrial HMI"),
                                   mail_id="m1", key="application:example tech:industrial hmi software engineer")
    mail = json.loads((ALERTS / "jobs_ch_recommendations.json").read_text(encoding="utf-8"))
    mail_batch.propose(store, USER, [mail], letters=[])
    skipped = [j for j in store.list_for_user(USER) if j.get("status") == ops.SKIPPED]
    assert len(skipped) == 1 and "Application to Example Tech AG" in skipped[0]["skip_reason"]


def test_outcomes_command(mail_store, capsys, monkeypatch):
    monkeypatch.setenv("LW_USER_ID", USER)
    store = mail_store
    store.record_application_event(USER, ApplicationEvent("interview", company="A AG", job_title="Engineer"), mail_id="m1", key="application:a:engineer", letter_id="d1")
    store.record_application_event(USER, ApplicationEvent("rejection", company="B AG", job_title="Engineer"), mail_id="m2", key="application:b:engineer")
    mail_batch.main(["outcomes"], store=store)
    out = capsys.readouterr().out.splitlines()
    assert any(line.startswith("letter  interview") and "A AG" in line for line in out)
    assert any("applied · rejected" in line and "B AG" in line for line in out)
    summary = json.loads(out[-1])
    assert summary["with_letter"]["interview_or_further"] == 1 and summary["without_letter"]["rejected"] == 1


def test_dry_run_can_preview_classification(tmp_path, capsys, monkeypatch, no_mail_history):
    monkeypatch.setattr(mail_batch, "default_classifier", lambda: (lambda mail: ApplicationEvent("rejection", company="Viseca", summary="Not moving forward.")))
    path = tmp_path / "mail.jsonl"
    path.write_text(json.dumps(_alert("v1", "peopleandculture@example.com", "your application", "…")) + "\n", encoding="utf-8")
    mail_batch.main(["propose", "--mail-file", str(path), "--dry-run", "--classify"], store=object())
    row = json.loads(capsys.readouterr().out.splitlines()[0])
    assert row["classified"] == {"kind": "rejection", "company": "Viseca", "summary": "Not moving forward."}


def test_noise_senders_are_learned_and_left_out(mail_store, capsys, monkeypatch):
    monkeypatch.setenv("LW_USER_ID", USER)
    store = mail_store
    news = lambda mid: _alert(mid, "Jobs Newsletter <recommender@news.example.com>", "Jobs you may like", "…")
    mail_batch.propose(store, USER, [news("n1")], letters=[], classifier=lambda m: None)
    assert store.noise_senders(USER) == set()  # once is not a pattern
    mail_batch.propose(store, USER, [news("n2")], letters=[], classifier=lambda m: None)
    assert store.noise_senders(USER) == {"recommender@news.example.com"}
    # A sender that ever sent application news is never noise.
    hr = lambda mid, kind: _alert(mid, "hr@company.example.com", "Your application", "…")
    mail_batch.propose(store, USER, [hr("h1", None), hr("h2", None)], letters=[], classifier=lambda m: None)
    mail_batch.propose(store, USER, [hr("h3", None)], letters=[], classifier=lambda m: ApplicationEvent("rejection", company="Company"))
    assert store.noise_senders(USER) == {"recommender@news.example.com"}

    monkeypatch.setenv("LW_MAIL_IGNORE_SENDERS", "promo@courses.example.com")
    mail_batch.main(["unseen", "n3:recommender@news.example.com", "n1:recommender@news.example.com", "h4:hr@company.example.com",
                "p1:Courses <promo@courses.example.com>", "plain-id", "h4:hr@company.example.com"], store=store)
    captured = capsys.readouterr()
    assert captured.out.split() == ["h4", "plain-id"]
    assert "3 message(s) from noise senders left out" in captured.err



def test_mark_applied_by_company_matches_legal_suffixes(mail_store):
    store = mail_store
    open_id, _ = store.upsert_proposed(USER, url="https://example.com/a", company="V-ZUG AG")
    ready_id, _, _ = store.capture(USER, url="https://example.com/b", text="t", via="extension", company="v-zug")
    other_id, _ = store.upsert_proposed(USER, url="https://example.com/c", company="Zühlke")
    store.claim_next_captured("b", user_id=USER)
    store.finish_drafting(ready_id, "b", ops.READY)
    changed = store.mark_applied_by_company(USER, "V-ZUG", alert_message_id="applied-1")
    assert sorted(changed) == sorted([open_id, ready_id])
    assert store.get(open_id)["status"] == ops.APPLIED
    assert store.get(open_id)["alert_message_ids"] == ["applied-1"]
    assert store.get(other_id)["status"] == ops.PROPOSED
    assert store.mark_applied_by_company(USER, "") == []
