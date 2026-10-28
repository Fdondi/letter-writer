"""The opportunity batch end to end: Firestore emulator, fixture LLM clients, no real services."""
import json
from pathlib import Path

import pytest

from letter_writer import batch
from letter_writer import client as client_module
from letter_writer import firestore_store
from letter_writer import opportunity_store as ops
from letter_writer.tests.fake_llm import FakeClient, fake_get_client_factory, patch_everywhere

USER = "100200300400500600700"
ALERTS = Path(__file__).parent / "tests" / "fixtures" / "alerts"
JOB_URL = "https://www.jobs.ch/de/stellenangebote/detail/11111111-2222-4333-8444-555555555555/"
JOB_TEXT = "FAKE Fixture Engineer at FAKE Fixture Works in FAKE City. You know FixtureStack and FixtureLang."
PROFILE = {
    "cv_revisions": [{"content": "CV: FixtureStack professional, some FixtureLang.", "created_at": "2026-05-01T00:00:00"}],
}


@pytest.fixture
def fakes(monkeypatch):
    """Fixture clients for every vendor; no RAG, no company research cache, no profile reads."""
    import letter_writer.research as research
    import letter_writer_server.api.extract_pipeline as extract_pipeline

    def install(fail=None, profile=PROFILE):
        patch_everywhere(monkeypatch, client_module.get_client, fake_get_client_factory(fail))
        patch_everywhere(monkeypatch, firestore_store.get_user_data, lambda user_id, use_cache=True: profile)

    install()
    monkeypatch.setattr(extract_pipeline, "get_collection", lambda: None)
    monkeypatch.setattr(extract_pipeline, "OpenAI", lambda *a, **k: object())
    monkeypatch.setattr(extract_pipeline, "retrieve_similar_job_offers", lambda *a, **k: [])
    research_calls = []

    def fake_research(**kwargs):
        research_calls.append(kwargs)
        return {"results": {"openai": {"report": "FAKE research report on FAKE Fixture Works."}}, "source": "new"}

    monkeypatch.setattr(research, "perform_company_research", fake_research)
    monkeypatch.setenv("LW_USER_ID", USER)
    FakeClient.calls.clear()
    install.research_calls = research_calls
    return install


def _seed(store, url=JOB_URL, text=JOB_TEXT, vendors=None):
    opp_id, status, _ = store.capture(USER, url=url, text=text, via="extension", vendors_requested=vendors)
    assert status == ops.CAPTURED
    return opp_id


def _mail_file(tmp_path, names):
    path = tmp_path / "mail.jsonl"
    path.write_text("\n".join(json.dumps(json.loads((ALERTS / n).read_text(encoding="utf-8"))) for n in names) + "\nnot json\n", encoding="utf-8")
    return path


# --- propose ---------------------------------------------------------------------------------


# --- run-captured ----------------------------------------------------------------------------


def test_run_captured_drafts_with_every_vendor_and_saves_the_session(opportunity_store, fakes):
    store = opportunity_store
    opp_id = _seed(store)
    report = batch.run_captured(store, USER, cli_vendors=["openai", "mistral"], spending_check=None)
    assert report == [{"id": opp_id, "status": ops.READY, "vendors_done": ["openai", "mistral"], "vendors_failed": {}}]

    opp = store.get(opp_id)
    assert opp["status"] == ops.READY and opp["lease"] is None
    assert opp["vendors_done"] == ["openai", "mistral"]
    assert opp["input_needed_count"] > 0
    assert opp["fit_summary"]["matched"] == ["FixtureStack"]
    assert opp["company"] == "" or opp["company"] == "FAKE Fixture Works"
    assert opp["cost_subscription_estimate_usd"] == 0

    state = store.load_state(opp_id, USER)
    assert "cv_text" not in state and "user" not in state
    assert state["job_text"]
    assert state["metadata"]["common"]["company_name"] == "FAKE Fixture Works"
    for vendor in ("openai", "mistral"):
        v = state["vendors"][vendor]
        assert v["letter_plan"].startswith(f"[{vendor}]")
        assert v["draft_letter"].startswith(f"[{vendor}]")
        assert v["final_letter"].startswith(f"[{vendor}]")
        assert v["company_report"] == "FAKE research report on FAKE Fixture Works."
    # Research ran once for all vendors.
    assert len(fakes.research_calls) == 1


def _roles(vendor):
    return [c["role"] for c in FakeClient.calls if c["vendor"] == vendor]


def test_zero_rounds_with_comments_is_the_draft_commented(opportunity_store, fakes):
    store = opportunity_store
    opp_id = _seed(store)
    batch.run_captured(store, USER, cli_vendors=["openai"], settings=batch.DraftSettings(rewrite_rounds=0, final_feedback=True), spending_check=None)
    v = store.load_state(opp_id, USER)["vendors"]["openai"]
    assert v["draft_letter"] and not v.get("final_letter")
    assert v["feedback"] and v["comments_on"] == "draft_letter"
    assert "letter_refine" not in _roles("openai")
    opp = store.get(opp_id)
    assert opp["rewrite_rounds"] == 0 and opp["final_feedback"] is True


def test_zero_rounds_without_comments_is_the_bare_draft(opportunity_store, fakes):
    store = opportunity_store
    opp_id = _seed(store)
    batch.run_captured(store, USER, cli_vendors=["openai"], settings=batch.DraftSettings(rewrite_rounds=0, final_feedback=False), spending_check=None)
    v = store.load_state(opp_id, USER)["vendors"]["openai"]
    assert v["draft_letter"] and not v.get("feedback") and v["comments_on"] is None
    assert not {"feedback", "feedback_review", "letter_refine"} & set(_roles("openai")), "no checks nobody reads"


def test_two_rounds_rewrite_twice_and_comment_the_last_version(opportunity_store, fakes, monkeypatch):
    import letter_writer.phased_service as phased

    store = opportunity_store
    opp_id = _seed(store, vendors=["openai"])
    store._ref(opp_id).update({"rewrite_rounds": 2, "final_feedback": True})
    rechecked = []
    real_check = phased.check_letter

    def spy(**kwargs):
        rechecked.append(kwargs["letter"])
        return real_check(**kwargs)

    monkeypatch.setattr(phased, "check_letter", spy)
    batch.run_captured(store, USER, spending_check=None)  # the job's settings, not the CLI default
    assert _roles("openai").count("letter_refine") == 2
    v = store.load_state(opp_id, USER)["vendors"]["openai"]
    # The draft phase comments the draft; then the first rewrite and the last version are commented.
    assert len(rechecked) == 2 and rechecked[-1] == v["final_letter"]
    v = store.load_state(opp_id, USER)["vendors"]["openai"]
    assert v["comments_on"] == "final_letter" and v["batch_settings"] == {"rewrite_rounds": 2, "final_feedback": True}
    assert v["final_letter"].startswith("[openai]") and v["feedback"]


def test_one_round_without_final_comments_is_the_old_behaviour(opportunity_store, fakes):
    store = opportunity_store
    opp_id = _seed(store, vendors=["openai"])
    batch.run_captured(store, USER, settings=batch.DraftSettings(rewrite_rounds=1, final_feedback=False), spending_check=None)
    v = store.load_state(opp_id, USER)["vendors"]["openai"]
    assert _roles("openai").count("letter_refine") == 1 and v["comments_on"] == "draft_letter"


def test_new_settings_redraft_but_keep_the_old_letter_if_that_fails(opportunity_store, fakes):
    store = opportunity_store
    opp_id = _seed(store, vendors=["openai"])
    batch.run_captured(store, USER, spending_check=None)
    old = store.load_state(opp_id, USER)["vendors"]["openai"]
    store.set_status(opp_id, ops.CAPTURED, from_states=[ops.READY], user_id=USER, fields={"rewrite_rounds": 0})
    fakes({"openai": {"letter_draft"}})
    batch.run_captured(store, USER, spending_check=None)
    opp = store.get(opp_id)
    assert opp["status"] == ops.READY and "openai" in opp["vendors_failed"]
    assert store.load_state(opp_id, USER)["vendors"]["openai"] == old


def test_jobs_vendor_choice_wins_and_spending_limit_only_stops_api_vendors(opportunity_store, fakes):
    store = opportunity_store
    opp_id = _seed(store, vendors=["claude_code", "openai"])
    checked = []

    def over_limit(user_id):
        checked.append(user_id)
        return "Daily spending limit of $5.00 reached."

    report = batch.run_captured(store, USER, cli_vendors=["gemini"], spending_check=over_limit)
    assert checked == [USER]
    assert report[0]["status"] == ops.READY
    opp = store.get(opp_id)
    assert opp["vendors_done"] == ["claude_code"]
    assert opp["vendors_failed"] == {"openai": "Daily spending limit of $5.00 reached."}
    assert {c["vendor"] for c in FakeClient.calls} >= {"claude_code"}
    assert "gemini" not in {c["vendor"] for c in FakeClient.calls}


def test_a_failing_vendor_is_recorded_and_the_rest_continue(opportunity_store, fakes):
    fakes({"mistral": {"letter_plan"}})
    store = opportunity_store
    opp_id = _seed(store)
    batch.run_captured(store, USER, cli_vendors=["openai", "mistral"], spending_check=None)
    opp = store.get(opp_id)
    assert opp["status"] == ops.READY
    assert opp["vendors_done"] == ["openai"]
    assert "fake mistral failure in letter_plan" in opp["vendors_failed"]["mistral"]


def test_all_vendors_failing_marks_failed_and_retry_requeues(opportunity_store, fakes, capsys):
    fakes({"openai": {"letter_draft"}})
    store = opportunity_store
    opp_id = _seed(store)
    report = batch.run_captured(store, USER, cli_vendors=["openai"], spending_check=None)
    assert report[0]["status"] == ops.FAILED
    assert store.get(opp_id)["status"] == ops.FAILED
    assert batch.main(["retry", opp_id], store=store) == 0
    opp = store.get(opp_id)
    assert opp["status"] == ops.CAPTURED and opp["vendors_failed"] == {}
    with pytest.raises(ops.TransitionError):
        batch.retry(store, USER, opp_id)


def test_retry_keeps_finished_vendors_and_drafts_only_the_rest(opportunity_store, fakes):
    fakes({"mistral": {"letter_plan"}})
    store = opportunity_store
    opp_id = _seed(store, vendors=["openai", "mistral"])
    batch.run_captured(store, USER, spending_check=None)
    first = store.load_state(opp_id, USER)
    assert store.get(opp_id)["vendors_done"] == ["openai"]

    fakes()  # mistral works again
    FakeClient.calls.clear()
    batch.retry(store, USER, opp_id)
    report = batch.run_captured(store, USER, spending_check=None)
    assert report[0]["vendors_done"] == ["openai", "mistral"] and report[0]["vendors_failed"] == {}
    openai_roles = {c["role"] for c in FakeClient.calls if c["vendor"] == "openai"}
    # Only the missing vendor drafts; openai just links the shared questions across both drafts.
    assert openai_roles == {"feedback_review"}, openai_roles
    assert {"letter_plan", "letter_draft", "letter_refine"} <= {c["role"] for c in FakeClient.calls if c["vendor"] == "mistral"}
    assert len(fakes.research_calls) == 1, "extraction and research are reused, not repeated"
    state = store.load_state(opp_id, USER)
    assert state["vendors"]["openai"] == first["vendors"]["openai"]
    assert state["vendors"]["mistral"]["final_letter"].startswith("[mistral]")
    assert state["vendors"]["mistral"]["company_report"] == first["vendors"]["openai"]["company_report"]


def test_a_vendor_failing_again_on_retry_keeps_the_ones_that_succeeded(opportunity_store, fakes):
    fakes({"mistral": {"letter_plan"}})
    store = opportunity_store
    opp_id = _seed(store, vendors=["openai", "mistral"])
    batch.run_captured(store, USER, spending_check=None)
    kept = store.load_state(opp_id, USER)["vendors"]["openai"]
    batch.retry(store, USER, opp_id)
    batch.run_captured(store, USER, spending_check=None)  # mistral still failing
    opp = store.get(opp_id)
    assert opp["status"] == ops.READY
    assert opp["vendors_done"] == ["openai"] and "mistral" in opp["vendors_failed"]
    assert store.load_state(opp_id, USER)["vendors"]["openai"] == kept


def test_a_finished_draft_survives_a_new_vendor_list(opportunity_store, fakes):
    store = opportunity_store
    opp_id = _seed(store, vendors=["openai"])
    batch.run_captured(store, USER, spending_check=None)
    kept = store.load_state(opp_id, USER)["vendors"]["openai"]
    # The same posting sent again asking for another vendor.
    store.set_status(opp_id, ops.CAPTURED, from_states=[ops.READY], user_id=USER, fields={"vendors_requested": ["mistral"]})
    FakeClient.calls.clear()
    batch.run_captured(store, USER, spending_check=None)
    state = store.load_state(opp_id, USER)
    assert state["vendors"]["openai"] == kept
    assert state["vendors"]["mistral"]["final_letter"].startswith("[mistral]")
    assert set(store.get(opp_id)["vendors_done"]) == {"openai", "mistral"}
    assert "letter_plan" not in {c["role"] for c in FakeClient.calls if c["vendor"] == "openai"}


def test_drafts_written_before_a_run_dies_are_kept(opportunity_store, fakes, monkeypatch):
    store = opportunity_store
    opp_id = _seed(store, vendors=["openai", "mistral"])

    def crash(session, states):
        raise RuntimeError("the run died after drafting")

    monkeypatch.setattr(batch.headless, "merge_vendor_states", crash)
    batch.run_captured(store, USER, spending_check=None)
    assert store.get(opp_id)["status"] == ops.FAILED
    saved = store.load_state(opp_id, USER)["vendors"]
    assert set(saved) == {"openai", "mistral"}, "each draft was stored as it finished"

    monkeypatch.undo()
    fakes()
    FakeClient.calls.clear()
    batch.retry(store, USER, opp_id)
    report = batch.run_captured(store, USER, spending_check=None)
    assert report[0]["status"] == ops.READY and set(report[0]["vendors_done"]) == {"openai", "mistral"}
    assert not {"letter_plan", "letter_draft", "letter_refine"} & {c["role"] for c in FakeClient.calls}, "nothing drafted twice"
    assert store.load_state(opp_id, USER)["vendors"] == saved


def test_new_posting_text_drafts_every_vendor_again(opportunity_store, fakes):
    store = opportunity_store
    opp_id = _seed(store, vendors=["openai"])
    batch.run_captured(store, USER, spending_check=None)
    store.set_status(opp_id, ops.CAPTURED, from_states=[ops.READY], user_id=USER, fields={"capture": {"text": JOB_TEXT + " Now also FixtureOps.", "via": "share_text"}})
    FakeClient.calls.clear()
    batch.run_captured(store, USER, spending_check=None)
    assert "openai" in {c["vendor"] for c in FakeClient.calls}
    assert len(fakes.research_calls) == 2


def test_progress_shows_each_step_and_finished_vendor_then_clears(opportunity_store, fakes, monkeypatch):
    store = opportunity_store
    opp_id = _seed(store, vendors=["openai", "mistral"])
    seen = []
    real = store.report_progress

    def spy(job_id, owner, progress):
        written = real(job_id, owner, progress)
        seen.append({"step": progress["step"], "done": sorted(progress["vendors_done"]), "total": progress["vendors_total"], "written": written})
        return written

    monkeypatch.setattr(store, "report_progress", spy)
    batch.run_captured(store, USER, spending_check=None)
    assert [p["step"] for p in seen[:3]] == ["reading", "research", "drafting"]
    assert seen[2]["done"] == [] and seen[-1]["done"] == ["mistral", "openai"]
    assert all(p["written"] and p["total"] == 2 for p in seen)
    assert store.get(opp_id).get("progress") is None, "cleared when the job is ready"
    assert real(opp_id, "another-batch", {"step": "drafting"}) is False, "only under the lease"


def test_missing_cv_fails_the_job_with_a_reason(opportunity_store, fakes):
    fakes(profile={"cv_revisions": []})
    store = opportunity_store
    opp_id = _seed(store)
    batch.run_captured(store, USER, cli_vendors=["openai"], spending_check=None)
    opp = store.get(opp_id)
    assert opp["status"] == ops.FAILED
    assert "No CV" in opp["vendors_failed"]["batch"]
    assert FakeClient.calls == []


def test_max_jobs_and_dry_run(opportunity_store, fakes):
    store = opportunity_store
    ids = [_seed(store, url=f"https://example.com/jobs/{i}", text=f"{JOB_TEXT} #{i}") for i in range(3)]
    preview = batch.run_captured(store, USER, max_jobs=2, dry_run=True)
    assert [p["id"] for p in preview] and all(p["dry_run"] for p in preview)
    assert all(store.get(i)["status"] == ops.CAPTURED for i in ids)
    report = batch.run_captured(store, USER, max_jobs=2, cli_vendors=["openai"], spending_check=None)
    assert len(report) == 2
    assert sorted(store.get(i)["status"] for i in ids) == [ops.CAPTURED, ops.READY, ops.READY]


def test_status_line(opportunity_store, fakes, capsys):
    store = opportunity_store
    store.upsert_proposed(USER, url="https://example.com/p")
    _seed(store)
    batch.run_captured(store, USER, cli_vendors=["openai"], spending_check=None)
    batch.main(["status"], store=store)
    line = capsys.readouterr().out.strip()
    assert line.startswith("proposed 1 · waiting for text 0 · captured 0 · ready 1 (")
    assert "questions)" in line


def test_seed_command(opportunity_store, tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("LW_USER_ID", USER)
    text = tmp_path / "job.txt"
    text.write_text(JOB_TEXT, encoding="utf-8")
    batch.main(["seed", "--url", JOB_URL, "--text-file", str(text), "--vendors", "claude_code,openai"], store=opportunity_store)
    out = json.loads(capsys.readouterr().out)
    opp = opportunity_store.get(out["id"])
    assert opp["status"] == ops.CAPTURED and opp["vendors_requested"] == ["claude_code", "openai"]


def test_requested_vendors_and_fit_summary():
    assert batch.requested_vendors({"vendors_requested": ["openai", "bogus", "openai"]}, ["gemini"]) == ["openai"]
    assert batch.requested_vendors({}, ["Gemini", "claude_code"]) == ["gemini", "claude_code"]
    # No list from the job or the command line: every vendor, Anthropic as Claude Code.
    everything = batch.requested_vendors({}, None)
    assert "claude_code" in everything and "anthropic" not in everything
    assert set(everything) == {v.value for v in batch.ModelVendor} - {"anthropic"}
    # Anthropic is one vendor: in the batch it is Claude Code, never the API.
    assert batch.requested_vendors({"vendors_requested": ["anthropic", "openai", "claude_code"]}, None) == ["claude_code", "openai"]
    summary = batch.fit_summary(
        {
            "competences": {
                "Rust": {"need": "critical", "level": "Newbie"},
                "C++": {"need": "critical", "level": "Senior professional"},
                "Go": {"need": "nice to have", "level": "Newbie"},
                "CUDA": {"need": "expected", "level": "Professional"},
            }
        }
    )
    assert summary == {"matched": ["C++", "CUDA"], "gaps": ["Rust"]}


def test_user_id_comes_from_the_flag_the_env_or_the_only_profile(monkeypatch):
    monkeypatch.delenv("LW_USER_ID", raising=False)
    one = lambda: [{"id": "only-sub"}]
    two = lambda: [{"id": "a"}, {"id": "b"}]
    assert batch.user_id_from_env(profiles=one) == "only-sub"
    assert batch.user_id_from_env("explicit", profiles=two) == "explicit"
    with pytest.raises(SystemExit, match="2 profiles"):
        batch.user_id_from_env(profiles=two)
    monkeypatch.setenv("LW_USER_ID", "from-env")
    assert batch.user_id_from_env(profiles=two) == "from-env"


def test_list_profiles_reads_personal_data(emulator_db):
    import uuid

    col = emulator_db.collection(f"personal_data_{uuid.uuid4().hex[:8]}")
    col.document("sub-1").set({"cv_revisions": [{"content": "CV"}], "updated_at": "2026-10-01"})
    assert batch.list_profiles(col) == [{"id": "sub-1", "cv_revisions": 1, "updated_at": "2026-10-01"}]


def test_host_defaults_never_override_explicit_settings(tmp_path):
    env = {}
    batch.apply_host_defaults(env)
    assert env["OLLAYA_BASE_URL"] == "http://127.0.0.1:11435"
    assert env["FIRESTORE_DATABASE"] == "letter"
    assert env.get("GOOGLE_APPLICATION_CREDENTIALS", "").endswith("gcloud-credentials.json") or not (batch.REPO_ROOT / "gcloud-credentials.json").exists()
    env = {"OLLAYA_BASE_URL": "http://ollaya:11435", "GOOGLE_APPLICATION_CREDENTIALS": "/x.json", "FIRESTORE_DATABASE": "other"}
    batch.apply_host_defaults(env)
    assert env == {"OLLAYA_BASE_URL": "http://ollaya:11435", "GOOGLE_APPLICATION_CREDENTIALS": "/x.json", "FIRESTORE_DATABASE": "other"}
    env = {"LW_OLLAYA_BASE_URL": "http://box:11435"}
    batch.apply_host_defaults(env)
    assert env["OLLAYA_BASE_URL"] == "http://box:11435"


# --- contract with the Android app -----------------------------------------------------------

SESSION_FIXTURE = Path(__file__).parent / "tests" / "fixtures" / "opportunity_session.json"


class _CapturingStore:
    def __init__(self):
        self.saved = None

    def load_state(self, opp_id, user_id=None):
        return None

    def save_state(self, opp_id, session):
        from letter_writer.firestore_store import firestore_safe_for_write

        self.saved = firestore_safe_for_write({k: v for k, v in session.items() if k != "cv_text"})


def _shape(value):
    if isinstance(value, dict):
        return {k: _shape(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [_shape(value[0])] if value else []
    return type(value).__name__


def test_session_fixture_matches_what_the_batch_writes(fakes):
    """``opportunity_session.json`` is what the phone's PipelineSessionTest reads.
    Regenerate with LW_UPDATE_FIXTURES=1 when the session shape changes on purpose."""
    import os

    store = _CapturingStore()
    opp = {"id": "fixture-opportunity", "url": JOB_URL, "capture": {"text": JOB_TEXT, "via": "extension"}}
    fields = batch.process_opportunity(store, opp, user_id=USER, vendors=["openai", "claude_code"], spending_check=None)
    produced = {
        "opportunity": {
            "user_id": USER,
            "status": fields["status"],
            "url": "https://www.jobs.ch/de/stellenangebote/detail/11111111-2222-4333-8444-555555555555",
            "vendors_done": fields["vendors_done"],
            "vendors_failed": {"gemini": "fake failure for the fixture"},
            "input_needed_count": fields["input_needed_count"],
            "fit_summary": fields["fit_summary"],
        },
        "state": store.saved,
    }
    if os.environ.get("LW_UPDATE_FIXTURES") == "1":
        SESSION_FIXTURE.write_text(json.dumps(produced, indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    committed = json.loads(SESSION_FIXTURE.read_text(encoding="utf-8"))
    assert _shape(committed["state"]) == _shape(json.loads(json.dumps(produced["state"], default=str)))
    assert committed["opportunity"]["vendors_done"] == ["openai", "claude_code"]


def test_detach_restarts_the_same_command_in_its_own_session(monkeypatch, tmp_path):
    monkeypatch.setattr(batch, "REPO_ROOT", tmp_path)
    started = {}

    class FakeProc:
        pid = 4242

    def fake_popen(cmd, **kwargs):
        started.update(cmd=cmd, **kwargs)
        return FakeProc()

    out = batch.detach_run_captured(["--user-id", "u", "run-captured", "--max-jobs", "3", "--detach"], popen=fake_popen)
    assert started["cmd"][1:] == ["-m", "letter_writer.batch", "--user-id", "u", "run-captured", "--max-jobs", "3"]
    assert started["start_new_session"] is True and started["cwd"] == str(tmp_path)
    assert out["detached"] == 4242 and out["log"].startswith("temp/opportunities/batch-")
    assert (tmp_path / "temp" / "opportunities" / "batch.pid").read_text() == "4242"


def test_detach_does_not_start_a_second_batch(monkeypatch, tmp_path):
    import os

    monkeypatch.setattr(batch, "REPO_ROOT", tmp_path)
    pid_dir = tmp_path / "temp" / "opportunities"
    pid_dir.mkdir(parents=True)
    (pid_dir / "batch.pid").write_text(str(os.getpid()))
    out = batch.detach_run_captured(["run-captured", "--detach"], popen=lambda *a, **k: pytest.fail("started twice"))
    assert out == {"already_running": os.getpid()}
