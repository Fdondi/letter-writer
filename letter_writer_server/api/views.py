import html
import json
import os
import logging
from pathlib import Path
from typing import Any, Dict, List
import urllib.error
import urllib.request
import base64
import io
from datetime import datetime

from django.http import JsonResponse, HttpRequest
from django.middleware.csrf import get_token
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods

from .spam_prevention import prevent_duplicate_requests, get_in_flight_requests, clear_in_flight_requests

logger = logging.getLogger(__name__)


def require_auth_user(request: HttpRequest):
    """Helper to require authentication and return user ID.
    
    Uses Google OAuth UID (from SocialAccount) if available, otherwise Django user ID.
    This ensures consistent identification using the Google account ID.
    
    Returns:
        tuple: (user_id_str, None) if authenticated, (None, JsonResponse) if not
        
    Raises:
        JsonResponse: HTTP 401 Unauthorized if not authenticated
    """
    if not request.user.is_authenticated:
        from django.http import JsonResponse
        return None, JsonResponse({"detail": "Authentication required"}, status=401)
    
    # Try to get Google OAuth UID first (preferred)
    user_id = None
    try:
        from allauth.socialaccount.models import SocialAccount
        social_account = SocialAccount.objects.filter(user=request.user, provider='google').first()
        if social_account:
            user_id = social_account.uid  # Google's user ID (stable, unique)
    except (ImportError, Exception):
        pass
    
    # Fallback to Django user ID if no Google account
    if not user_id:
        user_id = str(request.user.id)
    
    return str(user_id), None


def _migrate_old_cv_data(user_id: str) -> bool:
    """Migrate old personal_data/cv structure to new personal_data/{user_id} structure.
    
    Old structure: personal_data/cv with "revisions" field
    New structure: personal_data/{user_id} with "cv_revisions" field
    
    This is automatically called on first access if user document doesn't exist.
    
    Args:
        user_id: User ID (document ID for new structure)
    
    Returns:
        True if migration occurred, False if nothing to migrate
    """
    personal_collection = get_personal_data_collection()
    
    # Check if old cv document exists
    cv_doc_ref = personal_collection.document('cv')
    cv_doc = cv_doc_ref.get()
    
    if not cv_doc.exists:
        return False
    
    # Check if user document already exists (don't overwrite)
    user_doc_ref = get_personal_data_document(user_id)
    user_doc = user_doc_ref.get()
    
    if user_doc.exists:
        return False  # Already migrated or exists
    
    # Migrate: old "revisions" → new "cv_revisions"
    cv_data = cv_doc.to_dict()
    old_revisions = cv_data.get('revisions', [])
    
    if old_revisions:
        now = datetime.utcnow()
        user_doc_ref.set({
            'cv_revisions': old_revisions,  # Rename field from "revisions" to "cv_revisions"
            'updated_at': now,
        })
        return True
    
    return False

from letter_writer.service import refresh_repository, write_cover_letter
from letter_writer.client import ModelVendor
from letter_writer.generation import get_style_instructions
from letter_writer.phased_service import (
    advance_to_draft,
    advance_to_refinement,
)
from letter_writer.firestore_store import (
    append_negatives,
    get_collection,
    get_document,
    get_personal_data_collection,
    get_personal_data_document,
    get_user_data,
    clear_user_data_cache,
    list_documents,
    upsert_document,
)
from letter_writer.vector_store import (
    delete_documents,
    embed,
    upsert_documents,
)
from letter_writer.config import env_default
from openai import OpenAI
import traceback


# Authentication views

@require_http_methods(["GET"])
def csrf_token_view(request: HttpRequest):
    """Get CSRF token for use in API requests."""
    token = get_token(request)
    return JsonResponse({"csrfToken": token})


@require_http_methods(["GET"])
def auth_status_view(request: HttpRequest):
    """Get authentication status and configuration info."""
    from django.conf import settings
    
    status = {
        "authenticated": request.user.is_authenticated,
        "user": None,
        "auth_available": getattr(settings, "AUTHENTICATION_AVAILABLE", False),
        "cors_available": getattr(settings, "CORS_AVAILABLE", False),
    }
    
    if request.user.is_authenticated:
        try:
            from allauth.socialaccount.models import SocialAccount
            social_account = SocialAccount.objects.filter(user=request.user).first()
            provider = social_account.provider if social_account else None
        except (ImportError, Exception):
            provider = None
        
        status["user"] = {
            "id": request.user.id,
            "email": request.user.email,
            "name": request.user.get_full_name() or request.user.email,
            "provider": provider,
        }
    
    return JsonResponse(status)


@require_http_methods(["GET"])
def current_user_view(request: HttpRequest):
    """Get current authenticated user info."""
    if request.user.is_authenticated:
        # Check if user authenticated via social account (Google) - only if allauth is installed
        social_account = None
        try:
            from allauth.socialaccount.models import SocialAccount
            social_account = SocialAccount.objects.filter(user=request.user).first()
            provider = social_account.provider if social_account else None
        except ImportError:
            # allauth not installed
            provider = None
        except Exception:
            # Other error (e.g., table doesn't exist yet)
            provider = None
        
        return JsonResponse({
            "authenticated": True,
            "user": {
                "id": request.user.id,
                "email": request.user.email,
                "name": request.user.get_full_name() or request.user.email,
                "provider": provider,
            }
        })
    else:
        return JsonResponse({
            "authenticated": False,
            "user": None
        })


@require_http_methods(["GET", "POST"])
def login_view(request: HttpRequest):
    """API endpoint for login (redirects to Google OAuth)."""
    from django.shortcuts import redirect
    
    # If already authenticated, return user info
    if request.user.is_authenticated:
        return JsonResponse({
            "status": "ok",
            "authenticated": True,
            "user": {
                "id": request.user.id,
                "email": request.user.email,
                "name": request.user.get_full_name() or request.user.email,
            }
        })
    
    # Redirect to Google OAuth login
    return redirect("/accounts/google/login/")


def google_oauth_redirect(request):
    """Custom view to redirect directly to Google OAuth, bypassing django-allauth consent page.
    
    This view overrides django-allauth's /accounts/google/login/ URL.
    Instead of showing the intermediate consent page ("You are about to sign in..."),
    it redirects directly to Google's OAuth endpoint.
    
    This constructs the OAuth URL manually using credentials from settings.py (environment variables).
    """
    try:
        import os
        from django.contrib.sites.shortcuts import get_current_site
        from django.conf import settings
        from django.http import HttpResponseRedirect, HttpResponse
        from urllib.parse import urlencode
        
        logger.info("[OAuth] Starting Google OAuth redirect")
        
        # Get OAuth credentials from settings (which reads from environment variables)
        socialaccount_providers = getattr(settings, 'SOCIALACCOUNT_PROVIDERS', {})
        google_provider = socialaccount_providers.get('google', {})
        app_config = google_provider.get('APP', {})
        client_id = app_config.get('client_id', '')
        secret_present = bool(app_config.get('secret', ''))
        
        logger.info(f"[OAuth] Client ID present: {bool(client_id)}, Secret present: {secret_present}")
        logger.debug(f"[OAuth] Client ID (first 10 chars): {client_id[:10] if client_id else 'MISSING'}...")
        
        if not client_id:
            logger.error("[OAuth] Client ID missing - OAuth not configured")
            return HttpResponse(
                "Google OAuth is not configured. Set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_SECRET environment variables.",
                status=500
            )
        
        if not secret_present:
            logger.error("[OAuth] Client secret missing - token exchange will fail")
        
        # Use Google's standard OAuth URLs (these are constants)
        authorize_url = 'https://accounts.google.com/o/oauth2/v2/auth'
        
        # Build callback URL (same as django-allauth would use)
        current_site = get_current_site(request)
        site_domain = current_site.domain
        
        # Use ACCOUNT_DEFAULT_HTTP_PROTOCOL or detect from request
        protocol = getattr(settings, 'ACCOUNT_DEFAULT_HTTP_PROTOCOL', 'http')
        if request.is_secure() or 'K_SERVICE' in os.environ:  # GCP Cloud Run uses HTTPS
            protocol = 'https'
        elif 'localhost' in site_domain or '127.0.0.1' in site_domain or ':8000' in site_domain:
            protocol = 'http'
        
        # Clean up domain (remove protocol if present, remove port if not needed)
        if site_domain.startswith('http://') or site_domain.startswith('https://'):
            site_domain = site_domain.split('://', 1)[1]
        
        # Build callback URL - django-allauth uses this pattern
        callback_url = f"{protocol}://{site_domain}/accounts/google/login/callback/"
        
        logger.info(f"[OAuth] Callback URL: {callback_url}")
        
        # Get OAuth scope and params from settings or use defaults
        scope = google_provider.get('SCOPE', ['profile', 'email'])
        auth_params = google_provider.get('AUTH_PARAMS', {'access_type': 'online'})
        
        # Build query parameters for Google OAuth
        params = {
            'client_id': client_id,
            'redirect_uri': callback_url,
            'scope': ' '.join(scope),
            'response_type': 'code',
            **auth_params  # Include additional params like access_type
        }
        
        # Build the full Google OAuth authorization URL
        auth_url = f"{authorize_url}?{urlencode(params)}"
        
        logger.info(f"[OAuth] Redirecting to Google OAuth: {authorize_url} (client_id present: {bool(client_id)})")
        
        return HttpResponseRedirect(auth_url)
        
    except ImportError:
        # django-allauth not available
        from django.http import HttpResponse
        return HttpResponse(
            "django-allauth is not installed. Please install it first.",
            status=500
        )
    except Exception as e:
        logger.exception("[OAuth] Error in google_oauth_redirect")
        # On error, fall back to django-allauth's default behavior
        # Use django-allauth's OAuth2LoginView normally (will show consent page, but better than 500)
        try:
            from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
            from allauth.socialaccount.providers.oauth2.views import OAuth2LoginView
            
            logger.info("[OAuth] Falling back to django-allauth default OAuth2LoginView")
            
            # Create a view class that uses GoogleOAuth2Adapter
            class FallbackGoogleLoginView(OAuth2LoginView):
                adapter_class = GoogleOAuth2Adapter
            
            # Use the view class
            view = FallbackGoogleLoginView.as_view()
            return view(request)
        except Exception as inner_e:
            # If even that fails, just show the error
            logger.exception("[OAuth] Fallback also failed")
            from django.http import HttpResponse
            import traceback
            return HttpResponse(
                f"Error initiating Google OAuth: {str(e)}\n\nFallback error: {str(inner_e)}\n{traceback.format_exc()}",
                status=500,
                content_type='text/plain'
            )


@require_http_methods(["POST"])
def logout_view(request: HttpRequest):
    """Logout current user."""
    from django.conf import settings
    
    # Log for debugging
    print(f"[LOGOUT] Starting logout for user: {request.user}")
    print(f"[LOGOUT] Session key before logout: {request.session.session_key}")
    
    # Clear Django auth
    logout(request)
    
    # Flush session completely
    request.session.flush()
    
    print(f"[LOGOUT] Session key after flush: {request.session.session_key}")
    
    response = JsonResponse({"status": "ok", "message": "Logged out successfully"})
    
    # Delete session cookie with explicit path to match how it was set
    response.delete_cookie(
        settings.SESSION_COOKIE_NAME,
        path="/",
        domain=getattr(settings, 'SESSION_COOKIE_DOMAIN', None),
        samesite=getattr(settings, 'SESSION_COOKIE_SAMESITE', 'Lax'),
    )
    
    print(f"[LOGOUT] Cookie deletion set for: {settings.SESSION_COOKIE_NAME}")
    
    return response


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
    # Decode HTML entities (e.g., &#39; -> ', &quot; -> ", etc.)
    return [html.unescape(item.get("translatedText", "")) for item in translations]


# No additional business logic here; shared service functions are imported instead.

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
        "clear": bool,
    }

    try:
        kwargs = _build_kwargs(data, param_types)
        refresh_repository(**kwargs, logger=print)
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"detail": str(exc)}, status=500)

    return JsonResponse({"status": "ok"})


@prevent_duplicate_requests(endpoint_path="process-job")
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
        "refine": bool,
        "fancy": bool,
    }

    try:
        kwargs = _build_kwargs(data, param_types)
        
        # Add style_instructions from session or default
        instructions = request.session.get("style_instructions", "")
        if not instructions:
             instructions = get_style_instructions()
        kwargs["style_instructions"] = instructions
        
        letters = write_cover_letter(**kwargs, logger=print)
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"detail": str(exc)}, status=500)

    # Persist generation: store job_text and AI letters; keep first letter as primary.
    try:
        # Require authentication for document storage
        if not request.user.is_authenticated:
            # Skip document storage if not authenticated (legacy endpoint)
            pass
        else:
            user_id = str(request.user.id)
            collection = get_collection()
            job_text = data.get("job_text")
            company_name = data.get("company_name")
            ai_letters = [
                {"vendor": vendor, "text": payload.get("text", ""), "cost": payload.get("cost")}
                for vendor, payload in letters.items()
            ]
            primary_letter = next((l["text"] for l in ai_letters if l.get("text")), "")
            
            # Generate vector embedding
            openai_client = OpenAI()
            vector = embed(job_text, openai_client) if job_text else None
            
            document = upsert_document(
                collection,
                {
                    "company_name": company_name,
                    "job_text": job_text,
                    "ai_letters": ai_letters,
                    "letter_text": primary_letter,
                    "vector": vector,  # Firestore stores vector with document
                },
                allow_update=False,
                user_id=user_id,
            )
    except ValueError as e:
        return JsonResponse({"detail": f"letters generated but failed to save: {e}"}, status=500)
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"detail": f"letters generated but failed to save: {exc}"}, status=500)

    return JsonResponse({"status": "ok", "letters": letters, "document": document})


@prevent_duplicate_requests(endpoint_path="extract")
def extract_view(request: HttpRequest):
    """Extract job metadata from job text. Uses a default vendor (openai) for extraction."""
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON"}, status=400)

    job_text = data.get("job_text")
    if not job_text:
        return JsonResponse({"detail": "job_text is required"}, status=400)

    # Session ID comes from Django session cookie, not request body
    from .session_helpers import get_session_id, save_session_common_data
    session_id = get_session_id(request)

    # Use OpenAI as default for extraction (fast and reliable)
    try:
        from letter_writer.client import get_client
        from letter_writer.clients.base import ModelVendor
        from letter_writer.generation import extract_job_metadata
        from pathlib import Path

        ai_client = get_client(ModelVendor.OPENAI)
        trace_dir = Path("trace", "extraction.openai")
        extraction = extract_job_metadata(job_text, ai_client, trace_dir=trace_dir)
        
        # Save common data with extraction metadata (common to all vendors)
        # Load CV if not already in session
        import logging
        logger = logging.getLogger(__name__)
        
        cv_in_session = request.session.get("cv_text")
        needs_cv_load = not cv_in_session or not str(cv_in_session).strip()
        
        if needs_cv_load:
            logger.info("extract_view: CV not in session, loading from Firestore")
        
        save_session_common_data(
            request=request,
            job_text=job_text,
            metadata={"common": extraction},  # Store extraction as common metadata
            load_cv=needs_cv_load,  # Load CV if missing
        )
        
        # Verify CV is now in session
        cv_in_session = request.session.get("cv_text")
        if cv_in_session:
            logger.info(f"extract_view: CV present in session, length={len(cv_in_session)}")
        else:
            logger.error("extract_view: CV still missing after load attempt")
            from letter_writer.generation import MissingCVError
            raise MissingCVError("CV text is missing or empty - please upload your CV in the 'Your CV' tab")
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return JsonResponse({"detail": str(exc)}, status=500)

    return JsonResponse(
        {
            "status": "ok",
            "extraction": extraction,
            "session_id": session_id,
        }
    )


def init_session_view(request: HttpRequest):
    """Initialize a new session. Called when page loads or user first interacts.
    
    Also handles session recovery - if client sends full session data, restores it.
    """
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON"}, status=400)

    # Session ID comes from Django session cookie, not request body
    from .session_helpers import (
        get_session_id,
        save_session_common_data,
        check_session_exists,
        restore_session_data,
    )
    
    # Check if this is a recovery request (client sending full session data)
    # NOTE: cv_text is never sent from frontend, so we don't check for it
    is_recovery = bool(
        data.get("job_text") or
        data.get("metadata") or
        data.get("vendors")
    )
    
    session_id = get_session_id(request)
    session_exists = check_session_exists(request)
    
    try:
        if is_recovery and not session_exists:
            # Server lost session, client is restoring it
            # NOTE: cv_text is never sent from client, always loaded from Firestore
            session_id = restore_session_data(
                request=request,
                job_text=data.get("job_text", ""),
                metadata=data.get("metadata", {}),
                search_result=data.get("search_result"),
                vendors=data.get("vendors", {}),
            )
            return JsonResponse({
                "status": "ok",
                "session_id": session_id,
                "recovered": True,
                "message": "Session restored from client data",
            })
        else:
            # Normal initialization - only update if data is provided
            # When clicking back, session might exist but no data is sent,
            # so we should preserve existing session data
            # NOTE: cv_text is never sent from frontend, always loaded from Firestore
            job_text = data.get("job_text")
            metadata = data.get("metadata")
            
            # ALWAYS check if CV is missing and load it if needed
            # This is critical - CV must be in session before background phases start
            # This handles the case when clicking back (no API call) then starting phases
            import logging
            logger = logging.getLogger(__name__)
            
            cv_in_session = request.session.get("cv_text")
            cv_missing = not cv_in_session or not str(cv_in_session).strip()
            needs_cv_load = not session_exists or cv_missing
            
            logger.info(
                f"init_session: session_exists={session_exists}, cv_missing={cv_missing}, "
                f"needs_cv_load={needs_cv_load}, has_cv_in_session={bool(cv_in_session)}"
            )
            
            # Determine if we need to save session data
            has_new_data = job_text is not None or metadata is not None
            needs_save = has_new_data or not session_exists or needs_cv_load
            
            # ALWAYS load CV if needed, regardless of other conditions
            # This ensures CV is in session before any background phases start
            if needs_cv_load:
                logger.info("Loading CV from Firestore into session")
                save_session_common_data(
                    request=request,
                    job_text=job_text if job_text is not None else "",
                    metadata=metadata if metadata is not None else {},
                    load_cv=True,  # Always load CV if needed
                )
            elif needs_save:
                # Save other data but don't reload CV (already present)
                save_session_common_data(
                    request=request,
                    job_text=job_text if job_text is not None else "",
                    metadata=metadata if metadata is not None else {},
                    load_cv=False,  # CV already present, don't reload
                )
            
            # Verify CV is now in session after loading
            cv_after = request.session.get("cv_text")
            if not cv_after or not str(cv_after).strip():
                logger.error(f"init_session: CV still missing after load attempt! session_exists={session_exists}")
            else:
                logger.info(f"init_session: CV loaded successfully, length={len(cv_after)}")
            
            return JsonResponse({
                "status": "ok",
                "session_id": session_id,
                "session_exists": session_exists,
            })
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return JsonResponse({"detail": str(exc)}, status=500)


def restore_session_view(request: HttpRequest):
    """Restore session data from client.
    
    Called when server restarts and loses in-memory sessions.
    Client sends session data (job_text, metadata, vendors, etc.)
    and server restores it to the current session.
    NOTE: cv_text is NEVER restored from client - it's always loaded from Firestore.
    """
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON"}, status=400)

    try:
        from .session_helpers import restore_session_data, get_session_id
        
        # Restore full session from client data
        # NOTE: cv_text is never restored from client - always loaded from Firestore
        session_id = restore_session_data(
            request=request,
            job_text=data.get("job_text", ""),
            metadata=data.get("metadata", {}),
            search_result=data.get("search_result"),
            vendors=data.get("vendors", {}),
        )
        
        return JsonResponse({
            "status": "ok",
            "session_id": session_id,
            "message": "Session restored successfully",
        })
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return JsonResponse({"detail": str(exc)}, status=500)


def get_session_state_view(request: HttpRequest):
    """Get full session state for restoring frontend UI.

    Called on page load to restore user's work if they navigated away.
    Returns all session data (job_text, metadata, vendors, etc.)
    NOTE: cv_text is NOT included - it's never sent to frontend in compose mode.
    CV is only sent to frontend in the personal data tab.
    """
    if request.method != "GET":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    try:
        from .session_helpers import get_full_session_state, get_session_id
        
        session_id = get_session_id(request)
        session_state = get_full_session_state(request)
        
        if session_state is None:
            # No session data - return empty state
            return JsonResponse({
                "status": "ok",
                "session_id": session_id,
                "session_state": None,
                "has_data": False,
            })
        
        return JsonResponse({
            "status": "ok",
            "session_id": session_id,
            "session_state": session_state,
            "has_data": True,
        })
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return JsonResponse({"detail": str(exc)}, status=500)


def clear_session_view(request: HttpRequest):
    """Clear all session data.
    
    Called when:
    - User explicitly clicks "clear" button
    - Final data is saved/copied (user is done with this letter)
    
    This also triggers a cost flush to Firebase since the user has completed their letter.
    """
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    try:
        from .session_helpers import clear_session, get_session_id
        
        old_session_id = get_session_id(request)
        clear_session(request)
        new_session_id = get_session_id(request)
        
        # Flush costs to BigQuery when letter is completed
        # This ensures the user's costs are recorded immediately
        cost_flush_result = None
        if request.user.is_authenticated:
            try:
                # Get user_id
                user_id = None
                try:
                    from allauth.socialaccount.models import SocialAccount
                    social_account = SocialAccount.objects.filter(user=request.user, provider='google').first()
                    if social_account:
                        user_id = social_account.uid
                except (ImportError, Exception):
                    pass
                if not user_id:
                    user_id = str(request.user.id)
                
                from letter_writer.cost_tracker import flush_on_letter_completion
                cost_flush_result = flush_on_letter_completion(user_id)
            except Exception as e:
                logger.warning(f"Cost flush to BigQuery failed on session clear: {e}")
        
        return JsonResponse({
            "status": "ok",
            "old_session_id": old_session_id,
            "new_session_id": new_session_id,
            "message": "Session cleared successfully",
            "cost_flush": cost_flush_result,
        })
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return JsonResponse({"detail": str(exc)}, status=500)


@prevent_duplicate_requests(endpoint_path="phases/session")
def update_session_common_data_view(request: HttpRequest):
    """Update common session data. Called when 'start phases' is clicked if user modified data.
    
    Accepts individual fields that the user sees in the webpage:
    - job_text, cv_text
    - company_name, job_title, location, language, salary, requirements, point_of_contact
    
    These fields are saved as common metadata (together with job_text and cv_text).
    Qdrant connection is a server-side constant (from environment variables), not user-facing.
    """
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON"}, status=400)

    # Session ID comes from Django session cookie, not request body
    from .session_helpers import get_session_id, save_session_common_data, load_session_common_data
    session_id = get_session_id(request)

    job_text = data.get("job_text")
    # NOTE: cv_text is never saved to session - it's loaded from Firestore when needed via load_session_common_data()

    try:
        # Load existing session to preserve other fields
        # This also loads CV from Firestore if missing (emergency restore)
        existing = load_session_common_data(request)
        existing_metadata = existing["metadata"] if existing else {}
        
        # Check if CV is missing and needs to be loaded
        # This is critical - CV must be in session before background phases start
        cv_in_session = request.session.get("cv_text")
        cv_missing = not cv_in_session or not str(cv_in_session).strip()
        needs_cv_load = cv_missing
        
        import logging
        logger = logging.getLogger(__name__)
        if needs_cv_load:
            logger.info("update_session_common_data: CV missing, will load from Firestore")
        
        # Build common metadata from individual fields (if provided)
        # These are the fields the user sees in the webpage
        common_metadata = existing_metadata.get("common", {})
        
        # Update metadata fields if provided in request
        if "company_name" in data:
            common_metadata["company_name"] = data["company_name"]
        if "job_title" in data:
            common_metadata["job_title"] = data["job_title"]
        if "location" in data:
            common_metadata["location"] = data["location"]
        if "language" in data:
            common_metadata["language"] = data["language"]
        if "salary" in data:
            common_metadata["salary"] = data["salary"]
        if "requirements" in data:
            common_metadata["requirements"] = data["requirements"]
        if "point_of_contact" in data:
            common_metadata["point_of_contact"] = data["point_of_contact"]
        
        # Save updated metadata
        existing_metadata["common"] = common_metadata
        
        # Save common data (job_text and metadata)
        # Load CV if missing - this ensures CV is always in session
        # NOTE: cv_text is never saved to session from client - it's loaded from Firestore
        save_session_common_data(
            request=request,
            job_text=job_text,
            metadata=existing_metadata,
            load_cv=needs_cv_load,  # Load CV if missing
        )
        
        # Verify CV is now in session
        cv_after = request.session.get("cv_text")
        if not cv_after or not str(cv_after).strip():
            logger.error("update_session_common_data: CV still missing after load attempt!")
        else:
            logger.info(f"update_session_common_data: CV loaded successfully, length={len(cv_after)}")
        
        return JsonResponse({"status": "ok", "session_id": session_id})
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return JsonResponse({"detail": str(exc)}, status=500)


@prevent_duplicate_requests(endpoint_path="phases/background", use_vendor_in_key=True, replace_timeout=30.0)
def background_phase_view(request: HttpRequest, vendor: str):
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON"}, status=400)

    # Session ID comes from Django session cookie, not request body
    from .session_helpers import get_session_id, load_session_common_data, check_session_exists
    session_id = get_session_id(request)
    
    # Check if session exists - server tells client if it needs to restore
    if not check_session_exists(request):
        return JsonResponse({
            "status": "session_lost",
            "detail": "Session not found on server. Server restarted or session expired. Please restore session data.",
            "session_id": session_id,
            "requires_restore": True,
            "error_code": "SESSION_NOT_FOUND",
        }, status=410)  # 410 Gone - resource no longer available

    try:
        vendors = [ModelVendor(vendor)]
    except ValueError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)

    # Background phase reads ALL data from session - only session_id needed
    # Fields are saved to common store by extraction phase or /api/phases/session/ before this is called

    try:
        from letter_writer.phased_service import _run_background_phase
        from letter_writer.session_store import set_current_request
        
        # Set request in thread-local so session_store can use Django sessions
        set_current_request(request)
        
        # Load common data (read-only - background phase does NOT write common data)
        common_data = load_session_common_data(request)
        if common_data is None:
            return JsonResponse({
                "status": "session_lost",
                "detail": "Session data not found on server. Please restore session data.",
                "session_id": session_id,
                "requires_restore": True,
                "error_code": "SESSION_DATA_NOT_FOUND",
            }, status=410)
        
        # Metadata must exist in common store (created by extraction phase or session call)
        if "common" not in common_data["metadata"]:
            raise ValueError(f"Metadata not found in session. Please run extraction first or provide extraction data via /api/phases/session/")
        
        # Fail fast: validate cv_text and job_text before starting background phase
        # This catches empty cv_text immediately, before any expensive operations
        cv_text = common_data.get("cv_text", "")
        job_text = common_data.get("job_text", "")
        if not cv_text or not str(cv_text).strip():
            from letter_writer.generation import MissingCVError
            import logging
            logger = logging.getLogger(__name__)
            error_msg = f"CV text is missing or empty in session - cannot proceed with background phase"
            logger.error(error_msg, extra={"session_id": session_id, "vendor": vendor, "cv_text": cv_text})
            raise MissingCVError(error_msg)
        if not job_text or not str(job_text).strip():
            return JsonResponse({
                "status": "error",
                "detail": "Job text is missing or empty in session. Please provide job description.",
                "session_id": session_id,
                "error_code": "JOB_TEXT_MISSING",
            }, status=400)
        
        # Run background phase for this vendor (writes only vendor-specific data)
        # Note: _run_background_phase still expects session_id for compatibility, but we'll update it to use request
        vendor_state = _run_background_phase(session_id, vendors[0], common_data)
        
        # Track cost for this API call
        if vendor_state.cost > 0:
            from letter_writer.cost_tracker import track_api_cost
            # Get user_id if authenticated
            user_id = None
            if request.user.is_authenticated:
                try:
                    from allauth.socialaccount.models import SocialAccount
                    social_account = SocialAccount.objects.filter(user=request.user, provider='google').first()
                    if social_account:
                        user_id = social_account.uid
                except (ImportError, Exception):
                    pass
                if not user_id:
                    user_id = str(request.user.id)
            
            track_api_cost(
                service=f"background_{vendor}",
                cost=vendor_state.cost,
                metadata={
                    "vendor": vendor,
                    "phase": "background"
                },
                user_id=user_id
            )
        
        # Return only data for the requested vendor
        return JsonResponse(
            {
                "status": "ok",
                "company_report": vendor_state.company_report,
                "top_docs": vendor_state.top_docs,
                "cost": vendor_state.cost,
            }
        )
    except ValueError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return JsonResponse({"detail": str(exc)}, status=500)


@prevent_duplicate_requests(endpoint_path="phases/refine", use_vendor_in_key=True, replace_timeout=30.0)
def refinement_phase_view(request: HttpRequest, vendor: str):
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON"}, status=400)

    # Session ID comes from Django session cookie, not request body
    from .session_helpers import get_session_id, check_session_exists
    session_id = get_session_id(request)
    
    # Check if session exists - server tells client if it needs to restore
    if not check_session_exists(request):
        return JsonResponse({
            "status": "session_lost",
            "detail": "Session not found on server. Server restarted or session expired. Please restore session data.",
            "session_id": session_id,
            "requires_restore": True,
            "error_code": "SESSION_NOT_FOUND",
        }, status=410)  # 410 Gone - resource no longer available
    
    try:
        vendor_enum = ModelVendor(vendor)
    except ValueError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)

    fancy = _safe_bool(data.get("fancy", False))

    # Only use draft_override if it was explicitly provided in the request
    # If the key is missing, use None to fall back to session draft
    draft_override = data.get("draft_letter") if "draft_letter" in data else None

    try:
        from letter_writer.session_store import set_current_request
        # Set request in thread-local so session_store can use Django sessions
        set_current_request(request)
        
        state = advance_to_refinement(
            session_id=session_id,
            vendor=vendor_enum,
            draft_override=draft_override,
            feedback_override=data.get("feedback_override"),
            company_report_override=data.get("company_report"),
            top_docs_override=data.get("top_docs"),
            fancy=fancy,
        )
        
        # Track cost for this API call
        if state.cost > 0:
            from letter_writer.cost_tracker import track_api_cost
            # Get user_id if authenticated
            user_id = None
            if request.user.is_authenticated:
                try:
                    from allauth.socialaccount.models import SocialAccount
                    social_account = SocialAccount.objects.filter(user=request.user, provider='google').first()
                    if social_account:
                        user_id = social_account.uid
                except (ImportError, Exception):
                    pass
                if not user_id:
                    user_id = str(request.user.id)
            
            track_api_cost(
                service=f"refine_{vendor}",
                cost=state.cost,
                metadata={
                    "vendor": vendor,
                    "phase": "refine",
                    "fancy": fancy
                },
                user_id=user_id
            )
    except ValueError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return JsonResponse({"detail": str(exc)}, status=500)

    return JsonResponse(
        {
            "status": "ok",
            "final_letter": state.final_letter,
            "cost": state.cost,
        }
    )


@prevent_duplicate_requests(endpoint_path="phases/draft", use_vendor_in_key=True, replace_timeout=30.0)
def draft_phase_view(request: HttpRequest, vendor: str):
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON"}, status=400)

    # Session ID comes from Django session cookie, not request body
    from .session_helpers import get_session_id, check_session_exists
    session_id = get_session_id(request)
    
    # Check if session exists - server tells client if it needs to restore
    if not check_session_exists(request):
        return JsonResponse({
            "status": "session_lost",
            "detail": "Session not found on server. Server restarted or session expired. Please restore session data.",
            "session_id": session_id,
            "requires_restore": True,
            "error_code": "SESSION_NOT_FOUND",
        }, status=410)  # 410 Gone - resource no longer available
    
    try:
        vendor_enum = ModelVendor(vendor)
    except ValueError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)

    try:
        from letter_writer.session_store import set_current_request
        # Set request in thread-local so session_store can use Django sessions
        set_current_request(request)
        
        # Get instructions from session
        instructions = request.session.get("style_instructions", "")
        if not instructions:
             instructions = get_style_instructions()
             
        state = advance_to_draft(
            session_id=session_id,
            vendor=vendor_enum,
            company_report_override=data.get("company_report"),
            top_docs_override=data.get("top_docs"),
            style_instructions=instructions,
        )
        
        # Track cost for this API call
        if state.cost > 0:
            from letter_writer.cost_tracker import track_api_cost
            # Get user_id if authenticated
            user_id = None
            if request.user.is_authenticated:
                try:
                    from allauth.socialaccount.models import SocialAccount
                    social_account = SocialAccount.objects.filter(user=request.user, provider='google').first()
                    if social_account:
                        user_id = social_account.uid
                except (ImportError, Exception):
                    pass
                if not user_id:
                    user_id = str(request.user.id)
            
            track_api_cost(
                service=f"draft_{vendor}",
                cost=state.cost,
                metadata={
                    "vendor": vendor,
                    "phase": "draft"
                },
                user_id=user_id
            )
    except ValueError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return JsonResponse({"detail": str(exc)}, status=500)

    return JsonResponse(
        {
            "status": "ok",
            "draft_letter": state.draft_letter,
            "feedback": state.feedback,
            "cost": state.cost,
        }
    )


def vendors_view(request: HttpRequest):
    if request.method != "GET":
        return JsonResponse({"detail": "Method not allowed"}, status=405)
    
    vendors = [v.value for v in ModelVendor]
    
    # Determine which vendors are active
    active_vendors = None
    
    # First, check session metadata for selected_vendors (if session exists)
    if request.session.session_key:
        from .session_helpers import load_session_common_data
        session_data = load_session_common_data(request)
        if session_data and session_data.get("metadata"):
            metadata = session_data["metadata"]
            common_metadata = metadata.get("common", {})
            selected_vendors = common_metadata.get("selected_vendors")
            if selected_vendors and isinstance(selected_vendors, list):
                active_vendors = set(selected_vendors)
    
    # If not in session, check personal data document for default_models
    # Only check if user is authenticated (vendors endpoint doesn't require auth)
    if active_vendors is None and request.user.is_authenticated:
        user_id, error_response = require_auth_user(request)
        if not error_response:
            from letter_writer.firestore_store import get_user_data
            user_data = get_user_data(user_id, use_cache=True)
            if user_data:
                default_models = user_data.get("default_models")
                if default_models and isinstance(default_models, list) and len(default_models) > 0:
                    active_vendors = set(default_models)
    
    # If still no active vendors found, default to all vendors
    if active_vendors is None:
        active_vendors = set(vendors)
    
    # Split vendors into active and inactive lists
    active_list = [v for v in vendors if v in active_vendors]
    inactive_list = [v for v in vendors if v not in active_vendors]
    
    return JsonResponse({
        "active": active_list,
        "inactive": inactive_list
    })


def style_instructions_view(request: HttpRequest):
    # Determine user_id if authenticated
    user_id = None
    if request.user.is_authenticated:
        try:
            from allauth.socialaccount.models import SocialAccount
            social_account = SocialAccount.objects.filter(user=request.user, provider='google').first()
            if social_account:
                user_id = social_account.uid
        except (ImportError, Exception):
            pass
        if not user_id:
            user_id = str(request.user.id)

    if request.method == "GET":
        try:
            instructions = ""
            
            # 1. Check Session (fastest)
            if request.session.session_key:
                instructions = request.session.get("style_instructions", "")
            
            # 2. Check Firestore (if authenticated and not in session)
            if not instructions and user_id:
                user_data = get_user_data(user_id, use_cache=True)
                instructions = user_data.get("style_instructions", "")
                
                # Save to session if found
                if instructions and request.session.session_key:
                    request.session["style_instructions"] = instructions
            
            # 3. Fallback to File (default)
            if not instructions:
                instructions = get_style_instructions()
                
            return JsonResponse({"instructions": instructions})
        except Exception as exc:
            return JsonResponse({"detail": str(exc)}, status=500)
    
    elif request.method == "POST":
        # Update style instructions
        if not user_id:
             return JsonResponse({"detail": "Authentication required to save instructions"}, status=401)

        try:
            data = json.loads(request.body or "{}")
            instructions = data.get("instructions", "")
            
            if not instructions:
                return JsonResponse({"detail": "Instructions cannot be empty"}, status=400)
            
            # 1. Update Firestore
            user_doc_ref = get_personal_data_document(user_id)
            user_doc_ref.set({
                "style_instructions": instructions, 
                "updated_at": datetime.utcnow()
            }, merge=True)
            
            # Clear cache
            clear_user_data_cache(user_id)
            
            # 2. Update Session
            if not request.session.session_key:
                request.session.create()
            request.session["style_instructions"] = instructions
            
            # 3. NO LONGER write to file (avoids 403 and persists per user)
            
            return JsonResponse({"status": "ok", "instructions": instructions})
        except json.JSONDecodeError:
            return JsonResponse({"detail": "Invalid JSON"}, status=400)
        except Exception as exc:
            return JsonResponse({"detail": str(exc)}, status=500)
    
    else:
        return JsonResponse({"detail": "Method not allowed"}, status=405)


@prevent_duplicate_requests(endpoint_path="translate")
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

    # Calculate character count for cost tracking
    character_count = sum(len(text) for text in texts if text)
    
    # Get user_id if authenticated
    user_id = None
    if request.user.is_authenticated:
        try:
            from allauth.socialaccount.models import SocialAccount
            social_account = SocialAccount.objects.filter(user=request.user, provider='google').first()
            if social_account:
                user_id = social_account.uid
        except (ImportError, Exception):
            pass
        if not user_id:
            user_id = str(request.user.id)

    try:
        translations = _translate_with_google(texts, target_language, source_language)
        
        # Track cost: Google Translate charges $20 per million characters
        from letter_writer.cost_tracker import calculate_translation_cost, track_api_cost
        cost = calculate_translation_cost(character_count)
        
        track_api_cost(
            service="translate",
            cost=cost,
            metadata={
                "character_count": character_count,
                "text_count": len(texts),
                "target_language": target_language,
                "source_language": source_language,
            },
            user_id=user_id
        )
        
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"detail": str(exc)}, status=500)

    return JsonResponse({
        "translations": translations,
        "cost": cost,
        "character_count": character_count
    })


# ---------------------------------------------------------------------------
# Documents (Mongo + Qdrant)
# ---------------------------------------------------------------------------


def _json_error(detail: str, status: int = 400):
    return JsonResponse({"detail": detail}, status=status)


def _require_json_body(request: HttpRequest) -> Dict[str, Any] | None:
    try:
        return json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return None


def documents_view(request: HttpRequest):
    # Require authentication
    user_id, error_response = require_auth_user(request)
    if error_response:
        return error_response
    
    collection = get_collection()

    if request.method == "GET":
        params = request.GET
        docs = list_documents(
            collection,
            user_id=user_id,  # Filter by user_id for security
            company_name=params.get("company_name"),
            role=params.get("role"),
            limit=int(params.get("limit", 50)),
            skip=int(params.get("skip", 0)),
        )
        return JsonResponse({"documents": docs})

    if request.method != "POST":
        return _json_error("Method not allowed", status=405)

    data = _require_json_body(request)
    if data is None:
        return _json_error("Invalid JSON")

    company_name = data.get("company_name")
    job_text = data.get("job_text")
    if not job_text:
        return _json_error("job_text is required")

    # Generate vector embedding
    openai_client = OpenAI()
    vector = embed(job_text, openai_client)
    
    # Persist document with vector (Firestore stores everything together)
    data["vector"] = vector
    try:
        document = upsert_document(collection, data, allow_update=False, user_id=user_id)
    except ValueError as e:
        return _json_error(str(e), status=400)

    return JsonResponse({"document": document}, status=201)


def document_detail_view(request: HttpRequest, document_id: str):
    # Require authentication
    user_id, error_response = require_auth_user(request)
    if error_response:
        return error_response
    
    collection = get_collection()
    
    if request.method == "GET":
        try:
            existing = get_document(collection, document_id, user_id=user_id)
            if not existing:
                return _json_error("Not found", status=404)
            return JsonResponse({"document": existing})
        except PermissionError:
            return _json_error("Not found", status=404)  # Don't leak existence of other users' documents
        except ValueError as e:
            return _json_error(str(e), status=400)

    if request.method == "DELETE":
        try:
            existing = get_document(collection, document_id, user_id=user_id)
            if existing is None:
                return _json_error("Not found", status=404)
        except PermissionError:
            return _json_error("Not found", status=404)  # Don't leak existence of other users' documents
        except ValueError as e:
            return _json_error(str(e), status=400)
        
        # Firestore: delete document (vector is stored with document, so deleted together)
        # Note: delete_documents doesn't check user_id, but we've verified ownership above
        delete_documents(collection, [document_id])
        return JsonResponse({"status": "deleted"})

    if request.method != "PUT":
        return _json_error("Method not allowed", status=405)

    data = _require_json_body(request)
    if data is None:
        return _json_error("Invalid JSON")

    try:
        existing = get_document(collection, document_id, user_id=user_id)
        if existing is None:
            return _json_error("Not found", status=404)
    except PermissionError:
        return _json_error("Not found", status=404)  # Don't leak existence of other users' documents
    except ValueError as e:
        return _json_error(str(e), status=400)

    data["id"] = document_id
    try:
        updated = upsert_document(collection, data, allow_update=True, user_id=user_id)
        return JsonResponse({"document": updated})
    except PermissionError:
        return _json_error("Not found", status=404)  # Don't leak existence of other users' documents
    except ValueError as e:
        return _json_error(str(e), status=400)


def document_negatives_view(request: HttpRequest, document_id: str):
    # Require authentication
    user_id, error_response = require_auth_user(request)
    if error_response:
        return error_response
    
    if request.method != "POST":
        return _json_error("Method not allowed", status=405)

    data = _require_json_body(request)
    if data is None:
        return _json_error("Invalid JSON")
    negatives = data.get("negatives") or []

    collection = get_collection()
    try:
        updated = append_negatives(collection, document_id, negatives, user_id=user_id)
        if updated is None:
            return _json_error("Not found", status=404)
        return JsonResponse({"document": updated})
    except PermissionError:
        return _json_error("Not found", status=404)  # Don't leak existence of other users' documents
    except ValueError as e:
        return _json_error(str(e), status=400)


@prevent_duplicate_requests(endpoint_path="documents/reembed")
def document_reembed_view(request: HttpRequest, document_id: str):
    # Require authentication
    user_id, error_response = require_auth_user(request)
    if error_response:
        return error_response
    
    if request.method != "POST":
        return _json_error("Method not allowed", status=405)

    collection = get_collection()
    try:
        doc = get_document(collection, document_id, user_id=user_id)
        if not doc:
            return _json_error("Not found", status=404)
    except PermissionError:
        return _json_error("Not found", status=404)  # Don't leak existence of other users' documents
    except ValueError as e:
        return _json_error(str(e), status=400)
    
    if not doc.get("job_text"):
        return _json_error("Document is missing job_text", status=400)

    openai_client = OpenAI()
    vector = embed(doc["job_text"], openai_client)
    
    # Update document with new vector (Firestore stores vector with document)
    doc_ref = collection.document(document_id)
    doc_ref.update({"vector": vector})
    
    return JsonResponse({"status": "ok"})


# ---------------------------------------------------------------------------
# Personal Data (CV) Management
# ---------------------------------------------------------------------------


def _extract_text_from_file(file_content: bytes, filename: str) -> str:
    """Extract text from uploaded file (PDF, TXT, MD)."""
    filename_lower = filename.lower()
    
    if filename_lower.endswith('.txt'):
        try:
            return file_content.decode('utf-8')
        except UnicodeDecodeError:
            try:
                return file_content.decode('latin-1')
            except UnicodeDecodeError:
                return file_content.decode('utf-8', errors='replace')
    
    elif filename_lower.endswith('.md'):
        try:
            return file_content.decode('utf-8')
        except UnicodeDecodeError:
            return file_content.decode('utf-8', errors='replace')
    
    elif filename_lower.endswith('.pdf'):
        try:
            import PyPDF2
        except ImportError:
            raise ValueError("PyPDF2 is required for PDF extraction. Install with: pip install PyPDF2")
        try:
            pdf_file = io.BytesIO(file_content)
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            text_parts = []
            for page in pdf_reader.pages:
                text_parts.append(page.extract_text())
            return '\n'.join(text_parts)
        except Exception as exc:
            raise ValueError(f"Failed to extract text from PDF: {exc}")
    
    else:
        raise ValueError(f"Unsupported file type: {filename}. Supported: .txt, .md, .pdf")


def personal_data_view(request: HttpRequest):
    """Get or update personal data (CV, languages, etc) from personal_data collection.
    
    Uses user_id as document ID: personal_data/{user_id}
    Document structure:
    {
        "cv_revisions": [...],
        "default_languages": [...],
        "style_instructions": "...",
        "updated_at": timestamp,
    }
    
    This uses get_user_data() which can be cached in memory for the request duration.
    """
    # Require authentication
    user_id, error_response = require_auth_user(request)
    if error_response:
        return error_response
    
    if request.method == "GET":
        # Get user data (cached for request duration)
        # On first access, migrate old personal_data/cv if it exists
        # Note: user_id is already Google UID from require_auth_user()
        user_data = get_user_data(user_id, use_cache=True)
        
        # If user document doesn't exist, check for old structure and migrate
        if not user_data:
            migrated = _migrate_old_cv_data(user_id)
            if migrated:
                # Clear cache and reload after migration
                clear_user_data_cache(user_id)
                user_data = get_user_data(user_id, use_cache=False)
            else:
                user_data = {}  # No old data to migrate
        
        revisions = user_data.get("cv_revisions", [])
        default_languages = user_data.get("default_languages", [])
        default_models = user_data.get("default_models", [])
        min_column_width = user_data.get("min_column_width")
        
        # Convert Firestore Timestamps to ISO strings and find latest
        latest_content = ""
        if revisions:
            # Convert timestamps to datetime objects for comparison, then to ISO strings
            response_revisions = []
            revision_datetimes = []
            for rev in revisions:
                rev_copy = dict(rev)
                if "created_at" in rev_copy:
                    ts = rev_copy["created_at"]
                    # Convert to datetime if it's a Firestore Timestamp
                    if hasattr(ts, "timestamp"):  # Firestore Timestamp
                        dt = datetime.fromtimestamp(ts.timestamp())
                    elif isinstance(ts, datetime):
                        dt = ts
                    elif isinstance(ts, str):
                        # Already a string, try to parse it
                        try:
                            dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                        except:
                            dt = datetime.min
                    else:
                        dt = datetime.min
                    rev_copy["created_at"] = dt.isoformat()
                    revision_datetimes.append((dt, rev_copy))
                else:
                    revision_datetimes.append((datetime.min, rev_copy))
            
            # Find latest revision by datetime
            if revision_datetimes:
                latest_dt, latest = max(revision_datetimes, key=lambda x: x[0])
                latest_content = latest.get("content", "")
                response_revisions = [rev for _, rev in sorted(revision_datetimes, key=lambda x: x[0], reverse=True)]
            else:
                response_revisions = []
        else:
            response_revisions = []
        
        return JsonResponse({
            "cv": latest_content,
            "revisions": response_revisions,
            "default_languages": default_languages,
            "default_models": default_models,
            "min_column_width": min_column_width,
        })
    
    if request.method == "POST":
        # Handle file upload or text update
        content_type = request.content_type or ""
        
        # Get existing user document (using user_id as document ID)
        user_doc_ref = get_personal_data_document(user_id)
        user_doc = user_doc_ref.get()
        existing_data = user_doc.to_dict() if user_doc.exists else {}
        revisions = existing_data.get("cv_revisions", [])
        now = datetime.utcnow()
        updates = {"updated_at": now}
        
        if "multipart/form-data" in content_type:
            # File upload - Update CV
            if "file" not in request.FILES:
                return JsonResponse({"detail": "No file provided"}, status=400)
            
            uploaded_file = request.FILES["file"]
            filename = uploaded_file.name
            
            # Validate file type
            if not (filename.lower().endswith(('.txt', '.md', '.pdf'))):
                return JsonResponse({"detail": "Unsupported file type. Supported: .txt, .md, .pdf"}, status=400)
            
            try:
                file_content = uploaded_file.read()
                extracted_text = _extract_text_from_file(file_content, filename)
            except Exception as exc:
                return JsonResponse({"detail": str(exc)}, status=400)
            
            content = extracted_text
            source = f"upload:{filename}"
            
            # Create new revision
            new_revision = {
                "content": content,
                "source": source,
                "created_at": now,
                "revision_number": len(revisions) + 1,
            }
            revisions.append(new_revision)
            updates["cv_revisions"] = revisions
            
        else:
            # JSON update (CV or Settings)
            try:
                data = json.loads(request.body or "{}")
            except json.JSONDecodeError:
                return JsonResponse({"detail": "Invalid JSON"}, status=400)
            
            # Check if updating default_languages
            if "default_languages" in data:
                languages = data["default_languages"]
                if not isinstance(languages, list):
                    return JsonResponse({"detail": "default_languages must be a list"}, status=400)
                updates["default_languages"] = languages

            # Check if updating default_models
            if "default_models" in data:
                models = data["default_models"]
                if not isinstance(models, list):
                    return JsonResponse({"detail": "default_models must be a list"}, status=400)
                updates["default_models"] = models
                
                # Also update current session if it exists (as if user modified in compose tab)
                # This ensures the change takes effect immediately for active workflows
                if request.session.session_key:
                    from .session_helpers import load_session_common_data
                    existing = load_session_common_data(request)
                    if existing:
                        # Update session metadata to reflect selected vendors
                        if "metadata" not in request.session:
                            request.session["metadata"] = {}
                        if "common" not in request.session["metadata"]:
                            request.session["metadata"]["common"] = {}
                        request.session["metadata"]["common"]["selected_vendors"] = models
                        request.session.modified = True

            # Check if updating min_column_width
            if "min_column_width" in data:
                width = data["min_column_width"]
                if not isinstance(width, (int, float)) or width < 0:
                    return JsonResponse({"detail": "min_column_width must be a positive number"}, status=400)
                updates["min_column_width"] = int(width)

            # Check if updating style_instructions
            if "style_instructions" in data:
                updates["style_instructions"] = data["style_instructions"]
                
            # Check if updating CV content (mutually exclusive with other updates)
            if "content" in data:
                content = data.get("content", "")
                if not content:
                    return JsonResponse({"detail": "content is required"}, status=400)
                source = data.get("source", "manual_edit")
                
                # Create new revision
                new_revision = {
                    "content": content,
                    "source": source,
                    "created_at": now,
                    "revision_number": len(revisions) + 1,
                }
                revisions.append(new_revision)
                updates["cv_revisions"] = revisions
            
            # If no updates were made, return error
            if not updates or updates == {"updated_at": now}:
                return JsonResponse({"detail": "No valid data provided for update"}, status=400)
        
        # Update user document (merge with existing fields)
        user_doc_ref.set(updates, merge=True)
        
        # Clear cache after update
        clear_user_data_cache(user_id)
        
        # Prepare response
        response_data = {"status": "ok"}
        
        if "cv_revisions" in updates:
            # Convert timestamps for response
            response_revisions = []
            for rev in revisions:
                rev_copy = dict(rev)
                if "created_at" in rev_copy:
                    ts = rev_copy["created_at"]
                    if hasattr(ts, "isoformat"):
                        rev_copy["created_at"] = ts.isoformat()
                    elif isinstance(ts, datetime):
                        rev_copy["created_at"] = ts.isoformat()
                    elif hasattr(ts, "timestamp"):  # Firestore Timestamp
                        dt = datetime.fromtimestamp(ts.timestamp())
                        rev_copy["created_at"] = dt.isoformat()
                response_revisions.append(rev_copy)
            
            response_data["revisions"] = response_revisions
            # Also return the latest content if it was a CV update
            if "content" in locals():
                response_data["cv"] = content

        if "default_languages" in updates:
            response_data["default_languages"] = updates["default_languages"]

        if "style_instructions" in updates:
            response_data["style_instructions"] = updates["style_instructions"]
        
        return JsonResponse(response_data, status=201)
    
    return JsonResponse({"detail": "Method not allowed"}, status=405)


# ---------------------------------------------------------------------------
# Debug endpoints for spam prevention
# ---------------------------------------------------------------------------


def debug_in_flight_requests_view(request: HttpRequest):
    """Debug endpoint to inspect in-flight requests."""
    if request.method != "GET":
        return JsonResponse({"detail": "Method not allowed"}, status=405)
    
    in_flight = get_in_flight_requests()
    return JsonResponse({
        "count": len(in_flight),
        "requests": in_flight,
    })


def debug_clear_in_flight_requests_view(request: HttpRequest):
    """Debug endpoint to clear all in-flight requests."""
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed"}, status=405)
    
    cleared = clear_in_flight_requests()
    return JsonResponse({
        "status": "ok",
        "cleared_count": cleared,
    })


# ---------------------------------------------------------------------------
# Cost tracking endpoints
# ---------------------------------------------------------------------------


def cost_summary_view(request: HttpRequest):
    """Get pending API cost summary from Redis/memory.
    
    Returns current costs accumulated since last flush to BigQuery.
    """
    if request.method != "GET":
        return JsonResponse({"detail": "Method not allowed"}, status=405)
    
    from letter_writer.cost_tracker import get_cost_summary
    
    try:
        summary = get_cost_summary()
        return JsonResponse(summary)
    except Exception as exc:
        return JsonResponse({"detail": str(exc)}, status=500)


def cost_flush_view(request: HttpRequest):
    """Manually trigger a cost flush to BigQuery.
    
    This writes accumulated costs from Redis/memory to BigQuery and resets counters.
    Useful for admin/debugging purposes.
    """
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed"}, status=405)
    
    from letter_writer.cost_tracker import flush_costs_to_bigquery
    
    try:
        result = flush_costs_to_bigquery(reset_after_flush=True)
        return JsonResponse(result)
    except Exception as exc:
        return JsonResponse({"detail": str(exc)}, status=500)


def cost_user_view(request: HttpRequest):
    """Get user's cost totals from BigQuery + pending costs.
    
    Query params:
        months: Number of months to look back (default: 1)
    """
    if request.method != "GET":
        return JsonResponse({"detail": "Method not allowed"}, status=405)
    
    # Require authentication
    user_id, error_response = require_auth_user(request)
    if error_response:
        return error_response
    
    months = int(request.GET.get("months", 1))
    
    from letter_writer.cost_tracker import get_user_monthly_cost, get_cost_summary
    
    try:
        # Get historical costs from BigQuery
        result = get_user_monthly_cost(user_id, months_back=months)
        
        # Add pending costs from Redis/memory (not yet flushed)
        pending = get_cost_summary()
        pending_user = pending.get("by_user", {}).get(user_id, {})
        pending_cost = pending_user.get("total_cost", 0)
        
        # Combine totals
        result["total_cost"] = result.get("total_cost", 0) + pending_cost
        result["pending_cost"] = pending_cost
        
        return JsonResponse(result)
    except Exception as exc:
        return JsonResponse({"detail": str(exc)}, status=500)


def cost_global_view(request: HttpRequest):
    """Get global cost statistics from BigQuery.
    
    Query params:
        months: Number of months to look back (default: 1)
    """
    if request.method != "GET":
        return JsonResponse({"detail": "Method not allowed"}, status=405)
    
    months = int(request.GET.get("months", 1))
    
    from letter_writer.cost_tracker import get_global_monthly_cost
    
    try:
        result = get_global_monthly_cost(months_back=months)
        return JsonResponse(result)
    except Exception as exc:
        return JsonResponse({"detail": str(exc)}, status=500)


def cost_daily_view(request: HttpRequest):
    """Get user's daily cost breakdown from BigQuery.
    
    Query params:
        months: Number of months to look back (default: 1)
    """
    if request.method != "GET":
        return JsonResponse({"detail": "Method not allowed"}, status=405)
    
    # Require authentication
    user_id, error_response = require_auth_user(request)
    if error_response:
        return error_response
    
    months = int(request.GET.get("months", 1))
    
    from letter_writer.cost_tracker import get_user_daily_costs
    
    try:
        result = get_user_daily_costs(user_id, months_back=months)
        return JsonResponse(result)
    except Exception as exc:
        return JsonResponse({"detail": str(exc)}, status=500)