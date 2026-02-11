from .base import BaseClient, ModelSize
from anthropic import Anthropic
from typing import List, Dict
import typer
from langsmith import traceable

class ClaudeClient(BaseClient):
    def __init__(self):
        super().__init__()
        self.client = Anthropic()

    def _format_messages(self, user_messages: List[str]) -> List[Dict]:
        return [{"role": "user", "content": [{"type": "text", "text": message}]} for message in user_messages]

    @traceable(run_type="llm", name="Anthropic.call")
    def call(self, model_size: ModelSize | str, system: str, user_messages: List[str], search: bool = False) -> str:
        messages = self._format_messages(user_messages)
        if isinstance(model_size, str):
            model = model_size
        else:
            model = self.get_model_for_size(model_size)
        typer.echo(f"[INFO] using Anthropic model {model}" + (" with search" if search else ""))
        tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}] if search else []
        # Use 2048 for search, 8000 for everything else (letters, comments, etc.)
        max_tokens = 2048 if search else 8000
        
        # Build conversation history
        conversation_messages = messages.copy()
        total_input_tokens = 0
        total_output_tokens = 0
        
        # Initial request
        response = self.client.messages.create(
            model=model,
            system=system,
            messages=conversation_messages,
            tools=tools,
            max_tokens=max_tokens,
        )
        
        # Track usage from first response
        if response.usage:
            total_input_tokens += response.usage.input_tokens
            total_output_tokens += response.usage.output_tokens
        
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
                    
                    # Continue the conversation
                    continuation_response = self.client.messages.create(
                        model=model,
                        system=system,
                        messages=conversation_messages,
                        max_tokens=remaining_tokens,
                    )
                    
                    # Track usage from continuation
                    if continuation_response.usage:
                        total_input_tokens += continuation_response.usage.input_tokens
                        total_output_tokens += continuation_response.usage.output_tokens
                    
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
                search_queries=1 if search else 0
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
            return full_text
            
        # Handle different response content types if we didn't accumulate text
        if not response.content:
            return ""
            
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
            return full_text
        else:
            # No text found - might be tool use only
            typer.echo("[WARNING] No text content found in Anthropic response")
            return "Response contains tool usage but no text content found."
