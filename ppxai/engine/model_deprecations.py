"""
Model deprecation tracking — canonical table for the /doctor advisor.

Phase 2.4 (v1.17.4). Maintains a single source of truth for:
    - Which models are dead (shut down in the past) and must be removed
    - Which models are deprecated with an upcoming shutdown date
    - Which fresh models users should consider adopting

The table is consulted by the /doctor slash command (`commands/doctor.py`)
and the optional startup warning in the Rich TUI. It is **read-only**
from the command's perspective — /doctor never writes to user config.
Updates to this table happen in source code, not at runtime.

Sources:
    - Gemini: https://ai.google.dev/gemini-api/docs/deprecations
    - OpenAI: https://developers.openai.com/api/docs/deprecations
                + https://deprecations.info/v1/deprecations.json (cross-check)
    - Perplexity: https://docs.perplexity.ai/changelog/changelog
    - Anthropic: https://docs.anthropic.com/en/docs/about-claude/model-deprecations

Verification date: 2026-04-12.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Deprecation:
    """A single deprecation entry.

    Attributes:
        status: "shutdown" when the date has passed (model is dead),
                "deprecated" when still running with a future shutdown.
                The advisor computes this at query time from `shutdown_date`
                so the table itself doesn't need maintenance as dates pass.
        shutdown_date: ISO-format date the model becomes unavailable.
        replacement: Recommended model to migrate to. Shown in the /doctor
                     output as the remediation hint.
        reason: Optional short description of WHY the model was
                deprecated (API change, successor launch, etc.) to give
                users context they can use when deciding urgency.
    """
    shutdown_date: str  # ISO 8601 YYYY-MM-DD
    replacement: str
    reason: str = ""


# =============================================================================
# Gemini deprecations — verified 2026-04-12
# =============================================================================

GEMINI_DEPRECATIONS: Dict[str, Deprecation] = {
    "gemini-3-pro-preview": Deprecation(
        shutdown_date="2026-03-09",
        replacement="gemini-3.1-pro-preview",
        reason="Preview graduated to 3.1-pro; preview endpoint retired.",
    ),
    "gemini-2.0-flash": Deprecation(
        shutdown_date="2026-06-01",
        replacement="gemini-3-flash-preview",
        reason="Gemini 2.0 family end-of-life; 3.x offers better performance at similar cost.",
    ),
    "gemini-2.0-flash-lite": Deprecation(
        shutdown_date="2026-06-01",
        replacement="gemini-3.1-flash-lite",
        reason="Gemini 2.0 family end-of-life.",
    ),
    "gemini-2.5-pro": Deprecation(
        shutdown_date="2026-06-17",
        replacement="gemini-3.1-pro-preview",
        reason="Gemini 2.5 Pro retiring; 3.1 Pro delivers SWE-Bench 80.6% vs 2.5-Pro's ~70%.",
    ),
    "gemini-2.5-flash": Deprecation(
        shutdown_date="2026-06-17",
        replacement="gemini-3-flash-preview",
        reason="Gemini 2.5 Flash retiring; 3-flash-preview has 100% benchmark score.",
    ),
    "gemini-2.5-flash-lite": Deprecation(
        shutdown_date="2026-07-22",
        replacement="gemini-3.1-flash-lite",
        reason="2.5 Flash Lite retiring; 3.1 Flash Lite same price tier, better quality.",
    ),
    "gemini-3.1-flash-lite-preview": Deprecation(
        shutdown_date="2026-05-25",
        replacement="gemini-3.1-flash-lite",
        reason="Preview graduated to GA; identical model architecture, only the identifier changes.",
    ),
    "gemini-2.5-flash-image": Deprecation(
        shutdown_date="2026-10-02",
        replacement="gemini-3.1-flash-image-preview",
        reason="2.5 image generation retired; Nano Banana 2 is the successor.",
    ),
}


# =============================================================================
# OpenAI deprecations — verified 2026-04-12
# =============================================================================
#
# NONE of the models shipped in `ppxai-config.example.json` are scheduled for
# shutdown in 2026: the widely-reported "GPT-4o API shutdown" is specifically
# the `chatgpt-4o-latest` alias (not the base `gpt-4o` API model). Likewise
# `codex-mini-latest` is a distinct alias from our shipped `gpt-5.1-codex-mini`.
#
# This table is primarily for /doctor to warn users who still reference the
# deprecated model IDs in their OWN local configs (hand-written configs that
# pre-date the example file regeneration, or migrations from third-party
# tooling that used the older aliases).

OPENAI_DEPRECATIONS: Dict[str, Deprecation] = {
    # ----- Already shut down (status auto-transitions to "shutdown") -----
    "chatgpt-4o-latest": Deprecation(
        shutdown_date="2026-02-17",
        replacement="gpt-5.1-chat-latest",
        reason=(
            "ChatGPT-4o alias retired from API. Use base 'gpt-4o' or migrate "
            "to 'gpt-5.1-chat-latest' / 'gpt-5.4'."
        ),
    ),
    "codex-mini-latest": Deprecation(
        shutdown_date="2026-02-12",
        replacement="gpt-5.1-codex-mini",
        reason=(
            "codex-mini-latest alias retired. Use the versioned "
            "'gpt-5.1-codex-mini' or newer Codex variants."
        ),
    ),
    "gpt-4-0314": Deprecation(
        shutdown_date="2026-03-26",
        replacement="gpt-5",
        reason="Original GPT-4 snapshot retired from API.",
    ),
    "gpt-4-0125-preview": Deprecation(
        shutdown_date="2026-03-26",
        replacement="gpt-5",
        reason="GPT-4 preview snapshot retired.",
    ),
    "gpt-4-1106-preview": Deprecation(
        shutdown_date="2026-03-26",
        replacement="gpt-5",
        reason="GPT-4 preview snapshot retired.",
    ),
    "gpt-4-turbo-preview": Deprecation(
        shutdown_date="2026-03-26",
        replacement="gpt-5",
        reason="GPT-4 Turbo preview retired.",
    ),

    # ----- Upcoming: Realtime + Audio preview APIs (2026-05-07) -----
    "gpt-4o-realtime-preview": Deprecation(
        shutdown_date="2026-05-07",
        replacement="gpt-realtime-1.5",
        reason="Realtime API Beta retired; migrate to gpt-realtime-1.5.",
    ),
    "gpt-4o-mini-realtime-preview": Deprecation(
        shutdown_date="2026-05-07",
        replacement="gpt-realtime-mini",
        reason="Realtime API Beta retired.",
    ),
    "gpt-4o-audio-preview": Deprecation(
        shutdown_date="2026-05-07",
        replacement="gpt-audio-1.5",
        reason="Audio preview API retired.",
    ),
    "gpt-4o-mini-audio-preview": Deprecation(
        shutdown_date="2026-05-07",
        replacement="gpt-audio-mini",
        reason="Audio preview API retired.",
    ),

    # ----- Upcoming: DALL·E family (2026-05-12) -----
    "dall-e-2": Deprecation(
        shutdown_date="2026-05-12",
        replacement="gpt-image-1-mini",
        reason="DALL·E retired from API in favour of gpt-image-1 family.",
    ),
    "dall-e-3": Deprecation(
        shutdown_date="2026-05-12",
        replacement="gpt-image-1",
        reason="DALL·E 3 retired from API in favour of gpt-image-1.",
    ),

    # ----- Far future: Legacy instruct + base + GPT-3.5 Turbo (2026-09-28) -----
    "gpt-3.5-turbo-instruct": Deprecation(
        shutdown_date="2026-09-28",
        replacement="gpt-5-mini",
        reason="Legacy instruct model retired; GPT-5-mini covers the use case.",
    ),
    "gpt-3.5-turbo-1106": Deprecation(
        shutdown_date="2026-09-28",
        replacement="gpt-5-mini",
        reason="GPT-3.5 Turbo snapshot retired.",
    ),
    "babbage-002": Deprecation(
        shutdown_date="2026-09-28",
        replacement="gpt-5-mini",
        reason="Legacy base model retired.",
    ),
    "davinci-002": Deprecation(
        shutdown_date="2026-09-28",
        replacement="gpt-5-mini",
        reason="Legacy base model retired.",
    ),
}


# =============================================================================
# Perplexity deprecations — verified 2026-04-12 (no active deprecations)
# =============================================================================
#
# As of 2026-04-12 Perplexity has NO active deprecations in the 4 shipped Sonar
# models (sonar, sonar-pro, sonar-reasoning-pro, sonar-deep-research). The
# historical `llama-3.1-sonar-*` aliases were removed in Feb 2025 and predate
# any supported ppxai config. The table stays empty as a placeholder so future
# maintainers don't have to re-research the landscape.

PERPLEXITY_DEPRECATIONS: Dict[str, Deprecation] = {
    # Intentionally empty — see header comment.
}


# =============================================================================
# Merged lookup — every known deprecation across all providers
# =============================================================================

ALL_DEPRECATIONS: Dict[str, Deprecation] = {
    **GEMINI_DEPRECATIONS,
    **OPENAI_DEPRECATIONS,
    **PERPLEXITY_DEPRECATIONS,
}


# Models to recommend when a user's config doesn't include them.
# Listed in priority order — /doctor shows the first few as "consider
# adding" so newcomers don't have to read provider changelogs.
RECOMMENDED_NEW_MODELS: List[Dict[str, str]] = [
    {
        "provider": "openai",
        "model": "gpt-5.5",
        "reason": (
            "Newest OpenAI flagship (released 2026-04-23). 1M context, "
            "first fully retrained base since GPT-4.5. $5/MTok input — "
            "2× the price of gpt-5.4. Use for hardest tasks; "
            "gpt-5.4-mini remains best price/perf for everyday work."
        ),
    },
    {
        "provider": "openai",
        "model": "gpt-5.4-mini",
        "reason": (
            "Newest OpenAI small model (released 2026-03-17). 400K context, "
            "$0.75/$4.50 per MTok — best price/performance in the GPT-5.x tier."
        ),
    },
    {
        "provider": "openai",
        "model": "gpt-5.4",
        "reason": (
            "OpenAI flagship (released 2026-03-05). 1M context, "
            "75% computer use benchmark, $2.50/MTok input. "
            "Stable default — cheaper than gpt-5.5 with proven track record."
        ),
    },
    {
        "provider": "openai",
        "model": "gpt-5.3-codex",
        "reason": (
            "Code-specialized model — \"most capable agentic coding model "
            "to date\" per OpenAI. 400K context. Note: gpt-5.4 mainline "
            "absorbs these capabilities, but the dedicated Codex variant "
            "remains a valid choice for long agentic coding sessions."
        ),
    },
    {
        "provider": "gemini",
        "model": "gemini-3.1-flash-lite",
        "reason": "Cheapest Gemini 3 tier — good for high-volume workflows and VSCode inline suggestions.",
    },
    {
        "provider": "gemini",
        "model": "gemma-4-31b-it",
        "reason": "Open-weights alternative with free tier via Gemini API. Vision-capable.",
    },
    {
        "provider": "gemini",
        "model": "gemma-4-26b-a4b-it",
        "reason": "MoE variant with 3.8B active params — faster inference than 31B dense.",
    },
]

# Models that the advisor recommends as safe defaults by provider.
# Used both for "your default_model is deprecated, switch to this"
# warnings and as the suggested default for a fresh config.
RECOMMENDED_DEFAULTS: Dict[str, str] = {
    "gemini": "gemini-3-flash-preview",
    "openai": "gpt-5.4",              # Updated 2026-04-12 (was gpt-5.2)
    "perplexity": "sonar-pro",
    "anthropic": "claude-sonnet-4-6",
}


# =============================================================================
# Query API
# =============================================================================


def classify_model(model: str, today: Optional[date] = None) -> Optional[Dict[str, str]]:
    """Return deprecation info for a model, or None if not deprecated.

    The returned dict has a stable schema suitable for direct display
    in /doctor output without further processing:

        {
            "model": "gemini-2.5-flash",
            "status": "shutdown" | "deprecated",
            "shutdown_date": "2026-06-17",
            "replacement": "gemini-3-flash-preview",
            "reason": "...",
            "days_remaining": 72,   # present for "deprecated" only
        }

    The `status` field is computed from `shutdown_date` vs `today`, so
    an entry silently transitions from "deprecated" to "shutdown" as
    time passes without requiring table maintenance. `today` defaults
    to the current system date; tests inject a fixed date for
    reproducibility.
    """
    entry = ALL_DEPRECATIONS.get(model)
    if entry is None:
        return None

    current = today or date.today()
    try:
        shutdown = datetime.strptime(entry.shutdown_date, "%Y-%m-%d").date()
    except ValueError:
        # Malformed date in the table — treat as not deprecated to
        # avoid false positives, and log for maintainers.
        return None

    delta = (shutdown - current).days
    result: Dict[str, str] = {
        "model": model,
        "status": "shutdown" if delta < 0 else "deprecated",
        "shutdown_date": entry.shutdown_date,
        "replacement": entry.replacement,
        "reason": entry.reason,
    }
    if delta >= 0:
        result["days_remaining"] = str(delta)
    return result


def audit_config_models(
    provider_models: Dict[str, List[str]],
    today: Optional[date] = None,
) -> Dict[str, List[Dict[str, str]]]:
    """Walk a user's configured models and categorize each by deprecation status.

    Args:
        provider_models: Mapping of provider name → list of model IDs
            declared under that provider in the user's config.
            Typically built from `ppxai-config.json` by the caller.
        today: Override for "now" in tests.

    Returns:
        Dict with three stable lists suitable for direct display:
            {
                "dead": [<classified entries with status="shutdown">],
                "upcoming": [<classified entries with status="deprecated">],
                "healthy": [<plain model names, no deprecation>],
            }
        The "healthy" list contains just the model name (the caller
        already knows the provider). "dead" and "upcoming" carry the
        full classification dict.
    """
    dead: List[Dict[str, str]] = []
    upcoming: List[Dict[str, str]] = []
    healthy: List[str] = []

    for provider, models in provider_models.items():
        for model in models:
            info = classify_model(model, today=today)
            if info is None:
                healthy.append(model)
                continue
            # Attach the provider so the display can show the
            # full `providers.<provider>.models.<model>` JSON path.
            info["provider"] = provider
            if info["status"] == "shutdown":
                dead.append(info)
            else:
                upcoming.append(info)

    # Sort upcoming by days remaining (most urgent first).
    upcoming.sort(key=lambda e: int(e.get("days_remaining", 0)))
    return {"dead": dead, "upcoming": upcoming, "healthy": healthy}


def find_missing_recommended(
    provider_models: Dict[str, List[str]],
) -> List[Dict[str, str]]:
    """Return recommended models the user doesn't have in their config.

    Used by /doctor to suggest new models worth adopting. Skips
    recommendations whose provider isn't configured at all — we don't
    want to nag users about Gemma 4 if they haven't set up a Gemini
    API key.
    """
    result: List[Dict[str, str]] = []
    for rec in RECOMMENDED_NEW_MODELS:
        provider = rec["provider"]
        if provider not in provider_models:
            continue
        if rec["model"] not in provider_models[provider]:
            result.append(rec)
    return result


__all__ = [
    "Deprecation",
    "GEMINI_DEPRECATIONS",
    "OPENAI_DEPRECATIONS",
    "PERPLEXITY_DEPRECATIONS",
    "ALL_DEPRECATIONS",
    "RECOMMENDED_NEW_MODELS",
    "RECOMMENDED_DEFAULTS",
    "classify_model",
    "audit_config_models",
    "find_missing_recommended",
]
