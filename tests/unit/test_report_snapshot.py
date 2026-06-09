"""Snapshot tests for Markdown report output."""

from __future__ import annotations

from datetime import UTC, datetime

from syrupy.assertion import SnapshotAssertion

from appreview.report.markdown import generate_markdown_report
from appreview.storage.models import ClassificationOrm, ClusterOrm, RunOrm


def _make_fixed_run() -> RunOrm:
    """Create a deterministic RunOrm for snapshot testing."""
    run = RunOrm()
    run.id = "fixed-run-id-for-snapshot"
    run.started_at = datetime(2026, 6, 3, 11, 58, 0, tzinfo=UTC)
    run.finished_at = datetime(2026, 6, 3, 12, 0, 0, tzinfo=UTC)
    run.status = "success"
    run.app_name = "TestApp iOS"
    run.reviews_fetched = 30
    run.reviews_classified = 28
    run.llm_cost_usd = 0.42
    run.error_message = None
    return run


def _make_fixed_reviews() -> list:
    """Create deterministic reviews for snapshot testing."""
    from appreview.storage.models import ReviewOrm

    reviews = []
    for i in range(10):
        r = ReviewOrm()
        r.id = f"snapshot_r{i:03d}"
        r.source = "app_store"
        r.app_identifier = "1234567890"
        r.rating = 1 if i < 7 else 5
        r.title = "Crashes after update" if i < 7 else "Love it"
        r.body = (
            "App crashes every time since update" if i < 7
            else "Works perfectly, very helpful"
        )
        r.locale = "en-US"
        r.detected_language = "en"
        r.created_at = datetime(2026, 5, 28 + (i % 3), tzinfo=UTC)
        r.updated_at = None
        r.app_version = "2.3.1" if i < 5 else "2.3.0"
        r.territory = "US"
        r.raw_payload = {}
        r.fetched_at = datetime(2026, 6, 1, tzinfo=UTC)
        r.reviewer_nickname = f"User{i}"
        reviews.append(r)
    return reviews


def _make_fixed_clfs(reviews: list) -> list:
    """Create deterministic classifications for snapshot testing."""
    clfs = []
    for i, r in enumerate(reviews):
        clf = ClassificationOrm()
        clf.id = i + 1
        clf.review_source = "app_store"
        clf.review_id = r.id
        clf.category = "bug_crash" if i < 7 else "ui_ux"
        clf.sentiment = "negative" if i < 7 else "positive"
        clf.confidence = 0.92 if i < 7 else 0.88
        clf.classified_at = datetime(2026, 6, 3, 12, 0, tzinfo=UTC)
        clf.model_used = "gpt-4o-mini"
        clfs.append(clf)
    return clfs


def _make_fixed_cluster(run_id: str) -> ClusterOrm:
    """Create a deterministic cluster for snapshot testing."""
    c = ClusterOrm()
    c.id = "fixed-cluster-id"
    c.run_id = run_id
    c.category = "bug_crash"
    c.title = "App crashes on launch after update"
    c.representative_text = "App crashes every time since update"
    c.member_count = 7
    c.affected_versions = ["2.3.1"]
    c.suggestions = [
        "Fix the initialization sequence in the startup code",
        "Add crash reporting to identify the root cause",
        "Consider rolling back 2.3.1 until the fix is ready",
    ]
    c.review_ids = [f"snapshot_r{i:03d}" for i in range(7)]
    c.created_at = datetime(2026, 6, 3, 12, 0, tzinfo=UTC)
    return c


class FakeSnapshotAppConfig:
    """App config for snapshot tests."""

    name = "TestApp iOS"
    source = "app_store"
    app_id = "1234567890"
    package_name = None


class TestReportSnapshot:
    """Snapshot tests to detect unintended report format changes."""

    def test_markdown_report_snapshot(self, snapshot: SnapshotAssertion) -> None:
        """Markdown report should match stored snapshot."""
        run = _make_fixed_run()
        reviews = _make_fixed_reviews()
        clfs = _make_fixed_clfs(reviews)
        clusters = [_make_fixed_cluster(run.id)]

        # Replace dynamic date in output for deterministic snapshot
        report = generate_markdown_report(
            run,
            FakeSnapshotAppConfig(),
            reviews,  # type: ignore[arg-type]
            clfs,
            clusters,
        )

        # Normalize the dynamic "Generated:" timestamp for stable snapshot
        import re
        report = re.sub(
            r"Generated: \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC",
            "Generated: 2026-06-03 12:00 UTC",
            report,
        )

        assert report == snapshot
