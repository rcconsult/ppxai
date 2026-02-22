"""
Model profile system for the ppxai engine.

v1.15.6: Foundation data structures and registry for model-specific behavior
configuration. Profiles encode per-model tool calling strategy, API routing,
and capability flags derived from benchmark analysis (27 models, 7 categories).

v1.16.0 Step 2: Profiles are consulted by chat.py for tool calling mode
resolution, fallback behavior, and strip_json decisions.

This is a LEAF MODULE - no ppxai imports allowed (except types).
"""

import fnmatch
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional


@dataclass
class ToolCallingProfile:
    """How a model handles tool calling.

    Attributes:
        mode: Tool calling strategy.
            "native" - Use OpenAI-style function calling (tool_calls field)
            "prompt_based" - Inject tool schema into system prompt, parse JSON from text
            "auto" - Try native first, fall back to prompt-based on empty/failure
        fallback_on_empty: If native returns empty response, retry with prompt-based
        fallback_on_failure: If native tool call fails to parse, retry with prompt-based
        strip_json_from_text: Remove duplicate tool JSON from response text when
            native tool_calls are present (Gap 4: tool_json_in_content anti-pattern)
        parallel_tool_calls: Process all native tool calls, not just the first one
        api_path: OpenAI API endpoint routing.
            "chat" - /chat/completions (default, most models)
            "responses" - /responses (codex models)
            "auto" - Try chat first, fall back to responses on 404
    """
    mode: Literal["native", "prompt_based", "auto"] = "native"
    fallback_on_empty: bool = False
    fallback_on_failure: bool = False
    strip_json_from_text: bool = False
    parallel_tool_calls: bool = False
    api_path: Literal["chat", "responses", "auto"] = "chat"


@dataclass
class ModelProfile:
    """Complete behavioral profile for a model.

    Encodes the optimal configuration derived from benchmark testing.
    Used by the engine to make per-model decisions about tool calling
    strategy, API routing, and parameter handling.

    Attributes:
        tool_calling: Tool calling behavior configuration
        max_tokens: Default max_tokens for this model (0 = use provider default)
        max_tool_iterations: Max tool loop iterations for this model (0 = use default)
        supports_reasoning: Model supports reasoning/thinking tokens (o-series)
        restricted_params: Parameters that must NOT be sent to this model
            (e.g., temperature/top_p for o-series reasoning models)
        tier: Benchmark performance tier (S/A/B/C/D) for reference
    """
    tool_calling: ToolCallingProfile = field(default_factory=ToolCallingProfile)
    max_tokens: int = 0
    max_tool_iterations: int = 0
    supports_reasoning: bool = False
    restricted_params: List[str] = field(default_factory=list)
    tier: str = ""


# ──────────────────────────────────────────────────────────────────────
# Built-in model profiles
#
# Derived from MODEL-BEHAVIOR-ANALYSIS.md (27 models, 7 categories).
# Keys are glob patterns matched against model IDs (case-insensitive).
# First match wins — order matters (specific before generic).
# ──────────────────────────────────────────────────────────────────────

BUILTIN_PROFILES: Dict[str, ModelProfile] = {
    # ── Tier S: 80%+ success ──────────────────────────────────────────

    "gemini-2.5-pro*": ModelProfile(
        tool_calling=ToolCallingProfile(mode="native"),
        max_tokens=65_536,
        max_tool_iterations=25,
        tier="S",
    ),
    "gemini-2.5-flash-lite*": ModelProfile(
        tool_calling=ToolCallingProfile(
            mode="native",
            fallback_on_empty=True,
            fallback_on_failure=True,
        ),
        max_tokens=8_192,
        max_tool_iterations=10,
        tier="D",
    ),
    "gemini-2.5-flash*": ModelProfile(
        tool_calling=ToolCallingProfile(mode="native"),
        max_tokens=65_536,
        max_tool_iterations=25,
        tier="S",
    ),
    "qwen3-coder*": ModelProfile(
        tool_calling=ToolCallingProfile(
            mode="native",
            parallel_tool_calls=True,
        ),
        max_tool_iterations=20,
        tier="S",
    ),

    # ── Tier A: 65-75% success ────────────────────────────────────────

    "gpt-5.2*": ModelProfile(
        tool_calling=ToolCallingProfile(
            mode="native",
            strip_json_from_text=True,
            parallel_tool_calls=True,
        ),
        max_tokens=128_000,
        restricted_params=["temperature", "top_p"],
        tier="A",
    ),
    "gpt-4.1": ModelProfile(
        tool_calling=ToolCallingProfile(
            mode="native",
            strip_json_from_text=True,
        ),
        max_tokens=32_768,
        tier="A",
    ),
    "gpt-5-mini*": ModelProfile(
        tool_calling=ToolCallingProfile(
            mode="native",
            strip_json_from_text=True,
            fallback_on_empty=True,
        ),
        max_tokens=128_000,
        tier="A",
    ),
    "gpt-5": ModelProfile(
        tool_calling=ToolCallingProfile(
            mode="native",
            strip_json_from_text=True,
        ),
        max_tokens=128_000,
        tier="A",
    ),

    # ── Tier B: 60-72% success (prompt-based preferred) ───────────────

    "gpt-4.1-mini*": ModelProfile(
        tool_calling=ToolCallingProfile(mode="prompt_based"),
        max_tokens=32_768,
        tier="B",
    ),
    # NOTE: codex-mini MUST come before codex* to avoid glob shadowing
    "gpt-5.1-codex-mini*": ModelProfile(
        tool_calling=ToolCallingProfile(
            mode="native",
            api_path="responses",
            strip_json_from_text=True,
            fallback_on_empty=True,
        ),
        max_tokens=128_000,
        max_tool_iterations=20,
        restricted_params=["temperature", "top_p"],
        tier="B",
    ),
    "gpt-5.1-codex*": ModelProfile(
        tool_calling=ToolCallingProfile(
            mode="native",
            api_path="responses",
        ),
        max_tokens=128_000,
        restricted_params=["temperature", "top_p"],
        tier="B",
    ),
    "o4-mini*": ModelProfile(
        tool_calling=ToolCallingProfile(
            mode="prompt_based",
            fallback_on_empty=True,
        ),
        max_tokens=100_000,
        supports_reasoning=True,
        restricted_params=["temperature", "top_p"],
        tier="B",
    ),

    # ── Tier C: 40-60% success ────────────────────────────────────────

    "gpt-5-nano*": ModelProfile(
        tool_calling=ToolCallingProfile(
            mode="native",
            strip_json_from_text=True,
            fallback_on_empty=True,
        ),
        max_tokens=8_192,
        restricted_params=["temperature", "top_p"],
        tier="C",
    ),
    "gpt-4.1-nano*": ModelProfile(
        tool_calling=ToolCallingProfile(
            mode="native",
            strip_json_from_text=True,
        ),
        max_tokens=32_768,
        tier="C",
    ),
    "gpt-4o-mini*": ModelProfile(
        tool_calling=ToolCallingProfile(mode="native"),
        max_tokens=16_384,
        tier="C",
    ),
    "gpt-4o*": ModelProfile(
        tool_calling=ToolCallingProfile(mode="native"),
        max_tokens=16_384,
        tier="C",
    ),

    # ── Tier D: <40% success ──────────────────────────────────────────

    "gemini-2.0-flash-exp*": ModelProfile(
        tool_calling=ToolCallingProfile(mode="prompt_based"),
        max_tokens=8_192,
        tier="D",
    ),

    # ── Reasoning models (o-series) ──────────────────────────────────

    "o3-pro*": ModelProfile(
        tool_calling=ToolCallingProfile(mode="native"),
        max_tokens=100_000,
        supports_reasoning=True,
        restricted_params=["temperature", "top_p"],
        tier="A",
    ),
    "o3-mini*": ModelProfile(
        tool_calling=ToolCallingProfile(mode="native"),
        max_tokens=100_000,
        supports_reasoning=True,
        restricted_params=["temperature", "top_p"],
        tier="B",
    ),
    "o3*": ModelProfile(
        tool_calling=ToolCallingProfile(mode="native"),
        max_tokens=100_000,
        supports_reasoning=True,
        restricted_params=["temperature", "top_p"],
        tier="A",
    ),
    "o1-mini*": ModelProfile(
        tool_calling=ToolCallingProfile(mode="native"),
        max_tokens=65_536,
        supports_reasoning=True,
        restricted_params=["temperature", "top_p"],
        tier="C",
    ),
    "o1*": ModelProfile(
        tool_calling=ToolCallingProfile(mode="native"),
        max_tokens=100_000,
        supports_reasoning=True,
        restricted_params=["temperature", "top_p"],
        tier="B",
    ),

    # ── DGX / ASUS AI vLLM models (Qwen3 family) ─────────────────────

    # Qwen3-Coder-30B: top DGX performer (81.25%), uses qwen3_coder parser
    "*/qwen3-coder-30b*": ModelProfile(
        tool_calling=ToolCallingProfile(
            mode="native",
            parallel_tool_calls=True,
        ),
        max_tokens=8_192,
        max_tool_iterations=20,
        tier="S",
    ),
    # Qwen3-Coder-Next: newer coder variant (60.94%), uses qwen3_coder parser
    "*/qwen3-coder-next*": ModelProfile(
        tool_calling=ToolCallingProfile(
            mode="native",
            parallel_tool_calls=True,
        ),
        max_tokens=8_192,
        tier="B",
    ),
    # Qwen3-Next-80B Instruct: large MoE (54.69%), uses hermes parser
    "*/qwen3-next-80b*instruct*": ModelProfile(
        tool_calling=ToolCallingProfile(mode="native"),
        max_tokens=8_192,
        tier="C",
    ),
    # Qwen3-Next-80B Thinking: reasoning variant (57.81%), uses hermes parser
    "*/qwen3-next-80b*thinking*": ModelProfile(
        tool_calling=ToolCallingProfile(mode="native"),
        max_tokens=8_192,
        supports_reasoning=True,
        tier="B",
    ),
    # RedHatAI Qwen3-30B: community fine-tune (60.94%), uses hermes parser
    "*/qwen3-30b*": ModelProfile(
        tool_calling=ToolCallingProfile(mode="native"),
        max_tokens=8_192,
        tier="B",
    ),

    # ── Ollama-served Qwen models ───────────────────────────────────

    # qwen2.5-coder:32b-64k: best Ollama performer (57.81%), prompt-based
    "qwen2.5-coder:32b*": ModelProfile(
        tool_calling=ToolCallingProfile(mode="prompt_based"),
        max_tokens=4_096,
        tier="B",
    ),
    # qwen2.5-coder (other sizes): smaller coder models
    "qwen2.5-coder*": ModelProfile(
        tool_calling=ToolCallingProfile(mode="native"),
        max_tokens=4_096,
        tier="C",
    ),
    # qwen3:30b-a3b: MoE via Ollama (46.88%), prompt-based works better
    "qwen3:30b*": ModelProfile(
        tool_calling=ToolCallingProfile(mode="prompt_based"),
        max_tokens=8_192,
        tier="D",
    ),

    # ── Generic fallbacks (least specific, matched last) ──────────────

    # Perplexity Sonar models — prompt-based tool calling (Perplexity API has
    # native_tool_calling=False). Parser extracts tool JSON from response text.
    # NOTE: sonar-reasoning-pro MUST come before sonar* to avoid glob shadowing
    "sonar-reasoning-pro*": ModelProfile(
        tool_calling=ToolCallingProfile(mode="prompt_based"),
        max_tokens=12_288,
        supports_reasoning=True,
        tier="C",
    ),
    "sonar-deep-research*": ModelProfile(
        tool_calling=ToolCallingProfile(mode="prompt_based"),
        max_tokens=8_192,
        tier="C",
    ),
    "llama-3.1-sonar*": ModelProfile(
        tool_calling=ToolCallingProfile(mode="prompt_based"),
        max_tokens=2_048,
        tier="D",
    ),
    "sonar-pro*": ModelProfile(
        tool_calling=ToolCallingProfile(mode="prompt_based"),
        max_tokens=8_192,
        max_tool_iterations=20,
        tier="A",
    ),
    "sonar*": ModelProfile(
        tool_calling=ToolCallingProfile(mode="prompt_based"),
        max_tokens=2_048,
        max_tool_iterations=20,
        tier="B",
    ),

    # GPT-OSS (vLLM-served) — prompt-based recommended due to HarmonyError
    "openai/gpt-oss*": ModelProfile(
        tool_calling=ToolCallingProfile(mode="prompt_based"),
        max_tokens=16_384,
        tier="B",
    ),

    # ── Gemini 3 models ─────────────────────────────────────────────

    "gemini-3-flash*": ModelProfile(
        tool_calling=ToolCallingProfile(mode="native"),
        max_tokens=65_536,
        max_tool_iterations=25,
        tier="S",
    ),
    "gemini-3-pro*": ModelProfile(
        tool_calling=ToolCallingProfile(mode="native"),
        max_tokens=65_536,
        max_tool_iterations=25,
        tier="A",
    ),

}


class ModelProfileRegistry:
    """Registry for looking up model profiles by name.

    Supports glob-pattern matching against model IDs. Built-in profiles
    are loaded by default; custom profiles can be added and take priority.

    Usage:
        registry = ModelProfileRegistry()
        profile = registry.get("gpt-5.2")
        # Returns the gpt-5.2 profile with tier="A", native mode, etc.

        profile = registry.get("unknown-model")
        # Returns default ModelProfile() with native mode
    """

    def __init__(self) -> None:
        # Custom profiles take priority over built-ins
        self._custom: Dict[str, ModelProfile] = {}

    def get(self, model: str) -> ModelProfile:
        """Look up the profile for a model.

        Checks custom profiles first, then built-in profiles.
        Returns a default profile if no match found.

        Args:
            model: Model ID (e.g., "gpt-5.2", "gemini-2.5-pro-preview")

        Returns:
            ModelProfile for the model (default profile if not found)
        """
        model_lower = model.lower()

        # Check custom profiles first (exact match, then glob)
        for pattern, profile in self._custom.items():
            if fnmatch.fnmatch(model_lower, pattern.lower()):
                return profile

        # Check built-in profiles (glob match)
        for pattern, profile in BUILTIN_PROFILES.items():
            if fnmatch.fnmatch(model_lower, pattern.lower()):
                return profile

        # Default profile (native tool calling, no special flags)
        return ModelProfile()

    def register(self, pattern: str, profile: ModelProfile) -> None:
        """Register a custom profile for a model pattern.

        Custom profiles take priority over built-in profiles.

        Args:
            pattern: Glob pattern for model ID matching
            profile: ModelProfile to associate
        """
        self._custom[pattern] = profile

    def list_profiles(self) -> Dict[str, ModelProfile]:
        """Return all registered profiles (custom + built-in).

        Returns:
            Dict mapping pattern to profile, custom profiles first
        """
        result: Dict[str, ModelProfile] = {}
        result.update(self._custom)
        result.update(BUILTIN_PROFILES)
        return result


# Module-level singleton for convenience
_default_registry: Optional[ModelProfileRegistry] = None


def get_registry() -> ModelProfileRegistry:
    """Get the default model profile registry (singleton).

    Returns:
        ModelProfileRegistry with built-in profiles loaded
    """
    global _default_registry
    if _default_registry is None:
        _default_registry = ModelProfileRegistry()
    return _default_registry


def get_profile(model: str) -> ModelProfile:
    """Convenience function: look up a model profile.

    Args:
        model: Model ID

    Returns:
        ModelProfile for the model
    """
    return get_registry().get(model)
