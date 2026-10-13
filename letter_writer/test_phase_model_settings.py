"""Tests for per-vendor phase model override resolution."""

from letter_writer.phase_model_settings import (
    get_letter_plan_role_defaults,
    get_merged_phase_models,
    normalize_phase_model_overrides,
    resolve_client_model_role,
)
from letter_writer.clients.base import ModelRole


def test_normalize_phase_model_overrides_accepts_composite_keys():
    raw = {
        "openai": {
            "letter_plan": "openai/gpt-6-luna@low",
            "letter_draft": "openai/gpt-5.5@high",
        }
    }
    out = normalize_phase_model_overrides(raw)
    assert out["openai"]["letter_plan"] == "openai/gpt-6-luna@low"
    assert out["openai"]["letter_draft"] == "openai/gpt-5.5@high"
    assert "letter_refine" not in out["openai"]


def test_get_merged_phase_models_fills_defaults():
    overrides = {"openai": {"letter_plan": "openai/gpt-6-luna"}}
    merged = get_merged_phase_models(overrides)
    assert merged["openai"]["letter_plan"] == "openai/gpt-6-luna"
    assert "letter_draft" in merged["openai"]
    assert merged["openai"]["letter_draft"]


def test_get_deepseek_letter_draft_role_defaults():
    from letter_writer.phase_model_settings import get_letter_draft_role_defaults

    defaults = get_letter_draft_role_defaults()
    assert defaults.get("deepseek") == "deepseek/deepseek-v4-pro@high"


def test_get_letter_plan_role_defaults_matches_anthropic_json():
    import json
    from pathlib import Path

    from letter_writer.phase_model_settings import get_letter_plan_role_defaults

    cfg = json.loads(
        (Path(__file__).resolve().parent / "clients" / "anthropic.json").read_text(encoding="utf-8")
    )
    entry = cfg["roles"]["letter_plan"]
    expected_model = entry["model"]
    defaults = get_letter_plan_role_defaults()
    anthropic = defaults.get("anthropic", "")
    assert expected_model in anthropic
    assert anthropic.startswith("anthropic/")


def test_get_letter_plan_role_defaults_includes_reasoning_suffix():
    defaults = get_letter_plan_role_defaults()
    openai = defaults.get("openai", "")
    assert openai.startswith("openai/")
    assert "gpt-6.1-sol" in openai
    assert "@high" in openai


def test_resolve_client_model_role_returns_override_string():
    overrides = {"openai": {"letter_draft": "openai/gpt-5.5@high"}}
    role = resolve_client_model_role("openai", "letter_draft", overrides)
    assert role == "gpt-5.5@high"


def test_resolve_client_model_role_falls_back_to_enum():
    role = resolve_client_model_role("openai", "letter_plan", {})
    assert role == ModelRole.LETTER_PLAN


def test_get_extraction_vendor_defaults_to_openai():
    from letter_writer.personal_data_sections import get_extraction_vendor

    assert get_extraction_vendor({}) == "openai"
    assert get_extraction_vendor({"extraction_vendor": {"value": "gemini"}}) == "gemini"
    assert get_extraction_vendor({"extraction_vendor": "not-a-vendor"}) == "openai"


def test_bound_override_resolves_extraction_role():
    from letter_writer.clients.base import BaseClient

    client = BaseClient()
    client._vendor_key = "openai"
    client._role_overrides = {"extraction": "openai/gpt-6-sol@low"}
    assert client.resolve_effective_model_role(ModelRole.EXTRACTION) == "gpt-6-sol@low"
    assert client.resolve_effective_model_role(ModelRole.RAG_RANKER) == ModelRole.RAG_RANKER


def test_apply_stored_role_override_replaces_config_default_only():
    from letter_writer.phase_model_settings import (
        apply_stored_role_override,
        get_role_defaults_for_config_role,
    )

    default = get_role_defaults_for_config_role("extraction")["openai"]
    override = "openai/gpt-6-sol@low"
    user_data = {"vendor_role_model_overrides": {"openai": {"extraction": override}}}
    assert apply_stored_role_override(default, "extraction", user_data) == override
    assert (
        apply_stored_role_override("openai/some-other-model", "extraction", user_data)
        == "openai/some-other-model"
    )
