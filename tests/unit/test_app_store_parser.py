"""Unit tests for App Store source parsing."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from appreview.sources.app_store import AppStoreSource


class TestAppStoreParser:
    """Tests for App Store review parsing."""

    def test_parse_review_basic(self) -> None:
        """Should parse basic review fields correctly."""
        raw: dict[str, Any] = {
            "id": "123456",
            "type": "customerReviews",
            "attributes": {
                "rating": 1,
                "title": "Crashes on launch",
                "body": "The app keeps crashing!",
                "reviewerNickname": "TestUser",
                "createdDate": "2026-05-28T10:00:00Z",
                "territory": "JP",
                "appVersionString": "2.3.1",
            },
        }

        review = AppStoreSource._parse_review(raw, "1234567890")

        assert review.id == "123456"
        assert review.source == "app_store"
        assert review.app_identifier == "1234567890"
        assert review.rating == 1
        assert review.title == "Crashes on launch"
        assert review.body == "The app keeps crashing!"
        assert review.territory == "JP"
        assert review.app_version == "2.3.1"
        assert review.reviewer_nickname == "TestUser"

    def test_parse_review_datetime_format(self) -> None:
        """createdDate should be parsed to UTC-aware datetime."""
        raw: dict[str, Any] = {
            "id": "789",
            "attributes": {
                "rating": 5,
                "body": "Great!",
                "createdDate": "2026-05-28T10:00:00Z",
            },
        }
        review = AppStoreSource._parse_review(raw, "app123")
        assert review.created_at.tzinfo is not None
        assert review.created_at.year == 2026

    def test_parse_review_with_missing_optional_fields(self) -> None:
        """Optional fields should be None when missing."""
        raw: dict[str, Any] = {
            "id": "abc",
            "attributes": {
                "rating": 3,
                "body": "Average app.",
                "createdDate": "2026-05-28T10:00:00Z",
            },
        }
        review = AppStoreSource._parse_review(raw, "app123")
        assert review.title is None
        assert review.territory is None
        assert review.app_version is None

    def test_parse_review_preserves_raw_payload(self) -> None:
        """raw_payload should contain the original dict."""
        raw: dict[str, Any] = {
            "id": "test_id",
            "attributes": {
                "rating": 4,
                "body": "Good app",
                "createdDate": "2026-05-28T10:00:00Z",
            },
        }
        review = AppStoreSource._parse_review(raw, "app123")
        assert review.raw_payload == raw

    def test_parse_review_invalid_date_uses_now(self) -> None:
        """Invalid date format should not raise, uses current time."""
        raw: dict[str, Any] = {
            "id": "test_id",
            "attributes": {
                "rating": 3,
                "body": "Test",
                "createdDate": "not-a-date",
            },
        }
        before = datetime.now(tz=UTC)
        review = AppStoreSource._parse_review(raw, "app123")
        after = datetime.now(tz=UTC)
        # Should not raise, created_at should be recent
        assert before <= review.created_at <= after
