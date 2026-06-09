"""Review classification pipeline."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from appreview.analysis.language import LanguageDetector
from appreview.analysis.pii import mask_pii
from appreview.llm.base import ClassificationResult, LLMProvider, LLMUsage
from appreview.logging import get_logger
from appreview.sources.base import NormalizedReview

logger = get_logger(__name__)

# Default prompt template path
DEFAULT_CLASSIFY_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "classify.md"

# Concurrency limit for LLM requests
MAX_CONCURRENT_LLM_REQUESTS = 3


class ReviewClassifier:
    """Classifies reviews into categories using LLM."""

    def __init__(
        self,
        provider: LLMProvider,
        categories: list[str],
        batch_size: int = 20,
        pii_masking: bool = True,
        prompt_path: Path | None = None,
    ) -> None:
        """Initialize the classifier.

        Args:
            provider: LLM provider to use.
            categories: List of category names for classification.
            batch_size: Number of reviews per LLM request (max 20 recommended).
            pii_masking: Whether to mask PII before sending to LLM.
            prompt_path: Path to custom classify.md template. Uses default if None.
        """
        self._provider = provider
        self._categories = categories
        self._batch_size = min(batch_size, 20)
        self._pii_masking = pii_masking
        self._prompt_path = prompt_path or DEFAULT_CLASSIFY_PROMPT_PATH
        self._lang_detector = LanguageDetector()
        self._prompt_template = self._load_prompt()

    def _load_prompt(self) -> str:
        """Load the classification prompt template."""
        if self._prompt_path.exists():
            return self._prompt_path.read_text(encoding="utf-8")
        # Fallback inline template
        return DEFAULT_CLASSIFY_TEMPLATE

    def _prepare_review(self, review: NormalizedReview) -> NormalizedReview:
        """Apply language detection and PII masking to a review.

        Args:
            review: Original review.

        Returns:
            Modified review with language detected and PII masked.
        """
        body = review.body
        if self._pii_masking:
            body = mask_pii(body)

        detected_language = review.detected_language
        if detected_language is None:
            detected_language = self._lang_detector.detect(body)

        return review.model_copy(
            update={
                "body": body,
                "detected_language": detected_language,
            }
        )

    async def classify_reviews(
        self,
        reviews: list[NormalizedReview],
    ) -> tuple[list[dict[str, Any]], LLMUsage]:
        """Classify all reviews in batches.

        Args:
            reviews: List of reviews to classify.

        Returns:
            Tuple of (list of classification dicts, total LLMUsage).
        """
        if not reviews:
            return [], LLMUsage(input_tokens=0, output_tokens=0, model="none")

        # Apply preprocessing
        prepared = [self._prepare_review(r) for r in reviews]

        # Split into batches
        batches = [
            prepared[i : i + self._batch_size]
            for i in range(0, len(prepared), self._batch_size)
        ]

        logger.info(
            "Classifying reviews",
            total=len(reviews),
            batches=len(batches),
            batch_size=self._batch_size,
        )

        # Process batches with concurrency limit
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM_REQUESTS)

        async def classify_batch(
            batch: list[NormalizedReview],
        ) -> tuple[list[ClassificationResult], LLMUsage]:
            async with semaphore:
                return await self._provider.classify_batch(
                    batch, self._categories, self._prompt_template
                )

        tasks = [classify_batch(batch) for batch in batches]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        all_results: list[dict[str, Any]] = []
        total_input = 0
        total_output = 0
        total_cost = 0.0
        model_used = ""

        now = datetime.now(tz=UTC)

        for i, result in enumerate(batch_results):
            if isinstance(result, Exception):
                logger.error(
                    "Batch classification failed",
                    batch_index=i,
                    error=str(result),
                )
                # Add fallback for failed batch
                for review in batches[i]:
                    all_results.append({
                        "review_source": review.source,
                        "review_id": review.id,
                        "category": "other",
                        "sentiment": "neutral",
                        "confidence": 0.0,
                        "classified_at": now,
                        "model_used": "fallback",
                    })
                continue

            classifications, usage = result
            total_input += usage.input_tokens
            total_output += usage.output_tokens
            total_cost += float(usage.cost_usd)
            model_used = usage.model

            for clf in classifications:
                # Each review can have multiple categories
                review = next(
                    (r for r in batches[i] if r.id == clf.review_id), None
                )
                if review is None:
                    continue

                for category in clf.categories:
                    all_results.append({
                        "review_source": review.source,
                        "review_id": clf.review_id,
                        "category": category,
                        "sentiment": clf.sentiment,
                        "confidence": clf.confidence,
                        "classified_at": now,
                        "model_used": model_used,
                    })

        aggregate_usage = LLMUsage(
            input_tokens=total_input,
            output_tokens=total_output,
            model=model_used,
            cost_usd=round(total_cost, 6),  # type: ignore[arg-type]
        )

        logger.info(
            "Classification complete",
            classified=len(all_results),
            cost_usd=float(aggregate_usage.cost_usd),
        )

        return all_results, aggregate_usage


# Inline fallback template (used when prompts/classify.md doesn't exist)
DEFAULT_CLASSIFY_TEMPLATE = """\
You are an app review classifier. Classify each review into categories and determine sentiment.

Available categories: {{ categories | join(', ') }}

Rules:
- Assign 1-2 categories per review (most relevant first)
- If confidence < 0.5, use "other"
- sentiment: "positive" (rating 4-5, praise), "negative" (rating 1-2, complaints),
  "neutral" (mixed/rating 3)

Reviews to classify:
{% for review in reviews %}
Review ID: {{ review.id }}
Rating: {{ review.rating }}/5
{% if review.title %}Title: {{ review.title }}{% endif %}
Body: {{ review.body }}
---
{% endfor %}

Respond with JSON matching this schema exactly:
{
  "results": [
    {"review_id": "...", "categories": ["cat1"],
     "sentiment": "positive|negative|neutral", "confidence": 0.0-1.0}
  ]
}
"""
