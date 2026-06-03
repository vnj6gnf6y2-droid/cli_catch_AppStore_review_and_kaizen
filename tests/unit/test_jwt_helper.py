"""Unit tests for JWT helper."""

from __future__ import annotations

import time
from pathlib import Path

import jwt as pyjwt
import pytest

from appreview.sources.jwt_helper import AppStoreJWT


class TestAppStoreJWT:
    """Tests for JWT token generation and caching."""

    def test_token_contains_required_claims(self, fake_p8_key: Path) -> None:
        """JWT must contain iss, iat, exp, aud claims."""
        jwt_helper = AppStoreJWT(
            issuer_id="test-issuer-123",
            key_id="TEST1234",
            private_key_path=fake_p8_key,
        )
        token = jwt_helper.get_token()

        # Decode without verification to inspect claims
        decoded = pyjwt.decode(token, options={"verify_signature": False})
        assert decoded["iss"] == "test-issuer-123"
        assert decoded["aud"] == "appstoreconnect-v1"
        assert "iat" in decoded
        assert "exp" in decoded
        assert decoded["exp"] > decoded["iat"]

    def test_token_uses_es256_algorithm(self, fake_p8_key: Path) -> None:
        """JWT must be signed with ES256 algorithm."""
        jwt_helper = AppStoreJWT(
            issuer_id="test-issuer",
            key_id="KEY001",
            private_key_path=fake_p8_key,
        )
        token = jwt_helper.get_token()

        header = pyjwt.get_unverified_header(token)
        assert header["alg"] == "ES256"
        assert header["kid"] == "KEY001"

    def test_token_expiry_is_1200_seconds(self, fake_p8_key: Path) -> None:
        """JWT exp must be 1200 seconds after iat."""
        jwt_helper = AppStoreJWT(
            issuer_id="issuer",
            key_id="key",
            private_key_path=fake_p8_key,
        )
        before = int(time.time())
        token = jwt_helper.get_token()
        after = int(time.time())

        decoded = pyjwt.decode(token, options={"verify_signature": False})
        assert decoded["iat"] >= before
        assert decoded["iat"] <= after
        assert decoded["exp"] - decoded["iat"] == AppStoreJWT.TOKEN_TTL

    def test_token_is_cached(self, fake_p8_key: Path) -> None:
        """get_token() should return the same token if not expired."""
        jwt_helper = AppStoreJWT(
            issuer_id="issuer",
            key_id="key",
            private_key_path=fake_p8_key,
        )
        token1 = jwt_helper.get_token()
        token2 = jwt_helper.get_token()
        assert token1 == token2

    def test_token_regenerated_after_threshold(self, fake_p8_key: Path) -> None:
        """Token must be regenerated when 80% of TTL has elapsed."""
        jwt_helper = AppStoreJWT(
            issuer_id="issuer",
            key_id="key",
            private_key_path=fake_p8_key,
        )
        token1 = jwt_helper.get_token()

        # Simulate that 81% of TTL has passed
        jwt_helper._cached_iat = time.time() - (AppStoreJWT.TOKEN_TTL * 0.81)

        token2 = jwt_helper.get_token()
        # Tokens should be different since we regenerated
        assert token1 != token2
