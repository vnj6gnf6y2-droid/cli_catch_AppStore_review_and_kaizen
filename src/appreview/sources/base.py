"""Base protocol and shared types for review data sources."""

from __future__ import annotations

from datetime import datetime
from typing import AsyncIterator, ClassVar, Literal

from pydantic import BaseModel


class NormalizedReview(BaseModel):
    """Unified review model for both App Store and Google Play reviews."""

    id: str
    source: Literal["app_store", "google_play"]
    app_identifier: str
    rating: int
    title: str | None = None
    body: str
    locale: str | None = None
    detected_language: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    app_version: str | None = None
    territory: str | None = None
    raw_payload: dict  # type: ignore[type-arg]
    fetched_at: datetime
    reviewer_nickname: str | None = None


class HealthStatus(BaseModel):
    """Result of a health check for a data source."""

    source: str
    healthy: bool
    message: str
    latency_ms: float | None = None


class ReviewSource:
    """Protocol definition for review data sources.

    Concrete implementations: AppStoreSource, GooglePlaySource.
    """

    source_name: ClassVar[Literal["app_store", "google_play"]]

    async def fetch_reviews(
        self,
        since: datetime | None = None,
    ) -> AsyncIterator[NormalizedReview]:
        """Fetch reviews from the source.

        Args:
            since: Only return reviews created after this datetime.
                   If None, fetch all available reviews.

        Yields:
            NormalizedReview instances.
        """
        raise NotImplementedError
        # Make this a proper async generator
        if False:  # type: ignore[unreachable]
            yield NormalizedReview(
                id="",
                source="app_store",
                app_identifier="",
                rating=1,
                body="",
                raw_payload={},
                fetched_at=datetime.now(),
                created_at=datetime.now(),
            )

    async def health_check(self) -> HealthStatus:
        """Validate authentication and connectivity.

        Returns:
            HealthStatus indicating whether the source is reachable.
        """
        raise NotImplementedError
