from typing import Any, Dict, Optional, Tuple

from letter_writer.personal_data_sections import get_extraction_vendor

from .call_context import bind_vendor_role_overrides, current_vendor_role_overrides
from .clients.base import BaseClient, ModelVendor

# import clients on demand
def get_client(vendor: ModelVendor, *, user_data: Optional[Dict[str, Any]] = None) -> BaseClient:
    if user_data is not None:
        bind_vendor_role_overrides(user_data)
    if vendor == ModelVendor.OPENAI:
        from .clients.openai import OpenAIClient
        client: BaseClient = OpenAIClient()
    elif vendor == ModelVendor.ANTHROPIC:
        from .clients.anthropic import ClaudeClient
        client = ClaudeClient()
    elif vendor == ModelVendor.GEMINI:
        from .clients.gemini import GeminiClient
        client = GeminiClient()
    elif vendor == ModelVendor.MISTRAL:
        from .clients.mistral import MistralClient
        client = MistralClient()
    elif vendor == ModelVendor.GROK:
        from .clients.grok import GrokClient
        client = GrokClient()
    elif vendor == ModelVendor.DEEPSEEK:
        from .clients.deepseeek import DeepSeekClient
        client = DeepSeekClient()
    elif vendor == ModelVendor.LOCAL:
        from .clients.local import LocalClient
        client = LocalClient()
    else:
        raise ValueError(f"Invalid vendor: {vendor}")
    client._vendor_key = vendor.value
    client._role_overrides = current_vendor_role_overrides().get(vendor.value, {})
    return client


def get_extraction_client(user_data: Optional[Dict[str, Any]] = None) -> Tuple[ModelVendor, BaseClient]:
    """Client for job extraction: the vendor chosen next to Extract, with that user's model overrides."""
    vendor = ModelVendor(get_extraction_vendor(user_data or {}))
    return vendor, get_client(vendor, user_data=user_data)