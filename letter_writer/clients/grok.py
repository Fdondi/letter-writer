from .base import BaseClient, ModelSize
from typing import List
import os
import typer
import xai_sdk


class GrokClient(BaseClient):
    def __init__(self):
        api_key = os.getenv("XAI_API_KEY")
        if not api_key:
            raise RuntimeError("XAI_API_KEY environment variable is not set")
        
        # Use OpenAI client with xAI's endpoint
        self.client = xai_sdk.Client(api_key=api_key)
        self.sizes = {
            ModelSize.TINY: "grok-3-mini",
            ModelSize.BASE: "grok-3-mini", 
            ModelSize.MEDIUM: "grok-3-mini",
            ModelSize.LARGE: "grok-4-latest",
            ModelSize.XLARGE: "grok-4-latest",
        }

    def call(self, model_size: ModelSize, system: str, user_messages: List[str], search: bool = False) -> str:
        model = self.sizes[model_size]
        typer.echo(f"[INFO] using Grok model {model}")
        chat = self.client.chat.create(
            model=model,
            search_parameters=xai_sdk.search.SearchParameters(mode="on" if search else "off"),
        )

        chat.append(xai_sdk.chat.system(system))
        for message in user_messages:
            chat.append(xai_sdk.chat.user(message))

        response = chat.sample()
        return response.content.strip()
