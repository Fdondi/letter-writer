"""Shared prompt-cache helpers: combine static blocks, pad to provider minimums."""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Tuple

# Visible marker so padded bytes are auditable in traces (not silent filler).
_PAD_HEADER = (
    "\n\n---\n"
    "[Prompt-cache padding: no semantic content; satisfies provider minimum cache size.]\n"
    "---\n"
)
# Short repeated unit (~2 tokens each in most BPE vocabularies).
_PAD_UNIT = "cachepadding "

# ~4 characters per token for padding math (matches estimate_tokens).
_CHARS_PER_TOKEN = 4
# Never grow a cache block by more than this factor; skip padding otherwise.
_MAX_CACHE_BLOCK_GROWTH = 2.0


def estimate_tokens(text: str) -> int:
    """Conservative token estimate for mixed EN/DE text (~4 chars/token)."""
    return max(1, len(text or "") // _CHARS_PER_TOKEN)


def combine_cache_parts(*parts: str) -> str:
    """Join non-empty static sections into one cacheable prefix."""
    return "\n\n".join((p or "").strip() for p in parts if (p or "").strip())


def merge_cache_prefixes(
    system_cache_prefix: Optional[str],
    cache_prefix: Optional[str],
) -> Tuple[Optional[str], Optional[str]]:
    """Merge user + system cache prefixes into a single system-side block when both are set."""
    sys_p = (system_cache_prefix or "").strip()
    usr_p = (cache_prefix or "").strip()
    if sys_p and usr_p:
        return combine_cache_parts(sys_p, usr_p), None
    if sys_p:
        return sys_p, None
    if usr_p:
        return None, usr_p
    return None, None


def anthropic_min_cache_tokens(model: str) -> int:
    """Minimum cacheable prefix length per Anthropic model family."""
    m = (model or "").lower()
    if "haiku-4-5" in m:
        return 4096
    if "opus-4-6" in m or "opus-4-5" in m:
        return 4096
    if "opus-4-7" in m:
        return 2048
    if "sonnet-4-6" in m or "sonnet-4-5" in m or "sonnet-5" in m:
        return 1024
    if "opus-4-8" in m or "fable-5" in m:
        return 1024
    if "haiku-3" in m:
        return 2048
    return 2048


def openai_min_cache_tokens(_model: str) -> int:
    """OpenAI prompt caching minimum (all current models)."""
    return 1024


def min_cache_tokens(vendor: str, model: str) -> int:
    v = (vendor or "").lower()
    if v == "anthropic":
        return anthropic_min_cache_tokens(model)
    if v == "openai":
        return openai_min_cache_tokens(model)
    return 1024


def pad_cache_block(text: str, *, vendor: str, model: str) -> Tuple[str, int]:
    """Pad *text* toward the provider minimum when within a 2× size budget.

    Returns (text, padding_tokens_added). If reaching the minimum would require
    more than doubling the block, returns the original text unchanged (no padding).
    """
    body = (text or "").strip()
    if not body:
        return text or "", 0

    target = min_cache_tokens(vendor, model)
    target += max(32, target // 25)

    est = estimate_tokens(body)
    if est >= target:
        return body, 0

    max_total_tokens = int(est * _MAX_CACHE_BLOCK_GROWTH)
    if target > max_total_tokens:
        # Not enough content to justify padding — skip cache minimum.
        return body, 0

    need_tokens = target - est
    need_chars = need_tokens * _CHARS_PER_TOKEN + len(_PAD_UNIT)
    repeat_count = max(1, (need_chars + len(_PAD_UNIT) - 1) // len(_PAD_UNIT))
    pad_body = _PAD_HEADER + (_PAD_UNIT * repeat_count)
    padded = body + pad_body
    return padded, estimate_tokens(pad_body)


def prepare_cache_block(
    text: Optional[str],
    *,
    vendor: str,
    model: str,
) -> Optional[str]:
    """Pad an intentional cache prefix; None if empty."""
    body = (text or "").strip()
    if not body:
        return None
    padded, _added = pad_cache_block(body, vendor=vendor, model=model)
    return padded


def prompt_cache_key(*parts: str) -> str:
    """Stable routing key for requests that share the same cached prefix."""
    h = hashlib.sha256()
    for part in parts:
        text = (part or "").strip()
        if not text:
            continue
        h.update(text.encode("utf-8"))
        h.update(b"\0")
    return f"letter-writer:{h.hexdigest()[:32]}"


def cache_key_for_prefix(prefix: Optional[str], *, fallback: str) -> str:
    """Stable cache routing key for a shared prompt prefix."""
    body = (prefix or "").strip()
    if body:
        return prompt_cache_key(body)
    return fallback


def run_cache_grouped_tasks(
    tasks: List[Tuple[str, Optional[str], Callable[[], Any]]],
    *,
    max_parallel_groups: int = 8,
) -> Dict[str, Any]:
    """Run LLM tasks grouped by cache prefix.

    Calls that share the same ``prefix`` run sequentially so the provider can
    reuse one cache write (Anthropic/OpenAI). Independent prefix groups still
    run in parallel.
    """
    grouped: Dict[str, List[Tuple[str, Callable[[], Any]]]] = {}
    for name, prefix, fn in tasks:
        key = cache_key_for_prefix(prefix, fallback=f"task:{name}")
        grouped.setdefault(key, []).append((name, fn))

    results: Dict[str, Any] = {}

    def _run_chain(items: List[Tuple[str, Callable[[], Any]]]) -> None:
        for task_name, task_fn in items:
            results[task_name] = task_fn()

    workers = max(1, min(max_parallel_groups, len(grouped)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_run_chain, items) for items in grouped.values()]
        for future in as_completed(futures):
            future.result()
    return results
