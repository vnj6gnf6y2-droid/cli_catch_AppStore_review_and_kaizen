"""Unit tests for LLM cost calculation."""

from __future__ import annotations

from decimal import Decimal

from appreview.llm.cost import estimate_tokens, get_anthropic_cost, get_openai_cost


class TestOpenAICost:
    """Tests for OpenAI cost calculation."""

    def test_gpt4o_mini_cost(self) -> None:
        """GPT-4o-mini should use correct pricing."""
        cost = get_openai_cost("gpt-4o-mini", 1000, 500)
        # 1000 input at $0.00015/1K + 500 output at $0.0006/1K
        expected = Decimal("0.00015") + Decimal("0.0003")
        assert cost == expected

    def test_gpt4o_cost(self) -> None:
        """GPT-4o should use correct pricing."""
        cost = get_openai_cost("gpt-4o", 1000, 1000)
        # 1000 input at $0.0025/1K + 1000 output at $0.010/1K
        expected = Decimal("0.0025") + Decimal("0.010")
        assert cost == expected

    def test_zero_tokens_returns_zero(self) -> None:
        """Zero tokens should return zero cost."""
        cost = get_openai_cost("gpt-4o-mini", 0, 0)
        assert cost == Decimal("0")

    def test_unknown_model_uses_default(self) -> None:
        """Unknown model should fall back to a default pricing."""
        cost = get_openai_cost("unknown-model-xyz", 1000, 1000)
        assert cost > Decimal("0")

    def test_cost_is_decimal(self) -> None:
        """Cost should be returned as Decimal for precision."""
        cost = get_openai_cost("gpt-4o-mini", 500, 300)
        assert isinstance(cost, Decimal)


class TestAnthropicCost:
    """Tests for Anthropic cost calculation."""

    def test_haiku_cost(self) -> None:
        """Claude Haiku should use correct pricing."""
        cost = get_anthropic_cost("claude-3-5-haiku-20241022", 1000, 500)
        # 1000 * 0.00080/1K + 500 * 0.004/1K
        expected = Decimal("0.00080") + Decimal("0.002")
        assert cost == expected

    def test_unknown_model_uses_default(self) -> None:
        """Unknown Anthropic model should use fallback pricing."""
        cost = get_anthropic_cost("claude-unknown", 1000, 1000)
        assert cost > Decimal("0")


class TestEstimateTokens:
    """Tests for token count estimation."""

    def test_english_text(self) -> None:
        """English text should estimate ~4 chars per token."""
        text = "a" * 400  # 400 chars ≈ 100 tokens
        assert estimate_tokens(text) == 100

    def test_japanese_text(self) -> None:
        """Japanese CJK text should estimate ~2 chars per token."""
        text = "あ" * 200  # 200 CJK chars ≈ 100 tokens
        assert estimate_tokens(text) == 100

    def test_empty_text(self) -> None:
        """Empty text should return 0 tokens."""
        assert estimate_tokens("") == 0

    def test_mixed_text(self) -> None:
        """Mixed text should combine CJK and latin estimation."""
        text = "Hello" + "あいう"  # 5 latin + 3 CJK
        result = estimate_tokens(text)
        # 5 // 4 = 1, 3 // 2 = 1 → 2
        assert result == 2
