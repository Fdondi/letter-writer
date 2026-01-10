from django.urls import path, include
from django.conf import settings

urlpatterns = [
    # API endpoints
    path("api/", include("letter_writer_server.api.urls")),
]

# Conditionally add allauth URLs if available
if getattr(settings, "AUTHENTICATION_AVAILABLE", False):
    # Then include allauth URLs
    urlpatterns.insert(1, path("accounts/", include("allauth.urls"))) 