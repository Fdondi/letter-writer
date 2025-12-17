from .base import BaseClient, ModelSize
from typing import List
import os
import typer
import xai_sdk


class GrokClient(BaseClient):
    def __init__(self):
        super().__init__()
        api_key = os.getenv("XAI_API_KEY")
        if not api_key:
            raise RuntimeError("XAI_API_KEY environment variable is not set")
        
        # Use OpenAI client with xAI's endpoint
        self.client = xai_sdk.Client(api_key=api_key)
        self.sizes = {
            ModelSize.TINY: "grok-4-1-fast-non-reasoning",
            ModelSize.BASE: "grok-4-1-fast-reasoning", 
            ModelSize.MEDIUM: "grok-4-1-fast-reasoning",
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
        
        # Attempt to track cost if usage info is available (structure uncertain)
        if hasattr(response, 'usage') and response.usage:
            # Assuming standard structure
            input_tokens = getattr(response.usage, 'prompt_tokens', 0)
            output_tokens = getattr(response.usage, 'completion_tokens', 0)
            self.track_cost(model, input_tokens, output_tokens, search_queries=1 if search else 0)
            
        return response.content.strip()
