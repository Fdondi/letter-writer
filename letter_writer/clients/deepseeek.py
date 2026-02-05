from .base import BaseClient, ModelSize
from openai import OpenAI
from typing import List, Dict, Optional
import os
import typer


class DeepSeekClient(BaseClient):
    def __init__(self):
        super().__init__()
        self.client = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com"
        )

    def _format_messages(self, system: str, user_messages: List[str]) -> List[Dict]:
        return [{"role": "system", "content": system}] + [{"role": "user", "content": message} for message in user_messages]

    def call(self, model_size: ModelSize, system: str, user_messages: List[str], search: bool = False, model_override: Optional[str] = None) -> str:
        messages = self._format_messages(system, user_messages)
        model = self._resolve_model(model_size, model_override)
        self.last_model_used = model
        if search:
            typer.echo(f"[WARNING] Search functionality not supported for DeepSeek models, proceeding without search")
        typer.echo(f"[INFO] using DeepSeek model {model}")
        response = self.client.chat.completions.create(
            model=model,
            messages=messages, 
            stream=False,
        )
        
        if response.usage:
            self.track_cost(
                model,
                response.usage.prompt_tokens,
                response.usage.completion_tokens,
                search_queries=0 # No search support
            )

        return response.choices[0].message.content.strip()
