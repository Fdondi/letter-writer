import json
import sys
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List


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
    def __init__(self):
        self.total_cost = 0.0
        self._costs_cache: dict | None = None

    def _load_cost_config(self) -> dict:
        """Load `*.json` config that sits next to the concrete client module."""
        if self._costs_cache is not None:
            return self._costs_cache

        try:
            module_path = sys.modules[self.__module__].__file__
            config_path = Path(module_path).with_suffix(".json")
            if config_path.exists():
                self._costs_cache = json.loads(config_path.read_text(encoding="utf-8"))
            else:
                self._costs_cache = {}
        except Exception as e:
            print(f"[WARN] Failed to load cost config for {self.__class__.__name__}: {e}")
            self._costs_cache = {}
        return self._costs_cache

    def get_model_cost(self, model_name: str) -> dict:
        """Retrieve cost dict for a model from the client's JSON config.

        Expected JSON format (non-Gemini):
            {
              "defaults": { "search": 10.0 },
              "models": {
                "model-a": {"input": 1.0, "output": 5.0},
                "model-b": {"input": 3.0, "output": 15.0, "search": 15.0}
              }
            }

        Search pricing resolution:
        - model override: models[model_name].search (if present)
        - otherwise: defaults.search
        """
        cfg: Any = self._load_cost_config()
        if not isinstance(cfg, dict):
            return {"input": 0.0, "output": 0.0, "search": 0.0}

        defaults = cfg.get("defaults", {})
        default_search = float((defaults.get("search", 0.0) if isinstance(defaults, dict) else 0.0) or 0.0)

        models_cfg = cfg.get("models", {})
        if not isinstance(models_cfg, dict):
            return {"input": 0.0, "output": 0.0, "search": default_search}

        model_cfg = models_cfg.get(model_name, {})
        if not isinstance(model_cfg, dict):
            return {"input": 0.0, "output": 0.0, "search": default_search}

        return {
            "input": float(model_cfg.get("input", 0.0) or 0.0),
            "output": float(model_cfg.get("output", 0.0) or 0.0),
            "search": float(model_cfg.get("search", default_search) or 0.0),
        }

    def track_cost(self, model_name: str, input_tokens: int, output_tokens: int, search_queries: int = 0):
        """Calculate and accumulate cost for a request."""
        costs = self.get_model_cost(model_name)

        # Costs are per 1M tokens
        input_cost = (input_tokens / 1_000_000) * costs["input"]
        output_cost = (output_tokens / 1_000_000) * costs["output"]

        # Search costs are per 1000 queries
        search_cost = (search_queries / 1_000) * costs["search"]

        self.total_cost += input_cost + output_cost + search_cost

    def call(self, model_size: ModelSize, system: str, messages: List[Dict]) -> str:
        raise NotImplementedError("Subclasses must implement this method")
