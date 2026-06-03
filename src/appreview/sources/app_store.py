"""App Store Connect API review source."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, ClassVar, Literal

import httpx

from appreview.exceptions import (
    AppNotFoundError,
    AuthenticationError,
    PermissionError,
    RateLimitError,
    UpstreamError,
)
from appreview.logging import get_logger
from appreview.sources.base import HealthStatus, NormalizedReview
from appreview.sources.jwt_helper import AppStoreJWT

logger = get_logger(__name__)

BASE_URL = "https://api.appstoreconnect.apple.com/v1"
MAX_LIMIT = 200
REQUEST_DELAY_SECONDS = 0.2
MAX_RETRIES = 5
INITIAL_BACKOFF = 1.0


class AppStoreSource:
    """Fetches reviews from App Store Connect API."""

    source_name: ClassVar[Literal["app_store"]] = "app_store"

    def __init__(
        self,
        app_id: str,
        issuer_id: str,
        key_id: str,
        private_key_path: Path,
        territories: list[str] | None = None,
        request_delay_ms: int = 200,
    ) -> None:
        """Initialize App Store source.

        Args:
            app_id: Numeric App Store app ID.
            issuer_id: App Store Connect Issuer ID.
            key_id: App Store Connect Key ID.
            private_key_path: Path to .p8 private key file.
            territories: Optional list of territory codes to filter (e.g. ['JP', 'US']).
            request_delay_ms: Minimum delay between requests in milliseconds.
        """
        self._app_id = app_id
        self._jwt = AppStoreJWT(issuer_id, key_id, private_key_path)
        self._territories = territories
        self._request_delay = request_delay_ms / 1000.0

    def _get_headers(self) -> dict[str, str]:
        """Get authorization headers with current JWT."""
        return {"Authorization": f"Bearer {self._jwt.get_token()}"}

    async def _request_with_retry(
        self,
        client: httpx.AsyncClient,
        url: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a GET request with exponential backoff retry.

        Args:
            client: httpx async client.
            url: Full URL to request.
            params: Optional query parameters.

        Returns:
            Parsed JSON response.

        Raises:
            AuthenticationError: On 401.
            PermissionError: On 403.
            AppNotFoundError: On 404.
            RateLimitError: On 429.
            UpstreamError: On 5xx after retries.
        """
        backoff = INITIAL_BACKOFF
        for attempt in range(MAX_RETRIES + 1):
            await asyncio.sleep(self._request_delay if attempt > 0 else 0)

            response = await client.get(
                url,
                headers=self._get_headers(),
                params=params,
            )

            if response.status_code == 200:
                return response.json()  # type: ignore[no-any-return]

            if response.status_code == 401:
                raise AuthenticationError(
                    "App Store Connect: Authentication failed. "
                    "Check your Issuer ID, Key ID, and private key."
                )

            if response.status_code == 403:
                raise PermissionError(
                    "App Store Connect: Insufficient permissions. "
                    "Ensure the API key has at least Developer access."
                )

            if response.status_code == 404:
                raise AppNotFoundError(
                    f"App Store Connect: App not found (id={self._app_id}). "
                    "Verify the app_id in your configuration."
                )

            if response.status_code == 429:
                retry_after: float | None = None
                if "Retry-After" in response.headers:
                    try:
                        retry_after = float(response.headers["Retry-After"])
                    except ValueError:
                        pass
                if retry_after:
                    logger.warning(
                        "Rate limited by App Store Connect, waiting",
                        retry_after=retry_after,
                    )
                    await asyncio.sleep(retry_after)
                    continue
                raise RateLimitError(
                    "App Store Connect: Rate limit exceeded", retry_after=retry_after
                )

            if response.status_code >= 500:
                if attempt < MAX_RETRIES:
                    logger.warning(
                        "App Store Connect server error, retrying",
                        status=response.status_code,
                        attempt=attempt + 1,
                        backoff=backoff,
                    )
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 32.0)
                    continue
                raise UpstreamError(
                    f"App Store Connect: Server error {response.status_code} after "
                    f"{MAX_RETRIES} retries",
                    status_code=response.status_code,
                )

            raise UpstreamError(
                f"App Store Connect: Unexpected status {response.status_code}",
                status_code=response.status_code,
            )

        raise UpstreamError("App Store Connect: Max retries exceeded")

    @staticmethod
    def _parse_review(data: dict[str, Any], app_id: str) -> NormalizedReview:
        """Parse a raw API review into a NormalizedReview.

        Args:
            data: Raw review dict from the API.
            app_id: App ID string.

        Returns:
            NormalizedReview instance.
        """
        attrs = data.get("attributes", {})
        now = datetime.now(tz=timezone.utc)

        created_str = attrs.get("createdDate", "")
        try:
            created_at = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            created_at = now

        return NormalizedReview(
            id=data.get("id", ""),
            source="app_store",
            app_identifier=app_id,
            rating=int(attrs.get("rating", 0)),
            title=attrs.get("title"),
            body=attrs.get("body", ""),
            locale=attrs.get("reviewerNickname", None),  # not locale but close enough
            created_at=created_at,
            app_version=attrs.get("appVersionString"),
            territory=attrs.get("territory"),
            raw_payload=data,
            fetched_at=now,
            reviewer_nickname=attrs.get("reviewerNickname"),
        )

    async def fetch_reviews(
        self,
        since: datetime | None = None,
    ) -> AsyncIterator[NormalizedReview]:
        """Fetch reviews from App Store Connect API.

        Args:
            since: Only yield reviews created after this datetime.

        Yields:
            NormalizedReview instances.
        """
        return self._fetch_reviews_impl(since=since)

    async def _fetch_reviews_impl(
        self,
        since: datetime | None = None,
    ) -> AsyncIterator[NormalizedReview]:
        """Internal async generator for fetching reviews."""
        url = f"{BASE_URL}/apps/{self._app_id}/customerReviews"
        params: dict[str, Any] = {
            "limit": MAX_LIMIT,
            "sort": "-createdDate",
        }
        if self._territories:
            params["filter[territory]"] = ",".join(self._territories)

        async with httpx.AsyncClient(timeout=30.0) as client:
            while url:
                data = await self._request_with_retry(client, url, params)
                reviews_data = data.get("data", [])

                for review_data in reviews_data:
                    review = self._parse_review(review_data, self._app_id)

                    # Stop if we've reached reviews older than `since`
                    if since and review.created_at <= since:
                        logger.debug(
                            "Reached reviews older than since, stopping",
                            since=since.isoformat(),
                            review_created=review.created_at.isoformat(),
                        )
                        return

                    yield review

                # Handle pagination
                links = data.get("links", {})
                next_url = links.get("next")
                if next_url:
                    url = next_url
                    params = {}  # URL already contains params
                    await asyncio.sleep(self._request_delay)
                else:
                    break

    async def health_check(self) -> HealthStatus:
        """Check App Store Connect API connectivity.

        Returns:
            HealthStatus with connectivity result.
        """
        import time

        url = f"{BASE_URL}/apps/{self._app_id}/customerReviews"
        params = {"limit": 1}

        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await self._request_with_retry(client, url, params)
            latency = (time.monotonic() - start) * 1000
            return HealthStatus(
                source="app_store",
                healthy=True,
                message=f"App Store Connect API is reachable (app_id={self._app_id})",
                latency_ms=latency,
            )
        except (AuthenticationError, PermissionError, AppNotFoundError) as e:
            return HealthStatus(
                source="app_store",
                healthy=False,
                message=str(e),
            )
        except Exception as e:
            return HealthStatus(
                source="app_store",
                healthy=False,
                message=f"Unexpected error: {e}",
            )
