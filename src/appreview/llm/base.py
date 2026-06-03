"""Base types and protocols for LLM providers."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, ClassVar

from pydantic import BaseModel


class ClassificationResult(BaseModel):
    """Result of LLM classification for a single review."""

    review_id: str
    categories: list[str]
    sentiment: str  # "positive", "negative", "neutral"
    confidence: float


class ClusterResult(BaseModel):
    """Result of LLM clustering for a group of related negative reviews."""

    title: str
    review_ids: list[str]
    representative_text: str
    affected_versions: list[str]
    suggestions: list[str]


class LLMUsage(BaseModel):
    """Token usage stats from an LLM call."""

    input_tokens: int
    output_tokens: int
    model: str
    cost_usd: Decimal = Decimal("0")


class LLMProvider:
    """Abstract base for LLM providers.

    Concrete implementations: OpenAIProvider, AnthropicProvider, OllamaProvider.
    """

    name: ClassVar[str] = "base"

    async def classify_batch(
        self,
        reviews: list[Any],
        categories: list[str],
        prompt_template: str,
    ) -> tuple[list[ClassificationResult], LLMUsage]:
        """Classify a batch of reviews into categories.

        Args:
            reviews: List of NormalizedReview instances.
            categories: List of category names to classify into.
            prompt_template: Jinja2 template string for the classification prompt.

        Returns:
            Tuple of (list of ClassificationResult, LLMUsage).
        """
        raise NotImplementedError

    async def cluster_and_suggest(
        self,
        reviews: list[Any],
        category: str,
        prompt_template: str,
    ) -> tuple[list[ClusterResult], LLMUsage]:
        """Cluster negative reviews and generate improvement suggestions.

        Args:
            reviews: List of NormalizedReview instances (negative sentiment).
            category: Category being clustered.
            prompt_template: Jinja2 template string for the clustering prompt.

        Returns:
            Tuple of (list of ClusterResult, LLMUsage).
        """
        raise NotImplementedError

    def estimate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        model: str,
    ) -> Decimal:
        """Estimate cost for a given token count and model.

        Args:
            input_tokens: Number of input tokens.
            output_tokens: Number of output tokens.
            model: Model name string.

        Returns:
            Estimated cost in USD as Decimal.
        """
        raise NotImplementedError
