"""Tests for job-page capture stash (extension ingest)."""
import json
import time

import pytest

from letter_writer_server.core import job_capture_stash as stash


@pytest.fixture
def capture_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(stash, "_STASH_DIR", tmp_path)
    return tmp_path


def test_validate_ingest_rejects_empty():
    with pytest.raises(ValueError, match="no text or HTML"):
        stash.validate_ingest_payload({"url": "https://x", "text": "  ", "html": ""})


def test_validate_ingest_caps_text():
    payload = stash.validate_ingest_payload(
        {"url": "https://jobs.example/a", "title": "Role", "text": "hello", "html": "<p>x</p>"}
    )
    assert payload["text"] == "hello"
    assert payload["html"] == "<p>x</p>"


def test_store_and_load_roundtrip(capture_dir):
    cid = stash.store_capture(
        {"url": "https://jobs.example/a", "title": "Role", "text": "visible", "html": "<p>x</p>"}
    )
    loaded = stash.load_capture(cid)
    assert loaded["text"] == "visible"
    assert loaded["url"] == "https://jobs.example/a"


def test_load_missing_capture_is_none(capture_dir):
    assert stash.load_capture("does-not-exist") is None


def test_expired_capture_is_none(capture_dir):
    cid = stash.store_capture({"url": "", "title": "", "text": "old", "html": ""})
    path = stash._path_for(cid)
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["expires_at"] = time.time() - 10
    path.write_text(json.dumps(envelope), encoding="utf-8")
    assert stash.load_capture(cid) is None


def test_delete_capture(capture_dir):
    cid = stash.store_capture({"url": "", "title": "", "text": "bye", "html": ""})
    stash.delete_capture(cid)
    assert stash.load_capture(cid) is None
