"""Pytest setup for letter_writer tests: the no-real-services guard, then the shared fixtures."""
from letter_writer.tests import guard  # noqa: F401  (must run before anything loads .env)
from letter_writer.tests.pytest_fixtures import emulator_db, firestore_emulator_host, opportunity_store  # noqa: F401
