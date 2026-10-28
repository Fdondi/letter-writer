"""A stand-in for every vendor client: replies come from ``app/debug/fixtures`` (shared with the
Android app's ``FakeLlmClient``, which uses the same mapping). An unrecognized call raises instead
of returning something that could pass for a model reply. Never calls a real API.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from letter_writer.clients.base import BaseClient, ModelRole

FIXTURES = Path(__file__).resolve().parents[2] / "app" / "debug" / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class UnexpectedCall(AssertionError):
    pass


def _feedback_fixture(system: str) -> str:
    for marker, name in (
        ("consistency with the style instructions", "feedback_instruction.json"),
        ("factual accuracy against the user's CV", "feedback_accuracy.json"),
        ("addresses the needs of the company", "feedback_precision.json"),
        ("company's values, mission, tone", "feedback_empty.json"),
        ("senior hiring manager", "feedback_empty.json"),
        ("continuity of voice", "feedback_empty.json"),
        ("patterns behind edits", "feedback_empty.json"),
    ):
        if marker in system:
            return name
    raise UnexpectedCall(f"no fixture for feedback call: {system[:160]!r}")


def fixture_name(role: Any, system: str, user_messages: List[str], search: bool) -> str:
    user = "\n".join(user_messages or [])
    if isinstance(role, ModelRole):
        if role == ModelRole.LETTER_PLAN:
            return "letter_plan.txt"
        if role == ModelRole.LETTER_DRAFT:
            return "letter_draft.json"
        if role == ModelRole.LETTER_REFINE:
            return "letter_fancy.txt" if "more fancy style" in user else "letter_rewrite.txt"
        if role == ModelRole.EXTRACTION:
            if "point_of_contact" in user:
                return "extraction_metadata.json"
            if "hire_problem" in user:
                return "extraction_competences.json"
            if user.startswith("Key competences"):
                return "extraction_grade.json"
            raise UnexpectedCall(f"no fixture for extraction call: {user[:160]!r}")
        if role == ModelRole.FEEDBACK:
            return _feedback_fixture(system)
        if role == ModelRole.FEEDBACK_REVIEW:
            for prefix, name in (("Critiques:", "review_stage12.json"), ("Items:", "review_stage3.json"), ("Rows:", "review_stage4.json")):
                if user.startswith(prefix):
                    return name
            raise UnexpectedCall(f"no fixture for feedback review call: {user[:160]!r}")
        if role == ModelRole.FEEDBACK_CONTEXT:
            return "feedback_context.json"
        if role == ModelRole.TRANSLATION:
            return "translation.txt"
        if role == ModelRole.COMPANY_RESEARCH:
            return "company_report.txt"
        raise UnexpectedCall(f"no fixture for role {role.value}")
    if search:
        return "web_search.txt"
    if user.startswith("Research the following person"):
        return "poc_report.txt"
    if user.startswith("Search the internet and write a short"):
        return "company_report.txt"
    raise UnexpectedCall(f"no fixture for model {role!r}: {user[:160]!r}")


class FakeClient(BaseClient):
    """Fixture replies. Text replies to plan/refine carry ``[<vendor>]`` so tests can see which
    vendor wrote what; the draft JSON carries it inside ``draft_letter``."""

    calls_lock = threading.Lock()
    calls: List[Dict[str, Any]] = []  # every call of every FakeClient, for assertions

    def __init__(self, vendor: str = "fake", fail_roles: Optional[set] = None) -> None:
        super().__init__()
        self.vendor = vendor
        self.fail_roles = fail_roles or set()

    def call(
        self,
        model_role,
        system: str,
        user_messages: List[str],
        search: bool = False,
        response_format: Optional[Dict[str, Any]] = None,
        cache_prefix: Optional[str] = None,
        system_cache_prefix: Optional[str] = None,
        prompt_cache_key: Optional[str] = None,
    ) -> str:
        role_name = model_role.value if isinstance(model_role, ModelRole) else str(model_role)
        with FakeClient.calls_lock:
            FakeClient.calls.append({"vendor": self.vendor, "role": role_name, "search": search, "thread": threading.get_ident()})
        if role_name in self.fail_roles:
            raise RuntimeError(f"fake {self.vendor} failure in {role_name}")
        name = fixture_name(model_role, system or "", list(user_messages or []), search)
        text = fixture(name)
        if name in ("letter_plan.txt", "letter_rewrite.txt", "letter_fancy.txt"):
            text = f"[{self.vendor}] {text}"
        elif name == "letter_draft.json":
            data = json.loads(text)
            data["draft_letter"] = f"[{self.vendor}] {data['draft_letter']}"
            text = json.dumps(data)
        self.total_input_tokens += 10
        self.total_output_tokens += 5
        return text


def fake_get_client_factory(fail: Optional[Dict[str, set]] = None):
    """A drop-in for ``letter_writer.client.get_client``."""

    def get_client(vendor, *, user_data=None):
        key = getattr(vendor, "value", vendor)
        client = FakeClient(key, (fail or {}).get(key))
        client._vendor_key = key
        client._role_overrides = {}
        return client

    return get_client


def patch_everywhere(monkeypatch, original, replacement) -> int:
    """Replace every ``letter_writer*`` module attribute bound to ``original`` (covers
    ``from x import f`` copies), and every stale fake of it: a module imported lazily while an
    earlier test's fake was installed keeps that fake, which monkeypatch never undoes.
    Returns how many bindings changed."""
    target = getattr(original, "_lw_fake_for", None) or getattr(original, "__qualname__", None)
    try:
        replacement._lw_fake_for = target
    except AttributeError:
        pass
    count = 0
    for name, module in list(sys.modules.items()):
        if module is None or not name.startswith("letter_writer"):
            continue
        for attr, value in list(vars(module).items()):
            if value is original or (target and getattr(value, "_lw_fake_for", None) == target and value is not replacement):
                monkeypatch.setattr(module, attr, replacement)
                count += 1
    return count
