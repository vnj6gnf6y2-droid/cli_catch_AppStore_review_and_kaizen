"""Shared pytest fixtures for appreview-insight tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from appreview.sources.base import NormalizedReview
from appreview.storage.migrations import run_migrations
from appreview.storage.models import ClassificationOrm, ClusterOrm, ReviewOrm, RunOrm

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def app_store_response() -> dict[str, Any]:
    """Load App Store API fixture response."""
    with (FIXTURES_DIR / "app_store_response.json").open() as f:
        return json.load(f)


@pytest.fixture
def google_play_response() -> dict[str, Any]:
    """Load Google Play API fixture response."""
    with (FIXTURES_DIR / "google_play_response.json").open() as f:
        return json.load(f)


@pytest.fixture
def sample_review() -> NormalizedReview:
    """Create a sample NormalizedReview for testing."""
    return NormalizedReview(
        id="test_review_001",
        source="app_store",
        app_identifier="1234567890",
        rating=1,
        title="App crashes on launch",
        body="After the update, the app crashes every time. Please fix this bug!",
        locale="en-US",
        detected_language="en",
        created_at=datetime(2026, 5, 28, 10, 0, 0, tzinfo=timezone.utc),
        app_version="2.3.1",
        territory="US",
        raw_payload={"id": "test_review_001", "type": "customerReviews"},
        fetched_at=datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def sample_reviews() -> list[NormalizedReview]:
    """Create a list of sample reviews for testing."""
    now = datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    return [
        NormalizedReview(
            id=f"review_{i:03d}",
            source="app_store",
            app_identifier="1234567890",
            rating=rating,
            title=title,
            body=body,
            detected_language="en",
            created_at=datetime(2026, 5, 28 + i % 3, 10, 0, 0, tzinfo=timezone.utc),
            app_version=version,
            raw_payload={},
            fetched_at=now,
        )
        for i, (rating, title, body, version) in enumerate([
            (1, "Crashes", "The app crashes on startup since the last update.", "2.3.1"),
            (1, "Still broken", "Crashes every time I open it. Useless app.", "2.3.1"),
            (5, "Love it", "Great app, very useful and easy to use.", "2.3.0"),
            (2, "Very slow", "Takes 10 seconds to load. Very slow performance.", "2.3.1"),
            (1, "Crash again", "Another update, another crash. Fix this please.", "2.3.2"),
            (4, "Good update", "The new features are nice.", "2.3.0"),
            (2, "Battery drain", "The app drains my battery too fast.", "2.3.1"),
            (1, "UI broken", "After update the buttons don't work properly.", "2.3.2"),
        ])
    ]


@pytest_asyncio.fixture
async def async_db_engine():
    """Create an in-memory SQLite engine for testing."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    await run_migrations(engine)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(async_db_engine):
    """Create a database session for testing."""
    async with AsyncSession(async_db_engine) as session:
        async with session.begin():
            yield session


@pytest.fixture
def sample_config_yaml(tmp_path: Path) -> Path:
    """Create a sample appreview.yaml config file."""
    content = """
apps:
  - name: "TestApp iOS"
    source: app_store
    app_id: "1234567890"
    territories: ["JP", "US"]

llm:
  provider: openai
  classification_model: gpt-4o-mini
  suggestion_model: gpt-4o
  max_cost_usd_per_run: 5.00
  batch_size: 20
  temperature: 0.2

analysis:
  categories:
    - performance
    - ui_ux
    - feature_request
    - bug_crash
    - billing
    - auth
    - notification
    - other
  min_reviews_for_cluster: 2
  pii_masking: true

output:
  formats:
    - markdown
    - json
  output_dir: ./reports
  filename_template: "{date}-{app_name}-report"

storage:
  database_path: ./appreview.db
  anonymize_reviewers: false

fetch:
  since_days: 7
  request_delay_ms: 0
"""
    config_path = tmp_path / "appreview.yaml"
    config_path.write_text(content)
    return config_path


@pytest.fixture
def fake_p8_key(tmp_path: Path) -> Path:
    """Create a fake .p8 key file for testing JWT generation.

    Returns:
        Path to a PEM key file with a valid EC key.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_path = tmp_path / "AuthKey_TEST.p8"
    key_path.write_bytes(pem)
    return key_path
