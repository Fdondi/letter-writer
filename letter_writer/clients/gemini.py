from .base import BaseClient, ModelSize
from google import genai
from google.genai import types
from typing import List
import typer

class GeminiClient(BaseClient):
    def __init__(self):
        self.client = genai.Client()
        self.sizes = {
            ModelSize.TINY: "gemini-2.5-flash-lite-preview-06-17",
            ModelSize.BASE: "gemini-2.5-flash",
            ModelSize.MEDIUM: "gemini-2.5-flash",
            ModelSize.LARGE: "gemini-2.5-pro",
            ModelSize.XLARGE: "gemini-2.5-pro",
        }

    def call(self, model_size: ModelSize, system: str, user_messages: List[str], search: bool = False) -> str:
        if search:
            grounding_tool = types.Tool(
                google_search=types.GoogleSearch()
            )
            tools=[grounding_tool]
        else:
            tools = []
        typer.echo(f"[INFO] using Gemini model {self.sizes[model_size]}" + (" with search" if search else ""))
        response = self.client.models.generate_content(
            model=self.sizes[model_size],
            config=types.GenerateContentConfig(
                system_instruction=system,
                tools=tools,
            ),
            contents=user_messages
        )
        return response.text
