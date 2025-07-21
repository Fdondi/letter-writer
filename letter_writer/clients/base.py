from enum import Enum
from typing import List, Dict

class ModelVendor(Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    MISTRAL = "mistral"
    GROK = "grok"
    DEEPSEEK = "deepseek"

class ModelSize(Enum):
    TINY = "tiny"
    BASE = "base"
    MEDIUM = "medium"
    LARGE = "large"
    XLARGE = "xlarge"

class BaseClient:
    def call(self, model_size: ModelSize, system: str, messages: List[Dict]) -> str:
        raise NotImplementedError("Subclasses must implement this method")
