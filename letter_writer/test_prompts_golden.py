"""Shared prompt templates must render exactly the golden output the Android app also checks."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from letter_writer import prompts

ROOT = Path(__file__).resolve().parents[1]


def test_golden_prompts_match():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "prompts" / "capture_golden.py"), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={"LANGSMITH_TRACING": "false", "PATH": ""},
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_golden_costs_match():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "costs" / "capture_cost_golden.py"), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={"LANGSMITH_TRACING": "false", "PATH": ""},
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_render_requires_every_placeholder():
    with pytest.raises(KeyError):
        prompts.render("rewrite/plan_block.txt")


def test_render_does_not_expand_placeholders_inside_values():
    out = prompts.fill("a {{x}} b", x="{{y}}")
    assert out == "a {{y}} b"


def test_json_assets_parse():
    for path in prompts.PROMPTS_DIR.rglob("*.json"):
        json.loads(path.read_text(encoding="utf-8"))
