import json
import logging
import sys
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def merge_system_cache_prefix_into_system(
    system: str,
    system_cache_prefix: Optional[str],
) -> str:
    """Combine optional cached context with the task system prompt.

    ``accuracy_check`` and related paths pass CV/letter (or company/job/letter)
    via ``system_cache_prefix`` so Anthropic can cache that block separately.
    Vendors that do not implement split system blocks must merge this prefix
    into ``system`` or the model never sees the documents and may invent
    critiques.
    """
    prefix = (system_cache_prefix or "").strip()
    if not prefix:
        return system
    body = system or ""
    return f"{prefix}\n\n{body}" if body else prefix


def _parse_price_per_million_usd(val: Any) -> float:
    """Normalize per-1M-token USD price from client JSON (number or ``{low, high}`` range).

    Matches ``cost_tracker._parse_price_field`` so tiered entries in ``*.json`` do not
    break ``track_cost`` (e.g. OpenAI ``gpt-5.5`` input/output objects).
    """
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, dict):
        return float(val.get("low", val.get("high", 0.0)) or 0.0)
    return 0.0


class ModelVendor(Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    MISTRAL = "mistral"
    GROK = "grok"
    DEEPSEEK = "deepseek"
    LOCAL = "local"


class ModelRole(Enum):
    """Named LLM roles — each vendor maps roles to a concrete model in ``*.json``."""

    EXTRACTION = "extraction"
    FEEDBACK = "feedback"
    FEEDBACK_REVIEW = "feedback_review"
    FEEDBACK_CONTEXT = "feedback_context"
    RAG_RANKER = "rag_ranker"
    COMPANY_RESEARCH = "company_research"
    LETTER_PLAN = "letter_plan"
    LETTER_DRAFT = "letter_draft"
    LETTER_REFINE = "letter_refine"
    AGENTIC = "agentic"
    AUTOCOMPLETE = "autocomplete"
    AUTOCOMPLETE_PLAN = "autocomplete_plan"
    TRANSLATION = "translation"


class BaseClient:
    def __init__(self) -> None:
        self.total_cost = 0.0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cached_tokens = 0
        self.total_search_queries = 0
        self._costs_cache: dict | None = None
        self._last_mtime: float = 0.0

    def _load_cost_config(self) -> dict:
        """Load `*.json` config and hot-reload if the file changed on disk."""
        try:
            module_path = sys.modules[self.__module__].__file__
            if not module_path:
                return {}
            config_path = Path(module_path).with_suffix(".json")
            if not config_path.exists():
                return {}

            mtime = config_path.stat().st_mtime
            if self._costs_cache is not None and mtime <= self._last_mtime:
                return self._costs_cache

            # File is new or changed, reload it
            self._costs_cache = json.loads(config_path.read_text(encoding="utf-8"))
            self._last_mtime = mtime
            # logger.info("Reloaded config for %s", self.__class__.__name__)
        except Exception as e:
            logger.warning("Failed to load cost config for %s: %s", self.__class__.__name__, e)
            if self._costs_cache is None:
                self._costs_cache = {}
        return self._costs_cache or {}

    @property
    def config(self) -> dict:
        """Access the current (hot-reloaded) configuration."""
        return self._load_cost_config()

    def get_model_for_role(self, model_role: ModelRole) -> str:
        """Resolve model name from role using hot-reloaded config.

        Supports plain-string entries and dict entries with extra vendor keys::

            "feedback": "gpt-5-mini"
            "feedback": {"model": "gpt-5-mini", "reasoning_effort": "low"}
        """
        roles = self.config.get("roles", {})
        entry = roles.get(model_role.value)
        if not entry:
            raise ValueError(f"Model role '{model_role.value}' not defined in {self.__class__.__name__} config")
        if isinstance(entry, dict):
            model_name = entry.get("model")
            if not model_name:
                raise ValueError(f"Model role '{model_role.value}' missing 'model' key in {self.__class__.__name__} config")
            return model_name
        return entry

    def get_thinking_config(self, model_role: ModelRole) -> dict:
        """Return per-role thinking/reasoning params (vendor-specific keys).

        Returns an empty dict for plain-string role entries or entries with no
        extra keys beyond ``model``.  Each vendor client checks for its own key::

            OpenAI:    config.get("reasoning_effort")   # "none"|"low"|"medium"|"high"
            Anthropic: config.get("thinking")           # False | True
            Anthropic: config.get("effort") or config.get("thinking_effort")
                # optional: "low"|"medium"|"high"|"max"|"xhigh" (adaptive thinking only)
            Gemini:    config.get("thinking_level")     # None | "Low" | "Medium" | "High"
        """
        roles = self.config.get("roles", {})
        entry = roles.get(model_role.value)
        if isinstance(entry, dict):
            return {k: v for k, v in entry.items() if k != "model"}
        return {}

    def get_model_cost(self, model_name: str) -> dict:
        """Retrieve cost dict for a model from the client's JSON config.

        Expected JSON format (non-Gemini):
            {
              "defaults": { "search": 10.0 },
              "models": {
                "model-a": {"input": 1.0, "output": 5.0},
                "model-b": {"input": 3.0, "output": 15.0, "search": 15.0},
                "model-c": {"input": {"low": 1.0, "high": 2.0}, "output": {"low": 5.0, "high": 8.0}}
              }
            }

        ``input`` / ``output`` may be tiered objects ``{"low", "high"}``; the **low**
        tier is used for internal cost estimates (same rule as ``cost_tracker``).

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
            return {"input": 0.0, "output": 0.0, "search": default_search, "input_cached_mult": 0.5}

        model_cfg = models_cfg.get(model_name, {})
        if not isinstance(model_cfg, dict):
            return {"input": 0.0, "output": 0.0, "search": default_search, "input_cached_mult": 0.5}

        defaults = cfg.get("defaults", {}) or {}
        if not isinstance(defaults, dict):
            defaults = {}
        cached_mult = float(model_cfg.get("input_cached_mult", defaults.get("input_cached_mult", 0.5)) or 0.5)

        search_raw = model_cfg.get("search", default_search)
        search_price = _parse_price_per_million_usd(search_raw) if search_raw is not None else default_search

        return {
            "input": _parse_price_per_million_usd(model_cfg.get("input", 0.0)),
            "output": _parse_price_per_million_usd(model_cfg.get("output", 0.0)),
            "search": float(search_price or 0.0),
            "input_cached_mult": cached_mult,
        }

    def track_cost(
        self,
        model_name: str,
        input_tokens: int,
        output_tokens: int,
        search_queries: int = 0,
        cached_tokens: int = 0,
    ):
        """Calculate and accumulate cost and token counts for a request.

        When cached_tokens > 0, the cached portion is charged at input_cached_mult (default 0.5)
        of the normal input price (e.g. OpenAI prompt cache discount).
        """
        costs = self.get_model_cost(model_name)

        # Input: uncached full price, cached at discount
        uncached = max(0, input_tokens - cached_tokens)
        mult = costs.get("input_cached_mult", 0.5)
        input_cost = (uncached / 1_000_000) * costs["input"] + (
            (cached_tokens / 1_000_000) * costs["input"] * mult
        )
        output_cost = (output_tokens / 1_000_000) * costs["output"]
        search_cost = (search_queries / 1_000) * costs["search"]

        self.total_cost += input_cost + output_cost + search_cost
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cached_tokens += cached_tokens
        self.total_search_queries += search_queries

    def _record_llm_io(
        self,
        *,
        model: str,
        system: str,
        user_messages: List[str],
        search: bool,
        response_format: Optional[Dict[str, Any]],
        output_text: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Best-effort request-scoped audit logging for all LLM calls."""
        try:
            from ..session_store import append_application_event

            event: Dict[str, Any] = {
                "type": "llm_io",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "vendor": self.__class__.__name__.replace("Client", "").lower(),
                "model": model,
                "search": bool(search),
                "input": {
                    "system": system,
                    "user_messages": list(user_messages or []),
                    "response_format": response_format,
                },
            }
            if error is not None:
                event["output"] = {"error": str(error)}
            else:
                event["output"] = {"text": output_text or ""}
            append_application_event(event)
        except Exception:
            # Audit logging must never break generation paths.
            logger.debug("failed to append llm_io audit event", exc_info=True)

    def call(
        self,
        model_role: ModelRole | str,
        system: str,
        user_messages: List[str],
        search: bool = False,
        response_format: Optional[Dict[str, Any]] = None,
        cache_prefix: Optional[str] = None,
        system_cache_prefix: Optional[str] = None,
    ) -> str:
        """Execute an LLM call.

        ``cache_prefix`` — large context block prepended as a cached content
        block inside the first *user* message (repeated-observation pattern,
        e.g. feedback_review stage 2).

        ``system_cache_prefix`` — large context block prepended as the first
        *system* block with cache_control.  Enables cross-call caching when
        two calls share the same document set but differ in their instructions
        (e.g. precision_check vs company_fit_check).  Only Anthropic implements
        split cached system blocks.  Other clients must merge this into
        ``system`` via ``merge_system_cache_prefix_into_system`` (see OpenAI,
        Gemini, etc.).
        """
        raise NotImplementedError("Subclasses must implement this method")
