"""Tests for HARNESS_MODE auth, fixture load, and LLM 503."""

from __future__ import annotations

import os

os.environ.setdefault("APP_SECRET_KEY", "test-secret-for-harness")

import pytest
from fastapi.testclient import TestClient

from letter_writer_server.core.harness import (
    LLM_DISABLED_DETAIL,
    is_llm_blocked_path,
    reset_harness_personal_data,
)
from letter_writer_server.main import app


@pytest.fixture
def harness_env(monkeypatch):
    monkeypatch.setenv("HARNESS_MODE", "1")
    monkeypatch.setenv("ENVIRONMENT", "harness")
    reset_harness_personal_data()
    with TestClient(app) as client:
        yield client


def test_llm_path_matching():
    assert is_llm_blocked_path("POST", "/api/phases/draft/openai/")
    assert is_llm_blocked_path("POST", "/api/phases/agentic/feedback/start/")
    assert is_llm_blocked_path("POST", "/api/extract/")
    assert not is_llm_blocked_path("POST", "/api/job-capture/ingest/")
    assert not is_llm_blocked_path("POST", "/api/job-capture/abc/process/")
    assert not is_llm_blocked_path("GET", "/api/job-capture/abc/")
    assert not is_llm_blocked_path("GET", "/api/phases/draft/openai/")
    assert not is_llm_blocked_path("POST", "/api/phases/agentic/vote/")
    assert not is_llm_blocked_path("GET", "/api/phases/state/")


def test_harness_info_404_when_off(monkeypatch):
    monkeypatch.delenv("HARNESS_MODE", raising=False)
    with TestClient(app) as client:
        res = client.get("/api/harness/info/")
        assert res.status_code == 404


def test_harness_info_when_on(harness_env):
    res = harness_env.get("/api/harness/info/")
    assert res.status_code == 200
    data = res.json()
    assert data["mode"] is True
    assert data["llm"] is False
    assert data["synthetic"] is True


def test_auth_status_is_harness_user(harness_env):
    res = harness_env.get("/api/auth/status/")
    assert res.status_code == 200
    data = res.json()
    assert data["authenticated"] is True
    assert data["user"]["id"] == "harness-local"


def test_load_vendor_draft_notes(harness_env):
    loaded = harness_env.post("/api/harness/load/vendor-draft-notes")
    assert loaded.status_code == 200, loaded.text
    payload = loaded.json()
    assert payload["synthetic"] is True
    vendors = payload["session_state"]["vendors"]
    assert "payment systems in Zürich" in vendors["openai"]["draft_letter"]
    items = vendors["openai"]["feedback"]["precision"]
    assert items[0]["quote"] == "payment systems in Zürich"

    state = harness_env.get("/api/phases/state/")
    assert state.status_code == 200
    restored = state.json()["session_state"]
    assert "payment systems in Zürich" in restored["vendors"]["openai"]["draft_letter"]


def test_draft_post_503_in_harness(harness_env):
    res = harness_env.post("/api/phases/draft/openai/", json={})
    assert res.status_code == 503
    data = res.json()
    assert data["harness"] is True
    assert data["detail"] == LLM_DISABLED_DETAIL


def test_load_missing_fixture_404(harness_env):
    res = harness_env.post("/api/harness/load/does-not-exist")
    assert res.status_code == 404


def test_job_capture_ingest_cors_allows_extension_origins():
    moz = "moz-extension://aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    chrome = "chrome-extension://abcdefghijklmnopqrstuvwxyzabcdef"
    with TestClient(app) as client:
        for origin in (moz, chrome):
            preflight = client.options(
                "/api/job-capture/ingest/",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type",
                },
            )
            assert preflight.status_code == 200, preflight.text
            assert preflight.headers.get("access-control-allow-origin") == origin

            ingest = client.post(
                "/api/job-capture/ingest/",
                json={
                    "url": "https://jobs.example/role",
                    "title": "Engineer",
                    "text": "We hire engineers.",
                    "html": "<p>We hire engineers.</p>",
                },
                headers={"Origin": origin},
            )
            assert ingest.status_code == 200, ingest.text
            assert ingest.headers.get("access-control-allow-origin") == origin
            assert ingest.json().get("capture_id")


def test_job_capture_process_uses_jobs_ch_template_in_harness(harness_env):
    from letter_writer.test_page_templates import (
        JOBS_CH_COMPACT,
        JOBS_CH_UBS_LOCATION,
        JOBS_CH_UBS_SALARY,
        JOBS_CH_UBS_URL,
    )

    ingest = harness_env.post(
        "/api/job-capture/ingest/",
        json={
            "url": "https://www.jobs.ch/fr/offres-emplois/?term=cpp",
            "title": "1 393 Offres d'emploi de 1. Senior C++ Engineer",
            "text": "Aller directement au contenu\n1 393 Offres\nMetrohm AG",
            "html": JOBS_CH_COMPACT,
        },
    )
    assert ingest.status_code == 200, ingest.text
    capture_id = ingest.json()["capture_id"]
    proc = harness_env.post(f"/api/job-capture/{capture_id}/process/", json={})
    assert proc.status_code == 200, proc.text
    data = proc.json()
    assert data["extraction"]["company_name"] == "UBS Card Center AG"
    assert "Senior AI Machine Learning Engineer" in data["extraction"]["job_title"]
    assert "financial institution" in data["job_text"]
    assert "Metrohm" not in data["job_text"]
    assert "1 393" not in data["job_text"]
    assert data["extraction"]["source_url"] == JOBS_CH_UBS_URL
    assert data["extraction"]["location"] == JOBS_CH_UBS_LOCATION
    assert data["extraction"]["salary"] == JOBS_CH_UBS_SALARY
    assert data["source_url"] == JOBS_CH_UBS_URL


def test_job_capture_process_never_fetches_jobs_ch_company_profile(harness_env, monkeypatch):
    """JobCloud bans automated access: only pages the user opens are read (plan §2)."""
    from letter_writer import page_templates
    from letter_writer.test_page_templates import JOBS_CH_COMPACT

    assert not hasattr(page_templates, "attach_jobs_ch_company_about")
    import httpx

    def no_network(*args, **kwargs):
        raise AssertionError("job capture must not make HTTP requests")

    monkeypatch.setattr(httpx.Client, "send", no_network)
    ingest = harness_env.post(
        "/api/job-capture/ingest/",
        json={
            "url": "https://www.jobs.ch/fr/offres-emplois/?term=cpp",
            "title": "1 393 Offres d'emploi de 1. Senior C++ Engineer",
            "text": "Aller directement au contenu\n1 393 Offres\nMetrohm AG",
            "html": JOBS_CH_COMPACT,
        },
    )
    assert ingest.status_code == 200, ingest.text
    capture_id = ingest.json()["capture_id"]
    proc = harness_env.post(f"/api/job-capture/{capture_id}/process/", json={})
    assert proc.status_code == 200, proc.text
    assert not proc.json()["extraction"].get("additional_company_info")


def test_job_capture_process_is_synthetic_in_harness(harness_env):
    ingest = harness_env.post(
        "/api/job-capture/ingest/",
        json={
            "url": "https://jobs.example/role",
            "title": "Senior Engineer",
            "text": "We hire for payments in Zürich.",
            "html": "<html><body>We hire for payments in Zürich.</body></html>",
        },
    )
    assert ingest.status_code == 200, ingest.text
    capture_id = ingest.json()["capture_id"]
    proc = harness_env.post(f"/api/job-capture/{capture_id}/process/", json={})
    assert proc.status_code == 200, proc.text
    data = proc.json()
    assert data["synthetic"] is True
    assert data["harness"] is True
    assert data["job_text"] == "We hire for payments in Zürich."
    assert data["extraction"]["job_title"] == "Senior Engineer"
    assert data["extraction"]["company_name"] == ""
    assert data["extraction"]["competences"] == {}
    assert data["source_url"] == "https://jobs.example/role"
    assert data["extraction"]["source_url"] == "https://jobs.example/role"


def test_job_capture_peek_saves_source_url_without_consuming(harness_env):
    ingest = harness_env.post(
        "/api/job-capture/ingest/",
        json={
            "url": "https://jobs.example/role",
            "title": "Senior Engineer",
            "text": "We hire for payments in Zürich.",
            "html": "<p>We hire for payments in Zürich.</p>",
        },
    )
    assert ingest.status_code == 200, ingest.text
    capture_id = ingest.json()["capture_id"]

    peek = harness_env.get(f"/api/job-capture/{capture_id}/")
    assert peek.status_code == 200, peek.text
    peek_data = peek.json()
    assert peek_data["source_url"] == "https://jobs.example/role"
    assert peek_data["url"] == "https://jobs.example/role"
    assert peek_data["title"] == "Senior Engineer"

    state = harness_env.get("/api/phases/state/")
    assert state.status_code == 200, state.text
    common = (state.json().get("session_state") or {}).get("metadata", {}).get("common") or {}
    assert common.get("source_url") == "https://jobs.example/role"

    proc = harness_env.post(f"/api/job-capture/{capture_id}/process/", json={})
    assert proc.status_code == 200, proc.text
    assert proc.json()["job_text"] == "We hire for payments in Zürich."


def test_harness_refuses_production_environment(monkeypatch):
    monkeypatch.setenv("HARNESS_MODE", "1")
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(RuntimeError, match="cannot run"):
        with TestClient(app):
            pass


def test_jobs_page_has_one_synthetic_job_per_tab(harness_env):
    res = harness_env.get("/api/opportunities/")
    assert res.status_code == 200, res.text
    statuses = sorted(o["status"] for o in res.json()["opportunities"])
    assert statuses == ["applied", "approved", "captured", "done", "failed", "proposed", "ready", "skipped"]
    assert all(o["title"].startswith("FAKE") for o in res.json()["opportunities"])


def test_harness_ready_job_opens_with_drafts_and_jobs_are_read_only(harness_env):
    res = harness_env.post("/api/opportunities/harness-ready/open/")
    assert res.status_code == 200, res.text
    state = res.json()["session_state"]
    assert "cv_text" not in state
    assert set(state["vendors"]) == {"openai", "claude_code"}
    assert harness_env.post("/api/opportunities/harness-proposed/approve/").status_code == 409
    assert harness_env.post("/api/opportunities/manual/", json={"url": "https://example.com/j"}).status_code == 400
    assert harness_env.get("/api/job-capture/pending/").json()["opportunities"] == [
        {"id": "harness-approved", "url": "https://example.invalid/jobs/2", "canonical_key": "url:https://example.invalid/jobs/2"}
    ]
