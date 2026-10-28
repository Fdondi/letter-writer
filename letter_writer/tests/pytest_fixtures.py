"""Pytest fixtures shared by every test folder (imported into each conftest)."""
import uuid

import pytest

from letter_writer.tests import firestore_emulator
from letter_writer.tests.guard import BLOCKED_FIRESTORE_HOST

firestore_emulator.BLOCKED_HOSTS.add(BLOCKED_FIRESTORE_HOST)


@pytest.fixture(scope="session")
def firestore_emulator_host():
    reason = firestore_emulator.unavailable_reason()
    if reason:
        pytest.skip(reason)
    with firestore_emulator.running_emulator() as host:
        yield host


@pytest.fixture
def emulator_db(firestore_emulator_host):
    """A Firestore client on the local emulator."""
    return firestore_emulator.client()


@pytest.fixture
def opportunity_store(emulator_db):
    """An OpportunityStore on a collection of its own, so tests never see each other's jobs."""
    from letter_writer.opportunity_store import OpportunityStore

    return OpportunityStore(emulator_db, collection=f"opportunities_{uuid.uuid4().hex[:10]}")
