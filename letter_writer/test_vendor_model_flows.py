"""Tests for vendor model flow metadata."""

from letter_writer.vendor_model_flows import VENDOR_MODEL_FLOWS, get_vendor_model_flows


def test_vendor_model_flows_include_initial_compose_autocomplete_agentic():
    ids = {f["id"] for f in VENDOR_MODEL_FLOWS}
    assert ids == {"initial", "compose", "autocomplete", "agentic"}


def test_initial_flow_has_extraction_rag_and_research():
    initial = next(f for f in VENDOR_MODEL_FLOWS if f["id"] == "initial")
    keys = {r["key"] for r in initial["roles"]}
    assert keys == {"extraction", "rag_ranker", "company_research"}


def test_vendor_flow_includes_feedback_roles():
    compose = next(f for f in VENDOR_MODEL_FLOWS if f["id"] == "compose")
    keys = {r["key"] for r in compose["roles"]}
    assert {"feedback", "feedback_review", "feedback_context"}.issubset(keys)


def test_get_vendor_model_flows_returns_role_defaults_from_json():
    flows = get_vendor_model_flows()
    compose = next(f for f in flows if f["id"] == "compose")
    assert "letter_plan" in compose["role_defaults"]
    assert compose["role_defaults"]["letter_plan"].get("openai", "").startswith("openai/")
    autocomplete = next(f for f in flows if f["id"] == "autocomplete")
    assert "autocomplete" in autocomplete["role_defaults"]
    assert autocomplete["role_defaults"]["autocomplete"].get("deepseek") == "deepseek/deepseek-chat"
