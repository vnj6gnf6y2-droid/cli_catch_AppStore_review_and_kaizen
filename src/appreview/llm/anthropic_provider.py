"""Anthropic LLM provider implementation."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, ClassVar

from jinja2 import Template

from appreview.llm.base import ClassificationResult, ClusterResult, LLMProvider, LLMUsage
from appreview.llm.cost import get_anthropic_cost
from appreview.logging import get_logger

logger = get_logger(__name__)

CLASSIFY_TOOL_SCHEMA = {
    "name": "submit_classifications",
    "description": "Submit the classification results for the provided reviews.",
    "input_schema": {
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
                        "confidence": {"type": "number"},
                    },
                    "required": ["review_id", "categories", "sentiment", "confidence"],
                },
            }
        },
        "required": ["results"],
    },
}

CLUSTER_TOOL_SCHEMA = {
    "name": "submit_clusters",
    "description": "Submit the clustering results with improvement suggestions.",
    "input_schema": {
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
                        "suggestions": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": [
                        "title",
                        "review_ids",
                        "representative_text",
                        "affected_versions",
                        "suggestions",
                    ],
                },
            }
        },
        "required": ["clusters"],
    },
}


class AnthropicProvider(LLMProvider):
    """LLM provider using Anthropic Claude API with tool use for JSON enforcement."""

    name: ClassVar[str] = "anthropic"

    def __init__(
        self,
        api_key: str,
        classification_model: str = "claude-3-5-haiku-20241022",
        suggestion_model: str = "claude-3-5-sonnet-20241022",
        temperature: float = 0.2,
    ) -> None:
        """Initialize Anthropic provider.

        Args:
            api_key: Anthropic API key.
            classification_model: Model for classification tasks.
            suggestion_model: Model for clustering/suggestion tasks.
            temperature: Sampling temperature.
        """
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(api_key=api_key)
        self._classification_model = classification_model
        self._suggestion_model = suggestion_model
        self._temperature = temperature

    async def classify_batch(
        self,
        reviews: list[Any],
        categories: list[str],
        prompt_template: str,
    ) -> tuple[list[ClassificationResult], LLMUsage]:
        """Classify reviews using Anthropic tool use for JSON enforcement.

        Args:
            reviews: List of NormalizedReview instances.
            categories: Valid category names.
            prompt_template: Jinja2 template string.

        Returns:
            Tuple of (classification results, usage stats).
        """
        template = Template(prompt_template)
        reviews_data = [
            {"id": r.id, "rating": r.rating, "title": r.title or "", "body": r.body}
            for r in reviews
        ]
        prompt = template.render(categories=categories, reviews=reviews_data)

        response = await self._client.messages.create(
            model=self._classification_model,
            max_tokens=4096,
            temperature=self._temperature,
            tools=[CLASSIFY_TOOL_SCHEMA],  # type: ignore[list-item]
            tool_choice={"type": "tool", "name": "submit_classifications"},
            messages=[{"role": "user", "content": prompt}],
        )

        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        cost = get_anthropic_cost(self._classification_model, input_tokens, output_tokens)

        llm_usage = LLMUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=self._classification_model,
            cost_usd=cost,
        )

        # Extract tool use result
        tool_input: dict[str, Any] = {}
        for block in response.content:
            if block.type == "tool_use" and block.name == "submit_classifications":
                tool_input = block.input  # type: ignore[assignment]
                break

        results = self._parse_classification_results(
            tool_input.get("results", []), categories, reviews
        )
        return results, llm_usage

    def _parse_classification_results(
        self,
        results_data: list[dict[str, Any]],
        categories: list[str],
        reviews: list[Any],
    ) -> list[ClassificationResult]:
        """Parse classification results from tool input.

        Args:
            results_data: Raw results from tool use.
            categories: Valid category names.
            reviews: Original reviews for fallback.

        Returns:
            List of ClassificationResult instances.
        """
        results = []
        review_ids = {r.id for r in reviews}

        for item in results_data:
            try:
                review_id = item["review_id"]
                if review_id not in review_ids:
                    continue

                confidence = float(item.get("confidence", 0.0))
                if confidence < 0.5:
                    valid_categories = ["other"]
                else:
                    raw_categories = item.get("categories", ["other"])
                    valid_categories = [c for c in raw_categories if c in categories][:2]
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
                logger.debug("Skipping malformed item", error=str(e))

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

    async def cluster_and_suggest(
        self,
        reviews: list[Any],
        category: str,
        prompt_template: str,
    ) -> tuple[list[ClusterResult], LLMUsage]:
        """Cluster negative reviews using Anthropic tool use.

        Args:
            reviews: List of NormalizedReview instances.
            category: Category being analyzed.
            prompt_template: Jinja2 template string.

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
        prompt = template.render(category=category, reviews=reviews_data)

        response = await self._client.messages.create(
            model=self._suggestion_model,
            max_tokens=8192,
            temperature=self._temperature,
            tools=[CLUSTER_TOOL_SCHEMA],  # type: ignore[list-item]
            tool_choice={"type": "tool", "name": "submit_clusters"},
            messages=[{"role": "user", "content": prompt}],
        )

        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        cost = get_anthropic_cost(self._suggestion_model, input_tokens, output_tokens)

        llm_usage = LLMUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=self._suggestion_model,
            cost_usd=cost,
        )

        tool_input: dict[str, Any] = {}
        for block in response.content:
            if block.type == "tool_use" and block.name == "submit_clusters":
                tool_input = block.input  # type: ignore[assignment]
                break

        clusters_data = tool_input.get("clusters", [])
        clusters = []
        for item in clusters_data:
            try:
                clusters.append(
                    ClusterResult(
                        title=item.get("title", "Unknown Issue"),
                        review_ids=item.get("review_ids", []),
                        representative_text=item.get("representative_text", ""),
                        affected_versions=item.get("affected_versions", []),
                        suggestions=item.get("suggestions", []),
                    )
                )
            except (KeyError, ValueError) as e:
                logger.debug("Skipping malformed cluster", error=str(e))

        return clusters, llm_usage

    def estimate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        model: str,
    ) -> Decimal:
        """Estimate cost for Anthropic API call.

        Args:
            input_tokens: Number of input tokens.
            output_tokens: Number of output tokens.
            model: Anthropic model name.

        Returns:
            Estimated cost in USD.
        """
        return get_anthropic_cost(model, input_tokens, output_tokens)
