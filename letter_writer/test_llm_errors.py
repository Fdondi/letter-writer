"""Tests for LLM credit/quota error classification (non-retryable)."""

from letter_writer.clients.llm_errors import (
    InsufficientCreditsError,
    format_insufficient_credits_message,
    is_insufficient_credits_error,
    response_indicates_insufficient_credits,
    reraise_if_insufficient_credits,
)


class _FakeRateLimitError(Exception):
    def __init__(self, body, code=None):
        self.body = body
        self.code = code
        super().__init__(f"Error code: 429 - {body}")


def test_detects_openai_credit_balance_exhausted():
    body = {
        "error": {
            "message": "You have no credits remaining. Add credits to continue using the API.",
            "type": "insufficient_quota",
            "param": None,
            "code": "credit_balance_exhausted",
        }
    }
    exc = _FakeRateLimitError(body, code="credit_balance_exhausted")
    assert is_insufficient_credits_error(exc)
    assert response_indicates_insufficient_credits(429, body)


def test_detects_insufficient_quota_type():
    body = {
        "error": {
            "message": "You exceeded your current quota, please check your plan and billing details.",
            "type": "insufficient_quota",
            "code": "insufficient_quota",
        }
    }
    assert response_indicates_insufficient_credits(429, body)
    assert is_insufficient_credits_error(_FakeRateLimitError(body))


def test_does_not_flag_transient_rate_limit():
    body = {
        "error": {
            "message": "Rate limit reached for requests. Please try again later.",
            "type": "requests",
            "code": "rate_limit_exceeded",
        }
    }
    assert not response_indicates_insufficient_credits(429, body)
    assert not is_insufficient_credits_error(_FakeRateLimitError(body, code="rate_limit_exceeded"))


def test_reraise_converts_to_insufficient_credits_error():
    body = {
        "error": {
            "message": "You have no credits remaining.",
            "type": "insufficient_quota",
            "code": "credit_balance_exhausted",
        }
    }
    exc = _FakeRateLimitError(body, code="credit_balance_exhausted")
    try:
        reraise_if_insufficient_credits(exc, vendor="openai")
        assert False, "expected InsufficientCreditsError"
    except InsufficientCreditsError as mapped:
        assert "Not enough API credits for openai" in str(mapped)
        assert "Retry" in str(mapped)


def test_format_message_for_plain_exception():
    msg = format_insufficient_credits_message(
        Exception("You have no credits remaining."),
        vendor="openai",
    )
    assert msg.startswith("Not enough API credits for openai")
    assert "click Retry" in msg
