"""
Django management command to set up Google OAuth credentials from environment variables.

Usage:
    python manage.py setup_google_oauth

This command:
1. Reads GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_SECRET from environment variables
2. Creates or updates the Google SocialApplication in the database
3. Associates it with the current Site
"""

from django.core.management.base import BaseCommand
from django.contrib.sites.models import Site
import os


class Command(BaseCommand):
    help = 'Set up Google OAuth credentials from environment variables'

    def handle(self, *args, **options):
        try:
            from allauth.socialaccount.models import SocialApp
        except ImportError:
            self.stdout.write(
                self.style.ERROR('django-allauth is not installed. Install it first: pip install django-allauth')
            )
            return

        client_id = os.environ.get('GOOGLE_OAUTH_CLIENT_ID')
        secret = os.environ.get('GOOGLE_OAUTH_SECRET')

        if not client_id or not secret:
            self.stdout.write(
                self.style.ERROR(
                    'Missing OAuth credentials. Set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_SECRET in .env file.'
                )
            )
            return

        # Get or create the Site
        site = Site.objects.get(id=1)
        self.stdout.write(f'Using Site: {site.domain} ({site.name})')

        # Get or create the SocialApplication
        app, created = SocialApp.objects.get_or_create(
            provider='google',
            defaults={
                'name': 'Google',
                'client_id': client_id,
                'secret': secret,
            }
        )

        if not created:
            # Update existing app
            app.client_id = client_id
            app.secret = secret
            app.save()
            self.stdout.write(self.style.SUCCESS(f'Updated Google OAuth app: {app.name}'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Created Google OAuth app: {app.name}'))

        # Associate with site
        app.sites.add(site)
        self.stdout.write(self.style.SUCCESS(f'Associated app with site: {site.domain}'))

        # Verify setup
        app.refresh_from_db()
        self.stdout.write(f'\nOAuth Configuration:')
        self.stdout.write(f'  Provider: {app.provider}')
        self.stdout.write(f'  Client ID: {app.client_id[:30]}...')
        self.stdout.write(f'  Secret: {"*" * 20} (hidden)')
        self.stdout.write(f'  Sites: {[s.domain for s in app.sites.all()]}')

        # Protocol info
        from django.conf import settings
        protocol = getattr(settings, 'ACCOUNT_DEFAULT_HTTP_PROTOCOL', 'https')
        callback_url = f'{protocol}://{site.domain}/accounts/google/login/callback/'
        self.stdout.write(f'\nCallback URL (for Google Cloud Console):')
        self.stdout.write(self.style.WARNING(f'  {callback_url}'))
        self.stdout.write(
            self.style.WARNING(
                '\nMake sure this URL is added as an authorized redirect URI in Google Cloud Console!'
            )
        )
