import json
from pathlib import Path
from typing import Any, Dict

from django.http import JsonResponse, HttpRequest
from django.views.decorators.csrf import csrf_exempt

from letter_writer.service import refresh_repository, write_cover_letter
from letter_writer.client import ModelVendor
from letter_writer.generation import get_style_instructions


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