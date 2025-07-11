import os
from typing import Optional, List, Dict
from enum import Enum
import typer
from openai import OpenAI
from anthropic import Anthropic
from google import genai
from google.genai import types
from mistralai import Mistral, Tool

class ModelVendor(Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    MISTRAL = "mistral"
    GROK = "grok"

class ModelSize(Enum):
    TINY = "tiny"
    BASE = "base"
    MEDIUM = "medium"
    LARGE = "large"
    XLARGE = "xlarge"

class BaseClient:
    def call(self, model_size: ModelSize, system: str, messages: List[Dict]) -> str:
        raise NotImplementedError("Subclasses must implement this method")

class ClaudeClient(BaseClient):
    def __init__(self):
        self.client = Anthropic()
        self.sizes = {
            ModelSize.TINY: "claude-3-5-haiku-latest",
            ModelSize.BASE: "claude-sonnet-4-0",
            ModelSize.MEDIUM: "claude-sonnet-4-0",
            ModelSize.LARGE: "claude-sonnet-4-0",
            ModelSize.XLARGE: "claude-opus-4-0",
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
    
# using requests, as the library seems broken
class MistralClient(BaseClient):
    """Client that talks to Mistral via the official SDK instead of hand-rolled
    HTTP requests. This avoids schema/validation errors (like the missing
    `inputs` field the user hit) and automatically picks the right endpoint.
    """

    def __init__(self):
        api_key = os.getenv("MISTRAL_API_KEY")
        if not api_key:
            raise RuntimeError("MISTRAL_API_KEY environment variable is not set")

        # Official SDK – see https://docs.mistral.ai/getting-started/clients/
        self.client = Mistral(api_key=api_key)

        # Map logical sizes to actual model names – tweak as needed.
        self.sizes = {
            ModelSize.TINY: "mistral-small-latest",
            ModelSize.BASE: "mistral-medium-latest",
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

class GrokClient(BaseClient):
    def __init__(self):
        api_key = os.getenv("XAI_API_KEY")
        if not api_key:
            raise RuntimeError("XAI_API_KEY environment variable is not set")
        
        # Use OpenAI client with xAI's endpoint
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://api.x.ai/v1"
        )
        self.sizes = {
            ModelSize.TINY: "grok-3-mini",
            ModelSize.BASE: "grok-3-mini", 
            ModelSize.MEDIUM: "grok-3-mini",
            ModelSize.LARGE: "grok-4-latest",
            ModelSize.XLARGE: "grok-4-latest",
        }

    def _format_messages(self, system: str, user_messages: List[str]) -> List[Dict]:
        return [{"role": "system", "content": system}] + [{"role": "user", "content": message} for message in user_messages]

    def call(self, model_size: ModelSize, system: str, user_messages: List[str], search: bool = False) -> str:
        messages = self._format_messages(system, user_messages)
        model = self.sizes[model_size]
        if search:
            typer.echo(f"[WARNING] Search functionality not supported for Grok models, proceeding without search")
        typer.echo(f"[INFO] using Grok model {model}")
        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=2048,
        )
        return response.choices[0].message.content.strip()

def get_client(vendor: ModelVendor) -> BaseClient:
    if vendor == ModelVendor.OPENAI:
        return OpenAIClient()
    elif vendor == ModelVendor.ANTHROPIC:
        return ClaudeClient()
    elif vendor == ModelVendor.GEMINI:
        return GeminiClient()
    elif vendor == ModelVendor.MISTRAL:
        return MistralClient()
    elif vendor == ModelVendor.GROK:
        return GrokClient()
    else:
        raise ValueError(f"Invalid vendor: {vendor}")