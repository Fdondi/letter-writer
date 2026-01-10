import html
import json
import os
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
    
    This constructs the OAuth URL manually using django-allauth's OAuth2Client and adapter class attributes.
    """
    try:
        from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
        from allauth.socialaccount.models import SocialApp
        from allauth.socialaccount.providers.oauth2.client import OAuth2Client
        from django.contrib.sites.models import Site
        from django.http import HttpResponseRedirect
        from urllib.parse import urlencode
        
        # Get the current site
        site = Site.objects.get_current(request)
        
        # Get Google SocialApp (prefer one associated with current site)
        app = SocialApp.objects.filter(provider='google', sites__id=site.id).first()
        if not app:
            app = SocialApp.objects.filter(provider='google').first()
        
        if not app:
            from django.http import HttpResponse
            return HttpResponse(
                "Google OAuth is not configured. Please run: python manage.py setup_google_oauth",
                status=500
            )
        
        # Use Google's standard OAuth URLs (these are constants)
        # These match django-allauth's GoogleOAuth2Adapter defaults
        authorize_url = 'https://accounts.google.com/o/oauth2/v2/auth'
        access_token_url = 'https://oauth2.googleapis.com/token'
        
        # Build callback URL (same as django-allauth would use)
        from django.contrib.sites.shortcuts import get_current_site
        from django.conf import settings
        
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
        
        # Get OAuth scope and params from settings or use defaults
        socialaccount_providers = getattr(settings, 'SOCIALACCOUNT_PROVIDERS', {})
        google_provider = socialaccount_providers.get('google', {})
        scope = google_provider.get('SCOPE', ['profile', 'email'])
        auth_params = google_provider.get('AUTH_PARAMS', {'access_type': 'online'})
        
        # Manually construct Google OAuth authorization URL
        # OAuth2Client.get_redirect_url() seems to return relative URLs, so build it manually
        from urllib.parse import urlencode
        
        # Build query parameters for Google OAuth
        params = {
            'client_id': app.client_id,
            'redirect_uri': callback_url,
            'scope': ' '.join(scope),
            'response_type': 'code',
            **auth_params  # Include additional params like access_type
        }
        
        # Build the full Google OAuth authorization URL
        auth_url = f"{authorize_url}?{urlencode(params)}"
        
        return HttpResponseRedirect(auth_url)
        
    except ImportError:
        # django-allauth not available
        from django.http import HttpResponse
        return HttpResponse(
            "django-allauth is not installed. Please install it first.",
            status=500
        )
    except Exception as e:
        # On error, fall back to django-allauth's default behavior
        # Use django-allauth's OAuth2LoginView normally (will show consent page, but better than 500)
        try:
            from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
            from allauth.socialaccount.providers.oauth2.views import OAuth2LoginView
            
            # Create a view class that uses GoogleOAuth2Adapter
            class FallbackGoogleLoginView(OAuth2LoginView):
                adapter_class = GoogleOAuth2Adapter
            
            # Use the view class
            view = FallbackGoogleLoginView.as_view()
            return view(request)
        except Exception as inner_e:
            # If even that fails, just show the error
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
        
        # Save common session data with extraction metadata
        cv_text = data.get("cv_text")
        if cv_text is None:
            # Load CV from user's personal data (cached, loaded once per request)
            if request.user.is_authenticated:
                try:
                    user_id = str(request.user.id)
                    user_data = get_user_data(user_id, use_cache=True)
                    revisions = user_data.get("cv_revisions", [])
                    if revisions:
                        # Get the latest revision by comparing timestamps
                        def get_datetime(rev):
                            ts = rev.get("created_at")
                            if ts is None:
                                return datetime.min
                            if hasattr(ts, "timestamp"):  # Firestore Timestamp
                                return datetime.fromtimestamp(ts.timestamp())
                            elif isinstance(ts, datetime):
                                return ts
                            elif isinstance(ts, str):
                                try:
                                    return datetime.fromisoformat(ts.replace('Z', '+00:00'))
                                except:
                                    return datetime.min
                            return datetime.min
                        
                        latest = max(revisions, key=get_datetime)
                        cv_text = latest.get("content", "")
                    else:
                        cv_text = ""
                except Exception:
                    cv_text = ""
            else:
                cv_text = ""
        
        # Save common data with extraction metadata (common to all vendors)
        save_session_common_data(
            request=request,
            job_text=job_text,
            cv_text=cv_text,
            metadata={"common": extraction},  # Store extraction as common metadata
        )
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
    is_recovery = bool(
        data.get("job_text") or
        data.get("cv_text") or
        data.get("metadata") or
        data.get("vendors")
    )
    
    session_id = get_session_id(request)
    session_exists = check_session_exists(request)
    
    try:
        if is_recovery and not session_exists:
            # Server lost session, client is restoring it
            session_id = restore_session_data(
                request=request,
                job_text=data.get("job_text", ""),
                cv_text=data.get("cv_text", ""),
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
            # Normal initialization
            save_session_common_data(
                request=request,
                job_text=data.get("job_text", ""),
                cv_text=data.get("cv_text", ""),
                metadata=data.get("metadata", {}),
            )
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
    Client sends all session data (job_text, cv_text, metadata, vendors, etc.)
    and server restores it to the current session.
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
        session_id = restore_session_data(
            request=request,
            job_text=data.get("job_text", ""),
            cv_text=data.get("cv_text", ""),
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
    Returns all session data (job_text, cv_text, metadata, vendors, etc.)
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
    """
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    try:
        from .session_helpers import clear_session, get_session_id
        
        old_session_id = get_session_id(request)
        clear_session(request)
        new_session_id = get_session_id(request)
        
        return JsonResponse({
            "status": "ok",
            "old_session_id": old_session_id,
            "new_session_id": new_session_id,
            "message": "Session cleared successfully",
        })
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return JsonResponse({"detail": str(exc)}, status=500)


@prevent_duplicate_requests(endpoint_path="phases/session")
def update_session_common_data_view(request: HttpRequest):
    """Update common session data. Called when 'start phases' is clicked if user modified data.
    
    Accepts individual fields that the user sees in the webpage:
    - job_text, cv_text
    - company_name, job_title, location, language, salary, requirements
    
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
    cv_text = data.get("cv_text")
    if cv_text is None:
        # Load CV from user's personal data (cached, loaded once per request)
        if request.user.is_authenticated:
            try:
                user_id = str(request.user.id)
                user_data = get_user_data(user_id, use_cache=True)
                revisions = user_data.get("cv_revisions", [])
                if revisions:
                    # Get the latest revision by comparing timestamps
                    def get_datetime(rev):
                        ts = rev.get("created_at")
                        if ts is None:
                            return datetime.min
                        if hasattr(ts, "timestamp"):  # Firestore Timestamp
                            return datetime.fromtimestamp(ts.timestamp())
                        elif isinstance(ts, datetime):
                            return ts
                        elif isinstance(ts, str):
                            try:
                                return datetime.fromisoformat(ts.replace('Z', '+00:00'))
                            except:
                                return datetime.min
                        return datetime.min
                    
                    latest = max(revisions, key=get_datetime)
                    cv_text = latest.get("content", "")
                else:
                    cv_text = ""
            except Exception:
                cv_text = ""
        else:
            cv_text = ""

    try:
        # Load existing session to preserve other fields
        existing = load_session_common_data(request)
        existing_metadata = existing["metadata"] if existing else {}
        
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
        
        # Save updated metadata
        existing_metadata["common"] = common_metadata
        
        # Save common data (job_text, cv_text, and metadata)
        save_session_common_data(
            request=request,
            job_text=job_text,
            cv_text=cv_text,
            metadata=existing_metadata,
        )
        
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
        
        # Run background phase for this vendor (writes only vendor-specific data)
        # Note: _run_background_phase still expects session_id for compatibility, but we'll update it to use request
        vendor_state = _run_background_phase(session_id, vendors[0], common_data)
        
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
        
        state = advance_to_draft(
            session_id=session_id,
            vendor=vendor_enum,
            company_report_override=data.get("company_report"),
            top_docs_override=data.get("top_docs"),
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
    return JsonResponse({"vendors": vendors})


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

    try:
        translations = _translate_with_google(texts, target_language, source_language)
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"detail": str(exc)}, status=500)

    return JsonResponse({"translations": translations})


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
    if not company_name or not job_text:
        return _json_error("company_name and job_text are required")

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


def personal_data_cv_view(request: HttpRequest):
    """Get or update CV from personal_data collection.
    
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
        })
    
    if request.method == "POST":
        # Handle file upload or text update
        content_type = request.content_type or ""
        
        if "multipart/form-data" in content_type:
            # File upload
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
        else:
            # JSON text update
            try:
                data = json.loads(request.body or "{}")
            except json.JSONDecodeError:
                return JsonResponse({"detail": "Invalid JSON"}, status=400)
            
            content = data.get("content", "")
            if not content:
                return JsonResponse({"detail": "content is required"}, status=400)
            source = data.get("source", "manual_edit")
        
        # Get existing user document (using user_id as document ID)
        user_doc_ref = get_personal_data_document(user_id)
        user_doc = user_doc_ref.get()
        existing_data = user_doc.to_dict() if user_doc.exists else {}
        revisions = existing_data.get("cv_revisions", [])
        
        # Create new revision
        now = datetime.utcnow()
        new_revision = {
            "content": content,
            "source": source,
            "created_at": now,
            "revision_number": len(revisions) + 1,
        }
        
        revisions.append(new_revision)
        
        # Update user document (merge with existing fields like default_languages, style_instructions)
        user_doc_ref = get_personal_data_document(user_id)
        user_doc_ref.set({
            "cv_revisions": revisions,
            "updated_at": now,
        }, merge=True)
        
        # Clear cache after update
        clear_user_data_cache(user_id)
        
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
        
        return JsonResponse({
            "status": "ok",
            "cv": content,
            "revisions": response_revisions,
        }, status=201)
    
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