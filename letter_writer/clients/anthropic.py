import json

from .base import BaseClient, ModelRole
from .prompt_cache import merge_cache_prefixes, prepare_cache_block
from .model_override import apply_model_override_thinking
from anthropic import Anthropic
from typing import List, Dict, Any, Optional, FrozenSet
import typer
from langsmith import traceable

# Anthropic rejects ``thinking.type == "enabled"`` (budget_tokens) on these
# families; use adaptive thinking + ``output_config.effort`` instead. See:
# https://platform.claude.com/docs/en/about-claude/models/migration-guide
_ADAPTIVE_THINKING_MODEL_MARKERS: FrozenSet[str] = frozenset(
    ("fable-5", "opus-4-8", "opus-4-7", "opus-4-6", "sonnet-5", "sonnet-4-6")
)
_VALID_THINKING_EFFORTS: FrozenSet[str] = frozenset(
    ("low", "medium", "high", "max", "xhigh")
)


def _anthropic_model_requires_adaptive_thinking(model: str) -> bool:
    m = (model or "").lower()
    return any(marker in m for marker in _ADAPTIVE_THINKING_MODEL_MARKERS)


class ClaudeClient(BaseClient):
    def __init__(self):
        super().__init__()
        self.client = Anthropic()

    @staticmethod
    def _thinking_request_kwargs(
        model: str,
        thinking_enabled: bool,
        max_tokens: int,
        thinking_cfg: dict,
    ) -> Dict[str, Any]:
        """Build ``thinking`` / ``output_config`` for :meth:`messages.create`.

        Newer models (Fable 5, Opus 4.8+, Sonnet 5, Sonnet 4.6, Mythos) require
        ``thinking.type`` ``adaptive`` and reject ``enabled`` + ``budget_tokens``.
        Older models still need manual extended thinking with ``budget_tokens``.
        See https://platform.claude.com/docs/en/build-with-claude/adaptive-thinking
        """
        if not thinking_enabled:
            return {}
        norm = (model or "").lower()
        # Substrings match dated IDs (e.g. claude-opus-4-7-20250514).
        adaptive_markers = (
            "claude-fable-5",
            "claude-opus-4-8",
            "claude-opus-4-7",
            "claude-opus-4-6",
            "claude-sonnet-5",
            "claude-sonnet-4-6",
            "claude-mythos",
            "mythos-preview",
        )
        if any(marker in norm for marker in adaptive_markers):
            effort_raw = thinking_cfg.get("effort") or thinking_cfg.get("thinking_effort") or "high"
            effort = str(effort_raw).lower() if effort_raw is not None else "high"
            if effort not in _VALID_THINKING_EFFORTS:
                typer.echo(
                    f"[WARNING] Invalid thinking effort {effort_raw!r}; using 'high'. "
                    f"Expected one of {sorted(_VALID_THINKING_EFFORTS)}."
                )
                effort = "high"
            return {
                "thinking": {"type": "adaptive"},
                "output_config": {"effort": effort},
            }
        # budget_tokens must be strictly less than max_tokens
        return {
            "thinking": {
                "type": "enabled",
                "budget_tokens": max(1, max_tokens // 2),
            },
        }

    def _format_messages(
        self,
        user_messages: List[str],
        cache_prefix: Optional[str] = None,
    ) -> List[Dict]:
        """Format user messages for the Anthropic API.

        When *cache_prefix* is supplied it becomes a cached text block inside
        the **first** user message, so all calls sharing the same system +
        cache_prefix enjoy Anthropic's prompt-cache discount (90 % off input
        after the first write).
        """
        formatted: List[Dict] = []
        for i, message in enumerate(user_messages):
            if i == 0 and cache_prefix:
                # First message: cacheable context block + dynamic observation
                formatted.append({
                    "role": "user",
                    "content": [
                        {"type": "text", "text": cache_prefix,
                         "cache_control": {"type": "ephemeral"}},
                        {"type": "text", "text": message},
                    ],
                })
            else:
                formatted.append({
                    "role": "user",
                    "content": [{"type": "text", "text": message}],
                })
        return formatted

    # ------------------------------------------------------------------
    # Cost tracking – Anthropic cache pricing
    # ------------------------------------------------------------------
    # Cache read  = 10 % of input price
    # Cache write = 125 % of input price (25 % premium)
    # Regular     = 100 %
    # ------------------------------------------------------------------
    def track_cost(
        self,
        model_name: str,
        input_tokens: int,
        output_tokens: int,
        search_queries: int = 0,
        cached_tokens: int = 0,
        *,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ):
        costs = self.get_model_cost(model_name)
        input_price = costs["input"]

        regular = max(0, input_tokens - cache_read_tokens - cache_write_tokens)
        input_cost = (
            (regular / 1_000_000) * input_price
            + (cache_read_tokens / 1_000_000) * input_price * 0.10
            + (cache_write_tokens / 1_000_000) * input_price * 1.25
        )
        output_cost = (output_tokens / 1_000_000) * costs["output"]
        search_cost = (search_queries / 1_000) * costs["search"]

        self.total_cost += input_cost + output_cost + search_cost
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cached_tokens += cache_read_tokens
        self.total_search_queries += search_queries

    @staticmethod
    def _extract_cache_metrics(usage) -> tuple:
        """Return (cache_read, cache_write) from an Anthropic usage object."""
        cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        cache_write = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        return cache_read, cache_write

    @traceable(run_type="llm", name="Anthropic.call")
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
        _ = prompt_cache_key  # Anthropic matches on prefix content; scheduling is caller-side
        if isinstance(model_role, str):
            model, thinking_cfg = apply_model_override_thinking("anthropic", model_role)
        else:
            model = self.get_model_for_role(model_role)
            thinking_cfg = self.get_thinking_config(model_role)
        thinking_enabled = bool(thinking_cfg.get("thinking", False))

        sys_cache_raw, usr_cache_raw = merge_cache_prefixes(system_cache_prefix, cache_prefix)
        sys_cache = prepare_cache_block(sys_cache_raw, vendor="anthropic", model=model) if sys_cache_raw else None
        usr_cache = prepare_cache_block(usr_cache_raw, vendor="anthropic", model=model) if usr_cache_raw else None
        if sys_cache and sys_cache != (sys_cache_raw or ""):
            typer.echo(f"[INFO] Anthropic cache padding: ~{len(sys_cache) - len(sys_cache_raw or '')} chars added to system prefix")
        if usr_cache and usr_cache != (usr_cache_raw or ""):
            typer.echo(f"[INFO] Anthropic cache padding: ~{len(usr_cache) - len(usr_cache_raw or '')} chars added to user prefix")

        messages = self._format_messages(user_messages, cache_prefix=usr_cache)
        def _return_with_audit(text: str) -> str:
            self._record_llm_io(
                model=model,
                system=system,
                user_messages=user_messages,
                search=search,
                response_format=response_format,
                output_text=text,
            )
            return text
        typer.echo(
            f"[INFO] using Anthropic model {model}"
            + (" with thinking" if thinking_enabled else "")
            + (" with search" if search else "")
            + (" with cache_prefix" if usr_cache_raw else "")
            + (" with system_cache_prefix" if sys_cache_raw else "")
        )

        # Build system block list.
        #
        # When system_cache_prefix is supplied it becomes the FIRST block with
        # cache_control, enabling cross-call caching for calls that share the
        # same document set (e.g. precision_check and company_fit_check both
        # see the same company_report + job_text + letter).  Anthropic keys the
        # cache on everything up to and including the marked block, so the
        # category-specific instructions that follow do not affect the key.
        #
        # Without system_cache_prefix the regular system text itself is cached,
        # which still helps for parallel observation-level calls in stage 2.
        if sys_cache:
            cached_system: Any = [
                {"type": "text", "text": sys_cache,
                 "cache_control": {"type": "ephemeral"}},
            ]
            if (system or "").strip():
                cached_system.append({"type": "text", "text": system})
        elif (system or "").strip():
            # Short task-only system prompts: cache_control may help implicit reuse,
            # but do not pad — padding is only for large shared prefix blocks.
            cached_system = [
                {"type": "text", "text": system,
                 "cache_control": {"type": "ephemeral"}},
            ]
        else:
            cached_system = []

        if response_format and isinstance(response_format, dict):
            schema = ((response_format.get("json_schema") or {}).get("schema") or {})
            tool_name = ((response_format.get("json_schema") or {}).get("name") or "phase_output")
            try:
                response = self.client.messages.create(
                    model=model,
                    system=cached_system,
                    messages=messages,
                    tools=[{
                        "name": tool_name,
                        "description": "Return structured JSON response for the current phase.",
                        "input_schema": schema,
                    }],
                    tool_choice={"type": "tool", "name": tool_name},
                    max_tokens=4000,
                )
            except Exception as e:
                self._record_llm_io(
                    model=model,
                    system=system,
                    user_messages=user_messages,
                    search=search,
                    response_format=response_format,
                    error=str(e),
                )
                raise
            if response.usage:
                cr, cw = self._extract_cache_metrics(response.usage)
                self.track_cost(
                    model,
                    response.usage.input_tokens,
                    response.usage.output_tokens,
                    search_queries=0,
                    cache_read_tokens=cr,
                    cache_write_tokens=cw,
                )
                if cr:
                    typer.echo(f"[INFO] Anthropic cache read: {cr} tokens")
                if cw:
                    typer.echo(f"[INFO] Anthropic cache write: {cw} tokens")
            if response.content:
                for block in response.content:
                    if getattr(block, "type", None) == "tool_use":
                        payload = getattr(block, "input", None)
                        if isinstance(payload, dict):
                            return _return_with_audit(json.dumps(payload))
            return _return_with_audit("{}")
        tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}] if search else []
        # Use 2048 for search, 8000 for everything else (letters, comments, etc.)
        max_tokens = 2048 if search else 8000

        # Build conversation history
        conversation_messages = messages.copy()
        total_input_tokens = 0
        total_output_tokens = 0
        total_cache_read = 0
        total_cache_write = 0

        # Initial request
        # Thinking is enabled only on non-search paths (search needs max_tokens=2048
        # which is too low to fit a meaningful thinking budget alongside the response).
        create_kwargs: Dict[str, Any] = {
            "model": model,
            "system": cached_system,
            "messages": conversation_messages,
            "tools": tools,
            "max_tokens": max_tokens,
        }
        if not search:
            create_kwargs.update(
                self._thinking_request_kwargs(
                    model, thinking_enabled, max_tokens, thinking_cfg
                )
            )
        try:
            response = self.client.messages.create(**create_kwargs)
        except Exception as e:
            self._record_llm_io(
                model=model,
                system=system,
                user_messages=user_messages,
                search=search,
                response_format=response_format,
                error=str(e),
            )
            raise

        # Track usage from first response
        if response.usage:
            total_input_tokens += response.usage.input_tokens
            total_output_tokens += response.usage.output_tokens
            cr, cw = self._extract_cache_metrics(response.usage)
            total_cache_read += cr
            total_cache_write += cw
            if cr:
                typer.echo(f"[INFO] Anthropic cache read: {cr} tokens")
            if cw:
                typer.echo(f"[INFO] Anthropic cache write: {cw} tokens")

        # Log stop reason for debugging
        stop_reason = getattr(response, 'stop_reason', None)
        if stop_reason:
            typer.echo(f"[DEBUG] Anthropic stop_reason: {stop_reason}")
            if stop_reason == "max_tokens":
                typer.echo(f"[WARNING] Response was truncated due to max_tokens limit ({max_tokens})")

        # Add assistant's response to conversation
        conversation_messages.append({
            "role": "assistant",
            "content": response.content
        })

        # Check if we need to continue (tool use detected)
        needs_continuation = False
        if response.content:
            for block in response.content:
                # Check if there's a tool_use block (model wants to use a tool)
                if hasattr(block, 'type') and block.type == 'tool_use':
                    needs_continuation = True
                    break

        # For web_search_20250305, Anthropic handles tool execution automatically,
        # but we may need to continue to get the final synthesized response
        # Continue conversation if stop_reason suggests we should or if we have tool results
        if needs_continuation or (stop_reason and stop_reason not in ['end_turn', 'stop_sequence']):
            # Check if response contains tool results that need synthesis
            has_tool_results = False
            if response.content:
                for block in response.content:
                    if hasattr(block, 'type') and 'tool_result' in str(block.type).lower():
                        has_tool_results = True
                        break

            # If we have tool results but no comprehensive text response, continue
            if has_tool_results:
                # Extract text so far
                text_so_far = []
                for block in response.content:
                    if hasattr(block, 'text') and block.text:
                        text_so_far.append(block.text)

                # If we only have minimal text, continue the conversation
                if not text_so_far or len(' '.join(text_so_far)) < 200:
                    typer.echo("[DEBUG] Continuing conversation to synthesize tool results")
                    # Send a follow-up to encourage synthesis
                    conversation_messages.append({
                        "role": "user",
                        "content": [{"type": "text", "text": "Please provide a concise synthesis of the search results in your response."}]
                    })

                    # Calculate remaining tokens to respect the global limit
                    current_usage = response.usage.output_tokens if response.usage else 0
                    remaining_tokens = max(1, max_tokens - current_usage)

                    # Continue the conversation (system prompt cached from initial request)
                    try:
                        continuation_response = self.client.messages.create(
                            model=model,
                            system=cached_system,
                            messages=conversation_messages,
                            max_tokens=remaining_tokens,
                        )
                    except Exception as e:
                        self._record_llm_io(
                            model=model,
                            system=system,
                            user_messages=user_messages,
                            search=search,
                            response_format=response_format,
                            error=str(e),
                        )
                        raise

                    # Track usage from continuation
                    if continuation_response.usage:
                        total_input_tokens += continuation_response.usage.input_tokens
                        total_output_tokens += continuation_response.usage.output_tokens
                        cr, cw = self._extract_cache_metrics(continuation_response.usage)
                        total_cache_read += cr
                        total_cache_write += cw

                    # Add continuation text to our collection
                    if continuation_response.content:
                        for block in continuation_response.content:
                            if hasattr(block, 'text') and block.text:
                                text_so_far.append(block.text)

                    # Update response to continuation response for final processing,
                    # but keep accumulated text_so_far separate
                    response = continuation_response

        # Track total cost
        if total_input_tokens > 0 or total_output_tokens > 0:
            self.track_cost(
                model,
                total_input_tokens,
                total_output_tokens,
                search_queries=1 if search else 0,
                cache_read_tokens=total_cache_read,
                cache_write_tokens=total_cache_write,
            )

        # Return accumulated text if we have any, otherwise parse the last response
        if 'text_so_far' in locals() and text_so_far:
            full_text = "\n\n".join(text_so_far)
            # Clean up newlines only if this was a search request
            if search:
                # 1. Collapse multiple newlines to single newline
                import re
                full_text = re.sub(r'\n+', '\n', full_text)
                # 2. Join lines unless the next line starts with a capital letter, bullet point, or markdown header/bold
                # Logic: Look for a newline followed by a character that IS NOT (uppercase, *, -, or #)
                # We use a negative lookahead to identify lines that should be joined
                full_text = re.sub(r'\n(?![A-Z*#\-])', ' ', full_text)

            typer.echo(f"[DEBUG] Anthropic response length (accumulated): {len(full_text)} characters, {len(full_text.split())} words")
            return _return_with_audit(full_text)

        # Handle different response content types if we didn't accumulate text
        if not response.content:
            return _return_with_audit("")

        # Collect all text from all content blocks
        text_parts = []
        for content_block in response.content:
            if hasattr(content_block, 'text') and content_block.text:
                text_parts.append(content_block.text)
            elif hasattr(content_block, 'type'):
                # Log non-text blocks for debugging
                block_type = getattr(content_block, 'type', 'unknown')
                typer.echo(f"[DEBUG] Found non-text content block type: {block_type}")
                # Log detailed info for tool results/usage
                if block_type == 'tool_use' or block_type == 'server_tool_use':
                    tool_name = getattr(content_block, 'name', 'unknown')
                    tool_input = getattr(content_block, 'input', {})
                    typer.echo(f"[DEBUG] Tool Use - Name: {tool_name}, Input: {tool_input}")
                elif block_type == 'tool_result' or block_type == 'web_search_tool_result':
                    tool_id = getattr(content_block, 'tool_use_id', 'unknown')
                    is_error = getattr(content_block, 'is_error', False)
                    # Truncate content for display
                    content = getattr(content_block, 'content', '')
                    content_preview = str(content)[:100] + "..." if len(str(content)) > 100 else str(content)
                    typer.echo(f"[DEBUG] Tool Result - ID: {tool_id}, Error: {is_error}, Content: {content_preview}")


        if text_parts:
            # Concatenate all text blocks
            full_text = "\n\n".join(text_parts)
            # Clean up newlines only if this was a search request
            if search:
                # 1. Collapse multiple newlines to single newline
                import re
                full_text = re.sub(r'\n+', '\n', full_text)
                # 2. Join lines unless the next line starts with a capital letter, bullet point, or markdown header/bold
                full_text = re.sub(r'\n(?![A-Z*#\-])', ' ', full_text)

            typer.echo(f"[DEBUG] Anthropic response length: {len(full_text)} characters, {len(full_text.split())} words")
            return _return_with_audit(full_text)
        else:
            # No text found - might be tool use only
            typer.echo("[WARNING] No text content found in Anthropic response")
            return _return_with_audit("Response contains tool usage but no text content found.")
