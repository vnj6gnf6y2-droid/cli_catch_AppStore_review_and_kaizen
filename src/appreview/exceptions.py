"""Custom exceptions for appreview-insight."""

from __future__ import annotations


class AppReviewError(Exception):
    """Base exception for appreview-insight."""

    exit_code: int = 1


class ConfigError(AppReviewError):
    """Configuration error (exit code 1)."""

    exit_code = 1

    def __init__(self, message: str, field: str | None = None) -> None:
        self.field = field
        super().__init__(message)


class AuthenticationError(AppReviewError):
    """Authentication failed (exit code 2)."""

    exit_code = 2


class PermissionError(AppReviewError):
    """Insufficient permissions (exit code 2)."""

    exit_code = 2


class AppNotFoundError(AppReviewError):
    """App not found in the store (exit code 3)."""

    exit_code = 3


class UpstreamError(AppReviewError):
    """Upstream API error after retries (exit code 3)."""

    exit_code = 3

    def __init__(self, message: str, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)


class RateLimitError(AppReviewError):
    """Rate limit exceeded (exit code 3)."""

    exit_code = 3

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        self.retry_after = retry_after
        super().__init__(message)


class LLMError(AppReviewError):
    """LLM provider error (exit code 4)."""

    exit_code = 4


class LLMResponseError(LLMError):
    """LLM returned an invalid or unparseable response."""

    pass


class CostLimitExceededError(AppReviewError):
    """Estimated cost exceeds configured limit (exit code 4)."""

    exit_code = 4

    def __init__(self, estimated: float, limit: float) -> None:
        self.estimated = estimated
        self.limit = limit
        super().__init__(
            f"Estimated cost ${estimated:.4f} exceeds limit ${limit:.4f}. "
            "Use -y to override."
        )


class UserAbortError(AppReviewError):
    """User aborted the operation (exit code 5)."""

    exit_code = 5
