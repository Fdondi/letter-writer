"""/api/opportunities and the job-capture changes, on the Firestore emulator (no real services)."""
import time

import pytest
from fastapi.testclient import TestClient

from letter_writer import firestore_store
from letter_writer import opportunity_store as ops
from letter_writer.tests.fake_llm import patch_everywhere
from letter_writer_server.api import opportunities as api
from letter_writer_server.core.session import Session, get_session
from letter_writer_server.main import app

USER = "100200300400500600700"
JOB_URL = "https://www.jobs.ch/de/stellenangebote/detail/11111111-2222-4333-8444-555555555555/?utm_source=mail"


@pytest.fixture
def env(opportunity_store, monkeypatch):
    session = Session(
        {"user": {"id": USER, "email": "me@example.invalid"}, "auth_time": time.time(), "cv_text": "LIVE CV"},
        session_key="test-session",
    )
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[api.get_store] = lambda: opportunity_store
    monkeypatch.setattr(api, "_store", opportunity_store)
    monkeypatch.delenv("OPPORTUNITY_OWNER_USER_ID", raising=False)
    patch_everywhere(monkeypatch, firestore_store.get_user_data, lambda user_id, use_cache=True: {"cv_revisions": []})
    with TestClient(app) as client:
        yield client, session, opportunity_store
    app.dependency_overrides.clear()


def _ready_job(store, with_cv_in_state=True):
    opp_id, _, _ = store.capture(USER, url=JOB_URL, text="Posting", via="extension")
    store.claim_next_captured("b", user_id=USER)
    state = {
        "job_text": "Posting",
        "metadata": {"common": {"company_name": "Fixture Appliances AG"}},
        "vendors": {"openai": {"draft_letter": "D", "final_letter": "F", "letter_plan": "P", "feedback": {}}},
        "style_instructions": "S",
    }
    if with_cv_in_state:
        state["cv_text"] = "MUST NOT LEAK"
    store.save_state(opp_id, state)
    # save_state already drops cv_text; write it raw too, to prove /open/ strips it as well.
    if with_cv_in_state:
        store._state_ref(opp_id).set({**state})
    store.finish_drafting(opp_id, "b", ops.READY, {"vendors_done": ["openai"], "input_needed_count": 1})
    return opp_id


def test_list_and_triage(env):
    client, _, store = env
    proposed, _ = store.upsert_proposed(USER, url=JOB_URL, title="Engineer", company="Fixture Appliances AG")
    store.upsert_proposed("someone-else", url="https://example.com/other")
    res = client.get("/api/opportunities/")
    assert res.status_code == 200
    items = res.json()["opportunities"]
    assert [i["id"] for i in items] == [proposed]
    assert items[0]["has_capture"] is False and "capture" not in items[0]

    assert client.post(f"/api/opportunities/{proposed}/skip/", json={"reason": "too far"}).json()["opportunity"]["skip_reason"] == "too far"
    assert client.get("/api/opportunities/?status=proposed").json()["opportunities"] == []
    assert client.post(f"/api/opportunities/{proposed}/unskip/").json()["opportunity"]["status"] == ops.PROPOSED
    approved = client.post(f"/api/opportunities/{proposed}/approve/").json()["opportunity"]
    assert approved["status"] == ops.APPROVED
    # Approving twice is a conflict, not a silent no-op.
    assert client.post(f"/api/opportunities/{proposed}/approve/").status_code == 409


def test_other_users_jobs_are_not_found(env):
    client, _, store = env
    other, _ = store.upsert_proposed("someone-else", url="https://example.com/other")
    assert client.get(f"/api/opportunities/{other}/").status_code == 404
    assert client.post(f"/api/opportunities/{other}/approve/").status_code == 404
    assert client.post(f"/api/opportunities/{other}/capture/", json={"text": "x"}).status_code == 404
    assert client.post(f"/api/opportunities/{other}/open/").status_code == 404
    assert client.post("/api/opportunities/missing/approve/").status_code == 404


def test_manual_and_capture(env):
    client, _, store = env
    res = client.post("/api/opportunities/manual/", json={"url": JOB_URL, "title": "Engineer"})
    assert res.status_code == 200 and res.json()["opportunity_status"] == ops.APPROVED
    opp_id = res.json()["id"]
    res = client.post(f"/api/opportunities/{opp_id}/capture/", json={"text": "The posting text"})
    assert res.json()["opportunity_status"] == ops.CAPTURED
    full = client.get(f"/api/opportunities/{opp_id}/").json()["opportunity"]
    assert full["capture_text"] == "The posting text" and full["capture_via"] == "share_text"
    assert client.post(f"/api/opportunities/{opp_id}/capture/", json={"text": "  "}).status_code == 400
    assert client.post("/api/opportunities/manual/", json={}).status_code == 400


def test_open_loads_drafts_into_the_session_without_cv(env):
    client, session, store = env
    opp_id = _ready_job(store)
    res = client.post(f"/api/opportunities/{opp_id}/open/")
    assert res.status_code == 200, res.text
    body = res.json()
    assert "cv_text" not in body["session_state"]
    assert "MUST NOT LEAK" not in res.text
    assert body["session_state"]["vendors"]["openai"]["final_letter"] == "F"
    assert body["opportunity"]["id"] == opp_id
    # The cookie session now holds the drafts, keeps the signed-in user and the live CV.
    assert session["vendors"]["openai"]["draft_letter"] == "D"
    assert session["user"]["id"] == USER
    assert session["cv_text"] == "LIVE CV"
    assert session[api.SESSION_OPPORTUNITY_KEY] == opp_id


def test_open_before_drafts_is_a_conflict(env):
    client, _, store = env
    opp_id, _ = store.upsert_proposed(USER, url=JOB_URL)
    assert client.post(f"/api/opportunities/{opp_id}/open/").status_code == 409


def test_done_links_the_saved_letter(env):
    client, session, store = env
    opp_id = _ready_job(store, with_cv_in_state=False)
    client.post(f"/api/opportunities/{opp_id}/open/")
    res = client.post(f"/api/opportunities/{opp_id}/done/", json={"document_id": "doc-1"})
    assert res.status_code == 200
    assert store.get(opp_id)["status"] == ops.DONE
    assert store.get(opp_id)["document_id"] == "doc-1"
    assert api.SESSION_OPPORTUNITY_KEY not in session
    assert client.post(f"/api/opportunities/{opp_id}/done/", json={"document_id": "doc-2"}).status_code == 409


def test_retry_failed(env):
    client, _, store = env
    opp_id, _, _ = store.capture(USER, url=JOB_URL, text="t", via="extension")
    store.claim_next_captured("b", user_id=USER)
    store.finish_drafting(opp_id, "b", ops.FAILED, {"vendors_failed": {"openai": "x"}})
    assert client.post(f"/api/opportunities/{opp_id}/retry/").json()["opportunity"]["status"] == ops.CAPTURED


# --- job capture --------------------------------------------------------------------------------


@pytest.fixture
def capture_env(opportunity_store, monkeypatch, tmp_path):
    monkeypatch.setenv("JOB_CAPTURE_STASH_DIR", str(tmp_path))
    monkeypatch.setattr(api, "_store", opportunity_store)
    monkeypatch.setattr("letter_writer_server.core.job_capture_stash._STASH_DIR", tmp_path, raising=False)
    with TestClient(app) as client:
        yield client, opportunity_store


def test_ingest_without_owner_only_stashes(capture_env, monkeypatch):
    client, store = capture_env
    monkeypatch.delenv("OPPORTUNITY_OWNER_USER_ID", raising=False)
    opp_id, _, _ = store.capture(USER, url=JOB_URL, via="share_url")
    res = client.post("/api/job-capture/ingest/", json={"url": JOB_URL, "text": "Posting"})
    assert res.status_code == 200 and "capture_id" in res.json()
    assert store.get(opp_id)["status"] == ops.APPROVED
    assert client.get("/api/job-capture/pending/").json()["opportunities"] == []


def test_ingest_attaches_to_the_owners_approved_job(capture_env, monkeypatch):
    client, store = capture_env
    monkeypatch.setenv("OPPORTUNITY_OWNER_USER_ID", USER)
    opp_id, _, _ = store.capture(USER, url=JOB_URL, via="share_url")
    pending = client.get("/api/job-capture/pending/").json()["opportunities"]
    assert pending == [{"id": opp_id, "url": ops.clean_url(JOB_URL), "canonical_key": ops.canonical_key(JOB_URL)}]

    other_url = JOB_URL.replace("?utm_source=mail", "?utm_source=extension&source=x")
    assert [o["id"] for o in client.get("/api/job-capture/pending/", params={"url": other_url}).json()["opportunities"]] == [opp_id]
    assert client.get("/api/job-capture/pending/", params={"url": "https://www.jobs.ch/de/other"}).json()["opportunities"] == []
    res = client.post("/api/job-capture/ingest/", json={"url": other_url, "text": "Posting from the page", "html": "<p>x</p>"})
    assert res.json() == {"status": "ok", "opportunity_id": opp_id, "opportunity_status": ops.CAPTURED, "message": res.json()["message"]}
    opp = store.get(opp_id)
    assert opp["status"] == ops.CAPTURED and opp["capture"]["via"] == "extension"
    assert client.get("/api/job-capture/pending/").json()["opportunities"] == []

    # A page that is not an approved job still goes to the stash for the interactive intake.
    res = client.post("/api/job-capture/ingest/", json={"url": "https://example.com/jobs/9", "text": "Other"})
    assert "capture_id" in res.json()


def test_ingest_queue_creates_a_captured_job(capture_env, monkeypatch):
    client, store = capture_env
    monkeypatch.setenv("OPPORTUNITY_OWNER_USER_ID", USER)
    res = client.post(
        "/api/job-capture/ingest/",
        json={"url": JOB_URL, "title": "Engineer at Fixture Appliances", "text": "Posting from the page", "queue": True},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["opportunity_status"] == ops.CAPTURED
    assert "desktop drafts it" in body["message"]
    opp = store.get(body["opportunity_id"])
    assert opp["status"] == ops.CAPTURED
    assert opp["capture"]["text"] == "Posting from the page"
    assert opp["capture"]["via"] == "extension"
    assert opp["title"] == "Engineer at Fixture Appliances"
    assert opp["url"] == ops.clean_url(JOB_URL)
    # Queued for the batch: not waiting for posting text anymore.
    assert client.get("/api/job-capture/pending/").json()["opportunities"] == []


def test_ingest_queue_follows_the_phones_capture_rules(capture_env, monkeypatch):
    client, store = capture_env
    monkeypatch.setenv("OPPORTUNITY_OWNER_USER_ID", USER)
    # An approved job gets the posting text attached and is queued.
    opp_id, _, _ = store.capture(USER, url=JOB_URL, via="share_url")
    res = client.post("/api/job-capture/ingest/", json={"url": JOB_URL, "text": "Posting", "queue": True})
    assert res.json()["opportunity_id"] == opp_id
    assert store.get(opp_id)["status"] == ops.CAPTURED

    # A job the desktop already drafted is not queued again.
    store.claim_next_captured("b", user_id=USER)
    store.finish_drafting(opp_id, "b", ops.READY, {"vendors_done": ["openai"]})
    res = client.post("/api/job-capture/ingest/", json={"url": JOB_URL, "text": "Posting v2", "queue": True})
    assert res.json()["opportunity_status"] == ops.READY
    assert "already ready" in res.json()["message"]
    assert store.get(opp_id)["capture"]["text"] == "Posting"


def test_ingest_queue_without_owner_stashes(capture_env, monkeypatch):
    client, store = capture_env
    monkeypatch.delenv("OPPORTUNITY_OWNER_USER_ID", raising=False)
    res = client.post("/api/job-capture/ingest/", json={"url": JOB_URL, "text": "Posting", "queue": True})
    assert res.status_code == 200
    assert "capture_id" in res.json()
    assert "note" in res.json()
    assert store.list_for_user(USER) == []


def test_saving_the_letter_of_an_opened_job_marks_it_done(env):
    client, session, store = env
    opp_id = _ready_job(store, with_cv_in_state=False)
    client.post(f"/api/opportunities/{opp_id}/open/")
    assert api.finish_session_opportunity(session, USER, "doc-9") == {"opportunity_id": opp_id}
    assert store.get(opp_id)["status"] == ops.DONE and store.get(opp_id)["document_id"] == "doc-9"
    # Later saves of the same letter, and letters not from a job, change nothing.
    assert api.finish_session_opportunity(session, USER, "doc-9") == {}
    assert store.get(opp_id)["document_id"] == "doc-9"
