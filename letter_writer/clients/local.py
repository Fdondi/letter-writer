from .base import BaseClient, ModelSize
from openai import OpenAI
from typing import List, Dict, Any, Optional
import os
from pathlib import Path
import typer
from langsmith import traceable


def _default_local_base_url() -> str:
    """LM Studio on the host: Docker must use host.docker.internal, not localhost."""
    if Path("/.dockerenv").exists():
        return "http://host.docker.internal:1234/v1"
    return "http://localhost:1234/v1"


class LocalClient(BaseClient):
    """Client for LM Studio (or any OpenAI-compatible local server).

    Base URL: ``LOCAL_LLM_BASE_URL`` if set, else ``http://localhost:1234/v1`` on the
    host, or ``http://host.docker.internal:1234/v1`` when running inside a container
    so the host's LM Studio is reachable. API key defaults to ``lm-studio`` or
    ``LOCAL_LLM_API_KEY``. Model sizes are ignored — whatever model is loaded locally is used.
    """

    def __init__(self):
        super().__init__()
        self._base_url = os.getenv("LOCAL_LLM_BASE_URL") or _default_local_base_url()
        api_key = os.getenv("LOCAL_LLM_API_KEY", "lm-studio")
        self.client = OpenAI(
            base_url=self._base_url,
            api_key=api_key,
        )

    def _format_messages(self, system: str, user_messages: List[str]) -> List[Dict]:
        return [{"role": "system", "content": system}] + [
            {"role": "user", "content": message} for message in user_messages
        ]

    @traceable(run_type="llm", name="Local.call")
    def call(
        self,
        model_size: ModelSize | str,
        system: str,
        user_messages: List[str],
        search: bool = False,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> str:
        messages = self._format_messages(system, user_messages)
        # LM Studio uses whatever model is loaded; the model param is ignored.
        model = "local-model"
        if search:
            typer.echo("[WARNING] search not supported for local models, ignoring")
        typer.echo(f"[INFO] using local model (LM Studio) at {self._base_url}")
        request_kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        if response_format:
            request_kwargs["response_format"] = response_format
        response = self.client.chat.completions.create(**request_kwargs)

        if response.usage:
            self.track_cost(
                model,
                response.usage.prompt_tokens,
                response.usage.completion_tokens,
            )

        return response.choices[0].message.content.strip()
