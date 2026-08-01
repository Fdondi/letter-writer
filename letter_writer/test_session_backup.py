"""Tests for silent host session backups."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from letter_writer_server.core import session_backup as sb


@pytest.fixture
def backup_dir(tmp_path, monkeypatch):
    path = tmp_path / "session_backups"
    path.mkdir()
    monkeypatch.setenv("SESSION_BACKUP_DIR", str(path))
    sb.clear_fingerprint_cache()
    yield path
    sb.clear_fingerprint_cache()


def test_fingerprint_ignores_heartbeat_and_expiry(backup_dir):
    base = {
        "job_text": "hello job",
        "vendors": {"openai": {"draft_letter": "Dear…"}},
        "agentic": {"status": "draft", "last_poll_at": 1.0},
        "_agentic_last_poll_at": 10.0,
        "_expires_at": 100.0,
    }
    fp1 = sb.work_content_fingerprint(base)
    changed = dict(base)
    changed["_agentic_last_poll_at"] = 99.0
    changed["_expires_at"] = 999.0
    changed["agentic"] = {"status": "draft", "last_poll_at": 2.0}
    fp2 = sb.work_content_fingerprint(changed)
    assert fp1 == fp2

    changed["job_text"] = "hello job changed"
    fp3 = sb.work_content_fingerprint(changed)
    assert fp3 != fp1


def test_maybe_write_skips_duplicate_fingerprint(backup_dir):
    data = {
        "job_text": "j",
        "user": {"id": "u1"},
        "metadata": {"common": {"company_name": "Acme"}},
        "vendors": {},
    }
    p1 = sb.maybe_write_session_backup("sesskey1234567890", data)
    assert p1 is not None
    assert p1.exists()
    files_after_first = list(backup_dir.glob("*.json"))
    assert len(files_after_first) == 2  # latest + stamped

    p2 = sb.maybe_write_session_backup("sesskey1234567890", data)
    assert p2 is None
    assert len(list(backup_dir.glob("*.json"))) == 2

    data2 = dict(data)
    data2["job_text"] = "j2"
    p3 = sb.maybe_write_session_backup("sesskey1234567890", data2)
    assert p3 is not None
    assert len(list(backup_dir.glob("*.json"))) == 3  # latest overwritten + new stamp


def test_resolve_backup_path_rejects_traversal(backup_dir):
    with pytest.raises(ValueError):
        sb.resolve_backup_path("../etc/passwd")
    with pytest.raises(ValueError):
        sb.resolve_backup_path("..\\windows\\system32")
    with pytest.raises(ValueError):
        sb.resolve_backup_path("/abs/path.json")
    with pytest.raises(ValueError):
        sb.resolve_backup_path("notajson.txt")


def test_apply_backup_preserves_auth_and_rejects_other_user(backup_dir):
    live = {
        "user": {"id": "live-user", "email": "a@b.c"},
        "auth_time": 12345.0,
        "job_text": "old",
    }
    envelope = {
        "user_id": "other-user",
        "session": {
            "job_text": "restored job",
            "vendors": {"openai": {"draft_letter": "Hi"}},
            "user": {"id": "other-user"},
            "auth_time": 1.0,
        },
    }
    with pytest.raises(ValueError, match="different user"):
        sb.apply_backup_to_session_dict(live, envelope, "live-user")

    envelope["user_id"] = "live-user"
    state = sb.apply_backup_to_session_dict(live, envelope, "live-user")
    assert live["user"]["id"] == "live-user"
    assert live["auth_time"] == 12345.0
    assert live["job_text"] == "restored job"
    assert live["vendors"]["openai"]["draft_letter"] == "Hi"
    assert state["vendors"]["openai"]["draft_letter"] == "Hi"
    assert "user" not in state or state.get("user") is None


def test_list_session_backups_newest_first(backup_dir):
    older = {
        "format_version": 1,
        "saved_at": "2020-01-01T00:00:00+00:00",
        "session_key": "a",
        "user_id": "u",
        "company_name": "Old Co",
        "session": {"job_text": "old"},
    }
    newer = {
        "format_version": 1,
        "saved_at": "2024-01-01T00:00:00+00:00",
        "session_key": "b",
        "user_id": "u",
        "company_name": "New Co",
        "session": {"job_text": "new"},
    }
    old_path = backup_dir / "old.latest.json"
    new_path = backup_dir / "new.latest.json"
    old_path.write_text(json.dumps(older), encoding="utf-8")
    time.sleep(0.02)
    new_path.write_text(json.dumps(newer), encoding="utf-8")

    listed = sb.list_session_backups()
    assert len(listed) == 2
    assert listed[0]["filename"] == "new.latest.json"
    assert listed[1]["filename"] == "old.latest.json"
    assert listed[0]["company_name"] == "New Co"


def test_load_backup_envelope_roundtrip(backup_dir):
    data = {
        "job_text": "Arbeitgeber sucht…",
        "user": {"id": "u1"},
        "metadata": {"common": {"company_name": "Müller GmbH"}},
        "vendors": {"openai": {"letter_plan": "plan", "draft_letter": "draft"}},
    }
    sb.maybe_write_session_backup("keyABCDEFGHIJK", data)
    latest = backup_dir / "keyABCDEFGHIJK.latest.json"
    envelope = sb.load_backup_envelope(latest.name)
    assert envelope["user_id"] == "u1"
    assert envelope["session"]["job_text"] == "Arbeitgeber sucht…"
    assert "Müller" in envelope["company_name"]
