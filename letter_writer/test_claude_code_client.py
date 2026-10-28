"""ClaudeCodeClient with a stubbed CLI: no test here starts the real ``claude``."""
import json
import os
import sys
import time

import pytest

from letter_writer.client import get_client
from letter_writer.clients import claude_code
from letter_writer.clients.base import ModelRole, ModelVendor
from letter_writer.clients.claude_code import ClaudeCodeClient, ClaudeCodeError


@pytest.fixture(autouse=True)
def fake_binary(monkeypatch):
    monkeypatch.setattr(claude_code, "claude_binary", lambda: "/opt/fake/claude")


class Recorder:
    def __init__(self, result=None, code=0, stdout=None, stderr=""):
        self.calls = []
        self.result = result if result is not None else {"type": "result", "subtype": "success", "result": "hello"}
        self.code = code
        self.stdout = stdout
        self.stderr = stderr

    def __call__(self, argv, stdin_text, timeout_s, cwd, env):
        files = {name: open(os.path.join(cwd, name), encoding="utf-8").read() for name in os.listdir(cwd)}
        self.calls.append({"argv": argv, "stdin": stdin_text, "timeout": timeout_s, "cwd": cwd, "env": env, "files": files})
        out = self.stdout if self.stdout is not None else json.dumps(self.result)
        return self.code, out, self.stderr


def _flag(argv, name):
    return argv[argv.index(name) + 1]


def test_get_client_returns_claude_code_client():
    assert isinstance(get_client(ModelVendor.CLAUDE_CODE), ClaudeCodeClient)


def test_plain_call_has_no_tools_and_isolated_settings():
    rec = Recorder()
    client = ClaudeCodeClient(runner=rec)
    out = client.call(ModelRole.LETTER_DRAFT, "SYSTEM", ["first", "second"], system_cache_prefix="DOCS")
    assert out == "hello"
    argv = rec.calls[0]["argv"]
    assert argv[:2] == ["/opt/fake/claude", "-p"]
    assert _flag(argv, "--tools") == ""
    assert "--allowedTools" not in argv
    assert _flag(argv, "--output-format") == "json"
    assert _flag(argv, "--permission-mode") == "dontAsk"
    assert _flag(argv, "--setting-sources") == "project,local"
    assert "--strict-mcp-config" in argv and "--disable-slash-commands" in argv
    assert "--no-session-persistence" in argv
    assert "--bare" not in argv  # bare mode ignores the subscription login
    assert _flag(argv, "--model") == "claude-opus-5-5"
    assert _flag(argv, "--effort") == "medium"
    # The cached document block is merged into the replaced system prompt.
    assert _flag(argv, "--system-prompt") == "DOCS\n\nSYSTEM"
    assert "--json-schema" not in argv
    # User text only travels on stdin, never in argv.
    assert rec.calls[0]["stdin"] == "first\n\nsecond"
    assert "first" not in " ".join(argv)


def test_search_allows_only_web_tools():
    rec = Recorder()
    ClaudeCodeClient(runner=rec).call(ModelRole.COMPANY_RESEARCH, "s", ["q"], search=True)
    argv = rec.calls[0]["argv"]
    assert _flag(argv, "--tools") == "WebSearch,WebFetch"
    assert _flag(argv, "--allowedTools") == "WebSearch,WebFetch"


def test_schema_call_returns_structured_output_as_json():
    schema = {"type": "object", "properties": {"letter": {"type": "string"}}, "required": ["letter"]}
    rec = Recorder(result={"type": "result", "subtype": "success", "result": "", "structured_output": {"letter": "Dear"}})
    out = ClaudeCodeClient(runner=rec).call(
        ModelRole.LETTER_DRAFT,
        "s",
        ["u"],
        response_format={"type": "json_schema", "json_schema": {"name": "draft", "schema": schema}},
    )
    assert json.loads(out) == {"letter": "Dear"}
    assert json.loads(_flag(rec.calls[0]["argv"], "--json-schema")) == schema


def test_schema_call_without_structured_output_raises():
    rec = Recorder(result={"type": "result", "subtype": "success", "result": "plain text"})
    with pytest.raises(ClaudeCodeError, match="structured_output"):
        ClaudeCodeClient(runner=rec).call(
            ModelRole.FEEDBACK,
            "s",
            ["u"],
            response_format={"type": "json_schema", "json_schema": {"name": "x", "schema": {"type": "object"}}},
        )


@pytest.mark.parametrize(
    "result",
    [
        {"type": "result", "subtype": "error_max_budget_usd", "is_error": True},
        {"type": "result", "subtype": "error_during_execution", "is_error": True, "result": "boom"},
        {"type": "result", "subtype": "success", "is_error": True, "result": "Credit balance is too low"},
    ],
)
def test_cli_errors_raise(result):
    with pytest.raises(ClaudeCodeError):
        ClaudeCodeClient(runner=Recorder(result=result)).call(ModelRole.FEEDBACK, "s", ["u"])


def test_nonzero_exit_without_output_raises_with_stderr():
    rec = Recorder(code=1, stdout="", stderr="Not logged in")
    with pytest.raises(ClaudeCodeError, match="Not logged in"):
        ClaudeCodeClient(runner=rec).call(ModelRole.FEEDBACK, "s", ["u"])


def test_garbage_output_raises():
    with pytest.raises(ClaudeCodeError, match="no JSON"):
        ClaudeCodeClient(runner=Recorder(stdout="not json at all")).call(ModelRole.FEEDBACK, "s", ["u"])


def test_missing_cli_raises(monkeypatch):
    monkeypatch.setattr(claude_code, "claude_binary", lambda: None)
    with pytest.raises(ClaudeCodeError, match="not installed"):
        ClaudeCodeClient(runner=Recorder()).call(ModelRole.FEEDBACK, "s", ["u"])


def test_large_system_prompt_goes_through_a_file():
    rec = Recorder()
    big = "x" * (claude_code._MAX_INLINE_SYSTEM_CHARS + 10)
    ClaudeCodeClient(runner=rec).call(ModelRole.FEEDBACK, big, ["u"])
    call = rec.calls[0]
    assert "--system-prompt" not in call["argv"]
    path = _flag(call["argv"], "--system-prompt-file")
    assert os.path.dirname(path) == call["cwd"]
    assert call["files"]["system_prompt.txt"] == big


def test_cost_is_a_subscription_estimate_not_api_spend():
    before = claude_code.subscription_spend_usd()
    rec = Recorder(
        result={
            "type": "result",
            "subtype": "success",
            "result": "ok",
            "total_cost_usd": 0.25,
            "usage": {"input_tokens": 100, "cache_read_input_tokens": 50, "output_tokens": 20},
        }
    )
    client = ClaudeCodeClient(runner=rec)
    client.call(ModelRole.FEEDBACK, "s", ["u"])
    assert client.total_cost == 0.0
    assert client.total_input_tokens == 150
    assert client.total_output_tokens == 20
    assert client.total_subscription_estimate_usd == pytest.approx(0.25)
    assert claude_code.subscription_spend_usd() - before == pytest.approx(0.25)


def test_runs_in_an_empty_temp_dir_without_api_credentials(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "parent")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/home/me/.claude")
    rec = Recorder()
    ClaudeCodeClient(runner=rec).call(ModelRole.FEEDBACK, "s", ["u"])
    call = rec.calls[0]
    assert call["files"] == {}
    assert not os.path.exists(call["cwd"])  # removed after the call
    env = call["env"]
    assert "ANTHROPIC_API_KEY" not in env and "CLAUDECODE" not in env and "CLAUDE_CODE_SESSION_ID" not in env
    assert env["CLAUDE_CONFIG_DIR"] == "/home/me/.claude"


def test_model_override_string_with_effort():
    rec = Recorder()
    ClaudeCodeClient(runner=rec).call("claude-sonnet-5-5@high", "s", ["u"])
    argv = rec.calls[0]["argv"]
    assert _flag(argv, "--model") == "claude-sonnet-5-5"
    assert _flag(argv, "--effort") == "high"


def test_timeout_sends_sigint_first(tmp_path):
    marker = tmp_path / "got_sigint"
    script = (
        "import signal, sys, time\n"
        f"def h(*a):\n    open({str(marker)!r}, 'w').write('int'); sys.exit(130)\n"
        "signal.signal(signal.SIGINT, h)\n"
        "print('ready', flush=True)\n"
        "time.sleep(30)\n"
    )
    started = time.monotonic()
    with pytest.raises(ClaudeCodeError, match="timed out"):
        claude_code.run_cli([sys.executable, "-c", script], "", 1.0, str(tmp_path), dict(os.environ))
    assert marker.read_text() == "int"
    assert time.monotonic() - started < 15
