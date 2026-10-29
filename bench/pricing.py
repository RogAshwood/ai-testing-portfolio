"""pricing.py: token prices for cost reporting, in USD per million tokens.

Source: OpenAI pricing page as supplied by Roger on 2026-10-24 (standard input
and output prices; cached-input prices are not used because runs are not
cached). A model without a price here is reported with cost None, never guessed.

To confirm: Days 2 and 3 used the judge id 'gpt-6-sol', but the price table
lists 'gpt-6.1-sol'. Until confirmed, 'gpt-6-sol' uses the 'gpt-6.1-sol' price
and every cost line marks it provisional (PROVISIONAL below).

Change history:
  2026-10-24  v1  first version (Day 4).
"""

from __future__ import annotations

PRICES_PER_M = {                       # model: (input, output)
    "gpt-6-luna": (0.10, 0.50),
    "gpt-6.1-sol": (2.00, 10.00),
    "gpt-6-sol": (2.00, 10.00),        # provisional: assumed equal to gpt-6.1-sol
    "gpt-6-astra": (10.00, 50.00),
}
PROVISIONAL = {"gpt-6-sol"}


def cost_usd(model: str, input_tokens: int | None, output_tokens: int | None) -> float | None:
    """Cost of one or more calls, or None if the model has no price or tokens are missing."""
    if model not in PRICES_PER_M or input_tokens is None or output_tokens is None:
        return None
    p_in, p_out = PRICES_PER_M[model]
    return round((input_tokens * p_in + output_tokens * p_out) / 1_000_000, 6)
