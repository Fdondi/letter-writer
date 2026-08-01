"""Tests for shared prompt-cache padding and block merging."""

from letter_writer.clients.prompt_cache import (
    combine_cache_parts,
    estimate_tokens,
    merge_cache_prefixes,
    pad_cache_block,
)


def test_combine_cache_parts_skips_empty():
    assert combine_cache_parts("a", "", "b") == "a\n\nb"


def test_merge_cache_prefixes_combines_into_system_side():
    sys_p, usr_p = merge_cache_prefixes("system docs", "user docs")
    assert usr_p is None
    assert "system docs" in sys_p
    assert "user docs" in sys_p


def test_pad_cache_block_skips_when_2x_budget_too_small():
    short = "x" * 100
    padded, added = pad_cache_block(short, vendor="openai", model="gpt-5.6-terra")
    assert added == 0
    assert padded == short
    assert "[Prompt-cache padding" not in padded


def test_pad_cache_block_adds_when_within_2x_budget():
    body = "word " * 500
    est = estimate_tokens(body)
    padded, added = pad_cache_block(body, vendor="openai", model="gpt-5.6-terra")
    assert added > 0
    assert "[Prompt-cache padding" in padded
    assert estimate_tokens(padded) <= est * 2 + 50


def test_run_cache_grouped_tasks_sequences_shared_prefix():
    from letter_writer.clients.prompt_cache import run_cache_grouped_tasks

    calls: list[str] = []
    shared = "same-prefix"
    run_cache_grouped_tasks(
        [
            ("a", shared, lambda: calls.append("a")),
            ("b", shared, lambda: calls.append("b")),
            ("c", "other-prefix", lambda: calls.append("c")),
        ],
        max_parallel_groups=3,
    )
    assert calls.count("a") == 1 and calls.count("b") == 1 and calls.count("c") == 1
    assert (calls.index("a") < calls.index("b")) or (calls.index("b") < calls.index("a"))


def test_feedback_contexts_share_cache_keys():
    from letter_writer.clients.prompt_cache import cache_key_for_prefix
    from letter_writer.generation import _company_job_letter_context, _cv_letter_context

    company_ctx = _company_job_letter_context(
        company_report="co", job_text="job", letter="letter"
    )
    k1 = cache_key_for_prefix(company_ctx, fallback="x")
    k2 = cache_key_for_prefix(company_ctx, fallback="y")
    assert k1 == k2

    cv_ctx = _cv_letter_context(cv_text="cv", letter="letter")
    assert cache_key_for_prefix(cv_ctx, fallback="a") == cache_key_for_prefix(
        cv_ctx, fallback="b"
    )
    assert cache_key_for_prefix(cv_ctx, fallback="a") != k1


def test_pad_cache_block_noop_when_already_large():
    big = "word " * 3000
    padded, added = pad_cache_block(big, vendor="openai", model="gpt-5.6-terra")
    assert added == 0
    assert padded == big.strip()
