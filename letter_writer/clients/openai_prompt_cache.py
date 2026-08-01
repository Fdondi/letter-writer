"""OpenAI prompt-cache helpers (GPT-5.6 explicit breakpoints + legacy prefix layout)."""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional, Tuple

from .base import merge_system_cache_prefix_into_system
from .prompt_cache import merge_cache_prefixes, prepare_cache_block

_EXPLICIT_BREAKPOINT: Dict[str, str] = {"mode": "explicit"}


def is_gpt_56_family(model: str) -> bool:
    """True for ``gpt-5.6`` and ``gpt-5.6-{sol,terra,luna}``."""
    m = (model or "").lower().strip()
    return m == "gpt-5.6" or m.startswith("gpt-5.6-")


def prompt_cache_key(*parts: Optional[str]) -> str:
    """Stable routing key for requests that share the same cached prefix."""
    h = hashlib.sha256()
    for part in parts:
        text = (part or "").strip()
        if not text:
            continue
        h.update(text.encode("utf-8"))
        h.update(b"\0")
    return f"letter-writer:{h.hexdigest()[:32]}"


def _text_block(text: str, *, breakpoint: bool = False) -> Dict[str, Any]:
    block: Dict[str, Any] = {"type": "text", "text": text}
    if breakpoint:
        block["prompt_cache_breakpoint"] = dict(_EXPLICIT_BREAKPOINT)
    return block


def build_openai_messages(
    system: str,
    user_messages: List[str],
    *,
    cache_prefix: Optional[str] = None,
    system_cache_prefix: Optional[str] = None,
    model: str,
) -> Tuple[List[Dict[str, Any]], Optional[str], bool]:
    """Return ``(messages, prompt_cache_key, use_explicit_cache_options)``."""
    sys_prefix_raw, usr_prefix_raw = merge_cache_prefixes(system_cache_prefix, cache_prefix)
    system_body = (system or "").strip()
    users = list(user_messages or [])

    sys_prefix = (
        prepare_cache_block(sys_prefix_raw, vendor="openai", model=model) if sys_prefix_raw else None
    )
    usr_prefix = (
        prepare_cache_block(usr_prefix_raw, vendor="openai", model=model) if usr_prefix_raw else None
    )

    if is_gpt_56_family(model) and (sys_prefix or usr_prefix):
        messages: List[Dict[str, Any]] = []
        if sys_prefix or system_body:
            sys_blocks: List[Dict[str, Any]] = []
            if sys_prefix:
                sys_blocks.append(_text_block(sys_prefix, breakpoint=True))
            if system_body:
                sys_blocks.append(_text_block(system_body))
            messages.append({"role": "system", "content": sys_blocks})

        for i, message in enumerate(users):
            msg_text = (message or "").strip()
            if i == 0 and usr_prefix:
                user_blocks = [_text_block(usr_prefix, breakpoint=True)]
                if msg_text:
                    user_blocks.append(_text_block(msg_text))
                messages.append({"role": "user", "content": user_blocks})
            elif msg_text:
                messages.append({"role": "user", "content": msg_text})

        key = prompt_cache_key(sys_prefix_raw, usr_prefix_raw) if (sys_prefix_raw or usr_prefix_raw) else None
        return messages, key, True

    # Pre-GPT-5.6: identical prefix at the start of the prompt enables automatic caching.
    merged_prefix = sys_prefix or usr_prefix
    system_prompt = merge_system_cache_prefix_into_system(system, merged_prefix)
    messages = [{"role": "system", "content": system_prompt}]
    for i, message in enumerate(users):
        msg_text = (message or "").strip()
        if msg_text:
            messages.append({"role": "user", "content": msg_text})
    return messages, None, False
