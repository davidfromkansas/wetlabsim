"""What model calls cost, where we know it. Shared by the model proxy (which stops a run at its
budget) and the run timeline (which shows where a run's money went)."""
from __future__ import annotations

# Dollars per million tokens (input, output, cache read, cache write), by model family: Anthropic's
# list prices for the current models (Opus 5.5, Sonnet 5.5, Haiku 5.5, Fable 5.1). Cache writes are
# taken as 1.25x input (5-minute cache); Haiku's cache read as 0.1x input.
ANTHROPIC_PRICES = {"opus": (4.0, 20.0, 0.20, 5.0), "sonnet": (2.0, 10.0, 0.20, 2.5),
                    "haiku": (0.10, 0.50, 0.01, 0.125), "fable": (10.0, 50.0, 0.25, 12.5)}


def anthropic_cost(model: str, usage: dict) -> float:
    """Dollars for one Anthropic API call, from its usage block."""
    p = next((v for k, v in ANTHROPIC_PRICES.items() if k in (model or "").lower()), ANTHROPIC_PRICES["opus"])
    return (usage.get("input_tokens", 0) * p[0] + usage.get("output_tokens", 0) * p[1]
            + usage.get("cache_read_input_tokens", 0) * p[2]
            + usage.get("cache_creation_input_tokens", 0) * p[3]) / 1e6
