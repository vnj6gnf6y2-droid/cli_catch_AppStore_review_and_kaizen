"""LLM pricing tables.

Prices are per 1,000 tokens (input and output separately).
These are hardcoded approximations — always verify with official pricing pages.

# 料金は2026-06-03 時点。最新は各社公式を確認のこと。
# OpenAI: https://platform.openai.com/docs/pricing
# Anthropic: https://www.anthropic.com/pricing
# Ollama: local, no cost
"""

from __future__ import annotations

from decimal import Decimal

# Price per 1K tokens: {model: (input_price, output_price)}
# 料金は2026-06-03 時点。最新は各社公式を確認のこと。
OPENAI_PRICES: dict[str, tuple[Decimal, Decimal]] = {
    "gpt-4o": (Decimal("0.0025"), Decimal("0.010")),
    "gpt-4o-mini": (Decimal("0.00015"), Decimal("0.0006")),
    "gpt-4-turbo": (Decimal("0.010"), Decimal("0.030")),
    "gpt-4": (Decimal("0.030"), Decimal("0.060")),
    "gpt-3.5-turbo": (Decimal("0.0005"), Decimal("0.0015")),
    "o1": (Decimal("0.015"), Decimal("0.060")),
    "o1-mini": (Decimal("0.003"), Decimal("0.012")),
    "o3-mini": (Decimal("0.0011"), Decimal("0.0044")),
}

# 料金は2026-06-03 時点。最新は各社公式を確認のこと。
ANTHROPIC_PRICES: dict[str, tuple[Decimal, Decimal]] = {
    "claude-3-5-sonnet-20241022": (Decimal("0.003"), Decimal("0.015")),
    "claude-3-5-haiku-20241022": (Decimal("0.00080"), Decimal("0.004")),
    "claude-3-opus-20240229": (Decimal("0.015"), Decimal("0.075")),
    "claude-3-sonnet-20240229": (Decimal("0.003"), Decimal("0.015")),
    "claude-3-haiku-20240307": (Decimal("0.00025"), Decimal("0.00125")),
}


def get_openai_cost(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    """Calculate OpenAI API cost.

    Args:
        model: OpenAI model name.
        input_tokens: Number of input tokens.
        output_tokens: Number of output tokens.

    Returns:
        Estimated cost in USD.
    """
    # Try exact match first, then prefix match
    prices = OPENAI_PRICES.get(model)
    if prices is None:
        for key in OPENAI_PRICES:
            if model.startswith(key) or key.startswith(model.split("-")[0]):
                prices = OPENAI_PRICES[key]
                break

    if prices is None:
        # Default to gpt-4o-mini pricing if unknown
        prices = OPENAI_PRICES["gpt-4o-mini"]

    input_price, output_price = prices
    return (
        Decimal(input_tokens) / 1000 * input_price
        + Decimal(output_tokens) / 1000 * output_price
    )


def get_anthropic_cost(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    """Calculate Anthropic API cost.

    Args:
        model: Anthropic model name.
        input_tokens: Number of input tokens.
        output_tokens: Number of output tokens.

    Returns:
        Estimated cost in USD.
    """
    prices = ANTHROPIC_PRICES.get(model)
    if prices is None:
        # Default to haiku pricing if unknown
        prices = ANTHROPIC_PRICES["claude-3-5-haiku-20241022"]

    input_price, output_price = prices
    return (
        Decimal(input_tokens) / 1000 * input_price
        + Decimal(output_tokens) / 1000 * output_price
    )


def estimate_tokens(text: str) -> int:
    """Rough token count estimate (4 chars ≈ 1 token for English).

    For non-Latin scripts (CJK), 2 chars ≈ 1 token.

    Args:
        text: Input text.

    Returns:
        Estimated token count.
    """
    # Count CJK characters
    cjk_count = sum(
        1 for c in text if "\u4e00" <= c <= "\u9fff" or "\u3040" <= c <= "\u30ff"
    )
    latin_count = len(text) - cjk_count

    return cjk_count // 2 + latin_count // 4
