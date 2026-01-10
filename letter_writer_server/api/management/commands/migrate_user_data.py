"""
Django management command to migrate existing Firestore data to user-scoped structure.

This command:
1. Migrates personal_data/cv → personal_data/{user_id} with cv_revisions structure
2. Adds user_id to all existing documents in the documents collection
3. Assigns all existing data to the specified user (or first authenticated user)

Usage:
    python manage.py migrate_user_data [--user-id USER_ID] [--dry-run]

If --user-id is not provided, uses the first authenticated user.
If --dry-run is set, only shows what would be migrated without making changes.
"""

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from letter_writer.firestore_store import (
    get_collection,
    get_personal_data_collection,
    get_personal_data_document,
    get_firestore_client,
)
from datetime import datetime
from google.cloud import firestore


def get_google_uid_for_user(user: User) -> str | None:
    """Get Google OAuth UID for a Django user."""
    try:
        from allauth.socialaccount.models import SocialAccount
        social_account = SocialAccount.objects.filter(user=user, provider='google').first()
        if social_account:
            return social_account.uid
    except (ImportError, Exception):
        pass
    return None


class Command(BaseCommand):
    help = 'Migrate existing Firestore data to user-scoped structure'

    def add_arguments(self, parser):
        parser.add_argument(
            '--user-id',
            type=int,
            help='User ID to assign all existing data to (if not provided, uses first authenticated user)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be migrated without making changes',
        )

    def handle(self, *args, **options):
        user_id_arg = options.get('user_id')
        dry_run = options.get('dry_run', False)

        # Get user
        if user_id_arg:
            try:
                user = User.objects.get(id=user_id_arg)
            except User.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f'User with ID {user_id_arg} does not exist.')
                )
                return
        else:
            # Use first authenticated user (has email and is active)
            user = User.objects.filter(is_active=True).exclude(email='').first()
            if not user:
                self.stdout.write(
                    self.style.ERROR(
                        'No authenticated user found. Create a user first or use --user-id.'
                    )
                )
                return

        # Get Google OAuth UID (preferred) or fall back to Django user ID
        google_uid = get_google_uid_for_user(user)
        if google_uid:
            user_id_str = google_uid
            self.stdout.write(f'Using user: {user.email} (Django ID: {user.id}, Google UID: {google_uid})')
        else:
            user_id_str = str(user.id)
            self.stdout.write(
                self.style.WARNING(
                    f'Using user: {user.email} (Django ID: {user.id}, no Google OAuth account found - using Django ID)'
                )
            )
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made'))

        # 1. Migrate personal_data/cv → personal_data/{user_id}
        personal_collection = get_personal_data_collection()
        cv_doc_ref = personal_collection.document('cv')
        cv_doc = cv_doc_ref.get()

        if cv_doc.exists:
            self.stdout.write('\n=== Migrating personal_data/cv ===')
            cv_data = cv_doc.to_dict()
            
            # Check if user document already exists
            user_doc_ref = get_personal_data_document(user_id_str)
            user_doc = user_doc_ref.get()
            
            if user_doc.exists:
                self.stdout.write(
                    self.style.WARNING(
                        f'Personal data document for user {user_id_str} already exists. Skipping migration.'
                    )
                )
            else:
                # Migrate old structure (cv document with "revisions" field)
                # to new structure (user document with "cv_revisions" field)
                old_revisions = cv_data.get('revisions', [])
                
                if old_revisions:
                    if dry_run:
                        self.stdout.write(
                            f'  Would migrate {len(old_revisions)} CV revisions to personal_data/{user_id_str}'
                        )
                        self.stdout.write(
                            f'  Would rename "revisions" field to "cv_revisions"'
                        )
                    else:
                        # Create user document with cv_revisions
                        user_doc_ref.set({
                            'cv_revisions': old_revisions,
                            'updated_at': firestore.SERVER_TIMESTAMP,
                        })
                        self.stdout.write(
                            self.style.SUCCESS(
                                f'  Migrated {len(old_revisions)} CV revisions to personal_data/{user_id_str}'
                            )
                        )
                else:
                    self.stdout.write('  No revisions found in old cv document')
        else:
            self.stdout.write('No personal_data/cv document found - nothing to migrate')

        # 2. Add user_id to all documents in documents collection
        self.stdout.write('\n=== Migrating documents collection ===')
        collection = get_collection()
        all_docs = list(collection.stream())
        
        docs_without_user_id = [doc for doc in all_docs if not doc.to_dict().get('user_id')]
        
        self.stdout.write(f'Total documents: {len(all_docs)}')
        self.stdout.write(f'Documents without user_id: {len(docs_without_user_id)}')
        
        if docs_without_user_id:
            if dry_run:
                self.stdout.write(
                    self.style.WARNING(
                        f'  Would add user_id={user_id_str} to {len(docs_without_user_id)} documents'
                    )
                )
                # Show sample document IDs
                for doc in docs_without_user_id[:5]:
                    doc_data = doc.to_dict()
                    company = doc_data.get('company_name_original') or doc_data.get('company_name', 'N/A')
                    self.stdout.write(f'    - Document {doc.id}: {company}')
                if len(docs_without_user_id) > 5:
                    self.stdout.write(f'    ... and {len(docs_without_user_id) - 5} more')
            else:
                # Batch update all documents
                client = get_firestore_client()
                batch = client.batch()
                batch_count = 0
                updated_count = 0
                
                for doc in docs_without_user_id:
                    doc_ref = collection.document(doc.id)
                    batch.update(doc_ref, {'user_id': user_id_str})
                    batch_count += 1
                    updated_count += 1
                    
                    # Firestore batch limit is 500 operations
                    if batch_count >= 500:
                        batch.commit()
                        self.stdout.write(f'  Committed batch of {batch_count} updates...')
                        batch = client.batch()
                        batch_count = 0
                
                # Commit remaining updates
                if batch_count > 0:
                    batch.commit()
                
                self.stdout.write(
                    self.style.SUCCESS(
                        f'  Added user_id to {updated_count} documents'
                    )
                )
        else:
            self.stdout.write('  All documents already have user_id')

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    '\nDry run complete. Run without --dry-run to apply changes.'
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS('\nMigration complete!')
            )
