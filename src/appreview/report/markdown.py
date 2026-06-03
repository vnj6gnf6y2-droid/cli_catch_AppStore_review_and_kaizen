"""Markdown report generator."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from appreview.storage.models import ClassificationOrm, ClusterOrm, ReviewOrm, RunOrm


def _format_dt(dt: datetime | None) -> str:
    """Format a datetime as UTC string."""
    if dt is None:
        return "N/A"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def generate_markdown_report(
    run: RunOrm,
    app_config: Any,
    reviews: list[ReviewOrm],
    classifications: list[ClassificationOrm],
    clusters: list[ClusterOrm],
    previous_negative_ratio: float | None = None,
) -> str:
    """Generate a Markdown report from run data.

    Args:
        run: Run record.
        app_config: AppConfig instance.
        reviews: Reviews analyzed in this run.
        classifications: Classification results.
        clusters: Cluster results.
        previous_negative_ratio: Negative ratio from previous run for comparison.

    Returns:
        Markdown string.
    """
    total = len(reviews)
    if total == 0:
        return _empty_report(run, app_config)

    # Calculate stats
    negative_ids = {
        clf.review_id
        for clf in classifications
        if clf.sentiment == "negative"
    }
    negative_count = len(negative_ids)
    negative_ratio = negative_count / total if total > 0 else 0.0

    # Category counts (from negative reviews only)
    category_counts: Counter[str] = Counter()
    for clf in classifications:
        if clf.sentiment == "negative":
            category_counts[clf.category] += 1

    top_categories = category_counts.most_common(5)

    # Version trends
    version_stats: dict[str, dict[str, Any]] = {}
    for review in reviews:
        v = review.app_version or "unknown"
        if v not in version_stats:
            version_stats[v] = {"total": 0, "negative": 0, "categories": Counter()}
        version_stats[v]["total"] += 1

    for clf in classifications:
        review = next((r for r in reviews if r.id == clf.review_id), None)
        if review:
            v = review.app_version or "unknown"
            if v in version_stats and clf.sentiment == "negative":
                version_stats[v]["negative"] += 1
                version_stats[v]["categories"][clf.category] += 1

    # Sort versions (attempt semver, fallback to alpha)
    def version_key(v: str) -> tuple[int, ...]:
        try:
            parts = v.split(".")
            return tuple(int(p) for p in parts)
        except ValueError:
            return (0,)

    sorted_versions = sorted(
        version_stats.items(),
        key=lambda x: version_key(x[0]),
        reverse=True,
    )[:10]  # Top 10 versions

    # Build report
    lines: list[str] = []

    # Header
    lines.append(f"# AppReview Insight Report — {app_config.name}")
    lines.append(
        f"Generated: {_format_dt(datetime.now(tz=timezone.utc))}  |  Run ID: {run.id}"
    )
    lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append("")

    neg_ratio_pct = f"{negative_ratio:.0%}"
    if previous_negative_ratio is not None:
        diff = negative_ratio - previous_negative_ratio
        sign = "+" if diff >= 0 else ""
        neg_ratio_pct += f" (前回比 {sign}{diff:.0%})"

    top_cat_str = ", ".join(f"{cat} ({cnt})" for cat, cnt in top_categories[:3])

    lines.append(f"- **Reviews analyzed:** {total}")
    lines.append(f"- **Negative ratio:** {neg_ratio_pct}")
    lines.append(f"- **Top categories:** {top_cat_str or 'N/A'}")
    lines.append(f"- **LLM cost:** ${run.llm_cost_usd:.4f}")
    lines.append("")

    # Top Issues (clusters)
    if clusters:
        lines.append("## Top Issues")
        lines.append("")

        # Sort clusters by member count descending
        sorted_clusters = sorted(clusters, key=lambda c: c.member_count, reverse=True)

        for i, cluster in enumerate(sorted_clusters, 1):
            lines.append(
                f"### {i}. {cluster.title} ({cluster.category}, {cluster.member_count}件)"
            )
            lines.append("")

            if cluster.affected_versions:
                lines.append(
                    f"**Affected versions:** {', '.join(cluster.affected_versions)}"
                )
                lines.append("")

            if cluster.representative_text:
                lines.append("**Representative review:**")
                lines.append(f"> {cluster.representative_text}")
                lines.append("")

            if cluster.suggestions:
                lines.append("**Suggested improvements:**")
                for j, suggestion in enumerate(cluster.suggestions, 1):
                    lines.append(f"{j}. {suggestion}")
                lines.append("")

    # Version Trends
    if sorted_versions:
        lines.append("## Version Trends")
        lines.append("")
        lines.append("| Version | Reviews | Negative% | Top Issue |")
        lines.append("|---------|---------|-----------|-----------|")

        for version, stats in sorted_versions:
            v_total = stats["total"]
            v_negative = stats["negative"]
            v_neg_pct = f"{v_negative / v_total:.0%}" if v_total > 0 else "0%"
            top_issue = (
                stats["categories"].most_common(1)[0][0]
                if stats["categories"]
                else "N/A"
            )
            lines.append(
                f"| {version} | {v_total} | {v_neg_pct} | {top_issue} |"
            )

        lines.append("")

    # Methodology
    lines.append("## Methodology")
    lines.append("")
    lines.append(
        f"Classification model: {run.app_name or 'N/A'}  |  "
        f"Reviews fetched on {_format_dt(run.started_at)}."
    )
    lines.append("")
    lines.append(
        "_This report was generated by [appreview-insight](https://github.com/<owner>/appreview-insight)._"
    )

    return "\n".join(lines)


def _empty_report(run: RunOrm, app_config: Any) -> str:
    """Generate an empty report when no reviews were found."""
    return (
        f"# AppReview Insight Report — {app_config.name}\n"
        f"Generated: {_format_dt(datetime.now(tz=timezone.utc))}  |  Run ID: {run.id}\n\n"
        "## Summary\n\n"
        "No reviews found for the specified time period.\n"
    )
