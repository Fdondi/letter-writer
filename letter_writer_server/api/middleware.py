"""
Middleware to fix Host header for OAuth redirect URIs in Docker environments.

When running in Docker, requests to the backend have Host header set to internal
service name (e.g., 'backend:8000'), but OAuth providers like Google need the
public-facing hostname (e.g., 'localhost:8000').

This middleware fixes the Host header for OAuth-related requests to use the
Site domain instead of the request hostname.
"""

from django.contrib.sites.models import Site
import logging
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)


class OAuthHostFixMiddleware(MiddlewareMixin):
    """Fix Host header for OAuth requests to use Site domain."""
    
    def process_request(self, request):
        """Override request hostname for OAuth-related paths."""
        # Log OAuth callback requests for debugging (without sensitive data)
        if request.path == "/accounts/google/login/callback/":
            # Redact sensitive authorization code from logs
            safe_params = {k: ("REDACTED" if k == "code" else v) for k, v in request.GET.items()}
            logger.info(f"[OAuth Callback] Incoming callback request: method={request.method}, query_params={safe_params}")
        
        # Only fix OAuth-related paths
        if not request.path.startswith('/accounts/'):
            return None
        
        try:
            # Get the Site domain (the public-facing hostname, should include port e.g. localhost:8443)
            site = Site.objects.get(id=1)
            site_domain = site.domain
            request_host = request.get_host()
            # Prefer request host when it has a port and site_domain doesn't (avoid stripping port)
            if ':' in request_host and ':' not in site_domain and site_domain in request_host.split(':')[0]:
                site_domain = request_host
            # If request hostname is different from Site domain, fix it
            # This happens in Docker where Host header is 'backend:8000'
            # but we need 'localhost:8443' for OAuth redirect URIs
            if request_host != site_domain:
                # Override META['HTTP_HOST'] to use Site domain
                # This affects request.build_absolute_uri() which django-allauth uses
                request.META['HTTP_HOST'] = site_domain
                
                # Also update SERVER_NAME if it exists
                if 'SERVER_NAME' in request.META:
                    request.META['SERVER_NAME'] = site_domain.split(':')[0]
                
                # Update SERVER_PORT if port is specified in Site domain
                if ':' in site_domain:
                    hostname, port = site_domain.split(':')
                    request.META['SERVER_PORT'] = port
                    request.META['SERVER_NAME'] = hostname
                else:
                    # No port specified, keep default port
                    if 'SERVER_PORT' not in request.META:
                        # Default to port 80 for HTTP, 443 for HTTPS
                        protocol = request.scheme
                        request.META['SERVER_PORT'] = '443' if protocol == 'https' else '80'
                    request.META['SERVER_NAME'] = site_domain
                    
        except Site.DoesNotExist:
            # Site not configured, skip fix
            pass
        except Exception as e:
            # Log error but don't break the request
            logger.warning(f"[OAuth Middleware] Failed to fix OAuth Host header: {e}")
        
        return None
