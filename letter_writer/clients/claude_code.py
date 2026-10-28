"""Claude Code CLI (``claude -p``) as one more vendor, billed to the host user's subscription.

Only the opportunity batch (``python -m letter_writer.batch``) uses it: the CLI and its login
live on the host, not in the backend container. Every call is tool-less, except ``search=True``,
which allows only WebSearch and WebFetch. User settings (hooks, plugins), MCP servers, skills
and project files are kept out by running in an empty temp directory with
``--setting-sources project,local --strict-mcp-config --disable-slash-commands``.

Spend is not API spend: the client's ``total_cost`` stays 0 (prices in ``claude_code.json`` are 0),
and ``total_cost_usd`` from the CLI accumulates in :func:`subscription_spend_usd` as an estimate.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .base import BaseClient, ModelRole, merge_system_cache_prefix_into_system
from .model_override import apply_model_override_thinking

logger = logging.getLogger(__name__)

SEARCH_TOOLS = "WebSearch,WebFetch"
# Linux caps one argv string at 128 KiB; longer system prompts go through a file.
_MAX_INLINE_SYSTEM_CHARS = 100_000


class ClaudeCodeError(RuntimeError):
    """``claude -p`` failed, timed out, or returned no usable output."""


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


TIMEOUT_S = _env_float("LW_CLAUDE_CODE_TIMEOUT_S", 300.0)
MAX_BUDGET_USD = _env_float("LW_CLAUDE_CODE_MAX_BUDGET_USD", 2.0)
_SEMAPHORE = threading.BoundedSemaphore(max(1, int(_env_float("LW_CLAUDE_CODE_CONCURRENCY", 2))))

_spend_lock = threading.Lock()
_spend_usd = 0.0


def subscription_spend_usd() -> float:
    """Estimated subscription spend (CLI ``total_cost_usd``) of all calls in this process."""
    with _spend_lock:
        return _spend_usd


def _add_spend(amount: float) -> None:
    global _spend_usd
    with _spend_lock:
        _spend_usd += amount


def claude_binary() -> Optional[str]:
    """Path of the ``claude`` CLI (``LW_CLAUDE_BIN`` overrides), or None when it is not installed."""
    return shutil.which(os.environ.get("LW_CLAUDE_BIN") or "claude")


def subprocess_env(base: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Environment for the CLI: no API credentials (they would bill the API instead of the
    subscription) and none of the parent Claude Code session's variables (the routine runs
    inside one)."""
    env = dict(os.environ if base is None else base)
    for key in list(env):
        if key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "CLAUDECODE"):
            env.pop(key)
        elif key.startswith("CLAUDE_CODE_") or key in ("CLAUDE_PID", "CLAUDE_EFFORT", "CLAUDE_JOB_DIR"):
            env.pop(key)
    return env


def schema_from_response_format(response_format: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The JSON Schema inside an OpenAI-style ``{"type": "json_schema", "json_schema": {"schema": …}}``."""
    if not isinstance(response_format, dict):
        return None
    schema = (response_format.get("json_schema") or {}).get("schema")
    return schema if isinstance(schema, dict) and schema else None


def build_argv(
    *,
    binary: str,
    model: str,
    system_prompt: str,
    system_prompt_file: Optional[str],
    schema: Optional[Dict[str, Any]],
    search: bool,
    effort: Optional[str],
    max_budget_usd: float,
) -> List[str]:
    argv = [
        binary,
        "-p",
        "--output-format", "json",
        "--model", model,
        "--permission-mode", "dontAsk",
        "--setting-sources", "project,local",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--max-budget-usd", f"{max_budget_usd:.2f}",
    ]
    if system_prompt_file:
        argv += ["--system-prompt-file", system_prompt_file]
    else:
        argv += ["--system-prompt", system_prompt]
    if search:
        argv += ["--tools", SEARCH_TOOLS, "--allowedTools", SEARCH_TOOLS]
    else:
        argv += ["--tools", ""]
    if effort:
        argv += ["--effort", effort]
    if schema is not None:
        argv += ["--json-schema", json.dumps(schema, separators=(",", ":"))]
    return argv


Runner = Callable[[List[str], str, float, str, Dict[str, str]], Tuple[int, str, str]]


def run_cli(argv: List[str], stdin_text: str, timeout_s: float, cwd: str, env: Dict[str, str]) -> Tuple[int, str, str]:
    """Run the CLI; on timeout send SIGINT (lets it stop cleanly), then kill if it lingers."""
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
        env=env,
    )
    try:
        out, err = proc.communicate(stdin_text, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        proc.send_signal(signal.SIGINT)
        try:
            proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
        raise ClaudeCodeError(f"claude -p timed out after {timeout_s:.0f}s")
    return proc.returncode, out, err


def parse_result(stdout: str, *, structured: bool) -> Tuple[str, Dict[str, Any]]:
    """Text of a ``--output-format json`` result (the structured output as JSON when a schema was
    passed) and the whole result object. Raises :class:`ClaudeCodeError` on any failure."""
    raw = (stdout or "").strip()
    result: Any = None
    for candidate in (raw, raw.splitlines()[-1] if raw else ""):
        try:
            result = json.loads(candidate)
            break
        except json.JSONDecodeError:
            continue
    if not isinstance(result, dict):
        raise ClaudeCodeError(f"claude -p printed no JSON result: {stdout[:300]!r}")
    if result.get("is_error") or result.get("subtype") not in (None, "success"):
        detail = result.get("result") or result.get("subtype") or "unknown error"
        raise ClaudeCodeError(f"claude -p failed ({result.get('subtype')}): {str(detail)[:500]}")
    if structured:
        if "structured_output" not in result or result["structured_output"] is None:
            raise ClaudeCodeError("claude -p returned no structured_output for a JSON-schema call")
        return json.dumps(result["structured_output"], ensure_ascii=False), result
    text = result.get("result")
    if not isinstance(text, str):
        raise ClaudeCodeError("claude -p returned no result text")
    return text, result


class ClaudeCodeClient(BaseClient):
    def __init__(self, runner: Optional[Runner] = None) -> None:
        super().__init__()
        self._runner: Runner = runner or run_cli
        self.total_subscription_estimate_usd = 0.0

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
        _ = prompt_cache_key  # no prompt caching through the CLI
        model_role = self.resolve_effective_model_role(model_role)
        if isinstance(model_role, str):
            model, thinking_cfg = apply_model_override_thinking("claude_code", model_role)
        else:
            model = self.get_model_for_role(model_role)
            thinking_cfg = self.get_thinking_config(model_role)
        effort = thinking_cfg.get("effort") or thinking_cfg.get("thinking_effort")

        system_prompt = merge_system_cache_prefix_into_system(system, system_cache_prefix)
        parts = [p for p in [cache_prefix or ""] + list(user_messages or []) if p]
        prompt = "\n\n".join(parts)
        schema = schema_from_response_format(response_format)
        binary = claude_binary()
        if not binary:
            raise ClaudeCodeError("The claude CLI is not installed on this machine (set LW_CLAUDE_BIN or install Claude Code).")

        with tempfile.TemporaryDirectory(prefix="lw-claude-code-") as cwd:
            prompt_file = None
            if len(system_prompt) > _MAX_INLINE_SYSTEM_CHARS:
                prompt_file = str(Path(cwd, "system_prompt.txt"))
                Path(prompt_file).write_text(system_prompt, encoding="utf-8")
            argv = build_argv(
                binary=binary,
                model=model,
                system_prompt=system_prompt,
                system_prompt_file=prompt_file,
                schema=schema,
                search=search,
                effort=str(effort) if effort else None,
                max_budget_usd=MAX_BUDGET_USD,
            )
            logger.info("[claude_code] model=%s search=%s schema=%s", model, search, schema is not None)
            try:
                with _SEMAPHORE:
                    code, out, err = self._runner(argv, prompt, TIMEOUT_S, cwd, subprocess_env())
                if code != 0 and not (out or "").strip():
                    raise ClaudeCodeError(f"claude -p exited with {code}: {(err or '').strip()[:500]}")
                text, result = parse_result(out, structured=schema is not None)
            except Exception as exc:
                self._record_llm_io(
                    model=model,
                    system=system_prompt,
                    user_messages=user_messages,
                    search=search,
                    response_format=response_format,
                    error=str(exc),
                )
                raise

        usage = result.get("usage") or {}
        in_tokens = int(usage.get("input_tokens") or 0) + int(usage.get("cache_read_input_tokens") or 0) + int(
            usage.get("cache_creation_input_tokens") or 0
        )
        self.track_cost(
            model,
            in_tokens,
            int(usage.get("output_tokens") or 0),
            search_queries=0,
            cached_tokens=int(usage.get("cache_read_input_tokens") or 0),
        )
        estimate = float(result.get("total_cost_usd") or 0.0)
        self.total_subscription_estimate_usd += estimate
        _add_spend(estimate)
        self._record_llm_io(
            model=model,
            system=system_prompt,
            user_messages=user_messages,
            search=search,
            response_format=response_format,
            output_text=text,
        )
        return text
