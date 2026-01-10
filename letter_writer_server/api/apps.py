"""
Django app configuration for letter_writer_server.api.
"""

from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'letter_writer_server.api'

    def ready(self):
        """Import signals when app is ready."""
        import letter_writer_server.api.signals  # noqa: F401
