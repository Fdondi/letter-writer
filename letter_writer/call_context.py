"""Request-scoped vendor role model overrides, copied into worker threads."""

from __future__ import annotations

from contextvars import ContextVar, copy_context
from functools import partial
from typing import Any, Dict

from letter_writer.personal_data_sections import get_phase_model_overrides

_overrides: ContextVar[Dict[str, Dict[str, str]] | None] = ContextVar(
    "vendor_role_overrides", default=None
)


def bind_vendor_role_overrides(user_data: Dict[str, Any] | None) -> None:
    _overrides.set(get_phase_model_overrides(user_data or {}))


def current_vendor_role_overrides() -> Dict[str, Dict[str, str]]:
    return _overrides.get() or {}


def submit_with_context(executor, fn, /, *args, **kwargs):
    """Schedule fn in executor with this thread's context vars (including model overrides)."""
    ctx = copy_context()
    bound = partial(fn, *args, **kwargs)
    return executor.submit(ctx.run, bound)
