"""Opportunity keys (shared with the Android app) and the Firestore store (local emulator)."""
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from letter_writer import opportunity_store as ops
from letter_writer.opportunity_store import (
    APPLIED,
    APPROVED,
    ARCHIVED,
    CAPTURED,
    DONE,
    DRAFTING,
    FAILED,
    PROPOSED,
    RATED,
    READY,
    SKIPPED,
    OwnershipError,
    TransitionError,
)

FIXTURE = json.loads((Path(__file__).parent / "tests" / "fixtures" / "opportunity_keys.json").read_text(encoding="utf-8"))
USER = FIXTURE["user_id"]
JOB_URL = "https://www.jobs.ch/de/stellenangebote/detail/6ef0e053-1d7a-45bc-b9a7-a32dd1dfb5f7/?source=jobmail"


@pytest.mark.parametrize("case", FIXTURE["canonical_keys"], ids=lambda c: c["url"][:60])
def test_canonical_key_clean_url_and_source(case):
    assert ops.canonical_key(case["url"]) == case["canonical_key"]
    assert ops.clean_url(case["url"]) == case["clean_url"]
    assert ops.source_of(case["canonical_key"]) == case["source"]


def test_text_keys_and_document_ids():
    for case in FIXTURE["text_keys"]:
        assert ops.text_key(case["text"]) == case["text_key"]
    for case in FIXTURE["document_ids"]:
        assert ops.document_id(USER, case["canonical_key"]) == case["document_id"]


def test_document_id_depends_on_user():
    assert ops.document_id("a", "linkedin:1") != ops.document_id("b", "linkedin:1")


def test_transition_table_rejects_illegal_moves():
    ops.check_transition(PROPOSED, APPROVED)
    for current, target in [(PROPOSED, READY), (APPLIED, PROPOSED), (DONE, CAPTURED), (CAPTURED, READY), (READY, DRAFTING)]:
        with pytest.raises(TransitionError):
            ops.check_transition(current, target)
    with pytest.raises(TransitionError):
        ops.check_transition(PROPOSED, APPROVED, from_states=[SKIPPED])


# --- store on the emulator -------------------------------------------------------------------


def test_upsert_proposed_merges_and_never_downgrades(opportunity_store):
    store = opportunity_store
    opp_id, created = store.upsert_proposed(USER, url=JOB_URL, title="Engineer", company="", alert_message_id="m1")
    assert created
    again_id, created_again = store.upsert_proposed(
        USER, url=JOB_URL.replace("?source=jobmail", "?utm_source=x"), company="V-ZUG AG", alert_message_id="m2"
    )
    assert (again_id, created_again) == (opp_id, False)
    doc = store.get(opp_id)
    assert doc["status"] == PROPOSED
    assert doc["title"] == "Engineer" and doc["company"] == "V-ZUG AG"
    assert doc["alert_message_ids"] == ["m1", "m2"]
    assert doc["url"] == "https://www.jobs.ch/de/stellenangebote/detail/6ef0e053-1d7a-45bc-b9a7-a32dd1dfb5f7"
    assert doc["canonical_key"] == "jobs.ch:6ef0e053-1d7a-45bc-b9a7-a32dd1dfb5f7"

    store.set_status(opp_id, APPROVED, from_states=[PROPOSED], user_id=USER)
    store.upsert_proposed(USER, url=JOB_URL, title="Other title", alert_message_id="m2")
    doc = store.get(opp_id)
    assert doc["status"] == APPROVED
    assert doc["title"] == "Engineer"
    assert doc["alert_message_ids"] == ["m1", "m2"]


def test_set_status_checks_from_states_owner_and_table(opportunity_store):
    store = opportunity_store
    opp_id, _ = store.upsert_proposed(USER, url=JOB_URL)
    with pytest.raises(TransitionError):
        store.set_status(opp_id, APPROVED, from_states=[SKIPPED])
    with pytest.raises(TransitionError):
        store.set_status(opp_id, READY)
    with pytest.raises(OwnershipError):
        store.set_status(opp_id, APPROVED, user_id="intruder")
    doc = store.set_status(opp_id, SKIPPED, user_id=USER, fields={"skip_reason": "too far"})
    assert doc["status"] == SKIPPED and doc["skip_reason"] == "too far"
    with pytest.raises(KeyError):
        store.set_status("missing", APPROVED)


def test_capture_rules_match_the_phone(opportunity_store):
    store = opportunity_store
    link_id, status, _ = store.capture(USER, url=JOB_URL, via="share_url")
    assert status == APPROVED
    same_id, status, _ = store.capture(USER, url=JOB_URL, text="Posting text", via="extension")
    assert (same_id, status) == (link_id, CAPTURED)
    assert store.get(link_id)["capture"]["text"] == "Posting text"

    text_id, status, _ = store.capture(USER, text="  Pasted   job ", via="share_text")
    assert status == CAPTURED
    assert store.get(text_id)["canonical_key"] == ops.text_key("Pasted job")

    store.claim_next_captured("batch-1", user_id=USER, exclude=[text_id])
    _, status, message = store.capture(USER, url=JOB_URL, text="New text", via="extension")
    assert status == DRAFTING and "drafting" in message
    assert store.get(link_id)["capture"]["text"] == "Posting text"

    with pytest.raises(ValueError):
        store.capture(USER, via="share_text")
    with pytest.raises(OwnershipError):
        store.attach_capture(link_id, "intruder", text="x", via="share_text")


def test_attach_capture_queues_a_failed_job_again(opportunity_store):
    store = opportunity_store
    opp_id, _ = store.upsert_proposed(USER, url=JOB_URL)
    store.capture(USER, url=JOB_URL, text="v1", via="extension")
    store.claim_next_captured("b", user_id=USER)
    store.finish_drafting(opp_id, "b", FAILED, {"vendors_failed": {"openai": "boom"}})
    status, _ = store.attach_capture(opp_id, USER, text="v2", via="share_text")
    assert status == CAPTURED
    assert store.get(opp_id)["capture"]["text"] == "v2"


def test_claim_takes_oldest_capture_and_finish_releases_the_lease(opportunity_store):
    store = opportunity_store
    first, _, _ = store.capture(USER, url="https://example.com/jobs/1", text="one", via="extension")
    second, _, _ = store.capture(USER, url="https://example.com/jobs/2", text="two", via="extension")
    claimed = store.claim_next_captured("batch-a", lease_s=600, user_id=USER)
    assert claimed["id"] == first
    assert claimed["status"] == DRAFTING and claimed["lease"]["owner"] == "batch-a"
    assert store.claim_next_captured("batch-a", user_id=USER)["id"] == second
    assert store.claim_next_captured("batch-a", user_id=USER) is None

    with pytest.raises(TransitionError):
        store.finish_drafting(first, "someone-else", READY)
    done = store.finish_drafting(first, "batch-a", READY, {"vendors_done": ["openai"]})
    assert done["status"] == READY and done["lease"] is None and done["vendors_done"] == ["openai"]
    with pytest.raises(TransitionError):
        store.finish_drafting(first, "batch-a", DONE)


def test_expired_lease_is_reclaimed(opportunity_store):
    store = opportunity_store
    opp_id, _, _ = store.capture(USER, url=JOB_URL, text="t", via="extension")
    store.claim_next_captured("crashed-run", lease_s=3600, user_id=USER)
    assert store.claim_next_captured("next-run", user_id=USER) is None
    store._ref(opp_id).update({"lease": {"owner": "crashed-run", "until": datetime.now(timezone.utc) - timedelta(seconds=1)}})
    reclaimed = store.claim_next_captured("next-run", user_id=USER)
    assert reclaimed["id"] == opp_id and reclaimed["lease"]["owner"] == "next-run"
    with pytest.raises(TransitionError):
        store.finish_drafting(opp_id, "crashed-run", READY)


def test_concurrent_claims_never_double_claim(opportunity_store):
    store = opportunity_store
    ids = {store.capture(USER, url=f"https://example.com/jobs/{i}", text=f"job {i}", via="extension")[0] for i in range(4)}
    claims = []
    lock = threading.Lock()

    def worker(name):
        while True:
            got = store.claim_next_captured(name, user_id=USER)
            if got is None:
                return
            with lock:
                claims.append((name, got["id"]))

    threads = [threading.Thread(target=worker, args=(f"batch-{n}",)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    claimed_ids = [c[1] for c in claims]
    assert sorted(claimed_ids) == sorted(ids)
    assert len(claimed_ids) == len(set(claimed_ids))
    for name, opp_id in claims:
        assert store.get(opp_id)["lease"]["owner"] == name


def test_state_subdocument_never_stores_cv_and_is_firestore_safe(opportunity_store):
    store = opportunity_store
    opp_id, _, _ = store.capture(USER, url=JOB_URL, text="t", via="extension")
    store.save_state(opp_id, {"job_text": "J", "cv_text": "SECRET CV", "vendors": {"openai": {"draft_letter": "D"}}, "matrix": [[1, 2], [3]]})
    state = store.load_state(opp_id, USER)
    assert "cv_text" not in state
    assert state["vendors"]["openai"]["draft_letter"] == "D"
    assert state["matrix"] == ["[1, 2]", "[3]"]
    assert store.load_state(opp_id) == state
    with pytest.raises(OwnershipError):
        store.load_state(opp_id, "intruder")
    # The parent document stays small: drafts live only in the subdocument.
    assert "vendors" not in store.get(opp_id)


def test_list_for_user_filters_and_sorts(opportunity_store):
    store = opportunity_store
    a, _ = store.upsert_proposed(USER, url="https://example.com/a")
    b, _ = store.upsert_proposed(USER, url="https://example.com/b")
    store.upsert_proposed("other-user", url="https://example.com/c")
    store.set_status(a, SKIPPED)
    listed = store.list_for_user(USER)
    assert [i["id"] for i in listed] == [a, b]
    assert [i["id"] for i in store.list_for_user(USER, [PROPOSED])] == [b]


def test_rated_and_archived_lifecycle(opportunity_store):
    store = opportunity_store
    opp_id, _, _ = store.capture(USER, url=JOB_URL, text="text", via="extension")
    # The desktop's rating pass: captured -> rated with the fit fields.
    rated = store.set_status(opp_id, RATED, from_states=[CAPTURED], user_id=USER, fields={"fit_score": 4.2, "fit_rated_at": datetime.now(timezone.utc)})
    assert rated["status"] == RATED and rated["fit_score"] == 4.2
    # The daemon picks it: rated -> drafting under a lease, stamped processed_at.
    claimed = store.claim_for_drafting(opp_id, "batch-a", user_id=USER)
    assert claimed["status"] == DRAFTING and claimed["lease"]["owner"] == "batch-a"
    assert ops.as_utc(claimed["processed_at"]) is not None
    # Another run cannot take it while the lease holds.
    assert store.claim_for_drafting(opp_id, "batch-b", user_id=USER) is None
    store.finish_drafting(opp_id, "batch-a", READY)

    # A rated job the desktop never drafts is archived, then re-enabled by the user.
    opp2, _, _ = store.capture(USER, url="https://example.com/jobs/2", text="two", via="extension")
    store.set_status(opp2, RATED, from_states=[CAPTURED], user_id=USER, fields={"fit_rated_at": datetime.now(timezone.utc) - timedelta(days=4)})
    archived = store.set_status(opp2, ARCHIVED, from_states=[RATED], user_id=USER, fields={"archived_at": datetime.now(timezone.utc)})
    assert archived["status"] == ARCHIVED
    reenabled = store.set_status(opp2, RATED, from_states=[ARCHIVED], user_id=USER, fields={"fit_score_user": 5.0})
    assert reenabled["status"] == RATED and reenabled["fit_score_user"] == 5.0
    # New posting text re-queues a rated or archived job for the rating pass.
    status, _ = store.attach_capture(opp2, USER, text="new text", via="share_text")
    assert status == CAPTURED


def test_rated_and_archived_transition_table():
    for current, target in [(CAPTURED, RATED), (CAPTURED, FAILED), (RATED, DRAFTING), (RATED, ARCHIVED), (ARCHIVED, RATED), (ARCHIVED, CAPTURED)]:
        ops.check_transition(current, target)
    for current, target in [(RATED, READY), (ARCHIVED, DRAFTING), (PROPOSED, RATED), (APPLIED, ARCHIVED), (APPLIED, RATED)]:
        with pytest.raises(TransitionError):
            ops.check_transition(current, target)


def test_set_fit_score_checks_owner_and_status(opportunity_store):
    store = opportunity_store
    opp_id, _, _ = store.capture(USER, url=JOB_URL, text="text", via="extension")
    doc = store.set_fit_score(opp_id, 4.5, user_id=USER)
    assert doc["fit_score_user"] == 4.5
    doc = store.set_fit_score(opp_id, None, user_id=USER)
    assert doc["fit_score_user"] is None
    with pytest.raises(OwnershipError):
        store.set_fit_score(opp_id, 3.0, user_id="intruder")
    with pytest.raises(KeyError):
        store.set_fit_score("missing", 3.0, user_id=USER)
    store.claim_next_captured("b", user_id=USER)
    with pytest.raises(TransitionError):
        store.set_fit_score(opp_id, 3.0, user_id=USER)


def test_claim_for_drafting_only_takes_waiting_jobs(opportunity_store):
    store = opportunity_store
    opp_id, _, _ = store.capture(USER, url=JOB_URL, text="text", via="extension")
    assert store.claim_for_drafting(opp_id, "b", user_id=USER)["status"] == DRAFTING
    # Already drafting with a live lease: not claimable; once finished, it stays untouched.
    assert store.claim_for_drafting(opp_id, "b", user_id=USER) is None
    store.finish_drafting(opp_id, "b", READY)
    assert store.claim_for_drafting(opp_id, "b", user_id=USER) is None
