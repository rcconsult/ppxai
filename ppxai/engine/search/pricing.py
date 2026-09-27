"""Search-backend tool-cost pricing.

Moved out of `tools/builtin/web_premium.py` (ADR 0014 Decision 1), unchanged
in behaviour. Shared by the Perplexity and Gemini backends — DuckDuckGo is
free and never priced here.
"""

from __future__ import annotations

from ppxai.config import get_tool_pricing


def calculate_tool_cost(
    provider: str, tokens_in: int = 0, tokens_out: int = 0, query_count: int = 0
) -> float:
    """Calculate tool usage cost based on pricing model.

    Args:
        provider: Provider name ("perplexity" or "gemini_grounding")
        tokens_in: Input tokens (for per-token pricing)
        tokens_out: Output tokens (for per-token pricing)
        query_count: Number of queries (for per-query pricing)

    Returns:
        Estimated cost in USD
    """
    pricing = get_tool_pricing("web_search", provider)

    if not pricing:
        return 0.0

    pricing_model = pricing.get("model", "per_token")

    if pricing_model == "per_token":
        # Perplexity: per-million-token pricing
        input_price = pricing.get("input", 0.0)
        output_price = pricing.get("output", 0.0)
        input_cost = (tokens_in / 1_000_000) * input_price if input_price else 0.0
        output_cost = (tokens_out / 1_000_000) * output_price if output_price else 0.0
        return input_cost + output_cost

    elif pricing_model == "per_query":
        # Gemini grounding: `per_query` is USD per query, as the key says and
        # every shipped config states ("$35/1000 queries = $0.035 per
        # query"). Until v1.19.3 this divided by 1000 as if the value were a
        # per-thousand price, so each search was logged at 1/1000 of its
        # cost ($0.000035) and /cost under-reported Gemini grounding.
        per_query_price = pricing.get("per_query", 0.0)
        return query_count * per_query_price if per_query_price else 0.0

    return 0.0
