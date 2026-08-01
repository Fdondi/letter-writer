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
            "letter_plan": "openai/gpt-5-nano@low",
            "letter_draft": "openai/gpt-5.5@high",
        }
    }
    out = normalize_phase_model_overrides(raw)
    assert out["openai"]["letter_plan"] == "openai/gpt-5-nano@low"
    assert out["openai"]["letter_draft"] == "openai/gpt-5.5@high"
    assert "letter_refine" not in out["openai"]


def test_get_merged_phase_models_fills_defaults():
    overrides = {"openai": {"letter_plan": "openai/gpt-5-nano"}}
    merged = get_merged_phase_models(overrides)
    assert merged["openai"]["letter_plan"] == "openai/gpt-5-nano"
    assert "letter_draft" in merged["openai"]
    assert merged["openai"]["letter_draft"]


def test_get_deepseek_letter_draft_role_defaults():
    from letter_writer.phase_model_settings import get_letter_draft_role_defaults

    defaults = get_letter_draft_role_defaults()
    assert defaults.get("deepseek") == "deepseek/deepseek-v4-pro"


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
    assert "gpt-5.5" in openai
    assert "@high" in openai


def test_resolve_client_model_role_returns_override_string():
    overrides = {"openai": {"letter_draft": "openai/gpt-5.5@high"}}
    role = resolve_client_model_role("openai", "letter_draft", overrides)
    assert role == "gpt-5.5@high"


def test_resolve_client_model_role_falls_back_to_enum():
    role = resolve_client_model_role("openai", "letter_plan", {})
    assert role == ModelRole.LETTER_PLAN
