from __future__ import annotations

from typing import List, Tuple, Any

import typer

from .base import BaseClient, ModelSize

try:
    from google import genai  # type: ignore
    from google.genai import types  # type: ignore
except Exception:  # pragma: no cover
    genai = None  # type: ignore
    types = None  # type: ignore


class GeminiClient(BaseClient):
    def __init__(self):
        super().__init__()
        if genai is None:
            raise ImportError(
                "Gemini client requires the 'google-genai' package. Install it to use Gemini models."
            )
        self.client = genai.Client()

    def _get_gemini_pricing(self, model_name: str) -> dict:
        """
        Gemini pricing is data-driven and supports either:
        - fixed number: "input": 0.30
        - tier dict: "input": {"low": 1.25, "high": 2.50, "threshold": 200000}
        Threshold is optional and falls back to defaults.threshold.
        """
        cfg: Any = self._load_cost_config()
        if not isinstance(cfg, dict):
            return {
                "threshold_in": 0,
                "threshold_out": 0,
                "low_input": 0.0,
                "high_input": 0.0,
                "low_output": 0.0,
                "high_output": 0.0,
                "search": 0.0,
            }

        defaults = cfg.get("defaults", {})
        default_search = float((defaults.get("search", 0.0) if isinstance(defaults, dict) else 0.0) or 0.0)
        default_threshold = int((defaults.get("threshold", 0) if isinstance(defaults, dict) else 0) or 0)

        models = cfg.get("models", {})
        model_cfg = models.get(model_name, {}) if isinstance(models, dict) else {}
        if not isinstance(model_cfg, dict):
            model_cfg = {}

        def _parse_price_field(field, *, default_thr: int) -> Tuple[float, float, int]:
            if isinstance(field, (int, float)):
                v = float(field)
                return v, v, int(default_thr or 0)
            if isinstance(field, dict):
                low = float(field.get("low", 0.0) or 0.0)
                high = float(field.get("high", low) or 0.0)
                thr = int(field.get("threshold", default_thr) or 0)
                return low, high, thr
            return 0.0, 0.0, int(default_thr or 0)

        input_low, input_high, threshold_in = _parse_price_field(
            model_cfg.get("input", 0.0), default_thr=default_threshold
        )
        output_low, output_high, threshold_out = _parse_price_field(
            model_cfg.get("output", 0.0), default_thr=default_threshold
        )

        return {
            "threshold_in": threshold_in,
            "threshold_out": threshold_out,
            "low_input": input_low,
            "high_input": input_high,
            "low_output": output_low,
            "high_output": output_high,
            "search": float(model_cfg.get("search", default_search) or 0.0),
        }

    def track_cost(self, model_name: str, input_tokens: int, output_tokens: int, search_queries: int = 0):
        p = self._get_gemini_pricing(model_name)

        # Input/output measured against threshold independently.
        input_price = p["high_input"] if input_tokens > p["threshold_in"] else p["low_input"]
        output_price = p["high_output"] if output_tokens > p["threshold_out"] else p["low_output"]

        input_cost = (input_tokens / 1_000_000) * input_price
        output_cost = (output_tokens / 1_000_000) * output_price
        search_cost = (search_queries / 1_000) * p["search"]

        self.total_cost += input_cost + output_cost + search_cost

    def call(self, model_size: ModelSize, system: str, user_messages: List[str], search: bool = False) -> str:
        if types is None:
            raise ImportError(
                "Gemini client requires the 'google-genai' package. Install it to use Gemini models."
            )

        if search:
            grounding_tool = types.Tool(google_search=types.GoogleSearch())
            tools = [grounding_tool]
        else:
            tools = []

        model_name = self.get_model_for_size(model_size)
        typer.echo(f"[INFO] using Gemini model {model_name}" + (" with search" if search else ""))

        response = self.client.models.generate_content(
            model=model_name,
            config=types.GenerateContentConfig(
                system_instruction=system,
                tools=tools,
            ),
            contents=user_messages,
        )

        # Track cost if usage metadata is available
        usage = getattr(response, "usage_metadata", None)
        if usage is not None:
            self.track_cost(
                model_name,
                getattr(usage, "prompt_token_count", 0) or 0,
                getattr(usage, "candidates_token_count", 0) or 0,
                search_queries=1 if search else 0,
            )

        return response.text
