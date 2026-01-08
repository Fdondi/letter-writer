import os
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _get_gcp_allowed_hosts():
    """Automatically detect allowed hosts when running on GCP Cloud Run.
    
    Returns list of hosts to allow, or None if not on GCP.
    """
    # Check if running on Cloud Run (has K_SERVICE env var)
    service_name = os.environ.get("K_SERVICE")
    region = os.environ.get("K_REGION")
    
    if service_name and region:
        hosts = []
        
        # Try to get the actual service URL from metadata server
        try:
            # Query Cloud Run metadata server for service URL
            metadata_url = "http://metadata.google.internal/computeMetadata/v1/instance/attributes/service-url"
            req = urllib.request.Request(metadata_url)
            req.add_header("Metadata-Flavor", "Google")
            with urllib.request.urlopen(req, timeout=1) as response:
                service_url = response.read().decode("utf-8")
                # Extract hostname from URL (remove https://)
                hostname = service_url.replace("https://", "").replace("http://", "").split("/")[0]
                hosts.append(hostname)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
            # Metadata server not available - this is normal in some Cloud Run configurations
            # Fall back to service name (Cloud Run accepts this for internal requests)
            pass
        
        # Always include service name (useful for internal service-to-service calls)
        if service_name not in hosts:
            hosts.append(service_name)
        
        return hosts if hosts else None
    
    return None


def _get_allowed_hosts():
    """Get ALLOWED_HOSTS with automatic GCP detection."""
    # Manual override takes precedence
    if os.environ.get("DJANGO_ALLOWED_HOSTS"):
        hosts = os.environ["DJANGO_ALLOWED_HOSTS"].split(",")
        return [h.strip() for h in hosts if h.strip()]
    
    # Try to auto-detect GCP hosts
    gcp_hosts = _get_gcp_allowed_hosts()
    if gcp_hosts:
        return gcp_hosts
    
    # Default for local development (Docker Compose)
    return ["backend", "localhost", "127.0.0.1", "0.0.0.0"]


# SECURITY: SECRET_KEY must be set via environment variable
# Generate one with: python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]

# SECURITY: DEBUG must be explicitly set via environment variable
# Set DJANGO_DEBUG=false in production!
DEBUG = os.environ.get("DJANGO_DEBUG", "false").lower() in ("1", "true", "yes")

# SECURITY: ALLOWED_HOSTS with automatic GCP detection
# - If DJANGO_ALLOWED_HOSTS is set, uses that (manual override)
# - If running on Cloud Run, automatically detects service URL
# - Otherwise defaults to local development hosts (backend, localhost, etc.)
ALLOWED_HOSTS = _get_allowed_hosts()

# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "letter_writer_server.api",  # local REST API app
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "letter_writer_server.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "letter_writer_server.wsgi.application"

# Database
# https://docs.djangoproject.com/en/4.2/ref/settings/#databases

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# Password validation
# https://docs.djangoproject.com/en/4.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# Internationalization
# https://docs.djangoproject.com/en/4.2/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.2/howto/static-files/

STATIC_URL = "static/"

# Session configuration
# Custom backend: session key in cookie (small), data stored server-side (in-memory/filesystem)
# This allows large session data without hitting cookie size limits
# No Firestore costs - data stored in VM memory with optional filesystem backup
SESSION_ENGINE = "letter_writer_server.api.session_backend"
SESSION_COOKIE_NAME = "letter_writer_session"
SESSION_COOKIE_HTTPONLY = True  # Prevent JavaScript access (XSS protection)
SESSION_COOKIE_SECURE = os.environ.get("DJANGO_SESSION_COOKIE_SECURE", "false").lower() in ("1", "true", "yes")  # HTTPS only in production
SESSION_COOKIE_SAMESITE = "Lax"  # CSRF protection
SESSION_COOKIE_AGE = 60 * 60 * 24 * 30  # 30 days (same as Firestore TTL)
SESSION_SAVE_EVERY_REQUEST = False  # Only save when modified (saves writes)
SESSION_EXPIRE_AT_BROWSER_CLOSE = False  # Persist across browser restarts

# Optional: Persist sessions to filesystem across server restarts
# Set DJANGO_SESSION_PERSIST=true to enable (default: false, data lost on restart)
# Set DJANGO_SESSION_STORAGE_DIR to customize storage location (default: /tmp/django_sessions)

# Default primary key field type
# https://docs.djangoproject.com/en/4.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField" 