from .base import BaseClient, ModelSize
from openai import OpenAI
from typing import List, Dict
import typer

class OpenAIClient(BaseClient):
    def __init__(self):
        self.client = OpenAI()
        self.sizes = {
            ModelSize.TINY: "gpt-5-nano",
            ModelSize.BASE: "gpt-5-mini",
            ModelSize.MEDIUM: "gpt-5",
            ModelSize.LARGE: "gpt-5.2",
            ModelSize.XLARGE: "gpt-5.2",
        }

    def _format_messages(self, system: str, user_messages: List[str]) -> List[Dict]:
        return [{"role": "system", "content": system}] + [{"role": "user", "content": message} for message in user_messages]

    def call(self, model_size: ModelSize, system: str, user_messages: List[str], search: bool = False) -> str:
        messages = self._format_messages(system, user_messages)
        model = self.sizes[model_size]
        if search:
            if "gpt-4o" not in model:
                typer.echo(f"[WARNING] ignoring requested model {model}, using gpt-4o-search-preview instead")
            model = "gpt-4o-search-preview"
        typer.echo(f"[INFO] using OpenAI model {model}" + (" with search" if search else ""))
        response = self.client.chat.completions.create(
            model=model,
            messages=messages, 
        )
        return response.choices[0].message.content.strip()
