"""
Django signals for automatic data migration on first Google OAuth login.

When a user logs in via Google OAuth for the first time, automatically migrate
their data from the old structure (personal_data/cv) to the new structure
(personal_data/{google_uid}).
"""

from django.db.models.signals import post_save
from django.dispatch import receiver
from letter_writer.firestore_store import (
    get_personal_data_collection,
    get_personal_data_document,
    get_collection,
    get_firestore_client,
)
from datetime import datetime


def migrate_user_data_on_first_login(google_uid: str) -> bool:
    """Migrate old data structure to user's Google UID on first login.
    
    Args:
        google_uid: Google OAuth UID (SocialAccount.uid)
    
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
    user_doc_ref = get_personal_data_document(google_uid)
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


def handle_socialaccount_created(sender, instance, created, **kwargs):
    """Trigger data migration when a Google SocialAccount is first created."""
    # Only process if this is a SocialAccount from allauth
    if instance.provider != 'google':
        return  # Only handle Google OAuth
    
    # Only migrate on first creation
    if not created:
        return
    
    # Use Google's UID as the document ID
    google_uid = instance.uid
    
    # Migrate old data structure to this user's Google UID
    migrated = migrate_user_data_on_first_login(google_uid)
    
    if migrated:
        # Also migrate documents collection - add user_id to all existing documents
        # Since this is first login, assign all existing documents to this user
        collection = get_collection()
        all_docs = list(collection.stream())
        docs_without_user_id = [doc for doc in all_docs if not doc.to_dict().get('user_id')]
        
        if docs_without_user_id:
            client = get_firestore_client()
            batch = client.batch()
            batch_count = 0
            
            for doc in docs_without_user_id:
                doc_ref = collection.document(doc.id)
                batch.update(doc_ref, {'user_id': google_uid})
                batch_count += 1
                
                # Firestore batch limit is 500 operations
                if batch_count >= 500:
                    batch.commit()
                    batch = client.batch()
                    batch_count = 0
            
            # Commit remaining updates
            if batch_count > 0:
                batch.commit()


# Register the signal with the correct sender (only if allauth is available)
try:
    from allauth.socialaccount.models import SocialAccount
    post_save.connect(handle_socialaccount_created, sender=SocialAccount, weak=False)
except ImportError:
    # allauth not installed, signals won't be registered
    pass
