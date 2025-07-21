from .base import BaseClient, ModelSize
from openai import OpenAI
from typing import List, Dict
import typer

class OpenAIClient(BaseClient):
    def __init__(self):
        self.client = OpenAI()
        self.sizes = {
            ModelSize.TINY: "gpt-4.1-mini",
            ModelSize.BASE: "gpt-4.1",
            ModelSize.MEDIUM: "gpt-4.1",
            ModelSize.LARGE: "o4-mini"  ,
            ModelSize.XLARGE: "o3",
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
