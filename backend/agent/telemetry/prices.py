"""OpenRouter model prices (USD per million tokens).

Hand-curated. OpenRouter's billing is the source of truth — these numbers
exist for the `vellum usage` display only. Update when a model is added.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


MODEL_PRICES: dict[str, dict[str, float]] = {
    # Anthropic via OpenRouter
    "anthropic/claude-opus-4.6":    {"input": 15.00, "output": 75.00},
    "anthropic/claude-sonnet-4.6":  {"input":  3.00, "output": 15.00},
    "anthropic/claude-haiku-4.5":   {"input":  1.00, "output":  5.00},
    # OpenAI via OpenRouter
    "openai/gpt-5.4":               {"input":  2.50, "output": 15.00},
    "openai/gpt-5.4-mini":          {"input":  0.75, "output":  4.50},
    # Google via OpenRouter
    "google/gemini-3-pro-preview":  {"input":  2.00, "output": 12.00},
    "google/gemini-3-flash-preview":{"input":  0.50, "output":  3.00},
    "google/gemma-4-31b-it":        {"input":  0.20, "output":  0.30},
    "google/gemma-3-12b-it":        {"input":  0.05, "output":  0.10},
    # Qwen
    "qwen/qwen3.5-35b-a3b":         {"input":  0.16, "output":  1.30},
    "qwen/qwen3.6-plus":            {"input":  0.33, "output":  1.95},
    # Misc cheap fallbacks
    "minimax/minimax-m2.5":         {"input":  0.12, "output":  0.99},
    "z-ai/glm-5.1":                 {"input":  0.95, "output":  3.15},
}


def compute_cost_usd(model: str, in_tokens: int, out_tokens: int) -> float:
    """Compute usd cost for one call. Unknown models price at zero."""
    if model not in MODEL_PRICES:
        logger.debug("no price entry for model %s — recording zero cost", model)
        return 0.0
    p = MODEL_PRICES[model]
    return (in_tokens / 1_000_000) * p["input"] + (out_tokens / 1_000_000) * p["output"]
