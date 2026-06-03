"""Unit tests for Google Play source parsing."""

from __future__ import annotations

from typing import Any

import pytest

from appreview.sources.google_play import GooglePlaySource


class TestGooglePlayParser:
    """Tests for Google Play review parsing."""

    def test_parse_review_basic(self) -> None:
        """Should parse user comment fields correctly."""
        raw: dict[str, Any] = {
            "reviewId": "gp_001",
            "authorName": "TestUser",
            "comments": [
                {
                    "userComment": {
                        "text": "The app is buggy.",
                        "lastModified": {"seconds": "1748390400"},
                        "starRating": 1,
                        "reviewerLanguage": "en",
                        "appVersionName": "3.1.0",
                    }
                }
            ],
        }

        review = GooglePlaySource._parse_review(raw, "com.example.app")

        assert review is not None
        assert review.id == "gp_001"
        assert review.source == "google_play"
        assert review.app_identifier == "com.example.app"
        assert review.rating == 1
        assert review.body == "The app is buggy."
        assert review.app_version == "3.1.0"
        assert review.title is None  # Google Play reviews don't have titles
        assert review.reviewer_nickname == "TestUser"

    def test_parse_review_ignores_developer_replies(self) -> None:
        """Developer reply comments should be ignored."""
        raw: dict[str, Any] = {
            "reviewId": "gp_002",
            "authorName": "User",
            "comments": [
                {
                    "userComment": {
                        "text": "Great app!",
                        "lastModified": {"seconds": "1748390400"},
                        "starRating": 5,
                    }
                },
                {
                    "developerComment": {
                        "text": "Thank you!",
                        "lastModified": {"seconds": "1748476800"},
                    }
                },
            ],
        }

        review = GooglePlaySource._parse_review(raw, "com.example.app")
        assert review is not None
        assert review.body == "Great app!"

    def test_parse_review_no_user_comment_returns_none(self) -> None:
        """Reviews with only developer comments should return None."""
        raw: dict[str, Any] = {
            "reviewId": "gp_003",
            "comments": [
                {
                    "developerComment": {
                        "text": "Developer reply only",
                        "lastModified": {"seconds": "1748390400"},
                    }
                }
            ],
        }

        review = GooglePlaySource._parse_review(raw, "com.example.app")
        assert review is None

    def test_parse_review_timestamp(self) -> None:
        """lastModified seconds should be converted to UTC datetime."""
        raw: dict[str, Any] = {
            "reviewId": "gp_004",
            "comments": [
                {
                    "userComment": {
                        "text": "Test",
                        "lastModified": {"seconds": "1748390400"},  # 2026-05-27
                        "starRating": 3,
                    }
                }
            ],
        }

        review = GooglePlaySource._parse_review(raw, "com.example.app")
        assert review is not None
        assert review.created_at.tzinfo is not None
        assert review.created_at.year == 2025  # 1748390400 = 2025-05-27

    def test_parse_review_locale(self) -> None:
        """reviewerLanguage should be mapped to locale field."""
        raw: dict[str, Any] = {
            "reviewId": "gp_005",
            "comments": [
                {
                    "userComment": {
                        "text": "テストレビュー",
                        "lastModified": {"seconds": "1748390400"},
                        "starRating": 4,
                        "reviewerLanguage": "ja",
                    }
                }
            ],
        }

        review = GooglePlaySource._parse_review(raw, "com.example.app")
        assert review is not None
        assert review.locale == "ja"
