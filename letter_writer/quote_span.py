"""Resolve a feedback quote to a span in a draft letter.

Exact substring first, then whitespace/case-insensitive match, then closest
embedding among sentence and window candidates.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

EmbedFn = Callable[[List[str]], List[List[float]]]

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
MAX_CANDIDATES = 80


@dataclass(frozen=True)
class QuoteSpan:
    start: int
    end: int
    matched_text: str
    score: float
    method: str
    draft_vendor: Optional[str] = None


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def _normalize_with_map(text: str) -> Tuple[str, List[int]]:
    """Lowercase collapsed-whitespace string plus original index per output char."""
    out: List[str] = []
    idx_map: List[int] = []
    prev_space = True
    for i, ch in enumerate(text):
        if ch.isspace():
            if not prev_space:
                out.append(" ")
                idx_map.append(i)
                prev_space = True
            continue
        out.append(ch.casefold())
        idx_map.append(i)
        prev_space = False
    if out and out[-1] == " ":
        out.pop()
        idx_map.pop()
    return "".join(out), idx_map


def find_exact_span(letter: str, quote: str) -> Optional[Tuple[int, int]]:
    if not quote:
        return None
    idx = letter.find(quote)
    if idx >= 0:
        return (idx, idx + len(quote))
    return None


def find_normalized_span(letter: str, quote: str) -> Optional[Tuple[int, int]]:
    if not quote or not letter:
        return None
    letter_norm, letter_map = _normalize_with_map(letter)
    quote_norm, _ = _normalize_with_map(quote)
    if not quote_norm or not letter_norm:
        return None
    idx = letter_norm.find(quote_norm)
    if idx < 0:
        return None
    end_norm = idx + len(quote_norm) - 1
    start = letter_map[idx]
    end = letter_map[end_norm] + 1
    return (start, end)


def _sentence_spans(letter: str) -> List[Tuple[int, int]]:
    spans: List[Tuple[int, int]] = []
    pos = 0
    parts = _SENTENCE_SPLIT_RE.split(letter)
    if len(parts) <= 1:
        stripped = letter.strip()
        if stripped:
            start = letter.find(stripped)
            if start >= 0:
                spans.append((start, start + len(stripped)))
        return spans
    search_from = 0
    for part in parts:
        if not part.strip():
            continue
        start = letter.find(part, search_from)
        if start < 0:
            start = search_from
        end = start + len(part)
        spans.append((start, end))
        search_from = end
        pos = end
    _ = pos
    return spans


def _window_spans(letter: str, quote_len: int) -> List[Tuple[int, int]]:
    n = len(letter)
    if n == 0 or quote_len <= 0:
        return []
    sizes = sorted({max(8, quote_len), max(8, int(quote_len * 0.75)), max(8, int(quote_len * 1.25))})
    spans: List[Tuple[int, int]] = []
    seen = set()
    for size in sizes:
        if size > n:
            size = n
        stride = max(4, size // 2)
        for start in range(0, n - size + 1, stride):
            end = start + size
            key = (start, end)
            if key not in seen:
                seen.add(key)
                spans.append(key)
        if (n - size, n) not in seen:
            seen.add((n - size, n))
            spans.append((n - size, n))
    return spans


def candidate_spans(letter: str, quote: str) -> List[Tuple[int, int]]:
    qlen = max(8, len(quote.strip()) if quote else 8)
    spans = _sentence_spans(letter) + _window_spans(letter, qlen)
    unique: List[Tuple[int, int]] = []
    seen = set()
    for start, end in spans:
        if end <= start:
            continue
        key = (start, end)
        if key in seen:
            continue
        seen.add(key)
        unique.append(key)
        if len(unique) >= MAX_CANDIDATES:
            break
    return unique


def _default_embed_fn(texts: List[str]) -> List[List[float]]:
    # Lazy import: this module is loaded from feedback_checks, which unit tests import
    # without the OpenAI extra. Callers that hit vector fallback have the extra installed.
    from openai import OpenAI

    from .vector_store import embed_batch

    return embed_batch(texts, OpenAI())


def resolve_quote_span(
    letter: str,
    quote: str,
    *,
    embed_fn: Optional[EmbedFn] = None,
    allow_vector: bool = True,
) -> Optional[QuoteSpan]:
    """Return the best span for quote in letter, or None if quote is empty."""
    letter = letter or ""
    quote = (quote or "").strip()
    if not quote:
        return None
    if not letter.strip():
        return None

    exact = find_exact_span(letter, quote)
    if exact:
        start, end = exact
        return QuoteSpan(start, end, letter[start:end], 1.0, "exact")

    normalized = find_normalized_span(letter, quote)
    if normalized:
        start, end = normalized
        return QuoteSpan(start, end, letter[start:end], 0.99, "normalized")

    if not allow_vector:
        return None

    candidates = candidate_spans(letter, quote)
    if not candidates:
        return None

    fn = embed_fn if embed_fn is not None else _default_embed_fn
    texts = [quote] + [letter[s:e] for s, e in candidates]
    try:
        vectors = fn(texts)
    except Exception:
        logger.exception("quote span embedding failed")
        return None
    if not vectors or len(vectors) != len(texts):
        logger.warning(
            "quote span embed_fn returned %s vectors for %s texts",
            len(vectors) if vectors is not None else None,
            len(texts),
        )
        return None

    quote_vec = vectors[0]
    best_i = 0
    best_score = -1.0
    for i, vec in enumerate(vectors[1:]):
        score = _cosine(quote_vec, vec)
        if score > best_score:
            best_score = score
            best_i = i
    start, end = candidates[best_i]
    return QuoteSpan(start, end, letter[start:end], float(best_score), "vector")


def resolve_quote_span_multi(
    draft_letters: Dict[str, str],
    quote: str,
    *,
    embed_fn: Optional[EmbedFn] = None,
) -> Optional[QuoteSpan]:
    """Match quote against several drafts; prefer exact, then closest vector."""
    quote = (quote or "").strip()
    if not quote or not draft_letters:
        return None

    exact_hits: List[QuoteSpan] = []
    for vendor, letter in draft_letters.items():
        span = resolve_quote_span(letter or "", quote, allow_vector=False)
        if span is None:
            continue
        exact_hits.append(
            QuoteSpan(span.start, span.end, span.matched_text, span.score, span.method, vendor)
        )
    if exact_hits:
        exact_hits.sort(key=lambda s: (-s.score, s.start))
        return exact_hits[0]

    best: Optional[QuoteSpan] = None
    for vendor, letter in draft_letters.items():
        span = resolve_quote_span(letter or "", quote, embed_fn=embed_fn, allow_vector=True)
        if span is None:
            continue
        tagged = QuoteSpan(
            span.start, span.end, span.matched_text, span.score, span.method, vendor
        )
        if best is None or tagged.score > best.score:
            best = tagged
    return best


def apply_span_to_item(
    item: Dict[str, Any],
    span: Optional[QuoteSpan],
) -> Dict[str, Any]:
    if span is None:
        item["matched_text"] = ""
        item.pop("span_start", None)
        item.pop("span_end", None)
        return item
    item["matched_text"] = span.matched_text
    item["span_start"] = span.start
    item["span_end"] = span.end
    if span.draft_vendor:
        item["draft_vendor"] = span.draft_vendor
    return item


def attach_quote_span(
    item: Dict[str, Any],
    letter: str,
    *,
    embed_fn: Optional[EmbedFn] = None,
    draft_vendor: Optional[str] = None,
) -> Dict[str, Any]:
    quote = str(item.get("quote") or "").strip()
    item["quote"] = quote
    if not quote:
        return apply_span_to_item(item, None)
    span = resolve_quote_span(letter, quote, embed_fn=embed_fn)
    if span is not None and draft_vendor:
        span = QuoteSpan(
            span.start, span.end, span.matched_text, span.score, span.method, draft_vendor
        )
    return apply_span_to_item(item, span)


def attach_quote_spans_to_feedback(
    feedback: Dict[str, List[Dict[str, Any]]],
    letter: str,
    *,
    embed_fn: Optional[EmbedFn] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    for _key, items in (feedback or {}).items():
        if not isinstance(items, list):
            continue
        for it in items:
            if isinstance(it, dict):
                attach_quote_span(it, letter, embed_fn=embed_fn)
    return feedback
