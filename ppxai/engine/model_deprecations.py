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
    - NVIDIA NIM: live /models catalog at https://integrate.api.nvidia.com/v1/models
                (NVIDIA does not publish a deprecation calendar; "retired"
                here means absent from the live catalog on the verification date).

Verification date: 2026-07-11 (live /models sweep across OpenAI, Gemini,
NVIDIA NIM; Perplexity has no /models endpoint, verified via docs/changelog).
2026-07-11 sweep result: every model in the shipped catalog is still live on
all four providers — no new retirements to add. Watch items (gpt-5.6 GA,
Perplexity Agent API, gemini-3.1-pro-preview succession) are tracked in
docs/debt-inventory.md Item 38.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


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

GEMINI_DEPRECATIONS: dict[str, Deprecation] = {
    "gemini-3-pro-preview": Deprecation(
        shutdown_date="2026-03-09",
        replacement="gemini-3.1-pro-preview",
        reason="Preview graduated to 3.1-pro; preview endpoint retired.",
    ),
    "gemini-2.0-flash": Deprecation(
        shutdown_date="2026-06-01",
        replacement="gemini-3.6-flash",
        reason=(
            "Gemini 2.0 family end-of-life; 3.x offers better performance at "
            "similar cost. Replacement moved from gemini-3-flash-preview to "
            "gemini-3.6-flash for the same reason the 2.5-flash row did: a GA "
            "successor beats a preview one for a hint users follow. Both "
            "verified live 2026-09-01."
        ),
    ),
    "gemini-2.0-flash-lite": Deprecation(
        shutdown_date="2026-06-01",
        replacement="gemini-3.1-flash-lite",
        reason="Gemini 2.0 family end-of-life.",
    ),
    "gemini-2.5-pro": Deprecation(
        shutdown_date="2026-10-16",
        replacement="gemini-3.1-pro-preview",
        reason=(
            "Gemini 2.5 line sunset, EARLIEST 2026-10-16 (ai.google.dev "
            "deprecations page). 3.1 Pro delivers SWE-Bench 80.6% vs "
            "2.5-Pro's ~70%. NB the replacement is itself still PREVIEW — "
            "there is no GA successor in the Pro tier yet."
        ),
    ),
    "gemini-2.5-flash": Deprecation(
        shutdown_date="2026-10-16",
        replacement="gemini-3.6-flash",
        reason=(
            "Gemini 2.5 line sunset, EARLIEST 2026-10-16. Replacement moved "
            "from gemini-3-flash-preview to gemini-3.6-flash: the latter is "
            "GA and verified live (2026-08-31, generateContent + "
            "google_search with grounding), and a GA successor beats a "
            "preview one for a migration hint users will follow."
        ),
    ),
    "gemini-2.5-flash-lite": Deprecation(
        shutdown_date="2026-10-16",
        replacement="gemini-3.1-flash-lite",
        reason=(
            "Gemini 2.5 line sunset, EARLIEST 2026-10-16. 3.1 Flash Lite is "
            "the same price tier at better quality — but note it carries its "
            "OWN sunset date (2027-05-07 -> gemini-3.5-flash-lite), so this "
            "hint has a shelf life."
        ),
    ),
    "gemini-3.1-flash-lite-preview": Deprecation(
        shutdown_date="2026-05-25",
        replacement="gemini-3.1-flash-lite",
        reason="Preview graduated to GA; identical model architecture, only the identifier changes.",
    ),
    "gemini-2.5-flash-image": Deprecation(
        shutdown_date="2026-10-02",
        replacement="gemini-3.1-flash-image",
        reason=(
            "2.5 image generation retired; Nano Banana 2 is the successor. "
            "Points at the GA id, not `-preview`: both were verified live "
            "2026-09-01 and a GA successor beats a preview one for a hint "
            "users follow. NEAREST Gemini deadline — 2026-10-02."
        ),
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

OPENAI_DEPRECATIONS: dict[str, Deprecation] = {
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
# Perplexity deprecations — the ENDPOINT retires, not the models
# =============================================================================
#
# Perplexity retires the Sonar **chat-completions** endpoint on 2026-09-27.
# This is unlike every other table here: the models are not being withdrawn,
# the wire they are served on is. ppxai routes per model via
# `ModelFacts.wire_protocol` (ADR 0012), so the migration is an ID change
# rather than a model change — but only where a replacement ID exists.
#
# MEASURED 2026-08-31 against `https://api.perplexity.ai/v1/responses`, twice
# (probe + a plain SDK call, no framing):
#
#   perplexity/sonar                 200  — the ONLY Sonar on the new wire
#   sonar-pro                        400  validation failed: not supported
#   perplexity/sonar-pro             400  validation failed: not supported
#   perplexity/sonar-reasoning-pro   400  validation failed: not supported
#
# So `sonar` has a successor and the pro models, as of today, do not. Their
# entries below say that plainly instead of inventing a replacement ID that
# would 400 — a wrong migration hint is worse than an honest dead end, since
# the user would follow it and get a broken config.
#
# ⏰ RE-PROBE BEFORE 2026-09-27 — tracked as debt Item 64, not just here: a
# comment is only read by someone already editing this table, who is the
# person least in need of the reminder. If Perplexity ships the pro line on
# Responses, update `replacement` below (and see Item 64 for the rest of the
# migration: example config, pricing row, the migration fence's RETIRED set).
#
#   uv run python scripts/probe-perplexity-capabilities.py #       --api-path responses --model "perplexity/sonar-pro"

PERPLEXITY_DEPRECATIONS: dict[str, Deprecation] = {
    "sonar": Deprecation(
        shutdown_date="2026-09-27",
        replacement="perplexity/sonar",
        reason=(
            "The Sonar chat-completions endpoint retires. The same model is "
            "served on the Responses wire under the namespaced ID — and gains "
            "native tool calling there, which the chat wire refuses for this "
            "model (measured 2026-08-31)."
        ),
    ),
    "sonar-pro": Deprecation(
        shutdown_date="2026-09-27",
        replacement="perplexity/sonar",
        reason=(
            "The Sonar chat-completions endpoint retires and Perplexity does "
            "NOT serve sonar-pro on the Responses wire in either bare or "
            "namespaced form (measured 2026-08-31 — both 400). "
            "`perplexity/sonar` is the only Sonar successor available today; "
            "it is the lighter model, so re-check before the date in case the "
            "pro line lands on the new wire."
        ),
    ),
    "sonar-deep-research": Deprecation(
        shutdown_date="2026-09-27",
        replacement="perplexity/sonar",
        reason=(
            "Same as the pro ids: live on chat-completions, ABSENT from the "
            "Responses wire (measured 2026-09-01), so it dies with that "
            "endpoint. It had NO row until then — a configured model would "
            "have stopped working with no migration hint at all. There is no "
            "deep-research successor on Responses; `perplexity/sonar` is the "
            "only Sonar id served there."
        ),
    ),
    "sonar-reasoning-pro": Deprecation(
        shutdown_date="2026-09-27",
        replacement="perplexity/sonar",
        reason=(
            "Same as sonar-pro: chat-completions only, absent from the "
            "Responses wire as of 2026-08-31."
        ),
    ),
}


# =============================================================================
# NVIDIA NIM deprecations — verified 2026-05-31 against live /models
# =============================================================================
#
# NVIDIA does not publish a deprecation calendar; build.nvidia.com models
# simply appear and disappear from the catalog. These 5 model IDs shipped in
# earlier ppxai configs but are ABSENT from the live /models response as of
# 2026-05-31, so calls now 404. The `shutdown_date` is the verification date
# (the exact retirement date is unpublished); /doctor surfaces them so users
# who still reference them in their own configs get a migration hint.

NVIDIA_DEPRECATIONS: dict[str, Deprecation] = {
    # ---- Found by the Item 38 sweep, 2026-08-31 -------------------------
    # These four were CONFIGURED in the shipped example and answer HTTP 410
    # Gone with an explicit end-of-life date in the body. Two died BEFORE the
    # previous sweep (2026-07-11) and were missed: that sweep read the
    # /models listing, and a retired NIM model simply vanishes from it, so an
    # id nobody thought to look for looks identical to an id that is fine.
    # Calling the endpoint is what surfaces the date. The 410 body is quoted
    # in each reason because it is the primary evidence.
    #
    # The deepseek pair is not gone, it is RENAMED: NVIDIA moved to
    # date-suffixed ids, and the suffixed forms answer 200 (verified).
    "qwen/qwen3.5-122b-a10b": Deprecation(
        shutdown_date="2026-07-20",
        replacement="moonshotai/kimi-k3",
        reason=(
            "HTTP 410: \"has reached its end of life on 2026-07-20T00:00:00Z\". "
            "No successor in the qwen family remains on NIM — the whole family "
            "is absent from /models (measured 2026-08-31), so the replacement "
            "crosses vendors deliberately rather than naming a sibling that is "
            "also gone."
        ),
    ),
    "qwen/qwen3-next-80b-a3b-instruct": Deprecation(
        shutdown_date="2026-07-27",
        replacement="moonshotai/kimi-k3",
        reason=(
            "HTTP 410: \"has reached its end of life on 2026-07-27T00:00:00Z\". "
            "Same as its 122b sibling: no qwen model remains on NIM."
        ),
    ),
    "deepseek-ai/deepseek-v4-pro": Deprecation(
        shutdown_date="2026-08-07",
        replacement="moonshotai/kimi-k3",
        reason=(
            "HTTP 410: \"has reached its end of life on 2026-08-07T09:00:00Z\". "
            "NVIDIA moved to date-suffixed ids and the suffixed form answered "
            "200 on 2026-08-31 — but on 2026-09-01 BOTH suffixed deepseek ids "
            "failed to respond at all across three attempts, the last with a "
            "300s timeout and a retry. Listed is not the same as usable, so "
            "the hint points at `kimi-k3`, which answers."
        ),
    ),
    "deepseek-ai/deepseek-v4-flash": Deprecation(
        shutdown_date="2026-08-07",
        replacement="moonshotai/kimi-k3",
        reason=(
            "HTTP 410, same EOL timestamp as the Pro sibling. Its date-suffixed "
            "form is present on /models but did not respond on 2026-09-01 "
            "(same measurement as the Pro row), so the hint points at "
            "`kimi-k3` rather than at a listed-but-unreachable id."
        ),
    ),
    # Found 2026-08-31 by sweeping the OPERATOR's configured ids rather than
    # the example config's. None of these five had a deprecation row, so a
    # user running them got no /doctor warning at all — the table only knew
    # the models WE ship. Each date is quoted from that id's own 410 body.
    "qwen/qwen3-coder-480b-a35b-instruct": Deprecation(
        shutdown_date="2026-06-11",
        replacement="moonshotai/kimi-k3",
        reason=(
            "HTTP 410: \"end of life on 2026-06-11T00:00:00Z\" (measured "
            "2026-08-31). The qwen family is entirely gone from NIM, so the "
            "replacement crosses vendors; K3 is the live open-weight coder."
        ),
    ),
    "qwen/qwen3.5-397b-a17b": Deprecation(
        shutdown_date="2026-07-27",
        replacement="moonshotai/kimi-k3",
        reason=(
            "HTTP 410: \"end of life on 2026-07-27T00:00:00Z\". Same NIM-wide "
            "qwen withdrawal as its 122b sibling."
        ),
    ),
    "nvidia/llama-3.3-nemotron-super-49b-v1.5": Deprecation(
        shutdown_date="2026-08-26",
        replacement="moonshotai/kimi-k3",
        reason=(
            "HTTP 410: \"end of life on 2026-08-26T00:00:00Z\" — five days "
            "before the sweep that found it, and NVIDIA's own model. NIM "
            "publishes no deprecation calendar, so only a per-id call surfaces "
            "a retirement this fresh."
        ),
    ),
    "meta/llama-4-maverick-17b-128e-instruct": Deprecation(
        shutdown_date="2026-07-27",
        replacement="moonshotai/kimi-k3",
        reason=(
            "HTTP 410: \"end of life on 2026-07-27T00:00:00Z\". Previously "
            "noted only as regionally restricted (EU 'NIM unavailable in your "
            "location'); it is now withdrawn everywhere."
        ),
    ),
    "mistralai/mistral-large-3-675b-instruct-2512": Deprecation(
        shutdown_date="2026-07-23",
        replacement="moonshotai/kimi-k3",
        reason=(
            "HTTP 410: \"end of life on 2026-07-23T00:00:00Z\". The mistral "
            "line on NIM is gone with it: mistral-small-4-119b-2603 and "
            "mistral-medium-3.5-128b both answer 410 as well (measured "
            "2026-08-31), so there is no mistral successor to name."
        ),
    ),
    "qwen/qwen3-next-80b-a3b-thinking": Deprecation(
        shutdown_date="2026-05-31",
        replacement="moonshotai/kimi-k3",
        reason=(
            "Retired from NIM catalog 2026-05-31. Its instruct sibling was the "
            "replacement until that ALSO reached end of life 2026-07-27 "
            "(HTTP 410, measured 2026-08-31), so this now points at Kimi K3 — "
            "verified by CALLING it (200), not by finding it in /models."
        ),
    ),
    "qwen/qwen2.5-coder-32b-instruct": Deprecation(
        shutdown_date="2026-05-31",
        replacement="moonshotai/kimi-k3",
        reason="Retired from NIM catalog. Use a current coder/agentic model (DeepSeek V4 date-suffixed, or Kimi K3).",
    ),
    "moonshotai/kimi-k2-thinking": Deprecation(
        shutdown_date="2026-05-31",
        replacement="moonshotai/kimi-k3",
        reason="Retired from NIM catalog; superseded by Kimi K3.",
    ),
    "deepseek-ai/deepseek-v3.2": Deprecation(
        shutdown_date="2026-05-31",
        replacement="moonshotai/kimi-k3",
        reason="Retired from NIM catalog; superseded by DeepSeek V4 (Pro/Flash).",
    ),
    "mistralai/devstral-2-123b-instruct-2512": Deprecation(
        shutdown_date="2026-05-31",
        replacement="moonshotai/kimi-k3",
        reason="Retired from NIM catalog (absent from live /models 2026-05-31).",
    ),
}


# =============================================================================
# Merged lookup — every known deprecation across all providers
# =============================================================================

ALL_DEPRECATIONS: dict[str, Deprecation] = {
    **GEMINI_DEPRECATIONS,
    **OPENAI_DEPRECATIONS,
    **PERPLEXITY_DEPRECATIONS,
    **NVIDIA_DEPRECATIONS,
}


# Models to recommend when a user's config doesn't include them.
# Listed in priority order — /doctor shows the first few as "consider
# adding" so newcomers don't have to read provider changelogs.
RECOMMENDED_NEW_MODELS: list[dict[str, str]] = [
    {
        "provider": "openai",
        "model": "gpt-5.6-terra",
        "reason": (
            "Benchmarked 2026-08-31 at PARITY with gpt-5.5 (median 91.5 vs "
            "88.3 across 3 clean runs each) for 40% of the price "
            "($2/$12 vs $5/$30). Not a superiority claim — the spread "
            "exceeds the delta — but parity at 40% is the whole case. "
            "REQUIRES facts.wire_protocol='responses': the 5.6 line 400s on "
            "any tools array over chat-completions."
        ),
    },
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
        "model": "gemini-3.5-flash",
        "reason": (
            "Newest Gemini flash (GA 2026). Google's most intelligent flash "
            "tier for agentic + coding work; supersedes gemini-3-flash-preview. "
            "1M context, vision. Recommended default for the Gemini provider."
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
    {
        "provider": "nvidia",
        "model": "moonshotai/kimi-k3",
        "reason": "Best NIM model still live — the only Kimi id that answers 200 (2026-08-31 per-id sweep; k2.6 is listed but 404s \"not found for account\"). Replaces both the qwen recommendation and retired kimi-k2-thinking.",
    },
    # REMOVED 2026-09-01: deepseek-ai/deepseek-v4-pro-0813. It was recommended
    # here as a model to ADOPT while both suffixed deepseek ids failed to
    # respond at all — three attempts, 45s / 120s / 300s-with-retry, ten
    # minutes of wall clock, zero output. Its reason string also claimed the
    # suffixed form was the working one, which that measurement contradicts.
    # Recommending an id that never answers is worse than recommending
    # nothing: the user adopts it and their next request hangs.
]

# Models that the advisor recommends as safe defaults by provider.
# Used both for "your default_model is deprecated, switch to this"
# warnings and as the suggested default for a fresh config.
RECOMMENDED_DEFAULTS: dict[str, str] = {
    "gemini": "gemini-3.5-flash",     # Updated 2026-05-31 (was gemini-3-flash-preview; superseded by 3.5-flash GA)
    "openai": "gpt-5.6-terra",        # 2026-08-31: parity with gpt-5.5 at 40% price
    "perplexity": "perplexity/sonar",  # ADR 0012: only Sonar on the surviving wire
    "nvidia": "moonshotai/kimi-k3",  # 2026-08-31: the qwen line hit EOL (410)
    "anthropic": "claude-sonnet-4-6",
}


# =============================================================================
# Query API
# =============================================================================


def classify_model(model: str, today: date | None = None) -> dict[str, str] | None:
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
    result: dict[str, str] = {
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
    provider_models: dict[str, list[str]],
    today: date | None = None,
) -> dict[str, list[dict[str, str]]]:
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
    dead: list[dict[str, str]] = []
    upcoming: list[dict[str, str]] = []
    healthy: list[str] = []

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
    provider_models: dict[str, list[str]],
) -> list[dict[str, str]]:
    """Return recommended models the user doesn't have in their config.

    Used by /doctor to suggest new models worth adopting. Skips
    recommendations whose provider isn't configured at all — we don't
    want to nag users about Gemma 4 if they haven't set up a Gemini
    API key.
    """
    result: list[dict[str, str]] = []
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
    "NVIDIA_DEPRECATIONS",
    "ALL_DEPRECATIONS",
    "RECOMMENDED_NEW_MODELS",
    "RECOMMENDED_DEFAULTS",
    "classify_model",
    "audit_config_models",
    "find_missing_recommended",
]
