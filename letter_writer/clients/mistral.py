from .base import BaseClient, ModelSize
from mistralai import Mistral
from typing import List, Dict
import os
import typer

class MistralClient(BaseClient):
    """Client that talks to Mistral via the official SDK instead of hand-rolled
    HTTP requests. This avoids schema/validation errors (like the missing
    `inputs` field the user hit) and automatically picks the right endpoint.
    
    Uses Mistral's agents API for all requests:
    - With search: agent includes web_search tool ($30 per 1k search calls)
    - Without search: agent has no tools (no extra connector fees)
    
    This provides a consistent interface and enables web search when needed.
    """

    def __init__(self):
        super().__init__()
        api_key = os.getenv("MISTRAL_API_KEY")
        if not api_key:
            raise RuntimeError("MISTRAL_API_KEY environment variable is not set")

        # Official SDK – see https://docs.mistral.ai/getting-started/clients/
        self.client = Mistral(api_key=api_key)
        self._agent_cache = {}  # Cache agents by (model, search) tuple

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
        
        # Create agent with or without web_search tool
        try:
            if search:
                agent = self.client.beta.agents.create(
                    model=model,
                    name=f"Websearch Agent ({model})",
                    description="Agent capable of performing web searches to retrieve up-to-date information.",
                    instructions=system or "You can perform web searches using the web_search tool to find current information.",
                    tools=[{"type": "web_search"}],
                )
            else:
                agent = self.client.beta.agents.create(
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

    def call(
        self,
        model_size: ModelSize,
        system: str,
        user_messages: List[str],
        search: bool = False,
    ) -> str:
        model = self.get_model_for_size(model_size)
        
        typer.echo(
            f"[INFO] using Mistral model {model}" + (" with search" if search else "")
        )

        # Always use agents API for consistency
        # When search=False, agent is created without tools (no extra cost)
        # When search=True, agent includes web_search tool ($30 per 1k calls)
        agent_id = self._get_or_create_agent(model, system, search=search)
        
        # Combine user messages into a single input
        user_input = "\n\n".join(user_messages)
        
        # Start conversation with agent
        response = self.client.beta.conversations.start(
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
        
        return assistant_reply.strip() if isinstance(assistant_reply, str) else str(assistant_reply)
