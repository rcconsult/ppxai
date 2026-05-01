"""
Tests for model profile system (v1.15.6).

Tests the ModelProfile dataclasses, ModelProfileRegistry glob matching,
and built-in profile data integrity.
"""

import pytest

from ppxai.engine.model_profiles import (
    ModelProfile,
    ToolCallingProfile,
    ModelProfileRegistry,
    BUILTIN_PROFILES,
    get_profile,
    get_registry,
)


class TestToolCallingProfile:
    """Test ToolCallingProfile dataclass defaults."""

    def test_default_values(self):
        """Default profile uses native mode with no special flags."""
        profile = ToolCallingProfile()
        assert profile.mode == "native"
        assert profile.fallback_on_empty is False
        assert profile.fallback_on_failure is False
        assert profile.strip_json_from_text is False
        assert profile.parallel_tool_calls is False
        assert profile.api_path == "chat"

    def test_prompt_based_mode(self):
        """Create a prompt-based profile."""
        profile = ToolCallingProfile(mode="prompt_based")
        assert profile.mode == "prompt_based"

    def test_responses_api_path(self):
        """Create a profile with responses API path."""
        profile = ToolCallingProfile(api_path="responses")
        assert profile.api_path == "responses"


class TestModelProfile:
    """Test ModelProfile dataclass."""

    def test_default_values(self):
        """Default profile has sane defaults."""
        profile = ModelProfile()
        assert profile.tool_calling.mode == "native"
        assert profile.max_tokens == 0
        assert profile.supports_reasoning is False
        assert profile.restricted_params == []
        assert profile.tier == ""

    def test_reasoning_model(self):
        """Profile for reasoning model."""
        profile = ModelProfile(
            supports_reasoning=True,
            restricted_params=["temperature", "top_p"],
        )
        assert profile.supports_reasoning is True
        assert "temperature" in profile.restricted_params


class TestModelProfileRegistry:
    """Test ModelProfileRegistry glob matching."""

    def test_exact_match_builtin(self):
        """Match exact model name in built-in profiles."""
        registry = ModelProfileRegistry()
        profile = registry.get("gpt-5")
        assert profile.tier == "A"
        assert profile.tool_calling.mode == "native"

    def test_glob_match_builtin(self):
        """Match model name using glob pattern."""
        registry = ModelProfileRegistry()
        profile = registry.get("gemini-2.5-pro-preview")
        assert profile.tier == "S"
        assert profile.tool_calling.mode == "native"

    def test_glob_match_flash(self):
        """Match Gemini Flash model."""
        registry = ModelProfileRegistry()
        profile = registry.get("gemini-2.5-flash-preview-05-20")
        assert profile.tier == "S"

    def test_unknown_model_returns_default(self):
        """Unknown model returns default profile."""
        registry = ModelProfileRegistry()
        profile = registry.get("completely-unknown-model-xyz")
        assert profile.tier == ""
        assert profile.tool_calling.mode == "native"

    def test_case_insensitive_matching(self):
        """Matching is case-insensitive."""
        registry = ModelProfileRegistry()
        profile = registry.get("GPT-5.2")
        assert profile.tier == "A"

    def test_custom_profile_priority(self):
        """Custom profiles take priority over built-in."""
        registry = ModelProfileRegistry()
        custom = ModelProfile(tier="X", tool_calling=ToolCallingProfile(mode="prompt_based"))
        registry.register("gpt-5.2*", custom)

        profile = registry.get("gpt-5.2")
        assert profile.tier == "X"
        assert profile.tool_calling.mode == "prompt_based"

    def test_custom_does_not_affect_other_models(self):
        """Custom profile for one model doesn't affect others."""
        registry = ModelProfileRegistry()
        custom = ModelProfile(tier="X")
        registry.register("my-custom-model", custom)

        profile = registry.get("gpt-5.2")
        assert profile.tier == "A"  # Still uses built-in

    def test_list_profiles(self):
        """list_profiles returns all profiles."""
        registry = ModelProfileRegistry()
        profiles = registry.list_profiles()
        assert len(profiles) >= len(BUILTIN_PROFILES)


class TestBuiltinProfiles:
    """Test built-in profile data integrity."""

    def test_profile_count(self):
        """Reasonable number of built-in profiles."""
        assert len(BUILTIN_PROFILES) >= 10

    def test_o4_mini_is_prompt_based(self):
        """o4-mini should be prompt-based (benchmark-proven)."""
        profile = get_profile("o4-mini")
        assert profile.tool_calling.mode == "prompt_based"
        assert profile.supports_reasoning is True

    def test_gpt_4_1_mini_is_prompt_based(self):
        """gpt-4.1-mini should be prompt-based (benchmark-proven)."""
        profile = get_profile("gpt-4.1-mini")
        assert profile.tool_calling.mode == "prompt_based"

    def test_gpt_5_2_is_native(self):
        """gpt-5.2 should be native (best performing)."""
        profile = get_profile("gpt-5.2")
        assert profile.tool_calling.mode == "native"
        assert profile.tool_calling.strip_json_from_text is True
        assert profile.tool_calling.parallel_tool_calls is True

    def test_codex_uses_responses_api(self):
        """codex models should use responses API path."""
        profile = get_profile("gpt-5.1-codex")
        assert profile.tool_calling.api_path == "responses"

    def test_gpt_5_2_restricted_params(self):
        """gpt-5.2 should have restricted params."""
        profile = get_profile("gpt-5.2")
        assert "temperature" in profile.restricted_params
        assert "top_p" in profile.restricted_params

    def test_max_tokens_openai_models(self):
        """OpenAI models should have correct max_tokens from API docs."""
        cases = [
            ("gpt-5.2", 128_000),
            ("gpt-5", 128_000),
            ("gpt-5-mini", 128_000),
            ("gpt-4.1", 32_768),
            ("gpt-4.1-mini", 32_768),
            ("gpt-4.1-nano", 32_768),
            ("o4-mini", 100_000),
            ("gpt-5.1-codex", 128_000),
            ("gpt-5.1-codex-mini", 128_000),
        ]
        for model, expected in cases:
            profile = get_profile(model)
            assert profile.max_tokens == expected, \
                f"{model}: expected max_tokens={expected}, got {profile.max_tokens}"

    def test_max_tokens_gemini_models(self):
        """Gemini models should have correct max_tokens."""
        profile = get_profile("gemini-2.5-pro-preview")
        assert profile.max_tokens == 65_536
        profile = get_profile("gemini-2.5-flash-preview-05-20")
        assert profile.max_tokens == 65_536

    def test_max_tokens_reasoning_models(self):
        """Reasoning models should have correct max_tokens and flags."""
        cases = [
            ("o3", 100_000, True),
            ("o3-mini", 100_000, True),
            ("o3-pro", 100_000, True),
            ("o1", 100_000, True),
            ("o1-mini", 65_536, True),
        ]
        for model, expected_tokens, expected_reasoning in cases:
            profile = get_profile(model)
            assert profile.max_tokens == expected_tokens, \
                f"{model}: expected max_tokens={expected_tokens}, got {profile.max_tokens}"
            assert profile.supports_reasoning is expected_reasoning, \
                f"{model}: expected supports_reasoning={expected_reasoning}"
            assert "temperature" in profile.restricted_params, \
                f"{model}: should have temperature in restricted_params"

    def test_max_tokens_legacy_models(self):
        """Legacy GPT-4o models should have correct max_tokens."""
        for model in ["gpt-4o", "gpt-4o-mini"]:
            profile = get_profile(model)
            assert profile.max_tokens == 16_384, \
                f"{model}: expected max_tokens=16384, got {profile.max_tokens}"

    def test_gpt_5_5_resolves_to_native_profile(self):
        """gpt-5.5 (released 2026-04-23) should resolve to its own profile."""
        for model in ["gpt-5.5", "gpt-5.5-pro", "gpt-5.5-2026-04-23"]:
            profile = get_profile(model)
            assert profile.tool_calling.mode == "native", \
                f"{model} should be native, got {profile.tool_calling.mode}"
            assert profile.tool_calling.parallel_tool_calls is True, \
                f"{model} should support parallel tool calls"
            assert profile.supports_vision is True, \
                f"{model} should support vision"
            assert "temperature" in profile.restricted_params, \
                f"{model} should have temperature restricted"

    def test_gpt_5_3_codex_uses_responses_api(self):
        """gpt-5.3-codex must hit the Responses API path like other Codex variants."""
        profile = get_profile("gpt-5.3-codex")
        assert profile.tool_calling.api_path == "responses", \
            "gpt-5.3-codex should use Responses API"
        assert profile.tool_calling.mode == "native"
        assert profile.max_tokens == 128_000
        assert profile.supports_vision is True

    def test_gpt_5_pro_not_shadowed_by_gpt_5_glob(self):
        """gpt-5-pro must match its own profile, not gpt-5*."""
        profile = get_profile("gpt-5-pro")
        # gpt-5-pro is a premium tier — restricted params, native tool calling
        assert profile.tool_calling.mode == "native"
        assert "temperature" in profile.restricted_params, \
            "gpt-5-pro should have restricted sampling params"
        # Verify base gpt-5 still matches its own profile (no restricted params)
        base = get_profile("gpt-5")
        assert "temperature" not in base.restricted_params, \
            "Base gpt-5 should NOT have restricted_params (was: it doesn't in the registry)"

    def test_codex_mini_not_shadowed_by_codex_glob(self):
        """gpt-5.1-codex-mini must match its own profile, not gpt-5.1-codex*."""
        profile = get_profile("gpt-5.1-codex-mini")
        assert profile.tier == "B", f"codex-mini should be tier B, got {profile.tier}"
        assert profile.tool_calling.mode == "native", \
            f"codex-mini should be native, got {profile.tool_calling.mode}"
        # Verify codex (non-mini) still matches its own profile
        codex = get_profile("gpt-5.1-codex")
        assert codex.tier == "B"
        assert codex.tool_calling.mode == "native"

    def test_max_tokens_perplexity_models(self):
        """Perplexity sonar models should have correct max_tokens."""
        cases = [
            ("sonar", 2_048),
            ("sonar-pro", 8_192),
            ("sonar-reasoning-pro", 12_288),
            ("sonar-deep-research", 8_192),
            ("llama-3.1-sonar-large-128k-online", 2_048),
        ]
        for model, expected in cases:
            profile = get_profile(model)
            assert profile.max_tokens == expected, \
                f"{model}: expected max_tokens={expected}, got {profile.max_tokens}"

    def test_sonar_reasoning_pro_not_shadowed(self):
        """sonar-reasoning-pro must match its own profile, not sonar*."""
        profile = get_profile("sonar-reasoning-pro")
        assert profile.supports_reasoning is True, \
            "sonar-reasoning-pro should have supports_reasoning=True"
        assert profile.max_tokens == 12_288, \
            f"sonar-reasoning-pro: expected max_tokens=12288, got {profile.max_tokens}"
        # Regular sonar should NOT have reasoning flag
        sonar = get_profile("sonar")
        assert sonar.supports_reasoning is False

    def test_dgx_vllm_qwen3_coder(self):
        """Qwen3-Coder-30B vLLM model should match its profile."""
        profile = get_profile("Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8")
        assert profile.tier == "S"
        assert profile.tool_calling.mode == "native"
        assert profile.tool_calling.parallel_tool_calls is True
        assert profile.max_tokens == 8_192

    def test_dgx_vllm_qwen3_coder_next(self):
        """Qwen3-Coder-Next vLLM model should match its profile."""
        profile = get_profile("Qwen/Qwen3-Coder-Next-FP8")
        assert profile.tier == "B"
        assert profile.tool_calling.mode == "native"
        assert profile.max_tokens == 8_192

    def test_dgx_vllm_qwen3_next_instruct(self):
        """Qwen3-Next-80B Instruct should match its profile."""
        profile = get_profile("Qwen/Qwen3-Next-80B-A3B-Instruct-FP8")
        assert profile.tier == "C"
        assert profile.tool_calling.mode == "native"
        assert profile.supports_reasoning is False

    def test_dgx_vllm_qwen3_next_thinking(self):
        """Qwen3-Next-80B Thinking should match its profile."""
        profile = get_profile("Qwen/Qwen3-Next-80B-A3B-Thinking-FP8")
        assert profile.tier == "B"
        assert profile.supports_reasoning is True

    def test_dgx_vllm_redhat_qwen3(self):
        """RedHatAI Qwen3-30B should match its profile."""
        profile = get_profile("RedHatAI/Qwen3-30B-A3B-FP8-dynamic")
        assert profile.tier == "B"
        assert profile.tool_calling.mode == "native"

    def test_ollama_qwen_models(self):
        """Ollama-served Qwen models should have profiles."""
        cases = [
            ("qwen2.5-coder:32b", "prompt_based", 4_096, "B"),
            ("qwen2.5-coder:32b-64k", "prompt_based", 4_096, "B"),
            ("qwen2.5-coder:3b", "native", 4_096, "C"),
            ("qwen2.5-coder:0.5b", "native", 4_096, "C"),
            ("qwen3:30b-a3b", "prompt_based", 8_192, "D"),
        ]
        for model, expected_mode, expected_tokens, expected_tier in cases:
            profile = get_profile(model)
            assert profile.tool_calling.mode == expected_mode, \
                f"{model}: expected mode={expected_mode}, got {profile.tool_calling.mode}"
            assert profile.max_tokens == expected_tokens, \
                f"{model}: expected max_tokens={expected_tokens}, got {profile.max_tokens}"
            assert profile.tier == expected_tier, \
                f"{model}: expected tier={expected_tier}, got {profile.tier}"

    def test_gpt_oss_profile(self):
        """GPT-OSS vLLM model should be prompt-based with max_tokens."""
        profile = get_profile("openai/gpt-oss-120b")
        assert profile.tool_calling.mode == "prompt_based"
        assert profile.max_tokens == 16_384
        assert profile.tier == "B"

    def test_gemini_3_models(self):
        """Gemini 3 preview models should have profiles."""
        flash = get_profile("gemini-3-flash-preview")
        assert flash.tier == "S", f"gemini-3-flash: expected tier=S, got {flash.tier}"
        assert flash.max_tokens == 65_536

    def test_max_tokens_default_zero(self):
        """Unknown models should have max_tokens=0 (use provider default)."""
        profile = get_profile("unknown-model-xyz")
        assert profile.max_tokens == 0

    def test_all_profiles_have_valid_mode(self):
        """All profiles have valid tool calling mode."""
        valid_modes = {"native", "prompt_based", "auto"}
        for pattern, profile in BUILTIN_PROFILES.items():
            assert profile.tool_calling.mode in valid_modes, \
                f"Profile {pattern} has invalid mode: {profile.tool_calling.mode}"

    def test_all_profiles_have_valid_api_path(self):
        """All profiles have valid API path."""
        valid_paths = {"chat", "responses", "auto"}
        for pattern, profile in BUILTIN_PROFILES.items():
            assert profile.tool_calling.api_path in valid_paths, \
                f"Profile {pattern} has invalid api_path: {profile.tool_calling.api_path}"

    def test_all_profiles_have_tier(self):
        """All profiles have a tier assigned."""
        valid_tiers = {"S", "A", "B", "C", "D"}
        for pattern, profile in BUILTIN_PROFILES.items():
            assert profile.tier in valid_tiers, \
                f"Profile {pattern} has invalid tier: {profile.tier!r}"


class TestConvenienceFunctions:
    """Test module-level convenience functions."""

    def test_get_profile(self):
        """get_profile returns correct profile."""
        profile = get_profile("gpt-5.2")
        assert profile.tier == "A"

    def test_get_registry_singleton(self):
        """get_registry returns same instance."""
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2


class TestFlashLiteProfile:
    """Test gemini-2.5-flash-lite profile (v1.16.0).

    Flash-lite is a weak agent — needs fallback hints and low iteration cap.
    Must match BEFORE the general gemini-2.5-flash* pattern.
    """

    def test_flash_lite_matches_before_flash(self):
        """flash-lite pattern takes priority over flash wildcard."""
        registry = ModelProfileRegistry()
        lite = registry.get("gemini-2.5-flash-lite")
        flash = registry.get("gemini-2.5-flash")
        assert lite.tier == "D"
        assert flash.tier == "S"

    def test_flash_lite_has_fallback_flags(self):
        """flash-lite enables fallback_on_empty and fallback_on_failure."""
        profile = get_profile("gemini-2.5-flash-lite")
        assert profile.tool_calling.fallback_on_empty is True
        assert profile.tool_calling.fallback_on_failure is True

    def test_flash_lite_low_iteration_limit(self):
        """flash-lite has a low max_tool_iterations to prevent runaway loops."""
        profile = get_profile("gemini-2.5-flash-lite")
        assert profile.max_tool_iterations == 10

    def test_flash_lite_low_max_tokens(self):
        """flash-lite has low max_tokens to prevent truncated patches."""
        profile = get_profile("gemini-2.5-flash-lite")
        assert profile.max_tokens == 8_192


class TestGetEffectiveProfile:
    """Tests for get_effective_profile merging (v1.16.0 Step 5)."""

    def test_no_overrides_returns_builtin(self):
        """Without any overrides, returns the built-in profile unchanged."""
        from unittest.mock import patch, MagicMock
        from ppxai.engine.chat import get_effective_profile

        ctx = MagicMock()
        ctx._bootstrap_context = None

        with patch("ppxai.engine.chat.get_tool_calling_config", return_value={}):
            profile = get_effective_profile("gpt-5.2", "openai", ctx)
        builtin = get_profile("gpt-5.2")
        assert profile.tool_calling.mode == builtin.tool_calling.mode
        assert profile.tier == builtin.tier

    def test_config_overrides_builtin(self):
        """Config overrides take precedence over built-in profile."""
        from unittest.mock import patch, MagicMock
        from ppxai.engine.chat import get_effective_profile

        ctx = MagicMock()
        ctx._bootstrap_context = None

        overrides = {"mode": "prompt_based", "fallback_on_empty": True}
        with patch("ppxai.engine.chat.get_tool_calling_config", return_value=overrides):
            profile = get_effective_profile("gpt-5.2", "openai", ctx)
        assert profile.tool_calling.mode == "prompt_based"
        assert profile.tool_calling.fallback_on_empty is True
        # Non-overridden fields preserved from built-in
        builtin = get_profile("gpt-5.2")
        assert profile.tool_calling.strip_json_from_text == builtin.tool_calling.strip_json_from_text

    def test_bootstrap_overrides_builtin(self):
        """Bootstrap overrides take precedence over built-in profile."""
        from unittest.mock import patch, MagicMock
        from ppxai.engine.chat import get_effective_profile

        bootstrap = MagicMock()
        bootstrap.get_tool_calling_overrides.return_value = {"mode": "auto"}

        ctx = MagicMock()
        ctx._bootstrap_context = bootstrap

        with patch("ppxai.engine.chat.get_tool_calling_config", return_value={}):
            profile = get_effective_profile("gpt-5.2", "openai", ctx)
        assert profile.tool_calling.mode == "auto"

    def test_config_overrides_bootstrap(self):
        """Config overrides take precedence over bootstrap overrides."""
        from unittest.mock import patch, MagicMock
        from ppxai.engine.chat import get_effective_profile

        bootstrap = MagicMock()
        bootstrap.get_tool_calling_overrides.return_value = {"mode": "auto", "fallback_on_empty": True}

        ctx = MagicMock()
        ctx._bootstrap_context = bootstrap

        config_overrides = {"mode": "prompt_based"}
        with patch("ppxai.engine.chat.get_tool_calling_config", return_value=config_overrides):
            profile = get_effective_profile("gpt-5.2", "openai", ctx)
        # Config wins for mode
        assert profile.tool_calling.mode == "prompt_based"
        # Bootstrap wins for fallback_on_empty (config didn't set it)
        assert profile.tool_calling.fallback_on_empty is True

    def test_max_tokens_override(self):
        """max_tokens can be overridden via config."""
        from unittest.mock import patch, MagicMock
        from ppxai.engine.chat import get_effective_profile

        ctx = MagicMock()
        ctx._bootstrap_context = None

        overrides = {"max_tokens": 32768}
        with patch("ppxai.engine.chat.get_tool_calling_config", return_value=overrides):
            profile = get_effective_profile("gpt-5.2", "openai", ctx)
        assert profile.max_tokens == 32768

    def test_preserves_non_tc_fields(self):
        """Non-tool-calling fields (tier, supports_reasoning) are preserved."""
        from unittest.mock import patch, MagicMock
        from ppxai.engine.chat import get_effective_profile

        ctx = MagicMock()
        ctx._bootstrap_context = None

        overrides = {"mode": "prompt_based"}
        with patch("ppxai.engine.chat.get_tool_calling_config", return_value=overrides):
            profile = get_effective_profile("gpt-5.2", "openai", ctx)
        builtin = get_profile("gpt-5.2")
        assert profile.tier == builtin.tier
        assert profile.supports_reasoning == builtin.supports_reasoning
        assert profile.restricted_params == builtin.restricted_params


class TestNvidiaNimProfiles:
    """Sentinel: namespaced NIM model IDs (`<owner>/<model>`) match the
    correct profile. Free-form `qwen3-coder*` patterns without leading
    `*/` only match non-namespaced IDs — regression here means agentic
    NIM users silently fall back to the default profile.

    Added in v1.18.3 alongside the NVIDIA provider entry. Update this
    list whenever a new NIM model is added to the config — failure to
    match here means the model_profiles registry needs a new pattern.
    """

    def test_qwen3_coder_480b_namespaced(self):
        p = get_profile("qwen/qwen3-coder-480b-a35b-instruct")
        assert p.tier == "S", "Tier S expected (qwen3-coder family)"
        assert p.tool_calling.mode == "native"
        assert p.tool_calling.parallel_tool_calls is True

    def test_qwen3_5_122b_namespaced(self):
        p = get_profile("qwen/qwen3.5-122b-a10b")
        assert p.tier == "A", "Tier A expected (NIM benchmark 77.4%)"
        assert p.tool_calling.mode == "native"

    def test_qwen3_5_397b_namespaced(self):
        p = get_profile("qwen/qwen3.5-397b-a17b")
        assert p.tier == "B", "Tier B provisional (probe failed, family-inherited)"
        assert p.tool_calling.mode == "native"

    def test_qwen3_next_80b_thinking_supports_reasoning(self):
        p = get_profile("qwen/qwen3-next-80b-a3b-thinking")
        assert p.supports_reasoning is True

    def test_llama_3_3_nemotron_supports_reasoning(self):
        p = get_profile("nvidia/llama-3.3-nemotron-super-49b-v1.5")
        assert p.supports_reasoning is True, (
            "Nemotron uses /think /no_think in-prompt convention; "
            "supports_reasoning marks it as a reasoning-capable model"
        )
        assert p.tool_calling.mode == "native"

    def test_mistral_large_3_namespaced(self):
        p = get_profile("mistralai/mistral-large-3-675b-instruct-2512")
        assert p.tier == "B"
        assert p.tool_calling.mode == "native"

    def test_devstral_2_namespaced(self):
        p = get_profile("mistralai/devstral-2-123b-instruct-2512")
        assert p.tier == "B"
        assert p.tool_calling.mode == "native"

    def test_unknown_nim_model_falls_through_to_default(self):
        """Sanity: non-pattern-matching NIM model IDs should NOT silently
        match a wrong profile — they fall through to the default."""
        p = get_profile("nvidia/totally-fake-model-name-xyz")
        assert p.tier == ""  # default profile has empty tier
        assert p.tool_calling.mode == "native"  # default mode
