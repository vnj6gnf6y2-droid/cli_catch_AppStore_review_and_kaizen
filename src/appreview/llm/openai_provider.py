"""OpenAI LLM provider implementation."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, ClassVar

from jinja2 import Template

from appreview.exceptions import LLMResponseError
from appreview.llm.base import ClassificationResult, ClusterResult, LLMProvider, LLMUsage
from appreview.llm.cost import get_openai_cost
from appreview.logging import get_logger

logger = get_logger(__name__)

# JSON Schema for classification response
CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "review_id": {"type": "string"},
                    "categories": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 2,
                    },
                    "sentiment": {
                        "type": "string",
                        "enum": ["positive", "negative", "neutral"],
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["review_id", "categories", "sentiment", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}

# JSON Schema for clustering response
CLUSTER_SCHEMA = {
    "type": "object",
    "properties": {
        "clusters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "review_ids": {"type": "array", "items": {"type": "string"}},
                    "representative_text": {"type": "string"},
                    "affected_versions": {"type": "array", "items": {"type": "string"}},
                    "suggestions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 3,
                    },
                },
                "required": [
                    "title",
                    "review_ids",
                    "representative_text",
                    "affected_versions",
                    "suggestions",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["clusters"],
    "additionalProperties": False,
}


class OpenAIProvider(LLMProvider):
    """LLM provider using OpenAI API with structured outputs."""

    name: ClassVar[str] = "openai"

    def __init__(
        self,
        api_key: str,
        classification_model: str = "gpt-4o-mini",
        suggestion_model: str = "gpt-4o",
        temperature: float = 0.2,
    ) -> None:
        """Initialize OpenAI provider.

        Args:
            api_key: OpenAI API key.
            classification_model: Model for classification tasks.
            suggestion_model: Model for clustering/suggestion tasks.
            temperature: Sampling temperature (lower = more deterministic).
        """
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key)
        self._classification_model = classification_model
        self._suggestion_model = suggestion_model
        self._temperature = temperature

    async def classify_batch(
        self,
        reviews: list[Any],
        categories: list[str],
        prompt_template: str,
    ) -> tuple[list[ClassificationResult], LLMUsage]:
        """Classify a batch of reviews using OpenAI structured outputs.

        Args:
            reviews: List of NormalizedReview instances.
            categories: List of valid category names.
            prompt_template: Jinja2 template for the classification prompt.

        Returns:
            Tuple of (classification results, usage stats).
        """
        template = Template(prompt_template)
        reviews_data = [
            {"id": r.id, "rating": r.rating, "title": r.title or "", "body": r.body}
            for r in reviews
        ]
        prompt = template.render(
            categories=categories,
            reviews=reviews_data,
        )

        logger.debug(
            "Sending classification batch to OpenAI",
            model=self._classification_model,
            review_count=len(reviews),
        )

        response = await self._client.chat.completions.create(
            model=self._classification_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=self._temperature,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "classification_response",
                    "strict": True,
                    "schema": CLASSIFY_SCHEMA,
                },
            },
        )

        content = response.choices[0].message.content or ""
        usage = response.usage

        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0
        cost = get_openai_cost(self._classification_model, input_tokens, output_tokens)

        llm_usage = LLMUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=self._classification_model,
            cost_usd=cost,
        )

        results = self._parse_classification_response(content, categories, reviews)
        return results, llm_usage

    def _parse_classification_response(
        self,
        content: str,
        categories: list[str],
        reviews: list[Any],
    ) -> list[ClassificationResult]:
        """Parse and validate classification response JSON.

        Falls back to 'other' category if response is invalid.

        Args:
            content: JSON string from LLM.
            categories: Valid category names.
            reviews: Original review list (for fallback).

        Returns:
            List of ClassificationResult instances.
        """
        try:
            data = json.loads(content)
            results_data = data.get("results", [])
        except json.JSONDecodeError:
            logger.warning("Failed to parse classification response JSON, using fallback")
            return self._fallback_classification(reviews)

        results = []
        review_ids = {r.id for r in reviews}

        for item in results_data:
            try:
                review_id = item["review_id"]
                if review_id not in review_ids:
                    continue

                raw_categories = item.get("categories", ["other"])
                # Validate categories and apply confidence threshold
                confidence = float(item.get("confidence", 0.0))

                if confidence < 0.5:
                    valid_categories = ["other"]
                else:
                    valid_categories = [
                        c for c in raw_categories if c in categories
                    ][:2]
                    if not valid_categories:
                        valid_categories = ["other"]

                sentiment = item.get("sentiment", "neutral")
                if sentiment not in ("positive", "negative", "neutral"):
                    sentiment = "neutral"

                results.append(
                    ClassificationResult(
                        review_id=review_id,
                        categories=valid_categories,
                        sentiment=sentiment,
                        confidence=confidence,
                    )
                )
            except (KeyError, ValueError, TypeError) as e:
                logger.debug("Skipping malformed classification item", error=str(e))

        # Fill in any missing reviews with fallback
        result_ids = {r.review_id for r in results}
        for review in reviews:
            if review.id not in result_ids:
                results.append(
                    ClassificationResult(
                        review_id=review.id,
                        categories=["other"],
                        sentiment="neutral",
                        confidence=0.0,
                    )
                )

        return results

    def _fallback_classification(self, reviews: list[Any]) -> list[ClassificationResult]:
        """Return default classifications for all reviews.

        Args:
            reviews: List of NormalizedReview instances.

        Returns:
            List of fallback ClassificationResult instances.
        """
        return [
            ClassificationResult(
                review_id=r.id,
                categories=["other"],
                sentiment="neutral",
                confidence=0.0,
            )
            for r in reviews
        ]

    async def cluster_and_suggest(
        self,
        reviews: list[Any],
        category: str,
        prompt_template: str,
    ) -> tuple[list[ClusterResult], LLMUsage]:
        """Cluster negative reviews and generate improvement suggestions.

        Args:
            reviews: List of NormalizedReview instances with negative sentiment.
            category: Category being analyzed.
            prompt_template: Jinja2 template for the clustering prompt.

        Returns:
            Tuple of (cluster results, usage stats).
        """
        template = Template(prompt_template)
        reviews_data = [
            {
                "id": r.id,
                "rating": r.rating,
                "body": r.body,
                "version": r.app_version or "unknown",
            }
            for r in reviews
        ]
        prompt = template.render(
            category=category,
            reviews=reviews_data,
        )

        logger.debug(
            "Sending clustering request to OpenAI",
            model=self._suggestion_model,
            category=category,
            review_count=len(reviews),
        )

        response = await self._client.chat.completions.create(
            model=self._suggestion_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=self._temperature,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "cluster_response",
                    "strict": True,
                    "schema": CLUSTER_SCHEMA,
                },
            },
        )

        content = response.choices[0].message.content or ""
        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0
        cost = get_openai_cost(self._suggestion_model, input_tokens, output_tokens)

        llm_usage = LLMUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=self._suggestion_model,
            cost_usd=cost,
        )

        clusters = self._parse_cluster_response(content)
        return clusters, llm_usage

    def _parse_cluster_response(self, content: str) -> list[ClusterResult]:
        """Parse clustering response JSON.

        Args:
            content: JSON string from LLM.

        Returns:
            List of ClusterResult instances.

        Raises:
            LLMResponseError: If response cannot be parsed.
        """
        try:
            data = json.loads(content)
            clusters_data = data.get("clusters", [])
        except json.JSONDecodeError as e:
            msg = f"Failed to parse cluster response JSON: {e}"
            raise LLMResponseError(msg) from e

        results = []
        for item in clusters_data:
            try:
                results.append(
                    ClusterResult(
                        title=item.get("title", "Unknown Issue"),
                        review_ids=item.get("review_ids", []),
                        representative_text=item.get("representative_text", ""),
                        affected_versions=item.get("affected_versions", []),
                        suggestions=item.get("suggestions", []),
                    )
                )
            except (KeyError, ValueError) as e:
                logger.debug("Skipping malformed cluster item", error=str(e))

        return results

    def estimate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        model: str,
    ) -> Decimal:
        """Estimate cost for OpenAI API call.

        Args:
            input_tokens: Number of input tokens.
            output_tokens: Number of output tokens.
            model: OpenAI model name.

        Returns:
            Estimated cost in USD.
        """
        return get_openai_cost(model, input_tokens, output_tokens)
