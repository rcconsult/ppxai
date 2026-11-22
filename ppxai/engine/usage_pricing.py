"""The one place a `UsageStats` becomes dollars.

Every site that prices a turn (single request, tool loop, `/task` run,
oneshot recording) calls `price_usage`, so the three input classes
(uncached, cache write, cache read) cannot be dropped at one site while
another remembers them. See `UsageStats` for what each field means.
"""

from __future__ import annotations

from ..config import calculate_cost
from .types import UsageStats


def price_usage(usage: UsageStats, model: str, provider: str | None = None) -> float:
    """Estimated USD for `usage` (model tokens only; tool costs are separate)."""
    return calculate_cost(
        usage.prompt_tokens,
        usage.completion_tokens,
        model,
        provider,
        cache_write_tokens=usage.cache_creation_input_tokens,
        cache_read_tokens=usage.cache_read_input_tokens,
    )
