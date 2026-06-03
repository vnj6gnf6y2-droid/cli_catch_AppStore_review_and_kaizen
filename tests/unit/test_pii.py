"""Unit tests for PII masking."""

from __future__ import annotations

import pytest

from appreview.analysis.pii import mask_pii, mask_reviewer_nickname


class TestMaskPII:
    """Tests for PII masking patterns."""

    def test_masks_email_address(self) -> None:
        """Email addresses should be replaced with [REDACTED_EMAIL]."""
        text = "Contact me at user@example.com for support."
        result = mask_pii(text)
        assert "[REDACTED_EMAIL]" in result
        assert "user@example.com" not in result

    def test_masks_email_with_dots_and_plus(self) -> None:
        """Complex email formats should be masked."""
        text = "My email is john.doe+tag@sub.example.co.jp"
        result = mask_pii(text)
        assert "[REDACTED_EMAIL]" in result
        assert "john.doe+tag@sub.example.co.jp" not in result

    def test_masks_e164_phone_number(self) -> None:
        """E.164 format phone numbers should be masked."""
        text = "Call me at +81-90-1234-5678"
        result = mask_pii(text)
        assert "[REDACTED_PHONE]" in result

    def test_masks_japanese_phone_number(self) -> None:
        """Japanese phone number format should be masked."""
        text = "電話番号は03-1234-5678です。"
        result = mask_pii(text)
        assert "[REDACTED_PHONE]" in result
        assert "03-1234-5678" not in result

    def test_masks_credit_card_number(self) -> None:
        """Credit card-like 16-digit numbers should be masked."""
        text = "My card is 4111 1111 1111 1111 and it's not working."
        result = mask_pii(text)
        assert "[REDACTED_CARD]" in result
        assert "4111 1111 1111 1111" not in result

    def test_masks_url_token_parameter(self) -> None:
        """Sensitive URL query parameters should be masked."""
        text = "Try this link: https://example.com/api?token=secret123&lang=en"
        result = mask_pii(text)
        assert "secret123" not in result
        assert "[REDACTED_TOKEN]" in result

    def test_masks_url_key_parameter(self) -> None:
        """URL api_key parameter should be masked."""
        text = "URL: https://api.example.com?api_key=my_secret_key&format=json"
        result = mask_pii(text)
        assert "my_secret_key" not in result

    def test_preserves_normal_text(self) -> None:
        """Normal review text without PII should be unchanged."""
        text = "This app crashes every time I open it. Please fix this bug!"
        result = mask_pii(text)
        assert result == text

    def test_multiple_pii_in_one_text(self) -> None:
        """Multiple PII patterns in one review should all be masked."""
        text = (
            "Contact user@test.com or call 090-1234-5678. "
            "My card number 4111111111111111 was charged incorrectly."
        )
        result = mask_pii(text)
        assert "user@test.com" not in result
        assert "090-1234-5678" not in result
        assert "4111111111111111" not in result

    def test_empty_string(self) -> None:
        """Empty string should return empty string."""
        assert mask_pii("") == ""

    def test_does_not_mask_version_numbers(self) -> None:
        """Version numbers like 2.3.1 should not be incorrectly masked."""
        text = "The bug was introduced in version 2.3.1"
        result = mask_pii(text)
        assert "2.3.1" in result


class TestMaskReviewerNickname:
    """Tests for reviewer nickname anonymization."""

    def test_masks_long_nickname(self) -> None:
        """Long nicknames keep first and last character, middle is masked."""
        result = mask_reviewer_nickname("JohnDoe")
        # "JohnDoe" = 7 chars → "J" + "*" * 5 + "e"
        assert result == "J*****e"

    def test_masks_short_nickname(self) -> None:
        """Short nicknames are fully masked."""
        result = mask_reviewer_nickname("Jo")
        assert result == "**"

    def test_none_returns_none(self) -> None:
        """None input returns None."""
        assert mask_reviewer_nickname(None) is None

    def test_single_char(self) -> None:
        """Single character nickname is masked."""
        result = mask_reviewer_nickname("J")
        assert result == "*"
