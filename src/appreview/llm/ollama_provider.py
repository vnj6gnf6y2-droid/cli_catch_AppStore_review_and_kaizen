"""Ollama LLM provider implementation (local, no external network)."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, ClassVar

import httpx
from jinja2 import Template

from appreview.exceptions import LLMError, LLMResponseError
from appreview.llm.base import ClassificationResult, ClusterResult, LLMProvider, LLMUsage
from appreview.logging import get_logger

logger = get_logger(__name__)

# JSON example included in prompt to guide Ollama (structured output is less reliable)
CLASSIFY_JSON_EXAMPLE = """{
  "results": [
    {
      "review_id": "example_id",
      "categories": ["bug_crash", "performance"],
      "sentiment": "negative",
      "confidence": 0.85
    }
  ]
}"""

CLUSTER_JSON_EXAMPLE = """{
  "clusters": [
    {
      "title": "App crashes on launch",
      "review_ids": ["id1", "id2"],
      "representative_text": "The app crashes every time I open it.",
      "affected_versions": ["2.3.0"],
      "suggestions": ["Fix the initialization sequence", "Add crash reporting"]
    }
  ]
}"""


class OllamaProvider(LLMProvider):
    """LLM provider using local Ollama API.

    NOTE: When using Ollama, all processing is performed locally.
    No review data is sent to external servers.
    """

    name: ClassVar[str] = "ollama"

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        classification_model: str = "llama3",
        suggestion_model: str = "llama3",
        temperature: float = 0.2,
    ) -> None:
        """Initialize Ollama provider.

        Args:
            base_url: Ollama server base URL.
            classification_model: Model for classification.
            suggestion_model: Model for clustering/suggestions.
            temperature: Sampling temperature.
        """
        self._base_url = base_url.rstrip("/")
        self._classification_model = classification_model
        self._suggestion_model = suggestion_model
        self._temperature = temperature

    async def _generate(
        self,
        model: str,
        prompt: str,
    ) -> tuple[str, int, int]:
        """Send a generation request to Ollama.

        Args:
            model: Model name.
            prompt: Full prompt text.

        Returns:
            Tuple of (response text, input tokens, output tokens).

        Raises:
            LLMError: If Ollama is unreachable or returns an error.
        """
        url = f"{self._base_url}/api/generate"
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": self._temperature,
            },
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                response = await client.post(url, json=payload)
            except httpx.ConnectError as e:
                msg = (
                    f"Cannot connect to Ollama at {self._base_url}. "
                    "Is Ollama running? Start with: ollama serve"
                )
                raise LLMError(msg) from e

            if response.status_code != 200:
                msg = f"Ollama returned status {response.status_code}: {response.text[:200]}"
                raise LLMError(msg)

            data = response.json()
            text = data.get("response", "")
            # Ollama returns eval_count (output) and prompt_eval_count (input)
            input_tokens = data.get("prompt_eval_count", 0)
            output_tokens = data.get("eval_count", 0)

            return text, input_tokens, output_tokens

    async def classify_batch(
        self,
        reviews: list[Any],
        categories: list[str],
        prompt_template: str,
    ) -> tuple[list[ClassificationResult], LLMUsage]:
        """Classify reviews using Ollama with JSON format enforcement.

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
        base_prompt = template.render(categories=categories, reviews=reviews_data)

        # Add explicit JSON instructions for Ollama
        prompt = (
            f"{base_prompt}\n\n"
            f"You MUST respond with valid JSON only, no other text. "
            f"Follow this exact schema:\n{CLASSIFY_JSON_EXAMPLE}"
        )

        text, input_tokens, output_tokens = await self._generate(
            self._classification_model, prompt
        )

        llm_usage = LLMUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=self._classification_model,
            cost_usd=Decimal("0"),  # Ollama is free (local)
        )

        results = self._parse_classification(text, categories, reviews)
        return results, llm_usage

    def _parse_classification(
        self,
        text: str,
        categories: list[str],
        reviews: list[Any],
    ) -> list[ClassificationResult]:
        """Parse Ollama classification response.

        Args:
            text: Raw text from Ollama.
            categories: Valid category names.
            reviews: Original reviews for fallback.

        Returns:
            List of ClassificationResult instances.
        """
        try:
            # Try to extract JSON from response
            data = json.loads(text)
            results_data = data.get("results", [])
        except json.JSONDecodeError:
            logger.warning("Ollama returned invalid JSON, using fallback classification")
            return [
                ClassificationResult(
                    review_id=r.id,
                    categories=["other"],
                    sentiment="neutral",
                    confidence=0.0,
                )
                for r in reviews
            ]

        results = []
        review_ids = {r.id for r in reviews}

        for item in results_data:
            try:
                review_id = item.get("review_id", "")
                if review_id not in review_ids:
                    continue

                confidence = float(item.get("confidence", 0.0))
                if confidence < 0.5:
                    valid_categories = ["other"]
                else:
                    raw_cats = item.get("categories", ["other"])
                    valid_categories = [c for c in raw_cats if c in categories][:2]
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
            except (KeyError, ValueError, TypeError):
                pass

        # Fill missing
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
        """Cluster reviews using Ollama.

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
        base_prompt = template.render(category=category, reviews=reviews_data)
        prompt = (
            f"{base_prompt}\n\n"
            f"You MUST respond with valid JSON only, no other text. "
            f"Follow this exact schema:\n{CLUSTER_JSON_EXAMPLE}"
        )

        text, input_tokens, output_tokens = await self._generate(
            self._suggestion_model, prompt
        )

        llm_usage = LLMUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=self._suggestion_model,
            cost_usd=Decimal("0"),
        )

        try:
            data = json.loads(text)
            clusters_data = data.get("clusters", [])
        except json.JSONDecodeError as e:
            msg = f"Ollama returned invalid JSON for clustering: {e}"
            raise LLMResponseError(msg) from e

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
            except (KeyError, ValueError):
                pass

        return clusters, llm_usage

    def estimate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        model: str,
    ) -> Decimal:
        """Ollama is free (local). Always returns 0.

        Args:
            input_tokens: Ignored.
            output_tokens: Ignored.
            model: Ignored.

        Returns:
            Decimal("0")
        """
        return Decimal("0")
