from .base import BaseClient, ModelSize
from anthropic import Anthropic
from typing import List, Dict
import typer

class ClaudeClient(BaseClient):
    def __init__(self):
        self.client = Anthropic()
        self.sizes = {
            ModelSize.TINY: "claude-haiku-4-5",
            ModelSize.BASE: "claude-haiku-4-5",
            ModelSize.MEDIUM: "claude-sonnet-4-5",
            ModelSize.LARGE: "claude-sonnet-4-5",
            ModelSize.XLARGE: "claude-opus-4-5",
        }

    def _format_messages(self, user_messages: List[str]) -> List[Dict]:
        return [{"role": "user", "content": [{"type": "text", "text": message}]} for message in user_messages]

    def call(self, model_size: ModelSize, system: str, user_messages: List[str], search: bool = False) -> str:
        messages = self._format_messages(user_messages)
        model = self.sizes[model_size]
        typer.echo(f"[INFO] using Anthropic model {model}" + (" with search" if search else ""))
        tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}] if search else []
        response = self.client.messages.create(
            model=model,
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=2048,
        )
        
        # Handle different response content types
        if not response.content:
            return ""
        
        # Check if the first content block is a text block
        if hasattr(response.content[0], 'text'):
            return response.content[0].text
        else:
            # If it's a tool use block or other type, try to get the text from subsequent blocks
            # or return a message indicating tool use
            for content_block in response.content:
                if hasattr(content_block, 'text'):
                    return content_block.text
            return "Response contains tool usage but no text content found."
