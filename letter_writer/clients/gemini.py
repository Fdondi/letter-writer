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
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_search_queries += search_queries
        
        typer.echo(f"[DEBUG] track_cost called: in={input_tokens}, out={output_tokens}, totals: in={self.total_input_tokens}, out={self.total_output_tokens}")

    def call(self, model_size: ModelSize | str, system: str, user_messages: List[str], search: bool = False) -> str:
        if types is None:
            raise ImportError(
                "Gemini client requires the 'google-genai' package. Install it to use Gemini models."
            )

        if search:
            grounding_tool = types.Tool(google_search=types.GoogleSearch())
            tools = [grounding_tool]
        else:
            tools = []

        if isinstance(model_size, str):
            model_name = model_size
        else:
            model_name = self.get_model_for_size(model_size)
        typer.echo(f"[INFO] using Gemini model {model_name}" + (" with search" if search else ""))

        # Validate and filter user_messages - Gemini API requires all strings to be non-None
        validated_messages = []
        for i, msg in enumerate(user_messages):
            if msg is None:
                typer.echo(f"[WARNING] Skipping None message at index {i}")
                continue
            if not isinstance(msg, str):
                typer.echo(f"[WARNING] Converting non-string message at index {i} to string")
                msg = str(msg)
            if msg.strip():  # Only add non-empty messages
                validated_messages.append(msg)
        
        if not validated_messages:
            raise ValueError("No valid user messages provided to Gemini API (all were None or empty)")

        try:
            response = self.client.models.generate_content(
                model=model_name,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    tools=tools,
                ),
                contents=validated_messages,
            )
        except Exception as exc:
            raise RuntimeError(f"Gemini generate_content failed: {exc}") from exc

        # Track cost from usage metadata
        usage = getattr(response, "usage_metadata", None)
        
        # Debug: log what we're getting from the response
        typer.echo(f"[DEBUG] Gemini response usage_metadata: {usage}")
        if usage is not None:
            typer.echo(f"[DEBUG] prompt_token_count: {getattr(usage, 'prompt_token_count', 'MISSING')}")
            typer.echo(f"[DEBUG] candidates_token_count: {getattr(usage, 'candidates_token_count', 'MISSING')}")
        
        if usage is not None:
            prompt_tokens = getattr(usage, "prompt_token_count", None)
            output_tokens = getattr(usage, "candidates_token_count", None)
            
            # Get actual search count from grounding metadata when available (Gemini 3 bills per query)
            search_queries = 0
            if search and hasattr(response, "candidates") and response.candidates:
                cand = response.candidates[0]
                gm = getattr(cand, "grounding_metadata", None)
                if gm is not None:
                    wsq = getattr(gm, "web_search_queries", None)
                    if wsq is not None:
                        search_queries = len(wsq) if hasattr(wsq, "__len__") else (1 if wsq else 0)
                if search_queries == 0:
                    search_queries = 1  # Search enabled but no grounding metadata (fallback)
            
            # Track even if token counts are missing (as 0) - we still want the record
            self.track_cost(
                model_name,
                prompt_tokens if prompt_tokens is not None else 0,
                output_tokens if output_tokens is not None else 0,
                search_queries=search_queries,
            )
        else:
            typer.echo(f"[WARNING] Gemini response has no usage_metadata - token tracking unavailable")

        # Handle response text - may be None if response has no text content
        response_text = getattr(response, "text", None)
        if response_text is None:
            # Try to get text from candidates if available
            if hasattr(response, "candidates") and response.candidates:
                candidate = response.candidates[0]
                if hasattr(candidate, "content") and candidate.content:
                    if hasattr(candidate.content, "parts") and candidate.content.parts:
                        # Extract text from parts
                        text_parts = [
                            part.text for part in candidate.content.parts
                            if hasattr(part, "text") and part.text
                        ]
                        if text_parts:
                            response_text = "".join(text_parts)
            
            # If still None, raise an error with helpful context
            if response_text is None:
                error_msg = "Gemini API returned no text content"
                if hasattr(response, "candidates") and response.candidates:
                    candidate = response.candidates[0]
                    if hasattr(candidate, "finish_reason"):
                        error_msg += f" (finish_reason: {candidate.finish_reason})"
                    if hasattr(candidate, "safety_ratings"):
                        error_msg += f" (safety_ratings: {candidate.safety_ratings})"
                raise RuntimeError(error_msg)
        
        return response_text
