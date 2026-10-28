"""Headless sessions: phased_service without a request, in parallel threads, on fake clients."""
import threading

import pytest

from letter_writer import client as client_module
from letter_writer import firestore_store, session_store
from letter_writer.clients.base import ModelVendor
from letter_writer.headless import (
    headless_session,
    initial_session,
    persistable_state,
    run_vendors_parallel,
)
from letter_writer.phased_service import (
    VendorPhaseState,
    advance_to_draft,
    advance_to_plan,
    advance_to_refinement,
)
from letter_writer.tests.fake_llm import FakeClient, fake_get_client_factory, patch_everywhere

USER = "user-1"
PROFILE = {
    "cv_revisions": [
        {"content": "OLD CV", "created_at": "2025-01-01T00:00:00"},
        {"content": "NEW CV: C++ and CUDA", "created_at": "2026-05-01T00:00:00"},
    ],
    "style": {"value": "Write short sentences.", "updated_at": "2026-01-01"},
}


@pytest.fixture
def fakes(monkeypatch):
    def install(fail=None):
        patch_everywhere(monkeypatch, client_module.get_client, fake_get_client_factory(fail))
        patch_everywhere(monkeypatch, firestore_store.get_user_data, lambda user_id, use_cache=True: PROFILE)

    install()
    FakeClient.calls.clear()
    return install


def _common():
    data = initial_session(USER, PROFILE)
    data["job_text"] = "FAKE Fixture Engineer at FAKE Fixture Works. C++, CUDA."
    data["metadata"] = {"common": {"company_name": "FAKE Fixture Works", "job_title": "FAKE Fixture Engineer", "language": "English"}}
    data["selected_top_docs"] = []
    return data


def _draft(vendor, sess):
    key = sess.session_key
    session_store.save_vendor_data(key, vendor, VendorPhaseState(company_report="FAKE report"))
    v = ModelVendor(vendor)
    advance_to_plan(session_id=key, vendor=v, structure_instructions=sess["structure_instructions"], user_id=USER)
    advance_to_draft(session_id=key, vendor=v, style_instructions=sess["style_instructions"], user_id=USER)
    advance_to_refinement(session_id=key, vendor=v, style_instructions=sess["style_instructions"], user_id=USER)


def test_binds_and_restores_the_thread_session():
    assert session_store._get_session() is None
    with headless_session({"job_text": "J"}, "k1") as sess:
        assert session_store._get_session() is sess
        session_store.save_vendor_data("k1", "openai", VendorPhaseState(letter_plan="P"))
        assert sess["vendors"]["openai"]["letter_plan"] == "P"
        with headless_session({}, "inner") as inner:
            assert session_store._get_session() is inner
        assert session_store._get_session() is sess
    assert session_store._get_session() is None


def test_bindings_are_per_thread():
    barrier = threading.Barrier(2)
    seen = {}

    def worker(name):
        with headless_session({"job_text": name}, name):
            barrier.wait()
            seen[name] = session_store.load_session_common_data(name)["job_text"]

    threads = [threading.Thread(target=worker, args=(n,)) for n in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert seen == {"a": "a", "b": "b"}


def test_parallel_vendors_run_the_real_phases_without_cross_talk(fakes):
    common = _common()
    merged, errors = run_vendors_parallel(common, ["openai", "anthropic"], _draft, "opp-1")
    assert errors == {}
    assert set(merged) == {"openai", "anthropic"}
    for vendor in ("openai", "anthropic"):
        state = merged[vendor]
        assert state["letter_plan"].startswith(f"[{vendor}]")
        assert state["draft_letter"].startswith(f"[{vendor}]")
        assert state["final_letter"].startswith(f"[{vendor}]")
        assert state["company_report"] == "FAKE report"
        statuses = [i.get("status") for items in state["feedback"].values() for i in items]
        assert "INPUT_NEEDED" in statuses
    # Each vendor worked on its own copy; the input stays untouched.
    assert common["vendors"] == {}
    vendors_called = {c["vendor"] for c in FakeClient.calls}
    assert vendors_called == {"openai", "anthropic"}


def test_one_failing_vendor_does_not_stop_the_others(fakes):
    fakes({"openai": {"letter_draft"}})
    merged, errors = run_vendors_parallel(_common(), ["openai", "gemini"], _draft, "opp-2")
    assert set(merged) == {"gemini"}
    assert "fake openai failure in letter_draft" in errors["openai"]


def test_initial_session_uses_the_latest_cv_and_saved_or_default_instructions():
    data = initial_session(USER, PROFILE)
    assert data["cv_text"].startswith("NEW CV")
    assert data["style_instructions"] == "Write short sentences."
    assert data["structure_instructions"].strip()  # repo default
    assert data["user"]["id"] == USER


def test_persistable_state_drops_cv_user_and_audit_logs():
    with headless_session(_common(), "k") as sess:
        session_store.log_user_input_event("batch.test", {"x": 1})
        assert sess[session_store.APPLICATION_EVENT_LOG_KEY]
        state = persistable_state(sess)
    for key in ("cv_text", "user", session_store.APPLICATION_EVENT_LOG_KEY, session_store.PENDING_APPLICATION_EVENT_LOG_KEY):
        assert key not in state
    assert state["job_text"].startswith("FAKE Fixture Engineer")
