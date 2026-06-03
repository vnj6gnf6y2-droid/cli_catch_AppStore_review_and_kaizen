"""Live integration tests — require real API credentials.

These tests are skipped by default. Run with:
    pytest -m live

Requires environment variables to be set.
"""

from __future__ import annotations

import os

import pytest


@pytest.mark.live
class TestAppStoreLive:
    """Live tests for App Store Connect API."""

    @pytest.mark.asyncio
    async def test_fetch_reviews_live(self) -> None:
        """Fetch real reviews from App Store Connect."""
        from pathlib import Path

        from appreview.sources.app_store import AppStoreSource

        issuer_id = os.environ.get("APP_STORE_ISSUER_ID")
        key_id = os.environ.get("APP_STORE_KEY_ID")
        key_path = os.environ.get("APP_STORE_PRIVATE_KEY_PATH")
        app_id = os.environ.get("TEST_APP_STORE_APP_ID")

        if not all([issuer_id, key_id, key_path, app_id]):
            pytest.skip("Missing live test credentials")

        source = AppStoreSource(
            app_id=app_id,  # type: ignore[arg-type]
            issuer_id=issuer_id,  # type: ignore[arg-type]
            key_id=key_id,  # type: ignore[arg-type]
            private_key_path=Path(key_path),  # type: ignore[arg-type]
        )

        reviews = []
        async for review in source.fetch_reviews():
            reviews.append(review)
            if len(reviews) >= 5:
                break

        assert len(reviews) > 0
        for review in reviews:
            assert review.source == "app_store"
            assert 1 <= review.rating <= 5
            assert review.body


@pytest.mark.live
class TestGooglePlayLive:
    """Live tests for Google Play Developer API."""

    @pytest.mark.asyncio
    async def test_fetch_reviews_live(self) -> None:
        """Fetch real reviews from Google Play Developer API."""
        from pathlib import Path

        from appreview.sources.google_play import GooglePlaySource

        sa_path = os.environ.get("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON")
        package_name = os.environ.get("TEST_GOOGLE_PLAY_PACKAGE_NAME")

        if not all([sa_path, package_name]):
            pytest.skip("Missing live test credentials")

        source = GooglePlaySource(
            package_name=package_name,  # type: ignore[arg-type]
            service_account_json_path=Path(sa_path),  # type: ignore[arg-type]
        )

        reviews = []
        async for review in source.fetch_reviews():
            reviews.append(review)
            if len(reviews) >= 5:
                break

        assert len(reviews) > 0
        for review in reviews:
            assert review.source == "google_play"
            assert 1 <= review.rating <= 5
