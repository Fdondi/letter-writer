"""Pytest setup for the email experiments: the same no-real-services guard as letter_writer."""
import uuid

import pytest

from letter_writer.tests import guard  # noqa: F401  (must run before anything loads .env)
from letter_writer.tests.pytest_fixtures import emulator_db, firestore_emulator_host, opportunity_store  # noqa: F401


@pytest.fixture
def mail_store(emulator_db):
    """The store with the mail additions, on collections of its own."""
    from experimental.email.mail_store import MailOpportunityStore

    return MailOpportunityStore(emulator_db, collection=f"opportunities_{uuid.uuid4().hex[:10]}")
