from .base import BaseClient, ModelSize
from anthropic import Anthropic
from typing import List, Dict
import typer

class ClaudeClient(BaseClient):
    def __init__(self):
        super().__init__()
        self.client = Anthropic()

    def _format_messages(self, user_messages: List[str]) -> List[Dict]:
        return [{"role": "user", "content": [{"type": "text", "text": message}]} for message in user_messages]

    def call(self, model_size: ModelSize, system: str, user_messages: List[str], search: bool = False) -> str:
        messages = self._format_messages(user_messages)
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
                        "content": [{"type": "text", "text": "Please provide a comprehensive synthesis of the search results in your response."}]
                    })
                    
                    # Continue the conversation
                    continuation_response = self.client.messages.create(
                        model=model,
                        system=system,
                        messages=conversation_messages,
                        max_tokens=max_tokens,
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
                    
                    response = continuation_response
        
        # Track total cost
        if total_input_tokens > 0 or total_output_tokens > 0:
            self.track_cost(
                model,
                total_input_tokens,
                total_output_tokens,
                search_queries=1 if search else 0
            )
        
        # Handle different response content types
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
        
        if text_parts:
            # Concatenate all text blocks
            full_text = "\n\n".join(text_parts)
            typer.echo(f"[DEBUG] Anthropic response length: {len(full_text)} characters, {len(full_text.split())} words")
            return full_text
        else:
            # No text found - might be tool use only
            typer.echo("[WARNING] No text content found in Anthropic response")
            return "Response contains tool usage but no text content found."
