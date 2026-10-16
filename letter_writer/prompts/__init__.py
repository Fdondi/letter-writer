"""Shared prompt templates for the desktop backend and the Android app (app/).

Template files are used verbatim: no trimming, no trailing newline added.
``{{name}}`` placeholders are filled in a single pass, so values that contain
braces themselves (CVs, job ads, JSON) are never expanded again.

Golden renders for fixed inputs live in ``golden/``; regenerate or check them with
``scripts/prompts/capture_golden.py``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

PROMPTS_DIR = Path(__file__).resolve().parent
_PLACEHOLDER = re.compile(r"\{\{([a-z_][a-z0-9_]*)\}\}")


def load(name: str) -> str:
    """Return the template text at ``prompts/<name>`` exactly as stored."""
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def load_json(name: str) -> Any:
    return json.loads(load(name))


def fill(text: str, label: str = "template", **values: Any) -> str:
    """Fill every ``{{placeholder}}`` in ``text``; all must be provided."""
    missing = sorted(set(_PLACEHOLDER.findall(text)) - values.keys())
    if missing:
        raise KeyError(f"Prompt {label} needs values for: {', '.join(missing)}")
    return _PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), text)


def render(name: str, **values: Any) -> str:
    """Fill every ``{{placeholder}}`` in ``prompts/<name>``; all must be provided."""
    return fill(load(name), name, **values)
