from .base import BaseClient, ModelSize
from openai import OpenAI
from typing import List, Dict, Optional
import typer

class OpenAIClient(BaseClient):
    def __init__(self):
        super().__init__()
        self.client = OpenAI()

    def _format_messages(self, system: str, user_messages: List[str]) -> List[Dict]:
        return [{"role": "system", "content": system}] + [{"role": "user", "content": message} for message in user_messages]

    def call(self, model_size: ModelSize, system: str, user_messages: List[str], search: bool = False, model_override: Optional[str] = None) -> str:
        messages = self._format_messages(system, user_messages)
        model = self._resolve_model(model_size, model_override)
        if search:
            if "gpt-4o" not in model:
                typer.echo(f"[WARNING] ignoring requested model {model}, using gpt-4o-search-preview instead")
            model = "gpt-4o-search-preview"
        self.last_model_used = model
        typer.echo(f"[INFO] using OpenAI model {model}" + (" with search" if search else ""))
        response = self.client.chat.completions.create(
            model=model,
            messages=messages, 
        )
        
        if response.usage:
            self.track_cost(
                model,
                response.usage.prompt_tokens,
                response.usage.completion_tokens,
                search_queries=1 if search else 0
            )
            
        return response.choices[0].message.content.strip()
