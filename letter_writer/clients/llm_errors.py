"""Classify LLM provider errors that must not be auto-retried."""

from __future__ import annotations

from typing import Any, Optional

# Provider error codes that mean billing/quota exhaustion (not transient rate limits).
_INSUFFICIENT_CREDIT_CODES = frozenset(
    {
        "insufficient_quota",
        "credit_balance_exhausted",
        "billing_not_active",
    }
)

_INSUFFICIENT_CREDIT_TYPES = frozenset(
    {
        "insufficient_quota",
    }
)

# Substrings in provider messages (lowercase). Prefer codes when available.
_INSUFFICIENT_CREDIT_MARKERS = (
    "no credits remaining",
    "insufficient_quota",
    "credit_balance_exhausted",
    "credit balance is too low",
    "exceeded your current quota",
    "billing hard limit has been reached",
    "insufficient credits",
    "not enough credits",
)


class InsufficientCreditsError(Exception):
    """Provider rejected the call because the account has no usable credits/quota.

    Do not auto-retry: the user must add credits (or switch keys) and retry manually.
    """

    def __init__(
        self,
        message: str,
        *,
        vendor: Optional[str] = None,
        provider_code: Optional[str] = None,
        provider_type: Optional[str] = None,
    ) -> None:
        self.vendor = vendor
        self.provider_code = provider_code
        self.provider_type = provider_type
        super().__init__(message)


def _attr_or_none(obj: Any, name: str) -> Any:
    try:
        return getattr(obj, name, None)
    except Exception:
        return None


def _error_body_fields(exc: BaseException) -> tuple[Optional[str], Optional[str], str]:
    """Return (code, type, message) from a provider exception when possible."""
    code: Optional[str] = None
    typ: Optional[str] = None
    message = str(exc) if exc else ""

    body = _attr_or_none(exc, "body")
    if isinstance(body, dict):
        err = body.get("error") if isinstance(body.get("error"), dict) else body
        if isinstance(err, dict):
            raw_code = err.get("code")
            raw_type = err.get("type")
            raw_msg = err.get("message")
            if raw_code is not None:
                code = str(raw_code)
            if raw_type is not None:
                typ = str(raw_type)
            if raw_msg:
                message = str(raw_msg)

    # openai.APIError exposes .code; some SDKs nest under .error
    if code is None:
        raw_code = _attr_or_none(exc, "code")
        if raw_code is not None:
            code = str(raw_code)
    err_obj = _attr_or_none(exc, "error")
    if isinstance(err_obj, dict):
        if code is None and err_obj.get("code") is not None:
            code = str(err_obj.get("code"))
        if typ is None and err_obj.get("type") is not None:
            typ = str(err_obj.get("type"))
        if err_obj.get("message") and message == str(exc):
            message = str(err_obj.get("message"))

    return code, typ, message


def is_insufficient_credits_error(exc: BaseException) -> bool:
    """True when the failure is quota/billing exhaustion (not a transient 429)."""
    if isinstance(exc, InsufficientCreditsError):
        return True

    # Newer openai SDKs may expose a dedicated type.
    exc_name = type(exc).__name__
    if exc_name in ("InsufficientQuotaError", "InsufficientCreditsError"):
        return True

    code, typ, message = _error_body_fields(exc)
    if code and code.lower() in _INSUFFICIENT_CREDIT_CODES:
        return True
    if typ and typ.lower() in _INSUFFICIENT_CREDIT_TYPES:
        return True

    lowered = (message or "").lower()
    if any(marker in lowered for marker in _INSUFFICIENT_CREDIT_MARKERS):
        return True

    # Fall back to full exception string (e.g. RateLimitError repr).
    full = str(exc).lower()
    return any(marker in full for marker in _INSUFFICIENT_CREDIT_MARKERS)


def format_insufficient_credits_message(
    exc: BaseException,
    *,
    vendor: Optional[str] = None,
) -> str:
    """User-facing message: clear cause + instruction to retry manually after topping up."""
    if isinstance(exc, InsufficientCreditsError):
        return str(exc)

    code, typ, provider_message = _error_body_fields(exc)
    vendor_label = (vendor or "").strip() or "this provider"
    detail = (provider_message or str(exc) or "no credits remaining").strip()
    # Prefer the short provider sentence when the full repr is noisy.
    if "error code:" in detail.lower() and "message" in detail.lower():
        _, _, cleaned = _error_body_fields(exc)
        if cleaned and cleaned != detail:
            detail = cleaned
    extra = ""
    if code:
        extra = f" (code={code})"
    elif typ:
        extra = f" (type={typ})"
    return (
        f"Not enough API credits for {vendor_label}: {detail}{extra}. "
        "Add credits (or fix billing), then click Retry."
    )


def insufficient_credits_error_from_exception(
    exc: BaseException,
    *,
    vendor: Optional[str] = None,
) -> InsufficientCreditsError:
    code, typ, _ = _error_body_fields(exc)
    return InsufficientCreditsError(
        format_insufficient_credits_message(exc, vendor=vendor),
        vendor=vendor,
        provider_code=code,
        provider_type=typ,
    )


def reraise_if_insufficient_credits(
    exc: BaseException,
    *,
    vendor: Optional[str] = None,
) -> None:
    """Raise InsufficientCreditsError when ``exc`` is quota exhaustion; otherwise return."""
    if isinstance(exc, InsufficientCreditsError):
        raise exc
    if is_insufficient_credits_error(exc):
        raise insufficient_credits_error_from_exception(exc, vendor=vendor) from exc


def response_indicates_insufficient_credits(status_code: int, body: Any) -> bool:
    """Used by HTTP clients to skip SDK retries on quota-exhaustion 429s."""
    if status_code not in (402, 429):
        # Anthropic sometimes returns 400 for low credit balance.
        if status_code != 400:
            return False
    code: Optional[str] = None
    typ: Optional[str] = None
    message = ""
    if isinstance(body, dict):
        err = body.get("error") if isinstance(body.get("error"), dict) else body
        if isinstance(err, dict):
            if err.get("code") is not None:
                code = str(err.get("code"))
            if err.get("type") is not None:
                typ = str(err.get("type"))
            if err.get("message"):
                message = str(err.get("message"))
        if not message and isinstance(body.get("message"), str):
            message = body["message"]
    elif isinstance(body, str):
        message = body
    else:
        message = str(body or "")

    if code and code.lower() in _INSUFFICIENT_CREDIT_CODES:
        return True
    if typ and typ.lower() in _INSUFFICIENT_CREDIT_TYPES:
        return True
    lowered = message.lower()
    return any(marker in lowered for marker in _INSUFFICIENT_CREDIT_MARKERS)
