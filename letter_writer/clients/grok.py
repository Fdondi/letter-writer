from .base import BaseClient, ModelRole, merge_system_cache_prefix_into_system
from .model_override import apply_model_override_thinking
from typing import List, Dict, Any, Optional, Union
import json
import os
import typer
import xai_sdk
from xai_sdk.proto import chat_pb2
from xai_sdk.tools import web_search
from langsmith import traceable


def _xai_response_format(
    response_format: Optional[Dict[str, Any]],
) -> Optional[Union[str, chat_pb2.ResponseFormat]]:
    """Map the OpenAI-style ``response_format`` used by callers to the xAI SDK form."""
    if not response_format:
        return None
    fmt_type = response_format.get("type")
    if fmt_type == "json_schema":
        schema = (response_format.get("json_schema") or {}).get("schema")
        if schema:
            return chat_pb2.ResponseFormat(
                format_type=chat_pb2.FormatType.FORMAT_TYPE_JSON_SCHEMA,
                schema=json.dumps(schema),
            )
        return "json_object"
    if fmt_type == "json_object":
        return "json_object"
    return None


class GrokClient(BaseClient):
    def __init__(self):
        super().__init__()
        api_key = os.getenv("XAI_API_KEY")
        if not api_key:
            raise RuntimeError("XAI_API_KEY environment variable is not set")
        
        # Use OpenAI client with xAI's endpoint
        self.client = xai_sdk.Client(api_key=api_key)

    @traceable(run_type="llm", name="Grok.call")
    def call(
        self,
        model_role: ModelRole | str,
        system: str,
        user_messages: List[str],
        search: bool = False,
        response_format: Optional[Dict[str, Any]] = None,
        cache_prefix: Optional[str] = None,
        system_cache_prefix: Optional[str] = None,
        prompt_cache_key: Optional[str] = None,
    ) -> str:
        _ = cache_prefix, prompt_cache_key
        system_prompt = merge_system_cache_prefix_into_system(system, system_cache_prefix)
        model_role = self.resolve_effective_model_role(model_role)
        if isinstance(model_role, str):
            model, thinking_cfg = apply_model_override_thinking("grok", model_role)
        else:
            model = self.get_model_for_role(model_role)
            thinking_cfg = self.get_thinking_config(model_role)
        reasoning_effort = thinking_cfg.get("reasoning_effort")
        def _return_with_audit(text: str) -> str:
            self._record_llm_io(
                model=model,
                system=system_prompt,
                user_messages=user_messages,
                search=search,
                response_format=response_format,
                output_text=text,
            )
            return text
        typer.echo(
            f"[INFO] using Grok model {model}"
            + (f" reasoning_effort={reasoning_effort}" if reasoning_effort else "")
            + (" with structured output" if response_format else "")
        )
        
        # Use Agent Tools API for search (replaces deprecated SearchParameters)
        tools = [web_search()] if search else None
        create_kwargs: Dict[str, Any] = {"model": model, "tools": tools}
        if reasoning_effort:
            create_kwargs["reasoning_effort"] = reasoning_effort
        xai_format = _xai_response_format(response_format)
        if xai_format is not None:
            create_kwargs["response_format"] = xai_format
        chat = self.client.chat.create(**create_kwargs)

        chat.append(xai_sdk.chat.system(system_prompt))
        for message in user_messages:
            chat.append(xai_sdk.chat.user(message))

        try:
            response = chat.sample()
        except Exception as e:
            self._record_llm_io(
                model=model,
                system=system_prompt,
                user_messages=user_messages,
                search=search,
                response_format=response_format,
                error=str(e),
            )
            raise
        
        # Track cost using usage info from the response
        if hasattr(response, 'usage') and response.usage:
            input_tokens = getattr(response.usage, 'prompt_tokens', 0)
            output_tokens = getattr(response.usage, 'completion_tokens', 0)
            cached_tokens = int(getattr(response.usage, 'cached_prompt_text_tokens', 0) or 0)
            # Count search queries from server_side_tool_usage if available
            search_queries = 0
            if search and hasattr(response, 'server_side_tool_usage') and response.server_side_tool_usage:
                search_queries = response.server_side_tool_usage.get('SERVER_SIDE_TOOL_WEB_SEARCH', 0)
            self.track_cost(
                model,
                input_tokens,
                output_tokens,
                search_queries=search_queries,
                cached_tokens=cached_tokens,
            )
            if cached_tokens:
                typer.echo(f"[INFO] Grok cache read: {cached_tokens} tokens")
            
        return _return_with_audit(response.content.strip())
