from .base import BaseClient, ModelSize
from mistralai import Mistral
from typing import List, Dict
import os
import typer

class MistralClient(BaseClient):
    """Client that talks to Mistral via the official SDK instead of hand-rolled
    HTTP requests. This avoids schema/validation errors (like the missing
    `inputs` field the user hit) and automatically picks the right endpoint.
    """

    def __init__(self):
        super().__init__()
        api_key = os.getenv("MISTRAL_API_KEY")
        if not api_key:
            raise RuntimeError("MISTRAL_API_KEY environment variable is not set")

        # Official SDK – see https://docs.mistral.ai/getting-started/clients/
        self.client = Mistral(api_key=api_key)

        # Map logical sizes to actual model names – tweak as needed.
        self.sizes = {
            ModelSize.TINY: "open-mixtral-8x7b",
            ModelSize.BASE: "open-mixtral-8x7b",
            ModelSize.MEDIUM: "mistral-medium-latest",
            ModelSize.LARGE: "mistral-large-latest",
            ModelSize.XLARGE: "mistral-large-latest",
        }

    def _format_messages(self, system: str, user_messages: List[str]) -> List[Dict]:
        """Return messages in the schema expected by the SDK."""
        return (
            [{"role": "system", "content": system}]
            + [{"role": "user", "content": msg} for msg in user_messages]
        )

    def call(
        self,
        model_size: ModelSize,
        system: str,
        user_messages: List[str],
        search: bool = False,
    ) -> str:
        model = self.sizes[model_size]
        messages = self._format_messages(system, user_messages)

        # Configure tools if search is requested
        tools = None
        if search:
            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": "web_search",
                        "description": "Search the web for current information",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "The search query to execute"
                                }
                            },
                            "required": ["query"]
                        }
                    }
                }
            ]
        
        typer.echo(
            f"[INFO] using Mistral model {model}" + (" with search" if search else "")
        )

        # Make the request with or without tools
        if tools:
            response = self.client.chat.complete(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice="auto"
            )
        else:
            response = self.client.chat.complete(
                model=model,
                messages=messages,
            )

        # Handle response - if there are tool calls, we need to process them
        choice = response.choices[0]
        
        if response.usage:
            self.track_cost(
                model,
                response.usage.prompt_tokens,
                response.usage.completion_tokens,
                search_queries=1 if search else 0
            )

        if hasattr(choice.message, 'tool_calls') and choice.message.tool_calls:
            # For now, just return a message indicating web search was attempted
            # In a full implementation, you would execute the search and continue the conversation
            search_queries = []
            for tool_call in choice.message.tool_calls:
                if tool_call.function.name == "web_search":
                    import json
                    args = json.loads(tool_call.function.arguments)
                    search_queries.append(args.get('query', ''))
            
            if search_queries:
                return f"I would search for: {', '.join(search_queries)}. However, actual web search execution is not implemented in this demo client."
        
        # The SDK mirrors OpenAI's response shape.
        return choice.message.content.strip()
