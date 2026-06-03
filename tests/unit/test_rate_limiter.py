"""Unit tests for Google Play rate limiter."""

from __future__ import annotations

import asyncio
import time

import pytest

from appreview.sources.google_play import TokenBucketRateLimiter


class TestTokenBucketRateLimiter:
    """Tests for token bucket rate limiter."""

    @pytest.mark.asyncio
    async def test_allows_up_to_capacity_requests(self) -> None:
        """Should allow requests up to bucket capacity without waiting."""
        limiter = TokenBucketRateLimiter(capacity=5.0, refill_rate=0.0)

        start = time.monotonic()
        for _ in range(5):
            await limiter.acquire()
        elapsed = time.monotonic() - start

        # All 5 should complete quickly (< 0.1s)
        assert elapsed < 0.1

    @pytest.mark.asyncio
    async def test_blocks_when_bucket_empty(self) -> None:
        """Should wait when bucket is empty and refill rate is slow."""
        # Very slow refill: 2 tokens per second
        limiter = TokenBucketRateLimiter(capacity=1.0, refill_rate=2.0)

        start = time.monotonic()
        await limiter.acquire()  # Uses the 1 token
        await limiter.acquire()  # Must wait for refill
        elapsed = time.monotonic() - start

        # Should have waited ~0.5 seconds for 1 token at 2/sec refill
        assert elapsed >= 0.4  # Allow some tolerance

    @pytest.mark.asyncio
    async def test_rate_limit_200_per_hour_roughly(self) -> None:
        """200 requests at 200/hour rate should complete instantly."""
        # 200 tokens, refill doesn't matter for initial burst
        limiter = TokenBucketRateLimiter(
            capacity=200.0,
            refill_rate=200 / 3600,
        )

        start = time.monotonic()
        for _ in range(200):
            await limiter.acquire()
        elapsed = time.monotonic() - start

        # All 200 tokens available immediately
        assert elapsed < 1.0

    @pytest.mark.asyncio
    async def test_tokens_refill_over_time(self) -> None:
        """Tokens should refill based on elapsed time."""
        limiter = TokenBucketRateLimiter(capacity=10.0, refill_rate=100.0)

        # Drain some tokens
        for _ in range(5):
            await limiter.acquire()

        # Wait for some refill
        await asyncio.sleep(0.05)  # 0.05s * 100/s = 5 tokens refilled

        # Check that we can acquire more without waiting
        start = time.monotonic()
        for _ in range(4):
            await limiter.acquire()
        elapsed = time.monotonic() - start

        assert elapsed < 0.1
