from .base import BaseClient, ModelSize
from openai import OpenAI
from typing import List, Dict
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
    def call(self, model_size: ModelSize | str, system: str, user_messages: List[str], search: bool = False) -> str:
        messages = self._format_messages(system, user_messages)
        if isinstance(model_size, str):
            model = model_size
        else:
            model = self.get_model_for_size(model_size)
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
