"""Price fixed token counts with each desktop client's track_cost and write (or check) golden output.

Usage (from repo root):
    python scripts/costs/capture_cost_golden.py          # rewrite costs.json
    python scripts/costs/capture_cost_golden.py --check  # fail if output differs

Each case gives the token counts as track_cost receives them (after the client
has read its SDK's usage object). The Android unit test feeds the same counts
through its REST clients and must report the same dollar cost, so the two apps
cannot record different costs into letter_writer.api_costs for the same call.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from letter_writer.clients.anthropic import ClaudeClient  # noqa: E402
from letter_writer.clients.base import BaseClient  # noqa: E402
from letter_writer.clients.deepseeek import DeepSeekClient  # noqa: E402
from letter_writer.clients.gemini import GeminiClient  # noqa: E402
from letter_writer.clients.grok import GrokClient  # noqa: E402
from letter_writer.clients.mistral import MistralClient  # noqa: E402
from letter_writer.clients.openai import OpenAIClient  # noqa: E402

TARGET = ROOT / "letter_writer" / "prompts" / "golden" / "costs.json"

CLIENTS = {
    "openai": OpenAIClient,
    "anthropic": ClaudeClient,
    "gemini": GeminiClient,
    "mistral": MistralClient,
    "grok": GrokClient,
    "deepseek": DeepSeekClient,
}

# Token counts are arbitrary but exercise each pricing branch (cache reads/writes, Gemini tiers, search).
CASES: List[Dict[str, Any]] = [
    {"id": "openai_plain", "vendor": "openai", "model": "gpt-6-sol", "input": 12000, "output": 1500},
    {"id": "openai_cached_search", "vendor": "openai", "model": "gpt-6-sol", "input": 20000, "output": 900, "cached": 15000, "cache_write": 2000, "search": 1},
    {"id": "openai_high_tier", "vendor": "openai", "model": "gpt-6-sol", "input": 300000, "output": 40000},
    {"id": "grok_high_tier", "vendor": "grok", "model": "grok-4.7", "input": 300000, "output": 1000},
    {"id": "openai_search_model", "vendor": "openai", "model": "gpt-5-search-api", "input": 3000, "output": 800, "search": 1},
    {"id": "anthropic_cache", "vendor": "anthropic", "model": "claude-sonnet-4-5", "input": 30000, "output": 2000, "cache_read": 20000, "cache_write": 5000},
    {"id": "anthropic_plain", "vendor": "anthropic", "model": "claude-haiku-4-5", "input": 4000, "output": 700},
    {"id": "gemini_low_tier", "vendor": "gemini", "model": "gemini-3.1-pro-preview", "input": 50000, "output": 3000, "cached": 10000},
    {"id": "gemini_high_tier", "vendor": "gemini", "model": "gemini-3.1-pro-preview", "input": 250000, "output": 3000},
    {"id": "gemini_search", "vendor": "gemini", "model": "gemini-3.5-flash", "input": 8000, "output": 1200, "search": 3},
    {"id": "mistral_plain", "vendor": "mistral", "model": "mistral-medium-3-5", "input": 9000, "output": 1100},
    {"id": "grok_cached", "vendor": "grok", "model": "grok-4.7", "input": 15000, "output": 1300, "cached": 6000},
    {"id": "deepseek_cached", "vendor": "deepseek", "model": "deepseek-v4-pro", "input": 18000, "output": 1600, "cached": 12000},
    {"id": "unpriced_model", "vendor": "openai", "model": "no-such-model", "input": 1000, "output": 100},
]


def _bare_client(vendor: str) -> BaseClient:
    """The class's own pricing code without constructing an SDK client (no API key or network needed)."""
    cls = CLIENTS[vendor]
    client = cls.__new__(cls)
    BaseClient.__init__(client)
    if vendor == "mistral":
        client._cost_lock = threading.Lock()
    return client


def price(case: Dict[str, Any]) -> float:
    client = _bare_client(case["vendor"])
    args = dict(search_queries=case.get("search", 0))
    if case["vendor"] == "anthropic":
        args.update(cache_read_tokens=case.get("cache_read", 0), cache_write_tokens=case.get("cache_write", 0))
    elif case["vendor"] == "openai":
        args.update(cached_tokens=case.get("cached", 0), cache_write_tokens=case.get("cache_write", 0))
    else:
        args.update(cached_tokens=case.get("cached", 0))
    client.track_cost(case["model"], case["input"], case["output"], **args)
    return client.total_cost


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="compare instead of writing")
    args = parser.parse_args()
    out = {"cases": [dict(c, expected_cost=price(c)) for c in CASES]}
    text = json.dumps(out, indent=2) + "\n"
    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != text:
            print(f"Cost golden differs from {TARGET.relative_to(ROOT)}; rerun without --check and review the diff.")
            return 1
        print(f"Cost golden matches ({len(CASES)} cases).")
        return 0
    TARGET.write_text(text, encoding="utf-8")
    print(f"Wrote {len(CASES)} cases to {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
