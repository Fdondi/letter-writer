from .base import BaseClient, ModelSize
from openai import OpenAI
from typing import List, Dict
import os
import typer


class DeepSeekClient(BaseClient):
    def __init__(self):
        self.client = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com"
        )
        self.sizes = {
            ModelSize.TINY: "deepseek-chat",
            ModelSize.BASE: "deepseek-chat",
            ModelSize.MEDIUM: "deepseek-reasoner",
            ModelSize.LARGE: "deepseek-reasoner",
            ModelSize.XLARGE: "deepseek-reasoner",
        }

    def _format_messages(self, system: str, user_messages: List[str]) -> List[Dict]:
        return [{"role": "system", "content": system}] + [{"role": "user", "content": message} for message in user_messages]

    def call(self, model_size: ModelSize, system: str, user_messages: List[str], search: bool = False) -> str:
        messages = self._format_messages(system, user_messages)
        model = self.sizes[model_size]
        if search:
            typer.echo(f"[WARNING] Search functionality not supported for DeepSeek models, proceeding without search")
        typer.echo(f"[INFO] using DeepSeek model {model}")
        response = self.client.chat.completions.create(
            model=model,
            messages=messages, 
            stream=False,
        )
        return response.choices[0].message.content.strip()
