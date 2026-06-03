"""PII (Personally Identifiable Information) masking for review text."""

from __future__ import annotations

import re


# Regex patterns for PII detection
_EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",
    re.IGNORECASE,
)

_PHONE_PATTERNS = [
    # E.164 international format: +1234567890
    re.compile(r"\+\d{1,3}[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9}"),
    # Japanese formats: 03-1234-5678, 090-1234-5678, 0120-123-456
    re.compile(r"\b0\d{1,4}[-\s]?\d{2,4}[-\s]?\d{3,4}\b"),
]

_CREDIT_CARD_PATTERN = re.compile(
    r"\b(?:\d{4}[-\s]?){3}\d{4}\b|\b\d{16,19}\b"
)

_SENSITIVE_URL_PARAM_PATTERN = re.compile(
    r"([?&](?:token|key|secret|api_key|apikey|access_token|auth|password|passwd|pwd)"
    r"=)[^&\s#\"']+",
    re.IGNORECASE,
)

# Replacement tokens
_EMAIL_MASK = "[REDACTED_EMAIL]"
_PHONE_MASK = "[REDACTED_PHONE]"
_CC_MASK = "[REDACTED_CARD]"
_TOKEN_MASK = r"\1[REDACTED_TOKEN]"


def mask_pii(text: str) -> str:
    """Mask PII patterns in review text before sending to LLM.

    Replaces:
    - Email addresses → [REDACTED_EMAIL]
    - Phone numbers (E.164 and Japanese formats) → [REDACTED_PHONE]
    - Credit card-like numbers (16-19 digits) → [REDACTED_CARD]
    - Sensitive URL query parameters (token=, key=, etc.) → [REDACTED_TOKEN]

    Args:
        text: Raw review text.

    Returns:
        Text with PII masked.
    """
    # Mask emails
    text = _EMAIL_PATTERN.sub(_EMAIL_MASK, text)

    # Mask phone numbers
    for pattern in _PHONE_PATTERNS:
        text = pattern.sub(_PHONE_MASK, text)

    # Mask credit card numbers (be conservative — only mask clear card patterns)
    text = _CREDIT_CARD_PATTERN.sub(_mask_if_card, text)

    # Mask sensitive URL parameters
    text = _SENSITIVE_URL_PARAM_PATTERN.sub(_TOKEN_MASK, text)

    return text


def _mask_if_card(match: re.Match[str]) -> str:
    """Only mask if the match looks like a credit card number.

    Apply Luhn-like heuristic: reject obvious non-card numbers
    (e.g., version numbers like 20260101).

    Args:
        match: Regex match object.

    Returns:
        Replacement string.
    """
    raw = match.group(0)
    # Remove separators to get pure digits
    digits = re.sub(r"[-\s]", "", raw)

    # Skip if too short or too long
    if not (16 <= len(digits) <= 19):
        return raw

    # Skip obvious non-cards (e.g., dates like 20260603, version numbers)
    # Simple heuristic: if it starts with 19xx or 20xx it's probably a year
    if digits[:2] in ("19", "20") and len(digits) == 8:
        return raw

    return _CC_MASK


def mask_reviewer_nickname(text: str | None) -> str | None:
    """Anonymize a reviewer nickname.

    Args:
        text: Reviewer nickname.

    Returns:
        Masked string or None.
    """
    if text is None:
        return None
    if len(text) <= 2:
        return "*" * len(text)
    return text[0] + "*" * (len(text) - 2) + text[-1]
