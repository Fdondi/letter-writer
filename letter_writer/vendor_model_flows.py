"""Vendor model roles grouped by UI flow; defaults loaded from clients/<vendor>.json."""

from __future__ import annotations

from typing import Any, Dict, List, TypedDict

from .phase_model_settings import (
    CONFIGURABLE_VENDOR_ROLES,
    get_merged_vendor_role_models,
    get_role_defaults_for_config_role,
    normalize_vendor_role_model_overrides,
)

# Re-export for callers that imported from phase_model_settings
COMPOSE_PHASE_ROLES = ("letter_plan", "letter_draft", "letter_refine")


class _RoleDef(TypedDict):
    key: str
    label: str
    fallbacks: tuple[str, ...]


class _FlowDef(TypedDict):
    id: str
    title: str
    description: str
    roles: tuple[_RoleDef, ...]


VENDOR_MODEL_FLOWS: tuple[_FlowDef, ...] = (
    {
        "id": "initial",
        "title": "Initial",
        "description": "Job intake extraction, example-letter ranking, and company research before vendor phases.",
        "roles": (
            {"key": "extraction", "label": "Extraction", "fallbacks": ()},
            {"key": "rag_ranker", "label": "RAG ranker", "fallbacks": ()},
            {"key": "company_research", "label": "Company research", "fallbacks": ()},
        ),
    },
    {
        "id": "compose",
        "title": "Vendor flow",
        "description": "Multi-vendor plan → draft → refine on the Compose tab, including draft feedback checks.",
        "roles": (
            {"key": "letter_plan", "label": "Plan", "fallbacks": ("letter_draft",)},
            {"key": "letter_draft", "label": "Draft", "fallbacks": ()},
            {"key": "letter_refine", "label": "Refine", "fallbacks": ("letter_draft",)},
            {"key": "feedback", "label": "Feedback", "fallbacks": ()},
            {"key": "feedback_review", "label": "Feedback review", "fallbacks": ("feedback",)},
            {"key": "feedback_context", "label": "Feedback context", "fallbacks": ("feedback",)},
        ),
    },
    {
        "id": "autocomplete",
        "title": "Autocomplete flow",
        "description": "Tab completion and section plans on the Autocomplete tab.",
        "roles": (
            {"key": "autocomplete", "label": "Completion", "fallbacks": ("letter_draft",)},
            {"key": "autocomplete_plan", "label": "Plan", "fallbacks": ("letter_plan", "letter_draft")},
        ),
    },
    {
        "id": "agentic",
        "title": "Agentic flow",
        "description": "Per-topic draft author on the Agentic tab.",
        "roles": (
            {"key": "agentic", "label": "Draft", "fallbacks": ("letter_draft",)},
        ),
    },
)


def get_vendor_model_flows() -> List[Dict[str, Any]]:
    """Flow metadata + per-role defaults from each vendor's clients/<vendor>.json."""
    flows: List[Dict[str, Any]] = []
    for flow in VENDOR_MODEL_FLOWS:
        role_defaults: Dict[str, Dict[str, str]] = {}
        for role_def in flow["roles"]:
            role_defaults[role_def["key"]] = get_role_defaults_for_config_role(
                role_def["key"], fallbacks=role_def["fallbacks"]
            )
        flows.append(
            {
                "id": flow["id"],
                "title": flow["title"],
                "description": flow["description"],
                "roles": [{"key": r["key"], "label": r["label"]} for r in flow["roles"]],
                "role_defaults": role_defaults,
            }
        )
    return flows


def flatten_flow_role_defaults(flows: List[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    """role_key -> vendor -> composite."""
    out: Dict[str, Dict[str, str]] = {}
    for flow in flows or []:
        for role_key, vendor_map in (flow.get("role_defaults") or {}).items():
            if isinstance(vendor_map, dict):
                out[role_key] = vendor_map
    return out
