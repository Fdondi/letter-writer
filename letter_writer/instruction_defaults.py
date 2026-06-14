"""Repo default AI instruction files and content hashes for upstream-update detection."""

from __future__ import annotations

import hashlib
from typing import Callable, Dict, Tuple

from letter_writer.generation import (
    get_search_instructions,
    get_structure_instructions,
    get_style_instructions,
)

InstructionGetter = Callable[[], str]

INSTRUCTION_GETTERS: Dict[str, InstructionGetter] = {
    "style": get_style_instructions,
    "structure": get_structure_instructions,
    "search": get_search_instructions,
}


def normalize_instruction_text(text: str) -> str:
    return (text or "").replace("\r\n", "\n").strip()


def instruction_content_hash(text: str) -> str:
    normalized = normalize_instruction_text(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def get_default_instruction(kind: str) -> Tuple[str, str]:
    """Return (default_text, default_hash) for kind in style|structure|search."""
    getter = INSTRUCTION_GETTERS.get(kind)
    if getter is None:
        raise ValueError(f"Unknown instruction kind: {kind}")
    text = normalize_instruction_text(getter())
    return text, instruction_content_hash(text)
