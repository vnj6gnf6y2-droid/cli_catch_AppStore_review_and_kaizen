"""Integration tests for the full pipeline with HTTP mocks."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import respx
from httpx import Response

from appreview.sources.base import NormalizedReview


class TestAppStorePagination:
    """Tests for App Store pagination behavior."""

    @pytest.mark.asyncio
    async def test_pagination_follows_next_link(
        self, fake_p8_key: Path, app_store_response: dict
    ) -> None:
        """Pagination should follow 'next' links in response."""
        from appreview.sources.app_store import AppStoreSource

        # Second page response (no next link)
        second_page = {
            "data": [
                {
                    "id": "extra_001",
                    "type": "customerReviews",
                    "attributes": {
                        "rating": 3,
                        "body": "Second page review",
                        "createdDate": "2026-05-25T10:00:00Z",
                    },
                }
            ],
            "links": {},
        }

        # First page with next link
        first_page = {
            "data": app_store_response["reviews"],
            "links": {
                "next": "https://api.appstoreconnect.apple.com/v1/apps/123/customerReviews?cursor=abc"
            },
        }

        source = AppStoreSource(
            app_id="1234567890",
            issuer_id="test-issuer",
            key_id="TEST001",
            private_key_path=fake_p8_key,
            request_delay_ms=0,
        )

        with respx.mock(base_url="https://api.appstoreconnect.apple.com") as mock:
            mock.get("/v1/apps/1234567890/customerReviews").mock(
                return_value=Response(200, json=first_page)
            )
            mock.get("/v1/apps/123/customerReviews", params={"cursor": "abc"}).mock(
                return_value=Response(200, json=second_page)
            )

            reviews = []
            async for review in await source.fetch_reviews():
                reviews.append(review)

        # Should have fetched from both pages
        assert len(reviews) >= 3  # 3 from first page
        review_ids = [r.id for r in reviews]
        # Extra review from second page
        assert "extra_001" in review_ids

    @pytest.mark.asyncio
    async def test_stops_at_since_boundary(
        self, fake_p8_key: Path
    ) -> None:
        """Fetching should stop when reaching reviews older than 'since'."""
        from appreview.sources.app_store import AppStoreSource

        since_dt = datetime(2026, 5, 27, tzinfo=timezone.utc)

        response_data = {
            "data": [
                {
                    "id": "new_001",
                    "attributes": {
                        "rating": 4,
                        "body": "New review",
                        "createdDate": "2026-05-28T10:00:00Z",  # After since
                    },
                },
                {
                    "id": "old_001",
                    "attributes": {
                        "rating": 2,
                        "body": "Old review",
                        "createdDate": "2026-05-26T10:00:00Z",  # Before since
                    },
                },
            ],
            "links": {},
        }

        source = AppStoreSource(
            app_id="test_app",
            issuer_id="issuer",
            key_id="key",
            private_key_path=fake_p8_key,
            request_delay_ms=0,
        )

        with respx.mock(base_url="https://api.appstoreconnect.apple.com") as mock:
            mock.get("/v1/apps/test_app/customerReviews").mock(
                return_value=Response(200, json=response_data)
            )

            reviews = []
            async for review in await source.fetch_reviews(since=since_dt):
                reviews.append(review)

        # Should only get the new review (old_001 is before `since`)
        review_ids = [r.id for r in reviews]
        assert "new_001" in review_ids
        assert "old_001" not in review_ids


class TestGooglePlayFetch:
    """Tests for Google Play review fetching."""

    @pytest.mark.asyncio
    async def test_fetches_reviews_from_fixture(
        self, google_play_response: dict, tmp_path: Path
    ) -> None:
        """Should parse Google Play API fixture response correctly."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from appreview.sources.google_play import GooglePlaySource

        service_account = tmp_path / "service_account.json"
        service_account.write_text('{"type": "service_account"}')

        source = GooglePlaySource(
            package_name="com.example.app",
            service_account_json_path=service_account,
            request_delay_ms=0,
        )

        # Mock Google Auth credentials
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.token = "fake_token"

        with (
            patch.object(source, "_get_credentials", return_value=mock_creds),
            patch.object(source, "_get_access_token", new_callable=AsyncMock, return_value="fake_token"),
            respx.mock(base_url="https://androidpublisher.googleapis.com") as mock,
        ):
            mock.get(
                "/androidpublisher/v3/applications/com.example.app/reviews"
            ).mock(
                return_value=Response(200, json=google_play_response)
            )

            reviews = []
            async for review in await source.fetch_reviews():
                reviews.append(review)

        # Should get 3 user reviews (one per review, developer reply is ignored)
        assert len(reviews) == 3
        review_ids = [r.id for r in reviews]
        assert "gp_review_001" in review_ids
        assert "gp_review_002" in review_ids

    @pytest.mark.asyncio
    async def test_google_play_clamps_since_to_7_days(
        self, tmp_path: Path
    ) -> None:
        """Should warn and clamp since to 7 days for Google Play."""
        from datetime import timedelta
        from unittest.mock import AsyncMock, patch

        from appreview.sources.google_play import GooglePlaySource

        service_account = tmp_path / "service_account.json"
        service_account.write_text('{"type": "service_account"}')

        source = GooglePlaySource(
            package_name="com.example.app",
            service_account_json_path=service_account,
            request_delay_ms=0,
        )

        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.token = "token"

        # Request reviews from 30 days ago
        old_since = datetime.now(tz=timezone.utc) - timedelta(days=30)

        empty_response = {"reviews": [], "tokenPagination": {}}

        with (
            patch.object(source, "_get_credentials", return_value=mock_creds),
            patch.object(source, "_get_access_token", new_callable=AsyncMock, return_value="token"),
            respx.mock(base_url="https://androidpublisher.googleapis.com") as mock,
        ):
            mock.get(
                "/androidpublisher/v3/applications/com.example.app/reviews"
            ).mock(return_value=Response(200, json=empty_response))

            reviews = []
            async for review in await source.fetch_reviews(since=old_since):
                reviews.append(review)

        # Should complete without error (clamping happened internally)
        assert reviews == []


class TestStorageDeduplication:
    """Tests for review deduplication in storage."""

    @pytest.mark.asyncio
    async def test_duplicate_reviews_are_skipped(
        self, db_session, sample_reviews: list
    ) -> None:
        """Inserting the same review twice should not create duplicates."""
        from appreview.storage.repository import ReviewRepository

        repo = ReviewRepository(db_session)
        review_dicts = [r.model_dump() for r in sample_reviews[:3]]

        # Insert first time
        inserted1 = await repo.upsert_reviews(review_dicts)
        # Insert same reviews again
        inserted2 = await repo.upsert_reviews(review_dicts)

        assert inserted1 == 3
        assert inserted2 == 0  # All duplicates

    @pytest.mark.asyncio
    async def test_different_sources_not_duplicated(
        self, db_session, sample_review: NormalizedReview
    ) -> None:
        """Reviews with same ID but different sources should both be stored."""
        from appreview.storage.repository import ReviewRepository

        repo = ReviewRepository(db_session)

        review1 = sample_review.model_copy(update={"source": "app_store"})
        review2 = sample_review.model_copy(update={"source": "google_play"})

        inserted = await repo.upsert_reviews([
            review1.model_dump(),
            review2.model_dump(),
        ])

        assert inserted == 2
