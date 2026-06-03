"""Google Play Developer API review source."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncGenerator, AsyncIterator, ClassVar, Literal

import httpx

from appreview.exceptions import (
    AppNotFoundError,
    AuthenticationError,
    PermissionError,
    UpstreamError,
)
from appreview.logging import get_logger
from appreview.sources.base import HealthStatus, NormalizedReview

logger = get_logger(__name__)

BASE_URL = "https://androidpublisher.googleapis.com/androidpublisher/v3"
MAX_RESULTS = 100
# Google Play API limit: 200 GET requests per hour
RATE_LIMIT_REQUESTS = 200
RATE_LIMIT_WINDOW = 3600  # seconds
# Maximum lookback: 7 days (API limitation)
MAX_LOOKBACK_DAYS = 7


class TokenBucketRateLimiter:
    """Token bucket rate limiter for Google Play API.

    Allows up to `capacity` tokens, refilling at `refill_rate` tokens/second.
    """

    def __init__(self, capacity: float, refill_rate: float) -> None:
        """Initialize the rate limiter.

        Args:
            capacity: Maximum tokens in the bucket.
            refill_rate: Tokens added per second.
        """
        self._capacity = capacity
        self._refill_rate = refill_rate
        self._tokens = capacity
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Acquire one token, waiting if necessary."""
        async with self._lock:
            while True:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                # Wait for one token to be available
                wait_time = (1.0 - self._tokens) / self._refill_rate
                await asyncio.sleep(wait_time)

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_rate)
        self._last_refill = now


class GooglePlaySource:
    """Fetches reviews from Google Play Developer API.

    IMPORTANT: This API only returns reviews from the past 7 days.
    This tool must be run at least daily to avoid data gaps.
    """

    source_name: ClassVar[Literal["google_play"]] = "google_play"

    def __init__(
        self,
        package_name: str,
        service_account_json_path: Path,
        request_delay_ms: int = 200,
    ) -> None:
        """Initialize Google Play source.

        Args:
            package_name: Android package name (e.g., com.example.app).
            service_account_json_path: Path to service account JSON key file.
            request_delay_ms: Minimum delay between requests in milliseconds.
        """
        self._package_name = package_name
        self._service_account_path = service_account_json_path
        self._request_delay = request_delay_ms / 1000.0
        # 200 requests per hour = ~0.0556 per second
        self._rate_limiter = TokenBucketRateLimiter(
            capacity=float(RATE_LIMIT_REQUESTS),
            refill_rate=RATE_LIMIT_REQUESTS / RATE_LIMIT_WINDOW,
        )
        self._credentials: Any = None

    def _get_credentials(self) -> Any:
        """Get or create Google OAuth2 credentials."""
        if self._credentials is None:
            from google.oauth2 import service_account  # type: ignore[import]

            self._credentials = service_account.Credentials.from_service_account_file(
                str(self._service_account_path),
                scopes=["https://www.googleapis.com/auth/androidpublisher"],
            )
        return self._credentials

    async def _get_access_token(self) -> str:
        """Get a valid access token, refreshing if necessary.

        Returns:
            Bearer token string.
        """
        import google.auth.transport.requests as google_requests  # type: ignore[import]

        creds = self._get_credentials()

        # Refresh in a thread to avoid blocking the event loop
        def _refresh() -> None:
            request = google_requests.Request()
            if not creds.valid:
                creds.refresh(request)

        await asyncio.to_thread(_refresh)
        return str(creds.token)  # type: ignore[attr-defined]

    async def _request(
        self,
        client: httpx.AsyncClient,
        url: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated GET request.

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
            UpstreamError: On other errors.
        """
        await self._rate_limiter.acquire()

        token = await self._get_access_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.get(url, headers=headers, params=params)

        if response.status_code == 200:
            return response.json()  # type: ignore[no-any-return]

        if response.status_code == 401:
            raise AuthenticationError(
                "Google Play API: Authentication failed. "
                "Check your service account JSON file."
            )

        if response.status_code == 403:
            raise PermissionError(
                "Google Play API: Insufficient permissions. "
                "Ensure the service account has 'View app information and download bulk reports' "
                "and 'Reply to reviews' permissions in Play Console."
            )

        if response.status_code == 404:
            raise AppNotFoundError(
                f"Google Play API: Package not found ({self._package_name}). "
                "Verify the package_name in your configuration."
            )

        raise UpstreamError(
            f"Google Play API: Unexpected status {response.status_code}",
            status_code=response.status_code,
        )

    @staticmethod
    def _parse_review(data: dict[str, Any], package_name: str) -> NormalizedReview | None:
        """Parse a raw API review into a NormalizedReview.

        Only parses user comments (skips developer replies).

        Args:
            data: Raw review dict from the API.
            package_name: Android package name.

        Returns:
            NormalizedReview instance, or None if no user comment found.
        """
        review_id = data.get("reviewId", "")
        comments = data.get("comments", [])
        now = datetime.now(tz=timezone.utc)

        # Find the user comment (not developer reply)
        user_comment: dict[str, Any] | None = None
        for comment in comments:
            if "userComment" in comment:
                user_comment = comment["userComment"]
                break

        if not user_comment:
            return None

        # Parse timestamp (seconds since epoch)
        last_modified = user_comment.get("lastModified", {})
        seconds = last_modified.get("seconds", 0)
        try:
            created_at = datetime.fromtimestamp(int(seconds), tz=timezone.utc)
        except (ValueError, OSError):
            created_at = now

        # Rating (starRating field)
        rating = int(user_comment.get("starRating", 0))

        # Version
        app_version = user_comment.get("appVersionName")

        # Text
        body = user_comment.get("text", "")

        # reviewer info
        reviewer_name = data.get("authorName")

        return NormalizedReview(
            id=review_id,
            source="google_play",
            app_identifier=package_name,
            rating=rating,
            title=None,  # Google Play reviews don't have titles
            body=body,
            locale=user_comment.get("reviewerLanguage"),
            created_at=created_at,
            app_version=app_version,
            raw_payload=data,
            fetched_at=now,
            reviewer_nickname=reviewer_name,
        )

    def fetch_reviews(
        self,
        since: datetime | None = None,
    ) -> AsyncGenerator[NormalizedReview, None]:
        """Fetch reviews from Google Play Developer API.

        IMPORTANT: This API only returns reviews from the past 7 days.
        If `since` is more than 7 days ago, it will be clamped to 7 days
        and a warning will be logged.

        Args:
            since: Only yield reviews created after this datetime.

        Returns:
            Async generator of NormalizedReview instances.
        """
        return self._async_gen(since=since)

    async def _async_gen(
        self,
        since: datetime | None = None,
    ) -> AsyncGenerator[NormalizedReview, None]:
        """Internal async generator for fetching reviews."""
        now = datetime.now(tz=timezone.utc)
        max_lookback = now - timedelta(days=MAX_LOOKBACK_DAYS)

        if since is not None and since < max_lookback:
            logger.warning(
                "Google Play API only returns reviews from the past 7 days. "
                "Clamping 'since' to 7 days ago. "
                "Please ensure this tool runs at least daily to avoid data gaps.",
                requested_since=since.isoformat(),
                clamped_since=max_lookback.isoformat(),
            )
            since = max_lookback

        url = f"{BASE_URL}/applications/{self._package_name}/reviews"
        params: dict[str, Any] = {"maxResults": MAX_RESULTS}

        async with httpx.AsyncClient(timeout=30.0) as client:
            while True:
                data = await self._request(client, url, params)
                reviews_data = data.get("reviews", [])

                for review_data in reviews_data:
                    review = self._parse_review(review_data, self._package_name)
                    if review is None:
                        continue

                    if since and review.created_at <= since:
                        continue

                    yield review

                # Handle pagination
                token_page = data.get("tokenPagination", {})
                next_token = token_page.get("nextPageToken")
                if next_token:
                    params = {"maxResults": MAX_RESULTS, "token": next_token}
                    await asyncio.sleep(self._request_delay)
                else:
                    break

    async def health_check(self) -> HealthStatus:
        """Check Google Play API connectivity.

        Returns:
            HealthStatus with connectivity result.
        """
        url = f"{BASE_URL}/applications/{self._package_name}/reviews"
        params: dict[str, Any] = {"maxResults": 1}

        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await self._request(client, url, params)
            latency = (time.monotonic() - start) * 1000
            return HealthStatus(
                source="google_play",
                healthy=True,
                message=f"Google Play API is reachable (package={self._package_name})",
                latency_ms=latency,
            )
        except (AuthenticationError, PermissionError, AppNotFoundError) as e:
            return HealthStatus(
                source="google_play",
                healthy=False,
                message=str(e),
            )
        except Exception as e:
            return HealthStatus(
                source="google_play",
                healthy=False,
                message=f"Unexpected error: {e}",
            )
