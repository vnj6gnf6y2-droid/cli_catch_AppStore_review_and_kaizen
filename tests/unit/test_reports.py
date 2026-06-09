"""Unit tests for report generation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from appreview.report.json_output import generate_json_report
from appreview.report.markdown import generate_markdown_report
from appreview.storage.models import ClassificationOrm, ClusterOrm, RunOrm


def _make_run(run_id: str | None = None) -> RunOrm:
    """Create a sample RunOrm for testing."""
    run = RunOrm()
    run.id = run_id or str(uuid.uuid4())
    run.started_at = datetime(2026, 6, 3, 12, 0, 0, tzinfo=UTC)
    run.finished_at = datetime(2026, 6, 3, 12, 5, 0, tzinfo=UTC)
    run.status = "success"
    run.app_name = "TestApp"
    run.reviews_fetched = 50
    run.reviews_classified = 45
    run.llm_cost_usd = 0.0423
    run.error_message = None
    return run


def _make_review_orm(
    review_id: str,
    source: str = "app_store",
    rating: int = 1,
    body: str = "Test review body.",
    version: str = "2.3.1",
) -> object:
    """Create a sample ReviewOrm for testing."""
    from appreview.storage.models import ReviewOrm
    r = ReviewOrm()
    r.id = review_id
    r.source = source
    r.app_identifier = "1234567890"
    r.rating = rating
    r.title = "Test Review" if rating < 3 else "Great App"
    r.body = body
    r.locale = "en-US"
    r.detected_language = "en"
    r.created_at = datetime(2026, 5, 28, tzinfo=UTC)
    r.updated_at = None
    r.app_version = version
    r.territory = "US"
    r.raw_payload = {}
    r.fetched_at = datetime(2026, 6, 1, tzinfo=UTC)
    r.reviewer_nickname = "TestUser"
    return r


def _make_clf(
    review_id: str,
    source: str = "app_store",
    category: str = "bug_crash",
    sentiment: str = "negative",
    confidence: float = 0.9,
) -> ClassificationOrm:
    """Create a sample ClassificationOrm for testing."""
    clf = ClassificationOrm()
    clf.id = 1
    clf.review_source = source
    clf.review_id = review_id
    clf.category = category
    clf.sentiment = sentiment
    clf.confidence = confidence
    clf.classified_at = datetime(2026, 6, 3, 12, 0, tzinfo=UTC)
    clf.model_used = "gpt-4o-mini"
    return clf


def _make_cluster(
    run_id: str,
    category: str = "bug_crash",
    title: str = "App crashes on launch",
    member_count: int = 5,
) -> ClusterOrm:
    """Create a sample ClusterOrm for testing."""
    c = ClusterOrm()
    c.id = str(uuid.uuid4())
    c.run_id = run_id
    c.category = category
    c.title = title
    c.representative_text = "The app crashes every time I try to open it."
    c.member_count = member_count
    c.affected_versions = ["2.3.1", "2.3.2"]
    c.suggestions = [
        "Fix the initialization sequence",
        "Add crash reporting",
    ]
    c.review_ids = [f"review_{i}" for i in range(member_count)]
    c.created_at = datetime(2026, 6, 3, 12, 0, tzinfo=UTC)
    return c


class FakeAppConfig:
    """Fake app config for testing."""

    def __init__(self) -> None:
        self.name = "TestApp iOS"
        self.source = "app_store"
        self.app_id = "1234567890"
        self.package_name = None


class TestMarkdownReport:
    """Tests for Markdown report generation."""

    def test_generates_valid_markdown(self) -> None:
        """Should generate a Markdown string with expected sections."""
        run = _make_run()
        app_cfg = FakeAppConfig()
        reviews = [_make_review_orm(f"r{i}", rating=1 if i % 2 == 0 else 5) for i in range(10)]
        clfs = [
            _make_clf(f"r{i}", sentiment="negative" if i % 2 == 0 else "positive")
            for i in range(10)
        ]
        clusters = [_make_cluster(run.id)]

        result = generate_markdown_report(run, app_cfg, reviews, clfs, clusters)  # type: ignore[arg-type]

        assert "# AppReview Insight Report" in result
        assert "TestApp iOS" in result
        assert "## Summary" in result
        assert "## Top Issues" in result
        assert "## Version Trends" in result
        assert "## Methodology" in result

    def test_shows_cluster_title_and_suggestions(self) -> None:
        """Cluster titles and suggestions should appear in report."""
        run = _make_run()
        app_cfg = FakeAppConfig()
        reviews = [_make_review_orm("r1", rating=1)]
        clfs = [_make_clf("r1")]
        clusters = [_make_cluster(run.id, title="App crashes on launch")]

        result = generate_markdown_report(run, app_cfg, reviews, clfs, clusters)  # type: ignore[arg-type]

        assert "App crashes on launch" in result
        assert "Fix the initialization sequence" in result

    def test_empty_reviews_returns_empty_report(self) -> None:
        """No reviews should return an empty report message."""
        run = _make_run()
        app_cfg = FakeAppConfig()

        result = generate_markdown_report(run, app_cfg, [], [], [])  # type: ignore[arg-type]

        assert "No reviews found" in result

    def test_run_id_in_report(self) -> None:
        """Run ID should appear in the report header."""
        run_id = "test-run-id-12345"
        run = _make_run(run_id)
        app_cfg = FakeAppConfig()
        reviews = [_make_review_orm("r1")]
        clfs = [_make_clf("r1")]

        result = generate_markdown_report(run, app_cfg, reviews, clfs, [])  # type: ignore[arg-type]

        assert run_id in result

    def test_cost_in_report(self) -> None:
        """LLM cost should appear in summary."""
        run = _make_run()
        app_cfg = FakeAppConfig()
        reviews = [_make_review_orm("r1")]
        clfs = [_make_clf("r1")]

        result = generate_markdown_report(run, app_cfg, reviews, clfs, [])  # type: ignore[arg-type]

        assert "0.04" in result  # $0.0423


class TestJSONReport:
    """Tests for JSON report generation."""

    def test_generates_valid_json(self) -> None:
        """Should generate valid JSON with schema_version."""
        import json

        run = _make_run()
        app_cfg = FakeAppConfig()
        reviews = [_make_review_orm(f"r{i}") for i in range(5)]
        clfs = [_make_clf(f"r{i}") for i in range(5)]
        clusters = [_make_cluster(run.id)]

        result = generate_json_report(run, app_cfg, reviews, clfs, clusters)  # type: ignore[arg-type]

        data = json.loads(result)  # Should not raise
        assert data["schema_version"] == "0.1"
        assert data["run_id"] == run.id
        assert "summary" in data
        assert "clusters" in data
        assert "version_trends" in data

    def test_summary_includes_review_count(self) -> None:
        """Summary should include correct review count."""
        import json

        run = _make_run()
        app_cfg = FakeAppConfig()
        reviews = [_make_review_orm(f"r{i}") for i in range(7)]
        clfs = [_make_clf(f"r{i}") for i in range(7)]

        result = generate_json_report(run, app_cfg, reviews, clfs, [])  # type: ignore[arg-type]

        data = json.loads(result)
        assert data["summary"]["reviews_analyzed"] == 7

    def test_negative_ratio_calculated_correctly(self) -> None:
        """Negative ratio should be calculated from classifications."""
        import json

        run = _make_run()
        app_cfg = FakeAppConfig()
        reviews = [_make_review_orm(f"r{i}") for i in range(4)]
        clfs = [
            _make_clf("r0", sentiment="negative"),
            _make_clf("r1", sentiment="negative"),
            _make_clf("r2", sentiment="positive"),
            _make_clf("r3", sentiment="neutral"),
        ]

        result = generate_json_report(run, app_cfg, reviews, clfs, [])  # type: ignore[arg-type]

        data = json.loads(result)
        assert data["summary"]["negative_ratio"] == 0.5  # 2/4
