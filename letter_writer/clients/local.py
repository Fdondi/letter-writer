from .base import BaseClient, ModelRole, merge_system_cache_prefix_into_system
from openai import OpenAI
from typing import List, Dict, Any, Optional
import logging
import os
import time
from pathlib import Path
import typer
from langsmith import traceable

from letter_writer.local_pricing import (
    compute_local_inference_cost_usd,
    is_local_energy_pricing_configured,
)

logger = logging.getLogger(__name__)


def _running_in_container() -> bool:
    """Docker creates /.dockerenv; Podman creates /run/.containerenv instead."""
    return Path("/.dockerenv").exists() or Path("/run/.containerenv").exists()


def _default_local_base_url() -> str:
    """LM Studio on the host: containers must use host.docker.internal, not localhost."""
    if _running_in_container():
        return "http://host.docker.internal:1234/v1"
    return "http://localhost:1234/v1"


class LocalClient(BaseClient):
    """Client for LM Studio (or any OpenAI-compatible local server).

    Base URL: ``LOCAL_LLM_BASE_URL`` if set, else ``http://localhost:1234/v1`` on the
    host, or ``http://host.docker.internal:1234/v1`` when running inside a container
    so the host's LM Studio is reachable. API key defaults to ``lm-studio`` or
    ``LOCAL_LLM_API_KEY``. Model roles are ignored — whatever model is loaded locally is used.
    """

    def __init__(self):
        super().__init__()
        self._base_url = os.getenv("LOCAL_LLM_BASE_URL") or _default_local_base_url()
        api_key = os.getenv("LOCAL_LLM_API_KEY", "lm-studio")
        # Match reverse-proxy long timeouts: local inference often runs many minutes.
        _timeout_s = float(os.getenv("LOCAL_LLM_HTTP_TIMEOUT_SECONDS", "1800"))
        self.client = OpenAI(
            base_url=self._base_url,
            api_key=api_key,
            timeout=_timeout_s,
        )

    def _record_local_usage_and_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        energy_cost_usd: float,
    ) -> None:
        """Accumulate token counts for stats; dollar cost is energy-based only (not per-token)."""
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cost += energy_cost_usd

    def _format_messages(self, system: str, user_messages: List[str]) -> List[Dict]:
        return [{"role": "system", "content": system}] + [
            {"role": "user", "content": message} for message in user_messages
        ]

    @traceable(run_type="llm", name="Local.call")
    def call(
        self,
        model_role: ModelRole | str,
        system: str,
        user_messages: List[str],
        search: bool = False,
        response_format: Optional[Dict[str, Any]] = None,
        cache_prefix: Optional[str] = None,
        system_cache_prefix: Optional[str] = None,
    ) -> str:
        _ = cache_prefix
        system_prompt = merge_system_cache_prefix_into_system(system, system_cache_prefix)
        messages = self._format_messages(system_prompt, user_messages)
        # LM Studio uses whatever model is loaded; the model param is ignored.
        model = "local-model"
        def _return_with_audit(text: str) -> str:
            self._record_llm_io(
                model=model,
                system=system_prompt,
                user_messages=user_messages,
                search=search,
                response_format=response_format,
                output_text=text,
            )
            return text
        if search:
            typer.echo("[WARNING] search not supported for local models, ignoring")
        typer.echo(f"[INFO] using local model (LM Studio) at {self._base_url}")
        request_kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        if response_format:
            request_kwargs["response_format"] = response_format
        t0 = time.perf_counter()
        try:
            response = self.client.chat.completions.create(**request_kwargs)
        except Exception as e:
            self._record_llm_io(
                model=model,
                system=system_prompt,
                user_messages=user_messages,
                search=search,
                response_format=response_format,
                error=str(e),
            )
            raise
        elapsed = time.perf_counter() - t0

        energy_cost = compute_local_inference_cost_usd(elapsed)
        in_t = out_t = 0
        if response.usage:
            in_t = response.usage.prompt_tokens or 0
            out_t = response.usage.completion_tokens or 0
        self._record_local_usage_and_cost(in_t, out_t, energy_cost)

        if not is_local_energy_pricing_configured():
            logger.debug(
                "Local inference cost $0.00 (elapsed=%.2fs); set LOCAL_GPU_WATTS_AT_100 and "
                "LOCAL_ENERGY_PRICE_PER_KWH for energy-based pricing.",
                elapsed,
            )
        else:
            logger.debug(
                "Local inference energy cost $%.6f (elapsed=%.2fs)",
                energy_cost,
                elapsed,
            )

        return _return_with_audit(response.choices[0].message.content.strip())
