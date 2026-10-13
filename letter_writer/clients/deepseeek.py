from .base import BaseClient, ModelRole, merge_system_cache_prefix_into_system
from .model_override import apply_model_override_thinking
from openai import OpenAI
from typing import List, Dict, Any, Optional
import os
import typer
from langsmith import traceable


class DeepSeekClient(BaseClient):
    def __init__(self):
        super().__init__()
        self.client = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com"
        )

    def _format_messages(self, system: str, user_messages: List[str]) -> List[Dict]:
        return [{"role": "system", "content": system}] + [{"role": "user", "content": message} for message in user_messages]

    @traceable(run_type="llm", name="DeepSeek.call")
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
        _ = cache_prefix, prompt_cache_key
        system_prompt = merge_system_cache_prefix_into_system(system, system_cache_prefix)
        messages = self._format_messages(system_prompt, user_messages)
        model_role = self.resolve_effective_model_role(model_role)
        if isinstance(model_role, str):
            model, thinking_cfg = apply_model_override_thinking("deepseek", model_role)
        else:
            model = self.get_model_for_role(model_role)
            thinking_cfg = self.get_thinking_config(model_role)
        reasoning_effort = thinking_cfg.get("reasoning_effort")
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
            typer.echo(f"[WARNING] Search functionality not supported for DeepSeek models, proceeding without search")
        typer.echo(
            f"[INFO] using DeepSeek model {model}"
            + (f" reasoning_effort={reasoning_effort}" if reasoning_effort else "")
        )
        request_kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        if response_format:
            # DeepSeek rejects OpenAI-style json_schema; JSON mode is json_object only.
            request_kwargs["response_format"] = {"type": "json_object"}
        # Chat Completions: none disables thinking. low/high/max set reasoning_effort.
        # medium/xhigh are not sent; DeepSeek would collapse them onto high/max.
        if reasoning_effort == "none":
            request_kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        elif reasoning_effort in ("low", "high", "max"):
            request_kwargs["reasoning_effort"] = reasoning_effort
            request_kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
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
        
        if response.usage:
            usage = response.usage
            cached_tokens = int(getattr(usage, "prompt_cache_hit_tokens", 0) or 0)
            if not cached_tokens:
                details = getattr(usage, "prompt_tokens_details", None)
                cached_tokens = int(getattr(details, "cached_tokens", 0) or 0) if details else 0
            self.track_cost(
                model,
                usage.prompt_tokens,
                usage.completion_tokens,
                search_queries=0,  # No search support
                cached_tokens=cached_tokens,
            )

        return _return_with_audit(response.choices[0].message.content.strip())
