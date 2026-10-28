"""UI harness: synthetic sessions, no Google/Firestore/LLM.

Enabled only when HARNESS_MODE is truthy and ENVIRONMENT is not production.
All fixture JSON is labeled synthetic; generation endpoints stay disabled.
"""

from __future__ import annotations

import copy
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from letter_writer.page_templates import extract_from_captured_page

logger = logging.getLogger(__name__)

HARNESS_USER: Dict[str, str] = {
    "id": "harness-local",
    "email": "harness@local",
    "name": "Harness User",
}

LLM_DISABLED_DETAIL = "Harness: LLM disabled"
HARNESS_NOT_FOUND_DETAIL = "Harness API is only available when HARNESS_MODE=1"

_TRUTHY = frozenset({"1", "true", "yes", "on"})

# POST paths that would call a model or external embed. Exact prefix match.
LLM_PATH_PREFIXES = (
    "/api/phases/background/",
    "/api/phases/plan/",
    "/api/phases/draft/",
    "/api/phases/refine/",
    "/api/phases/feedback/request-context/",
    "/api/phases/agentic/draft/",
    "/api/phases/agentic/feedback/start/",
    "/api/phases/agentic/feedback/resume/",
    "/api/phases/agentic/rounds/add/",
    "/api/phases/agentic/refine/",
    "/api/extract/",
    "/api/process-job/",
    "/api/translate/",
    "/api/refresh/",
    "/api/research/",
    "/api/autocomplete/complete/",
    "/api/autocomplete/plan/",
    "/api/paragraph/draft/",
    "/api/paragraph/regenerate/",
    "/api/paragraph/continue/",
    "/api/paragraph/feedback/",
    "/api/phase-feedback/snapshot/",
    "/api/documents/",
)

_personal_data: Optional[Dict[str, Any]] = None


def is_harness_mode() -> bool:
    return (os.environ.get("HARNESS_MODE") or "").strip().lower() in _TRUTHY


def _environment_name() -> str:
    return (os.environ.get("ENVIRONMENT") or "").strip().lower() or "production"


def assert_harness_environment() -> None:
    """Refuse to run the harness stacked on a production environment name."""
    if not is_harness_mode():
        return
    env = _environment_name()
    if env == "production":
        raise RuntimeError(
            "HARNESS_MODE=1 cannot run with ENVIRONMENT=production. "
            "Set ENVIRONMENT=harness."
        )


def require_harness_mode() -> None:
    if not is_harness_mode():
        raise HTTPException(status_code=404, detail=HARNESS_NOT_FOUND_DETAIL)


def llm_disabled_body() -> Dict[str, Any]:
    return {"detail": LLM_DISABLED_DETAIL, "harness": True}


def is_llm_blocked_path(method: str, path: str) -> bool:
    if method.upper() != "POST":
        return False
    normalized = path if path.endswith("/") else f"{path}/"
    return any(normalized.startswith(prefix) for prefix in LLM_PATH_PREFIXES)


def harness_zero_costs() -> Dict[str, Any]:
    return {
        "total_cost": 0,
        "pending_cost": 0,
        "cost_available": True,
        "synthetic": True,
        "months": 1,
        "by_phase": {},
        "by_vendor": {},
        "by_vendor_phase": {},
        "days": [],
    }


def get_fixtures_dir() -> Path:
    override = (os.environ.get("HARNESS_FIXTURES_DIR") or "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "ui-harness" / "fixtures"


def _session_fixture_paths() -> List[Path]:
    fixtures_dir = get_fixtures_dir()
    if not fixtures_dir.is_dir():
        return []
    return sorted(
        p
        for p in fixtures_dir.glob("*.json")
        if p.name != "personal-data.json" and not p.name.endswith(".tmp")
    )


def list_fixture_catalog() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for path in _session_fixture_paths():
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("skip unreadable harness fixture %s: %s", path, e)
            continue
        if not isinstance(envelope, dict):
            continue
        rows.append(
            {
                "id": path.stem,
                "filename": path.name,
                "synthetic": bool(envelope.get("synthetic", True)),
                "stage": envelope.get("stage"),
                "company_name": envelope.get("company_name"),
                "job_title": envelope.get("job_title"),
                "empty": bool(envelope.get("empty", False)),
            }
        )
    return rows


def load_fixture_envelope(fixture_id: str) -> Dict[str, Any]:
    if not fixture_id or not isinstance(fixture_id, str):
        raise FileNotFoundError("fixture id is required")
    name = Path(fixture_id).name
    if name != fixture_id or name in (".", "..") or "/" in fixture_id or "\\" in fixture_id:
        raise ValueError("invalid fixture id")
    path = (get_fixtures_dir() / f"{name}.json").resolve()
    fixtures_dir = get_fixtures_dir().resolve()
    try:
        path.relative_to(fixtures_dir)
    except ValueError as e:
        raise ValueError("fixture path escapes fixtures directory") from e
    if not path.is_file():
        raise FileNotFoundError(f"fixture not found: {fixture_id}")
    envelope = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(envelope, dict):
        raise ValueError("fixture root must be a JSON object")
    session = envelope.get("session")
    if not isinstance(session, dict):
        raise ValueError("fixture missing session object")
    return envelope


def _default_personal_data() -> Dict[str, Any]:
    path = get_fixtures_dir() / "personal-data.json"
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    return {
        "cv_revisions": [
            {
                "content": (
                    "Alex Harness is a synthetic résumé used only in the Letter Writer UI harness. "
                    "Experience: payments in Zürich."
                ),
                "source": "harness",
                "created_at": "2026-01-01T00:00:00+00:00",
                "revision_number": 1,
            }
        ],
        "default_languages": [
            {
                "code": "de",
                "label": "DE",
                "color": "#3b82f6",
                "enabled": True,
                "level": "B2",
                "instructions": (
                    "Verwende echte Umlaute (ä, ö, ü, ß) — niemals ae, oe, ue oder ss als Ersatz."
                ),
            },
            {
                "code": "en",
                "label": "EN",
                "color": "#6366f1",
                "enabled": True,
                "level": "C2",
                "instructions": "",
            },
        ],
        "translation_provider": "google",
        "models": ["openai"],
        "background_models": [],
        "min_column_width": 200,
    }


def reset_harness_personal_data() -> Dict[str, Any]:
    global _personal_data
    _personal_data = copy.deepcopy(_default_personal_data())
    return _personal_data


def get_harness_user_data(user_id: Optional[str] = None) -> Dict[str, Any]:
    del user_id
    global _personal_data
    if _personal_data is None:
        reset_harness_personal_data()
    assert _personal_data is not None
    return _personal_data


def update_harness_user_data(updates: Dict[str, Any]) -> None:
    store = get_harness_user_data()
    for key, value in (updates or {}).items():
        if _is_delete_sentinel(value):
            store.pop(key, None)
        else:
            store[key] = value


def _is_delete_sentinel(value: Any) -> bool:
    name = type(value).__name__
    return name in {"Sentinel", "DeleteField"} or str(value).endswith("DELETE_FIELD")


class _HarnessSnapshot:
    def __init__(self, data: Dict[str, Any]):
        self._data = data

    @property
    def exists(self) -> bool:
        return True

    def to_dict(self) -> Dict[str, Any]:
        return dict(self._data)


class HarnessPersonalDataRef:
    """In-memory stand-in for a Firestore personal_data document reference."""

    def get(self) -> _HarnessSnapshot:
        return _HarnessSnapshot(get_harness_user_data())

    def set(self, data: Dict[str, Any], merge: bool = False) -> None:
        if merge:
            update_harness_user_data(data or {})
            return
        global _personal_data
        _personal_data = dict(data or {})

    def update(self, data: Dict[str, Any]) -> None:
        update_harness_user_data(data or {})


def apply_harness_job_capture(session: Any, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Fill intake from the captured page dump without calling a model.

    When a hostname template matches, uses the parsed posting. Otherwise uses the
    page's visible text and title as-is. Does not invent company, location,
    competences, or a cleaned posting.
    """
    visible = str(payload.get("text") or "").strip()
    html = str(payload.get("html") or "").strip()
    title = str(payload.get("title") or "").strip()
    url = str(payload.get("url") or "").strip()
    parsed = extract_from_captured_page(html, url)
    focused = str(parsed.get("job_text") or "").strip()
    if parsed.get("template"):
        job_text = focused or visible or html
        job_title = str(parsed.get("job_title") or "").strip()
        company_name = str(parsed.get("company_name") or "").strip()
        location = str(parsed.get("location") or "").strip()
        language = str(parsed.get("language") or "").strip()
        salary = str(parsed.get("salary") or "").strip()
        point_of_contact = parsed.get("point_of_contact")
        additional_company_info = str(parsed.get("additional_company_info") or "").strip()
        url = str(parsed.get("source_url") or "").strip() or url
    else:
        job_text = visible or html
        job_title = title
        company_name = ""
        location = ""
        language = ""
        salary = ""
        point_of_contact = None
        additional_company_info = ""
    extraction: Dict[str, Any] = {
        "company_name": company_name,
        "job_title": job_title,
        "location": location,
        "language": language,
        "salary": salary,
        "point_of_contact": point_of_contact,
        "additional_company_info": additional_company_info,
        "competences": {},
        "requirements": [],
        "hire_problem": "",
        "source_url": url,
    }
    metadata = dict(session.get("metadata") or {})
    common = dict(metadata.get("common") or {})
    common.update(extraction)
    metadata["common"] = common
    session["metadata"] = metadata
    session["job_text"] = job_text
    return {
        "status": "ok",
        "job_text": job_text,
        "extraction": extraction,
        "similar_documents": [],
        "top_docs": [],
        "session_id": session.session_key,
        "source_url": url,
        "synthetic": True,
        "harness": True,
        "detail": (
            "Harness: LLM disabled; intake filled from a page template when the URL matches, "
            "otherwise from captured page text."
        ),
    }


def harness_info() -> Dict[str, Any]:
    return {
        "mode": True,
        "llm": False,
        "synthetic": True,
        "environment": _environment_name(),
        "detail": LLM_DISABLED_DETAIL,
    }
