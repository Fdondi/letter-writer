from .base import BaseClient, ModelSize
from typing import List
import os
import typer
import xai_sdk
from xai_sdk.tools import web_search
from langsmith import traceable


class GrokClient(BaseClient):
    def __init__(self):
        super().__init__()
        api_key = os.getenv("XAI_API_KEY")
        if not api_key:
            raise RuntimeError("XAI_API_KEY environment variable is not set")
        
        # Use OpenAI client with xAI's endpoint
        self.client = xai_sdk.Client(api_key=api_key)

    @traceable(run_type="llm", name="Grok.call")
    def call(self, model_size: ModelSize | str, system: str, user_messages: List[str], search: bool = False) -> str:
        if isinstance(model_size, str):
            model = model_size
        else:
            model = self.get_model_for_size(model_size)
        typer.echo(f"[INFO] using Grok model {model}")
        
        # Use Agent Tools API for search (replaces deprecated SearchParameters)
        tools = [web_search()] if search else None
        chat = self.client.chat.create(
            model=model,
            tools=tools,
        )

        chat.append(xai_sdk.chat.system(system))
        for message in user_messages:
            chat.append(xai_sdk.chat.user(message))

        response = chat.sample()
        
        # Track cost using usage info from the response
        if hasattr(response, 'usage') and response.usage:
            input_tokens = getattr(response.usage, 'prompt_tokens', 0)
            output_tokens = getattr(response.usage, 'completion_tokens', 0)
            # Count search queries from server_side_tool_usage if available
            search_queries = 0
            if search and hasattr(response, 'server_side_tool_usage') and response.server_side_tool_usage:
                search_queries = response.server_side_tool_usage.get('SERVER_SIDE_TOOL_WEB_SEARCH', 0)
            self.track_cost(model, input_tokens, output_tokens, search_queries=search_queries)
            
        return response.content.strip()
