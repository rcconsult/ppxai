"""Shared reading of cached-input counts from provider usage objects.

OpenAI-wire and Gemini providers report cached input INSIDE their prompt
count, while `UsageStats.prompt_tokens` means UNCACHED input only. These
helpers pull the cached count out defensively (SDK objects or dicts, any
field absent or None) so each provider's parse stays a few lines.
"""

from __future__ import annotations

from typing import Any

from ..types import UsageStats


def get_field(obj: Any, name: str) -> Any:
    """`obj.name` or `obj[name]`, None when absent."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def as_count(value: Any) -> int:
    """Non-negative int, 0 for anything that is not a real number."""
    # bool and non-numerics (a Mock, a string) count as absent
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(0, int(value))


def cached_from_details(usage: Any, details_field: str, count_field: str = "cached_tokens") -> int:
    """`usage.<details_field>.<count_field>`, 0 when any link is missing."""
    return as_count(get_field(get_field(usage, details_field), count_field))


def split_cached_prompt(prompt_total: int, cached: int) -> tuple[int, int]:
    """(uncached_prompt, cached) with the cached part clamped to the total."""
    cached = max(0, min(cached, prompt_total))
    return prompt_total - cached, cached


def build_usage(
    prompt_total: int,
    completion_tokens: int,
    total_tokens: int,
    cached: int,
) -> UsageStats:
    """UsageStats from a provider whose prompt count INCLUDES cached input.

    `total_tokens` is left as the provider reported it: it already counts
    every input token once, which is the normalized meaning.
    """
    uncached, cached = split_cached_prompt(prompt_total, cached)
    return UsageStats(
        prompt_tokens=uncached,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        cache_read_input_tokens=cached,
    )


def oneshot_usage_dict(
    prompt_total: int, completion_tokens: int, total_tokens: int, cached: int = 0
) -> dict[str, int]:
    """The usage dict a provider's `oneshot()` returns, wire-stable.

    `/v1/oneshot` is a stable external contract, so `prompt_tokens` keeps
    its historical value here: the provider's own count, which INCLUDES
    cached input on OpenAI-wire and Gemini. The cached part rides along in
    extra keys (present only when there is any; `OneshotUsage` ignores
    them) so the cost recorder can bill it at the cached rate.
    """
    out = {
        "prompt_tokens": prompt_total,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }
    if cached > 0:
        uncached, cached = split_cached_prompt(prompt_total, cached)
        out["uncached_prompt_tokens"] = uncached
        out["cache_read_input_tokens"] = cached
    return out


def oneshot_usage_dict_from_sdk(usage_obj: Any) -> dict[str, int]:
    """`oneshot_usage_dict` from an OpenAI chat-completions usage object."""
    return oneshot_usage_dict(
        as_count(get_field(usage_obj, "prompt_tokens")),
        as_count(get_field(usage_obj, "completion_tokens")),
        as_count(get_field(usage_obj, "total_tokens")),
        cached_from_details(usage_obj, "prompt_tokens_details"),
    )


def oneshot_usage_dict_from_stats(stats: UsageStats) -> dict[str, int]:
    """`oneshot_usage_dict` from a normalized `UsageStats` (Gemini, Responses)."""
    return oneshot_usage_dict(
        stats.prompt_tokens + stats.cache_read_input_tokens,
        stats.completion_tokens,
        stats.total_tokens,
        stats.cache_read_input_tokens,
    )
