from .base import BaseClient, ModelSize
from openai import OpenAI
from typing import List, Dict
import typer
from langsmith import traceable

class OpenAIClient(BaseClient):
    def __init__(self):
        super().__init__()
        self.client = OpenAI()

    def _format_messages(self, system: str, user_messages: List[str]) -> List[Dict]:
        return [{"role": "system", "content": system}] + [{"role": "user", "content": message} for message in user_messages]

    @traceable(run_type="llm", name="OpenAI.call")
    def call(self, model_size: ModelSize | str, system: str, user_messages: List[str], search: bool = False) -> str:
        messages = self._format_messages(system, user_messages)
        if isinstance(model_size, str):
            model = model_size
        else:
            model = self.get_model_for_size(model_size)
        if search and "search" not in model:
            typer.echo(
                f"[WARNING] search requested for OpenAI model {model} without explicit search capability"
            )
        typer.echo(f"[INFO] using OpenAI model {model}" + (" with search" if search else ""))
        response = self.client.chat.completions.create(
            model=model,
            messages=messages, 
        )
        
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

        return response.choices[0].message.content.strip()
