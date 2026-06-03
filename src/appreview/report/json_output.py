"""JSON report generator."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from appreview.storage.models import ClassificationOrm, ClusterOrm, ReviewOrm, RunOrm

SCHEMA_VERSION = "0.1"


def generate_json_report(
    run: RunOrm,
    app_config: Any,
    reviews: list[ReviewOrm],
    classifications: list[ClassificationOrm],
    clusters: list[ClusterOrm],
) -> str:
    """Generate a JSON report from run data.

    Args:
        run: Run record.
        app_config: AppConfig instance.
        reviews: Reviews analyzed in this run.
        classifications: Classification results.
        clusters: Cluster results.

    Returns:
        JSON string.
    """
    total = len(reviews)
    negative_ids = {
        clf.review_id
        for clf in classifications
        if clf.sentiment == "negative"
    }
    negative_count = len(negative_ids)
    negative_ratio = negative_count / total if total > 0 else 0.0

    category_counts: Counter[str] = Counter()
    for clf in classifications:
        if clf.sentiment == "negative":
            category_counts[clf.category] += 1

    top_categories = [
        {"category": cat, "count": cnt}
        for cat, cnt in category_counts.most_common(10)
    ]

    # Version trends
    version_stats: dict[str, dict[str, Any]] = {}
    for review in reviews:
        v = review.app_version or "unknown"
        if v not in version_stats:
            version_stats[v] = {"total": 0, "negative": 0, "top_category": Counter()}
        version_stats[v]["total"] += 1

    for clf in classifications:
        review = next((r for r in reviews if r.id == clf.review_id), None)
        if review:
            v = review.app_version or "unknown"
            if v in version_stats and clf.sentiment == "negative":
                version_stats[v]["negative"] += 1
                version_stats[v]["top_category"][clf.category] += 1

    version_trends = []
    for version, stats in sorted(version_stats.items()):
        v_total = stats["total"]
        v_neg = stats["negative"]
        top_cat = stats["top_category"].most_common(1)
        version_trends.append({
            "version": version,
            "reviews": v_total,
            "negative_count": v_neg,
            "negative_ratio": round(v_neg / v_total, 4) if v_total > 0 else 0.0,
            "top_issue": top_cat[0][0] if top_cat else None,
        })

    # Clusters
    clusters_data = []
    for cluster in sorted(clusters, key=lambda c: c.member_count, reverse=True):
        clusters_data.append({
            "id": cluster.id,
            "category": cluster.category,
            "title": cluster.title,
            "member_count": cluster.member_count,
            "affected_versions": cluster.affected_versions,
            "representative_text": cluster.representative_text,
            "suggestions": cluster.suggestions,
            "review_ids": cluster.review_ids,
        })

    source = app_config.source if hasattr(app_config, "source") else "unknown"
    identifier = (
        app_config.app_id
        if source == "app_store"
        else app_config.package_name or ""
    )

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run.id,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "app": {
            "name": app_config.name,
            "source": source,
            "identifier": identifier,
        },
        "summary": {
            "reviews_analyzed": total,
            "negative_count": negative_count,
            "negative_ratio": round(negative_ratio, 4),
            "top_categories": top_categories,
            "llm_cost_usd": round(run.llm_cost_usd, 6),
        },
        "clusters": clusters_data,
        "version_trends": version_trends,
    }

    return json.dumps(report, ensure_ascii=False, indent=2)
