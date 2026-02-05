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

# Check if optional dependencies are installed (before using them)
# Note: django-cors-headers is in requirements.txt, so it should be installed
# If not available, the server will still work but CORS headers won't be set
# (This is fine for same-origin requests via Vite proxy, but needed for cross-origin in production)
try:
    import corsheaders
    CORS_AVAILABLE = True
except ImportError:
    # Not installed - continue without CORS (will use ALLOWED_HOSTS for CSRF_TRUSTED_ORIGINS)
    # To install: pip install django-cors-headers>=4.3.1 or rebuild Docker image
    CORS_AVAILABLE = False

try:
    import allauth
    AUTHENTICATION_AVAILABLE = True
except ImportError:
    # allauth is optional (authentication feature)
    # To install: pip install django-allauth>=0.57.0 or rebuild Docker image
    AUTHENTICATION_AVAILABLE = False

# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",  # Required for allauth (if enabled)
    # Local apps
    "letter_writer_server.api.apps.ApiConfig",  # local REST API app (use AppConfig to register signals)
]

# Conditionally add corsheaders if installed (only needed for cross-origin requests)
if CORS_AVAILABLE:
    INSTALLED_APPS.insert(-1, "corsheaders")  # Insert before local apps

# Conditionally add django-allauth apps if installed
if AUTHENTICATION_AVAILABLE:
    INSTALLED_APPS.extend([
        "allauth",
        "allauth.account",
        "allauth.socialaccount",
        "allauth.socialaccount.providers.google",
    ])
    # django-allauth requires SITE_ID
    SITE_ID = 1
else:
    SITE_ID = 1  # Still set SITE_ID for django.contrib.sites

# Set CSRF_TRUSTED_ORIGINS if CORS is not available (use same as ALLOWED_HOSTS)
# This needs to be after CORS_AVAILABLE is defined
if not CORS_AVAILABLE:
    CSRF_TRUSTED_ORIGINS = ALLOWED_HOSTS.copy()

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# Conditionally add CORS middleware if corsheaders is installed
if CORS_AVAILABLE:
    MIDDLEWARE.insert(1, "corsheaders.middleware.CorsMiddleware")  # After SecurityMiddleware, before SessionMiddleware

# Conditionally add OAuth Host fix middleware if authentication is available
# This fixes the Host header for OAuth requests in Docker environments
# Must be before SessionMiddleware so django-allauth uses the correct hostname
if AUTHENTICATION_AVAILABLE:
    MIDDLEWARE.insert(2, "letter_writer_server.api.middleware.OAuthHostFixMiddleware")  # After SecurityMiddleware/CORS, before SessionMiddleware

# Conditionally add allauth middleware if installed (required for django-allauth 0.57.0+)
if AUTHENTICATION_AVAILABLE:
    # allauth.account.middleware.AccountMiddleware must be added after AuthenticationMiddleware
    # Find the index of AuthenticationMiddleware and insert after it
    auth_middleware_idx = MIDDLEWARE.index("django.contrib.auth.middleware.AuthenticationMiddleware")
    MIDDLEWARE.insert(auth_middleware_idx + 1, "allauth.account.middleware.AccountMiddleware")

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
SESSION_COOKIE_SECURE = True
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

# Authentication configuration (django-allauth) - only if installed
if AUTHENTICATION_AVAILABLE:
    AUTHENTICATION_BACKENDS = [
        # Django's default authentication backend
        "django.contrib.auth.backends.ModelBackend",
        # django-allauth specific authentication methods
        "allauth.account.auth_backends.AuthenticationBackend",
    ]
    
    # django-allauth settings (using new format for django-allauth 0.57.0+)
    ACCOUNT_LOGIN_METHODS = {"email"}  # Use email for login
    ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]  # Required fields for signup
    ACCOUNT_EMAIL_VERIFICATION = "none"  # Set to "mandatory" for production if needed
    # Redirect after login/logout
    # For OAuth callbacks: django-allauth redirects back to the callback URL on the backend first
    # Then it redirects to LOGIN_REDIRECT_URL
    # Must use absolute URL to redirect to frontend (different port in dev)
    frontend_url = os.environ.get("FRONTEND_URL", "https://localhost:8443")
    # For SPA: redirect to frontend root after OAuth callback completes
    LOGIN_REDIRECT_URL = frontend_url.rstrip("/") + "/"  # Redirect to frontend app root after OAuth login
    LOGOUT_REDIRECT_URL = frontend_url.rstrip("/") + "/"  # Redirect to frontend app root after logout
    # HTTPS only; FRONTEND_URL must use https (local: https://localhost:8443, production: https://yourdomain.com)
    ACCOUNT_DEFAULT_HTTP_PROTOCOL = "https"

    # Social account settings (django-allauth)
    # Automatically create accounts for social logins (skip intermediate consent page)
    SOCIALACCOUNT_AUTO_SIGNUP = True  # Automatically create user account on first social login
    SOCIALACCOUNT_EMAIL_VERIFICATION = "none"  # Skip email verification for social accounts
    SOCIALACCOUNT_EMAIL_REQUIRED = False  # Don't require email (Google provides it)
    SOCIALACCOUNT_QUERY_EMAIL = True  # Request email from Google
    SOCIALACCOUNT_LOGIN_ON_GET = True  # Skip intermediate consent page, redirect directly to OAuth provider on GET request
    
    # Google OAuth configuration
    # Credentials are read ONLY from environment variables (never stored in database)
    # django-allauth supports both database (SocialApp model) and settings.py configuration
    # We use settings.py exclusively - no database storage of OAuth secrets
    google_client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
    google_secret = os.environ.get("GOOGLE_OAUTH_SECRET", "")
    
    # Log OAuth configuration status (without exposing secrets)
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"[OAuth Config] Client ID present: {bool(google_client_id)}, Secret present: {bool(google_secret)}")
    if google_client_id:
        logger.debug(f"[OAuth Config] Client ID (first 10 chars): {google_client_id[:10]}...")
    if not google_secret:
        logger.warning("[OAuth Config] GOOGLE_OAUTH_SECRET not set - OAuth callbacks will fail!")
    
    SOCIALACCOUNT_PROVIDERS = {
        "google": {
            "APP": {
                "client_id": google_client_id,
                "secret": google_secret,
            },
            "SCOPE": [
                "profile",
                "email",
            ],
            "AUTH_PARAMS": {
                "access_type": "online",
                "prompt": "select_account",  # Force account selection screen
            },
        }
    }
else:
    # Fallback: just use Django's default authentication
    AUTHENTICATION_BACKENDS = [
        "django.contrib.auth.backends.ModelBackend",
    ]

# CORS configuration (only if corsheaders is installed)
# Note: With Vite proxy (same-origin), CORS is not needed for local development
if CORS_AVAILABLE:
    # In production, specify exact origins instead of allowing all
    CORS_ALLOWED_ORIGINS_ENV = os.environ.get("DJANGO_CORS_ALLOWED_ORIGINS", "")
    if CORS_ALLOWED_ORIGINS_ENV:
        CORS_ALLOWED_ORIGINS = [origin.strip() for origin in CORS_ALLOWED_ORIGINS_ENV.split(",") if origin.strip()]
    else:
        CORS_ALLOWED_ORIGINS = [
            "https://localhost:8443",
            "https://127.0.0.1:8443",
        ]
    # Allow credentials (cookies, authorization headers) for CSRF
    CORS_ALLOW_CREDENTIALS = True
    # Allow CSRF cookie to be read by JavaScript (for SPA)
    CORS_EXPOSE_HEADERS = ["Set-Cookie"]
    CSRF_TRUSTED_ORIGINS = CORS_ALLOWED_ORIGINS.copy()
# Note: If CORS not available, CSRF_TRUSTED_ORIGINS is already set to ALLOWED_HOSTS earlier

# CSRF configuration for SPA
# Django's CSRF protection works with cookies for same-origin requests
# For cross-origin, we'll send token in header
CSRF_COOKIE_HTTPONLY = False  # Allow JavaScript to read CSRF token (required for SPA)
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_SAMESITE = "Lax"  # CSRF protection
CSRF_USE_SESSIONS = False  # Use cookies, not sessions (default)
CSRF_COOKIE_NAME = "csrftoken"  # Standard Django CSRF cookie name

# HTTPS only: trust X-Forwarded-Proto from reverse proxy (Nginx, Cloud Run)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Logging configuration
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "letter_writer_server.api.views": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "letter_writer_server.api.signals": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "letter_writer_server.settings": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        # Log OAuth-related messages from django-allauth
        "allauth": {
            "handlers": ["console"],
            "level": "WARNING",  # Change to INFO for more verbose OAuth logging
            "propagate": False,
        },
    },
} 