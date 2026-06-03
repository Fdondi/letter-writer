"""Ensure autocomplete API module imports (catches wrong firestore imports)."""


def test_autocomplete_api_imports():
    from letter_writer_server.api import autocomplete  # noqa: F401

    assert autocomplete.router is not None
