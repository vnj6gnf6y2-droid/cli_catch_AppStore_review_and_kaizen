"""JWT helper for App Store Connect API authentication."""

from __future__ import annotations

import time
from pathlib import Path

import jwt


class AppStoreJWT:
    """JWT token manager for App Store Connect API.

    Generates ES256-signed JWTs and caches them until 80% of their
    lifetime has elapsed, then regenerates.

    See: https://developer.apple.com/documentation/appstoreconnectapi/generating_tokens_for_api_requests
    """

    # Token TTL in seconds (Apple max is 1200 = 20 minutes)
    TOKEN_TTL: int = 1200
    # Regenerate when 80% of TTL has elapsed
    REFRESH_THRESHOLD: float = 0.8

    def __init__(self, issuer_id: str, key_id: str, private_key_path: Path) -> None:
        """Initialize the JWT manager.

        Args:
            issuer_id: App Store Connect Issuer ID.
            key_id: App Store Connect Key ID.
            private_key_path: Path to the .p8 private key file.
        """
        self._issuer_id = issuer_id
        self._key_id = key_id
        self._private_key = private_key_path.read_text()
        self._cached_token: str | None = None
        self._cached_iat: float = 0.0

    def get_token(self) -> str:
        """Get a valid JWT, regenerating if necessary.

        Returns:
            Signed JWT string ready for Authorization header.
        """
        now = time.time()
        elapsed = now - self._cached_iat
        refresh_at = self.TOKEN_TTL * self.REFRESH_THRESHOLD

        if self._cached_token is None or elapsed >= refresh_at:
            self._cached_token = self._generate_token()
            self._cached_iat = now

        return self._cached_token

    def _generate_token(self) -> str:
        """Generate a new signed JWT.

        Returns:
            Signed JWT string.
        """
        now = int(time.time())
        payload = {
            "iss": self._issuer_id,
            "iat": now,
            "exp": now + self.TOKEN_TTL,
            "aud": "appstoreconnect-v1",
        }
        headers = {
            "kid": self._key_id,
            "alg": "ES256",
        }
        return jwt.encode(  # type: ignore[return-value]
            payload,
            self._private_key,
            algorithm="ES256",
            headers=headers,
        )
