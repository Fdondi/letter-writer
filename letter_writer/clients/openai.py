from .base import BaseClient, ModelRole, merge_system_cache_prefix_into_system
from .model_override import apply_model_override_thinking
from .openai_prompt_cache import build_openai_messages, is_gpt_56_family
from .prompt_cache import merge_cache_prefixes
from openai import OpenAI
from typing import List, Dict, Any, Optional
import typer
from langsmith import traceable


class OpenAIClient(BaseClient):
    def __init__(self):
        super().__init__()
        self.client = OpenAI()

    def track_cost(
        self,
        model_name: str,
        input_tokens: int,
        output_tokens: int,
        search_queries: int = 0,
        cached_tokens: int = 0,
        *,
        cache_write_tokens: int = 0,
    ):
        costs = self.get_model_cost(model_name)
        input_price = costs["input"]
        read_mult = costs.get("input_cached_mult", 0.5)
        write_mult = float(costs.get("cache_write_mult", 1.0) or 1.0)

        regular = max(0, input_tokens - cached_tokens - cache_write_tokens)
        input_cost = (
            (regular / 1_000_000) * input_price
            + (cached_tokens / 1_000_000) * input_price * read_mult
            + (cache_write_tokens / 1_000_000) * input_price * write_mult
        )
        output_cost = (output_tokens / 1_000_000) * costs["output"]
        search_cost = (search_queries / 1_000) * costs["search"]

        self.total_cost += input_cost + output_cost + search_cost
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cached_tokens += cached_tokens
        self.total_search_queries += search_queries

    @staticmethod
    def _extract_cache_metrics(usage) -> tuple[int, int]:
        details = getattr(usage, "prompt_tokens_details", None)
        cache_read = int(getattr(details, "cached_tokens", 0) or 0) if details else 0
        cache_write = int(getattr(details, "cache_write_tokens", 0) or 0) if details else 0
        return cache_read, cache_write

    @traceable(run_type="llm", name="OpenAI.call")
    def call(
        self,
        model_role: ModelRole | str,
        system: str,
        user_messages: List[str],
        search: bool = False,
        response_format: Optional[Dict[str, Any]] = None,
        cache_prefix: Optional[str] = None,
        system_cache_prefix: Optional[str] = None,
        prompt_cache_key: Optional[str] = None,
    ) -> str:
        if isinstance(model_role, str):
            model, thinking_cfg = apply_model_override_thinking("openai", model_role)
        else:
            model = self.get_model_for_role(model_role)
            thinking_cfg = self.get_thinking_config(model_role)
        if search and "search" not in model:
            typer.echo(
                f"[WARNING] search requested for OpenAI model {model} without explicit search capability"
            )
        reasoning_effort = thinking_cfg.get("reasoning_effort")

        messages, cache_key, explicit_cache = build_openai_messages(
            system,
            user_messages,
            cache_prefix=cache_prefix,
            system_cache_prefix=system_cache_prefix,
            model=model,
        )
        merged_prefix, _ = merge_cache_prefixes(system_cache_prefix, cache_prefix)
        audit_system = merge_system_cache_prefix_into_system(system, merged_prefix)

        typer.echo(
            f"[INFO] using OpenAI model {model}"
            + (f" reasoning_effort={reasoning_effort}" if reasoning_effort and reasoning_effort != "none" else "")
            + (" with search" if search else "")
            + (" with explicit prompt cache" if explicit_cache else "")
            + (" with cache_prefix" if cache_prefix else "")
            + (" with system_cache_prefix" if system_cache_prefix else "")
        )

        request_kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        if response_format:
            request_kwargs["response_format"] = response_format
        if reasoning_effort and reasoning_effort != "none":
            request_kwargs["reasoning_effort"] = reasoning_effort
        if explicit_cache and (cache_key or prompt_cache_key):
            request_kwargs["prompt_cache_options"] = {"mode": "explicit"}
            request_kwargs["prompt_cache_key"] = prompt_cache_key or cache_key
        elif is_gpt_56_family(model):
            # GPT-5.6 benefits from a routing key even when relying on implicit caching.
            stable = (system_cache_prefix or cache_prefix or "").strip()
            if stable:
                request_kwargs["prompt_cache_key"] = cache_key or stable[:256]

        try:
            response = self.client.chat.completions.create(
                **request_kwargs,
            )
        except Exception as e:
            self._record_llm_io(
                model=model,
                system=audit_system,
                user_messages=user_messages,
                search=search,
                response_format=response_format,
                error=str(e),
            )
            raise

        if response.usage:
            cache_read, cache_write = self._extract_cache_metrics(response.usage)
            self.track_cost(
                model,
                response.usage.prompt_tokens,
                response.usage.completion_tokens,
                search_queries=1 if search else 0,
                cached_tokens=cache_read,
                cache_write_tokens=cache_write,
            )
            if cache_read:
                typer.echo(f"[INFO] OpenAI cache read: {cache_read} tokens")
            if cache_write:
                typer.echo(f"[INFO] OpenAI cache write: {cache_write} tokens")

        output = response.choices[0].message.content.strip()
        self._record_llm_io(
            model=model,
            system=audit_system,
            user_messages=user_messages,
            search=search,
            response_format=response_format,
            output_text=output,
        )
        return output
