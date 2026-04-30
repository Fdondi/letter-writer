from .base import BaseClient, ModelSize
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
        model_size: ModelSize | str,
        system: str,
        user_messages: List[str],
        search: bool = False,
        response_format: Optional[Dict[str, Any]] = None,
        cache_prefix: Optional[str] = None,
        system_cache_prefix: Optional[str] = None,
    ) -> str:
        _ = cache_prefix, system_cache_prefix  # DeepSeek does not support prompt caching
        messages = self._format_messages(system, user_messages)
        if isinstance(model_size, str):
            model = model_size
        else:
            model = self.get_model_for_size(model_size)
        def _return_with_audit(text: str) -> str:
            self._record_llm_io(
                model=model,
                system=system,
                user_messages=user_messages,
                search=search,
                response_format=response_format,
                output_text=text,
            )
            return text
        if search:
            typer.echo(f"[WARNING] Search functionality not supported for DeepSeek models, proceeding without search")
        typer.echo(f"[INFO] using DeepSeek model {model}")
        request_kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        if response_format:
            # DeepSeek rejects OpenAI-style json_schema; JSON mode is json_object only.
            request_kwargs["response_format"] = {"type": "json_object"}
        try:
            response = self.client.chat.completions.create(**request_kwargs)
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
            self.track_cost(
                model,
                response.usage.prompt_tokens,
                response.usage.completion_tokens,
                search_queries=0 # No search support
            )

        return _return_with_audit(response.choices[0].message.content.strip())
