"""Structured Massive/Polygon client errors."""

from __future__ import annotations

from typing import Any


class MassiveError(Exception):
    """Base error for Massive/Polygon vendor access."""


class MassiveConfigError(MassiveError):
    """Raised when vendor configuration is missing or invalid."""


class MassiveTransportError(MassiveError):
    """Raised when the transport cannot complete an HTTP request."""


class MassiveTimeoutError(MassiveTransportError):
    """Raised when the provider request times out."""


class MassiveHTTPError(MassiveError):
    """Raised for non-successful provider HTTP responses."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        body: Any | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body
        self.retry_after_seconds = retry_after_seconds


class MassiveAuthError(MassiveHTTPError):
    """Raised when the provider rejects credentials."""


class MassiveRateLimitError(MassiveHTTPError):
    """Raised when rate limits remain after configured retry attempts."""


class MassiveServerError(MassiveHTTPError):
    """Raised when retryable server errors remain after retries."""


class MassiveMalformedPayloadError(MassiveError):
    """Raised when a provider payload does not match the expected endpoint shape."""
