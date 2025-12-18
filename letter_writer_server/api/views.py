import json
import os
from pathlib import Path
from typing import Any, Dict, List
import urllib.error
import urllib.request

from django.http import JsonResponse, HttpRequest
from django.views.decorators.csrf import csrf_exempt

from letter_writer.service import refresh_repository, write_cover_letter
from letter_writer.client import ModelVendor
from letter_writer.generation import get_style_instructions
from letter_writer.phased_service import (
    advance_to_draft,
    advance_to_refinement,
    start_background_phase,
)
from letter_writer.config import env_default
import traceback


# Utility helpers

def _safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _build_kwargs(data: Dict[str, Any], param_types: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce JSON values to expected parameter types."""
    kwargs: Dict[str, Any] = {}
    for key, typ in param_types.items():
        if key not in data or data[key] is None:
            continue
        val = data[key]
        # Special handling for Path and bool
        if typ is Path:
            kwargs[key] = Path(val)
        elif typ is bool:
            kwargs[key] = _safe_bool(val)
        elif typ is int:
            kwargs[key] = int(val)
        elif typ is ModelVendor:
            try:
                kwargs[key] = ModelVendor(val)
            except ValueError:
                raise ValueError(f"Invalid model_vendor '{val}'. Valid options: {[m.value for m in ModelVendor]}")
        else:
            kwargs[key] = typ(val)
    return kwargs


def _translate_with_google(texts: List[str], target_language: str, source_language: str | None = None) -> List[str]:
    """Translate a list of texts using Google Translate API."""
    api_key = os.environ.get("GOOGLE_TRANSLATE_API_KEY")
    if not api_key:
        raise RuntimeError("Missing GOOGLE_TRANSLATE_API_KEY environment variable")

    if not texts:
        return []

    endpoint = f"https://translation.googleapis.com/language/translate/v2?key={api_key}"
    payload: Dict[str, Any] = {
        "q": texts,
        "target": target_language,
    }
    if source_language:
        payload["source"] = source_language

    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # noqa: PERF203
        error_body = exc.read().decode("utf-8") if exc.fp else str(exc)
        raise RuntimeError(f"Google Translate API error: {error_body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to reach Google Translate API: {exc}") from exc

    translations = response_data.get("data", {}).get("translations", [])
    return [item.get("translatedText", "") for item in translations]


# No additional business logic here; shared service functions are imported instead.

@csrf_exempt
def refresh_view(request: HttpRequest):
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON"}, status=400)

    param_types = {
        "jobs_source_folder": Path,
        "jobs_source_suffix": str,
        "letters_source_folder": Path,
        "letters_source_suffix": str,
        "letters_ignore_until": str,
        "letters_ignore_after": str,
        "negative_letters_source_folder": Path,
        "negative_letters_source_suffix": str,
        "qdrant_host": str,
        "qdrant_port": int,
        "clear": bool,
    }

    try:
        kwargs = _build_kwargs(data, param_types)
        refresh_repository(**kwargs, logger=print)
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"detail": str(exc)}, status=500)

    return JsonResponse({"status": "ok"})


@csrf_exempt
def process_job_view(request: HttpRequest):
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON"}, status=400)

    param_types = {
        "job_text": str,
        "cv_text": str,
        "company_name": str,
        "out": Path,
        "model_vendor": ModelVendor,
        "qdrant_host": str,
        "qdrant_port": int,
        "refine": bool,
        "fancy": bool,
    }

    try:
        kwargs = _build_kwargs(data, param_types)
        letters = write_cover_letter(**kwargs, logger=print)
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"detail": str(exc)}, status=500)

    return JsonResponse({"status": "ok", "letters": letters})


@csrf_exempt
def start_phased_job_view(request: HttpRequest):
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON"}, status=400)

    job_text = data.get("job_text")
    company_name = data.get("company_name")
    vendor_values = data.get("vendors") or []
    if not job_text or not company_name:
        return JsonResponse({"detail": "job_text and company_name are required"}, status=400)
    if not vendor_values:
        return JsonResponse({"detail": "vendors array is required"}, status=400)

    try:
        vendors = [ModelVendor(v) for v in vendor_values]
    except ValueError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)

    cv_text = data.get("cv_text")
    if cv_text is None:
        cv_path = Path(env_default("CV_PATH", "cv.md"))
        if cv_path.exists():
            cv_text = cv_path.read_text(encoding="utf-8")
        else:
            cv_text = ""

    qdrant_host = data.get("qdrant_host") or env_default("QDRANT_HOST", "localhost")
    qdrant_port = int(data.get("qdrant_port") or env_default("QDRANT_PORT", "6333"))

    try:
        session = start_background_phase(
            job_text=job_text,
            cv_text=cv_text,
            company_name=company_name,
            vendors=vendors,
            qdrant_host=qdrant_host,
            qdrant_port=qdrant_port,
        )
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return JsonResponse({"detail": str(exc)}, status=500)

    vendors_payload = {
        key: {
            "background_summary": state.background_summary,
            "main_points": state.main_points,
            "company_report": state.company_report,
            "top_docs": state.top_docs,
            "cost": state.cost,
        }
        for key, state in session.vendors.items()
    }
    return JsonResponse(
        {
            "status": "ok",
            "phase": "background",
            "session_id": session.session_id,
            "vendors": vendors_payload,
        }
    )


@csrf_exempt
def draft_phase_view(request: HttpRequest):
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON"}, status=400)

    session_id = data.get("session_id")
    vendor_val = data.get("vendor")
    if not session_id or not vendor_val:
        return JsonResponse({"detail": "session_id and vendor are required"}, status=400)
    try:
        vendor = ModelVendor(vendor_val)
    except ValueError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)

    try:
        state = advance_to_draft(
            session_id=session_id,
            vendor=vendor,
            company_report_override=data.get("company_report"),
            background_summary_override=data.get("background_summary"),
            top_docs_override=data.get("top_docs"),
            job_text_override=data.get("job_text"),
            cv_text_override=data.get("cv_text"),
        )
    except ValueError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return JsonResponse({"detail": str(exc)}, status=500)

    return JsonResponse(
        {
            "status": "ok",
            "phase": "draft",
            "vendor": vendor.value,
            "draft_letter": state.draft_letter,
            "company_report": state.company_report,
            "background_summary": state.background_summary,
            "top_docs": state.top_docs,
            "main_points": state.main_points,
            "cost": state.cost,
        }
    )


@csrf_exempt
def refinement_phase_view(request: HttpRequest):
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON"}, status=400)

    session_id = data.get("session_id")
    vendor_val = data.get("vendor")
    if not session_id or not vendor_val:
        return JsonResponse({"detail": "session_id and vendor are required"}, status=400)
    try:
        vendor = ModelVendor(vendor_val)
    except ValueError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)

    fancy = _safe_bool(data.get("fancy", False))

    try:
        state = advance_to_refinement(
            session_id=session_id,
            vendor=vendor,
            draft_override=data.get("draft_letter"),
            company_report_override=data.get("company_report"),
            top_docs_override=data.get("top_docs"),
            job_text_override=data.get("job_text"),
            cv_text_override=data.get("cv_text"),
            fancy=fancy,
        )
    except ValueError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return JsonResponse({"detail": str(exc)}, status=500)

    return JsonResponse(
        {
            "status": "ok",
            "phase": "refine",
            "vendor": vendor.value,
            "final_letter": state.final_letter,
            "draft_letter": state.draft_letter,
            "feedback": state.feedback,
            "company_report": state.company_report,
            "top_docs": state.top_docs,
            "main_points": state.main_points,
            "cost": state.cost,
        }
    )


@csrf_exempt
def vendors_view(request: HttpRequest):
    if request.method != "GET":
        return JsonResponse({"detail": "Method not allowed"}, status=405)
    vendors = [v.value for v in ModelVendor]
    return JsonResponse({"vendors": vendors})


@csrf_exempt
def style_instructions_view(request: HttpRequest):
    if request.method == "GET":
        # Return current style instructions
        try:
            instructions = get_style_instructions()
            return JsonResponse({"instructions": instructions})
        except Exception as exc:
            return JsonResponse({"detail": str(exc)}, status=500)
    
    elif request.method == "POST":
        # Update style instructions
        try:
            data = json.loads(request.body or "{}")
            instructions = data.get("instructions", "")
            
            if not instructions:
                return JsonResponse({"detail": "Instructions cannot be empty"}, status=400)
            
            # Write to the style instructions file
            style_file = Path(__file__).parent.parent.parent / "letter_writer" / "style_instructions.txt"
            style_file.write_text(instructions, encoding="utf-8")
            
            return JsonResponse({"status": "ok", "instructions": instructions})
        except json.JSONDecodeError:
            return JsonResponse({"detail": "Invalid JSON"}, status=400)
        except Exception as exc:
            return JsonResponse({"detail": str(exc)}, status=500)
    
    else:
        return JsonResponse({"detail": "Method not allowed"}, status=405)


@csrf_exempt
def translate_view(request: HttpRequest):
    """Translate text between English and German."""
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON"}, status=400)

    texts = data.get("texts") or ([] if data.get("text") is None else [data["text"]])
    target_language = (data.get("target_language") or "de").lower()
    source_language = data.get("source_language")

    if not texts or not isinstance(texts, list):
        return JsonResponse({"detail": "Field 'texts' (array) or 'text' (string) is required"}, status=400)

    if not target_language:
        return JsonResponse({"detail": "target_language is required"}, status=400)

    try:
        translations = _translate_with_google(texts, target_language, source_language)
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"detail": str(exc)}, status=500)

    return JsonResponse({"translations": translations})