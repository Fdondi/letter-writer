import os
import threading
from typing import Any, Dict, List, Optional, cast

import typer
from mistralai.client import Mistral

from .base import BaseClient, ModelSize
from langsmith import traceable

class MistralClient(BaseClient):
    """Client that talks to Mistral via the official SDK instead of hand-rolled
    HTTP requests. This avoids schema/validation errors (like the missing
    `inputs` field the user hit) and automatically picks the right endpoint.
    
    Uses Mistral's agents API for all requests:
    - With search: agent includes web_search tool ($30 per 1k search calls)
    - Without search: agent has no tools (no extra connector fees)
    
    This provides a consistent interface and enables web search when needed.

    The SDK uses httpx; one Mistral instance must not be shared across threads.
    Phased_service runs parallel feedback checks, so each thread lazily gets its own
    SDK via threading.local(). Agent ids and cost totals remain on this wrapper.
    """

    def __init__(self) -> None:
        super().__init__()
        api_key = os.getenv("MISTRAL_API_KEY")
        if not api_key:
            raise RuntimeError("MISTRAL_API_KEY environment variable is not set")

        self._api_key = api_key
        self._thread_local = threading.local()
        self._agent_cache: Dict[tuple, str] = {}
        self._agent_cache_lock = threading.Lock()
        self._cost_lock = threading.Lock()

    def _mistral(self) -> Mistral:
        client = getattr(self._thread_local, "client", None)
        if client is None:
            client = Mistral(api_key=self._api_key)
            self._thread_local.client = client
        return client

    def track_cost(
        self,
        model_name: str,
        input_tokens: int,
        output_tokens: int,
        search_queries: int = 0,
        cached_tokens: int = 0,
    ):
        with self._cost_lock:
            super().track_cost(
                model_name,
                input_tokens,
                output_tokens,
                search_queries=search_queries,
                cached_tokens=cached_tokens,
            )

    def _format_messages(self, system: str, user_messages: List[str]) -> List[Dict]:
        """Return messages in the schema expected by the SDK."""
        return (
            [{"role": "system", "content": system}]
            + [{"role": "user", "content": msg} for msg in user_messages]
        )

    def _get_or_create_agent(self, model: str, system: str, search: bool = False) -> str:
        """Get or create an agent, optionally with web_search capability."""
        cache_key = (model, search)
        if cache_key in self._agent_cache:
            return self._agent_cache[cache_key]

        with self._agent_cache_lock:
            if cache_key in self._agent_cache:
                return self._agent_cache[cache_key]
            sdk = self._mistral()
            try:
                if search:
                    agent = sdk.beta.agents.create(
                        model=model,
                        name=f"Websearch Agent ({model})",
                        description="Agent capable of performing web searches to retrieve up-to-date information.",
                        instructions=system or "You can perform web searches using the web_search tool to find current information.",
                        tools=cast(Any, [{"type": "web_search"}]),
                    )
                else:
                    agent = sdk.beta.agents.create(
                        model=model,
                        name=f"Agent ({model})",
                        description="Standard conversational agent.",
                        instructions=system or "You are a helpful assistant.",
                        tools=[],  # No tools for non-search requests
                    )

                agent_id = agent.id
                self._agent_cache[cache_key] = agent_id
                return agent_id
            except Exception as e:
                raise RuntimeError(f"Failed to create Mistral agent: {e}") from e

    def _extract_text_from_chunks(self, content) -> str:
        """Extract text from Mistral response content which may be chunks or a string.
        
        When using agents API with tools, content can be a list of chunk objects:
        - TextChunk: has .text attribute with the actual text
        - ToolReferenceChunk: metadata about tools used, can be skipped
        """
        if isinstance(content, str):
            return content
        
        if isinstance(content, list):
            text_parts = []
            for chunk in content:
                # Check if it's a TextChunk (has text attribute)
                if hasattr(chunk, 'text') and chunk.text:
                    text_parts.append(chunk.text)
                # ToolReferenceChunk and other metadata chunks can be skipped
                # as they don't contain the actual response text
            # Join text parts directly (LLM has already formatted the text appropriately)
            return "".join(text_parts) if text_parts else ""
        
        # Fallback: try to convert to string
        return str(content)

    def _chat_complete(
        self,
        model: str,
        system: str,
        user_messages: List[str],
        *,
        response_format: Optional[Dict[str, Any]] = None,
        search: bool = False,
    ) -> str:
        """Standard chat completion (token-efficient). Used when structured JSON is required."""
        messages = self._format_messages(system, user_messages)
        kwargs: Dict[str, Any] = {"model": model, "messages": messages}
        if response_format:
            # Mistral enforces valid JSON objects; map OpenAI-style json_schema to json_object.
            # https://docs.mistral.ai/capabilities/structured_output/json_mode
            kwargs["response_format"] = {"type": "json_object"}
        response = self._mistral().chat.complete(**kwargs)

        usage = getattr(response, "usage", None)
        if usage is not None:
            self.track_cost(
                model,
                int(getattr(usage, "prompt_tokens", 0) or 0),
                int(getattr(usage, "completion_tokens", 0) or 0),
                search_queries=1 if search else 0,
            )
        else:
            self.track_cost(model, 0, 0, search_queries=1 if search else 0)

        choices = getattr(response, "choices", None) or []
        if not choices:
            return ""
        msg = getattr(choices[0], "message", None)
        content = getattr(msg, "content", None) if msg is not None else None
        if content is None:
            return ""
        return str(content).strip()

    @traceable(run_type="llm", name="Mistral.call")
    def call(
        self,
        model_size: ModelSize | str,
        system: str,
        user_messages: List[str],
        search: bool = False,
        response_format: Optional[Dict[str, Any]] = None,
        cache_prefix: Optional[str] = None,
        system_cache_prefix: Optional[str] = None,
    ) -> str:
        _ = cache_prefix, system_cache_prefix  # Mistral does not support prompt caching
        if isinstance(model_size, str):
            model = model_size
        else:
            model = self.get_model_for_size(model_size)

        typer.echo(
            f"[INFO] using Mistral model {model}" + (" with search" if search else "")
        )

        # JSON / structured output: use chat.complete (Agents API ignores response_format).
        if response_format and not search:
            typer.echo("[INFO] Mistral: using chat.complete with JSON object mode (not Agents API)")
            return self._chat_complete(model, system, user_messages, response_format=response_format, search=False)
        if response_format and search:
            typer.echo(
                "[WARNING] Mistral: response_format ignored when search=True (Agents API path)"
            )

        # Agents API when search OR when no structured output is requested
        # When search=False, agent is created without tools (no extra cost)
        # When search=True, agent includes web_search tool ($30 per 1k calls)
        agent_id = self._get_or_create_agent(model, system, search=search)

        # Combine user messages into a single input
        user_input = "\n\n".join(user_messages)

        # Start conversation with agent
        response = self._mistral().beta.conversations.start(
            agent_id=agent_id,
            inputs=user_input
        )

        # Extract the assistant's reply from the response
        # Response has 'outputs' array with entries of different types
        # We want the 'message.output' type entry
        assistant_reply = None
        if hasattr(response, 'outputs') and response.outputs:
            for entry in response.outputs:
                # Look for message.output type entries
                if hasattr(entry, 'type') and entry.type == 'message.output':
                    assistant_reply = entry.content
                    break
                # Fallback: if no type field, assume first entry is the message
                elif assistant_reply is None and hasattr(entry, 'content'):
                    assistant_reply = entry.content

        if assistant_reply is None:
            typer.echo("[WARNING] No message.output entry found in agent response")
            return "No response from agent."

        # Track cost if usage info is available
        # Note: agents API may not provide detailed usage in the same format
        if hasattr(response, 'usage') and response.usage:
            self.track_cost(
                model,
                getattr(response.usage, 'prompt_tokens', 0),
                getattr(response.usage, 'completion_tokens', 0),
                search_queries=1 if search else 0
            )
        elif hasattr(response, 'prompt_tokens') or hasattr(response, 'completion_tokens'):
            # Fallback if usage is at top level
            self.track_cost(
                model,
                getattr(response, 'prompt_tokens', 0),
                getattr(response, 'completion_tokens', 0),
                search_queries=1 if search else 0
            )
        else:
            # If no usage info, still track search query if search was used
            self.track_cost(model, 0, 0, search_queries=1 if search else 0)

        # Extract text from chunks (handles both string and list of chunk objects)
        extracted_text = self._extract_text_from_chunks(assistant_reply)
        return extracted_text.strip()
