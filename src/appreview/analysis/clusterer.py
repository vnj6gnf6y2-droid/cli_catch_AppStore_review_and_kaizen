"""Review clustering and suggestion generation pipeline."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from appreview.llm.base import ClusterResult, LLMProvider, LLMUsage
from appreview.logging import get_logger
from appreview.sources.base import NormalizedReview
from appreview.storage.models import ClassificationOrm, ReviewOrm

logger = get_logger(__name__)

DEFAULT_SUGGEST_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "suggest.md"
MAX_CONCURRENT_LLM_REQUESTS = 3


class ReviewClusterer:
    """Groups negative reviews by category and generates improvement suggestions."""

    def __init__(
        self,
        provider: LLMProvider,
        min_reviews_for_cluster: int = 3,
        prompt_path: Path | None = None,
    ) -> None:
        """Initialize the clusterer.

        Args:
            provider: LLM provider for clustering and suggestions.
            min_reviews_for_cluster: Minimum reviews to form a cluster.
            prompt_path: Path to custom suggest.md template.
        """
        self._provider = provider
        self._min_reviews = min_reviews_for_cluster
        self._prompt_path = prompt_path or DEFAULT_SUGGEST_PROMPT_PATH
        self._prompt_template = self._load_prompt()

    def _load_prompt(self) -> str:
        """Load the clustering prompt template."""
        if self._prompt_path.exists():
            return self._prompt_path.read_text(encoding="utf-8")
        return DEFAULT_SUGGEST_TEMPLATE

    @staticmethod
    def _orm_to_review(review_orm: ReviewOrm) -> NormalizedReview:
        """Convert ORM model to NormalizedReview domain object.

        Args:
            review_orm: ReviewOrm database model.

        Returns:
            NormalizedReview instance.
        """
        from appreview.sources.base import NormalizedReview as NR

        return NR(
            id=review_orm.id,
            source=review_orm.source,  # type: ignore[arg-type]
            app_identifier=review_orm.app_identifier,
            rating=review_orm.rating,
            title=review_orm.title,
            body=review_orm.body,
            locale=review_orm.locale,
            detected_language=review_orm.detected_language,
            created_at=review_orm.created_at,
            updated_at=review_orm.updated_at,
            app_version=review_orm.app_version,
            territory=review_orm.territory,
            raw_payload=review_orm.raw_payload,
            fetched_at=review_orm.fetched_at,
            reviewer_nickname=review_orm.reviewer_nickname,
        )

    def group_by_category(
        self,
        reviews: list[ReviewOrm],
        classifications: list[ClassificationOrm],
    ) -> dict[str, list[NormalizedReview]]:
        """Group negative reviews by their primary category.

        Args:
            reviews: All reviews to consider.
            classifications: Classification results.

        Returns:
            Dict mapping category name to list of NormalizedReview.
        """
        # Build index: review_id -> list of classifications
        clf_index: dict[str, list[ClassificationOrm]] = {}
        for clf in classifications:
            if clf.sentiment == "negative":
                if clf.review_id not in clf_index:
                    clf_index[clf.review_id] = []
                clf_index[clf.review_id].append(clf)

        # Build index: review_id -> ReviewOrm
        review_index = {r.id: r for r in reviews}

        # Group by category (use first/primary category)
        category_groups: dict[str, list[NormalizedReview]] = {}
        for review_id, clfs in clf_index.items():
            if review_id not in review_index:
                continue
            # Use the category with highest confidence
            primary = max(clfs, key=lambda c: c.confidence)
            category = primary.category

            if category not in category_groups:
                category_groups[category] = []
            category_groups[category].append(
                self._orm_to_review(review_index[review_id])
            )

        return category_groups

    async def cluster_all(
        self,
        reviews: list[ReviewOrm],
        classifications: list[ClassificationOrm],
        run_id: str,
    ) -> tuple[list[dict[str, Any]], LLMUsage]:
        """Cluster negative reviews across all categories.

        Args:
            reviews: All reviews from the database.
            classifications: All classification results.
            run_id: Current run UUID.

        Returns:
            Tuple of (list of cluster dicts for DB storage, aggregate LLMUsage).
        """
        category_groups = self.group_by_category(reviews, classifications)

        # Filter categories with enough reviews
        eligible_categories = {
            cat: reviews_in_cat
            for cat, reviews_in_cat in category_groups.items()
            if len(reviews_in_cat) >= self._min_reviews
        }

        if not eligible_categories:
            logger.info(
                "No categories with enough negative reviews for clustering",
                min_required=self._min_reviews,
            )
            return [], LLMUsage(input_tokens=0, output_tokens=0, model="none")

        logger.info(
            "Clustering negative reviews by category",
            categories=list(eligible_categories.keys()),
        )

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM_REQUESTS)

        async def cluster_category(
            category: str, cat_reviews: list[NormalizedReview]
        ) -> tuple[list[ClusterResult], LLMUsage]:
            async with semaphore:
                return await self._provider.cluster_and_suggest(
                    cat_reviews, category, self._prompt_template
                )

        tasks = [
            cluster_category(cat, cat_reviews)
            for cat, cat_reviews in eligible_categories.items()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_clusters: list[dict[str, Any]] = []
        total_input = 0
        total_output = 0
        total_cost = 0.0
        model_used = ""
        now = datetime.now(tz=UTC)

        for (category, _cat_reviews), result in zip(
            eligible_categories.items(), results, strict=False
        ):
            if isinstance(result, Exception):
                logger.error(
                    "Clustering failed for category",
                    category=category,
                    error=str(result),
                )
                continue

            cluster_results, usage = result
            total_input += usage.input_tokens
            total_output += usage.output_tokens
            total_cost += float(usage.cost_usd)
            model_used = usage.model

            for cluster in cluster_results:
                # Filter clusters below minimum threshold
                if len(cluster.review_ids) < self._min_reviews:
                    logger.debug(
                        "Discarding small cluster",
                        title=cluster.title,
                        count=len(cluster.review_ids),
                    )
                    continue

                all_clusters.append({
                    "id": str(uuid.uuid4()),
                    "run_id": run_id,
                    "category": category,
                    "title": cluster.title,
                    "representative_text": cluster.representative_text,
                    "member_count": len(cluster.review_ids),
                    "affected_versions": cluster.affected_versions,
                    "suggestions": cluster.suggestions,
                    "review_ids": cluster.review_ids,
                    "created_at": now,
                })

        aggregate_usage = LLMUsage(
            input_tokens=total_input,
            output_tokens=total_output,
            model=model_used,
            cost_usd=round(total_cost, 6),  # type: ignore[arg-type]
        )

        logger.info(
            "Clustering complete",
            clusters=len(all_clusters),
            cost_usd=float(aggregate_usage.cost_usd),
        )

        return all_clusters, aggregate_usage


DEFAULT_SUGGEST_TEMPLATE = """\
You are an expert mobile app product manager. Analyze these negative app reviews
in the "{{ category }}" category.

Group them by the specific problem they describe. For each group:
1. Give a concise title describing the problem
2. Pick the most representative review text
3. List affected app versions (if mentioned)
4. Provide 1-3 concrete, actionable improvement suggestions

Reviews:
{% for review in reviews %}
Review ID: {{ review.id }}
Rating: {{ review.rating }}/5
Version: {{ review.version }}
Text: {{ review.body }}
---
{% endfor %}

Respond with JSON matching this schema exactly:
{
  "clusters": [
    {
      "title": "Brief problem description",
      "review_ids": ["id1", "id2"],
      "representative_text": "Most representative review text",
      "affected_versions": ["1.2.3"],
      "suggestions": ["Actionable fix 1", "Actionable fix 2"]
    }
  ]
}
"""
