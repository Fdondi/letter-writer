from .base import BaseClient, ModelSize
from openai import OpenAI
from typing import List, Dict, Any, Optional
import typer
from langsmith import traceable

class OpenAIClient(BaseClient):
    def __init__(self):
        super().__init__()
        self.client = OpenAI()

    def _format_messages(self, system: str, user_messages: List[str]) -> List[Dict]:
        return [{"role": "system", "content": system}] + [{"role": "user", "content": message} for message in user_messages]

    @traceable(run_type="llm", name="OpenAI.call")
    def call(
        self,
        model_size: ModelSize | str,
        system: str,
        user_messages: List[str],
        search: bool = False,
        response_format: Optional[Dict[str, Any]] = None,
        cache_prefix: Optional[str] = None,
        system_cache_prefix: Optional[str] = None,
    ) -> str:
        _ = cache_prefix, system_cache_prefix  # OpenAI handles prompt caching automatically
        messages = self._format_messages(system, user_messages)
        if isinstance(model_size, str):
            model = model_size
            thinking_cfg: dict = {}
        else:
            model = self.get_model_for_size(model_size)
            thinking_cfg = self.get_thinking_config(model_size)
        if search and "search" not in model:
            typer.echo(
                f"[WARNING] search requested for OpenAI model {model} without explicit search capability"
            )
        reasoning_effort = thinking_cfg.get("reasoning_effort")
        typer.echo(
            f"[INFO] using OpenAI model {model}"
            + (f" reasoning_effort={reasoning_effort}" if reasoning_effort and reasoning_effort != "none" else "")
            + (" with search" if search else "")
        )
        request_kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        if response_format:
            request_kwargs["response_format"] = response_format
        if reasoning_effort and reasoning_effort != "none":
            request_kwargs["reasoning_effort"] = reasoning_effort
        try:
            response = self.client.chat.completions.create(
                **request_kwargs,
            )
        except Exception as e:
            self._record_llm_io(
                model=model,
                system=system,
                user_messages=user_messages,
                search=search,
                response_format=response_format,
                error=str(e),
            )
            raise
        
        if response.usage:
            details = getattr(response.usage, "prompt_tokens_details", None)
            cached = int(getattr(details, "cached_tokens", 0) or 0)
            self.track_cost(
                model,
                response.usage.prompt_tokens,
                response.usage.completion_tokens,
                search_queries=1 if search else 0,
                cached_tokens=cached,
            )
            if cached:
                typer.echo(f"[INFO] prompt cache hit: {cached} tokens")

        output = response.choices[0].message.content.strip()
        self._record_llm_io(
            model=model,
            system=system,
            user_messages=user_messages,
            search=search,
            response_format=response_format,
            output_text=output,
        )
        return output
