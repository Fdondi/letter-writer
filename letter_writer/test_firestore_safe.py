"""Tests for Firestore document sanitization."""

import json
import math

from letter_writer.firestore_store import (
    _firestore_safe_value,
    _prepare_autocomplete_history,
)


def test_firestore_safe_value_stringifies_nested_arrays():
    payload = {"items": [["a", "b"], {"ok": True}]}
    safe = _firestore_safe_value(payload)
    assert safe["items"][0] == json.dumps(["a", "b"], ensure_ascii=False)
    assert safe["items"][1] == {"ok": True}


def test_firestore_safe_value_rejects_nan_floats():
    safe = _firestore_safe_value({"cost": float("nan"), "ok": 1.5})
    assert safe["cost"] is None
    assert safe["ok"] == 1.5


def test_prepare_autocomplete_history_normalizes_chunks():
    history = {
        "fixed_context": "ctx",
        "chunks": [
            {
                "text": "before",
                "accepted": "yes",
                "rejected": ["no"],
                "model": "openai/gpt",
                "cost": float("nan"),
            }
        ],
        "cycle_models": ["a", "b"],
        "total_cost": 0.5,
    }
    prepared = _prepare_autocomplete_history(history)
    assert prepared is not None
    assert prepared["chunks"][0]["rejected"] == ["no"]
    assert prepared["chunks"][0]["cost"] is None
    assert prepared["cycle_models"] == ["a", "b"]


def test_prepare_autocomplete_history_empty_returns_none():
    assert _prepare_autocomplete_history(None) is None
    assert _prepare_autocomplete_history({}) is None
