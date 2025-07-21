from .clients.base import BaseClient, ModelVendor

# import clients on demand
def get_client(vendor: ModelVendor) -> BaseClient:
    if vendor == ModelVendor.OPENAI:
        from .clients.openai import OpenAIClient
        return OpenAIClient()
    elif vendor == ModelVendor.ANTHROPIC:
        from .clients.anthropic import ClaudeClient
        return ClaudeClient()
    elif vendor == ModelVendor.GEMINI:
        from .clients.gemini import GeminiClient
        return GeminiClient()
    elif vendor == ModelVendor.MISTRAL:
        from .clients.mistral import MistralClient
        return MistralClient()
    elif vendor == ModelVendor.GROK:
        from .clients.grok import GrokClient
        return GrokClient()
    elif vendor == ModelVendor.DEEPSEEK:
        from .clients.deepseeek import DeepSeekClient
        return DeepSeekClient()
    else:
        raise ValueError(f"Invalid vendor: {vendor}")