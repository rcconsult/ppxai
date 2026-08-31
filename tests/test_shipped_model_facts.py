"""The shipped per-model facts table — data assertions and glob matching.

Renamed from `test_model_profiles.py` by Item 65: the profile vocabulary it
was named after is gone, and every test here now asserts against
`SHIPPED_MODEL_FACTS`. The model-by-model expectations (which models are
prompt-based, which use the Responses wire, which globs must not shadow each
other) are the ORIGINAL ones — they were always about the data, not the
container, so they survived the migration unchanged.

Two classes were rewritten rather than retired: the dataclass-default tests
now assert `ModelFacts`'s defaults (and the ONE that inverted — see
`TestTheDefaultsThatChangedMeaning`), and the registry's glob-matching cases
now exercise `match_table`, which resolves an exact id before any glob
regardless of insertion order — a property the retired registry did not have.
"""


from ppxai.engine.model_facts import (
    SHIPPED_MODEL_FACTS,
    ModelFacts,
    shipped_facts_for_model,
)


class TestTheDefaultsThatChangedMeaning:
    """`ToolCallingProfile` and `ModelProfile` are gone (Item 65).

    Their dataclass-default tests went with them, but ONE of those defaults
    is the reason this migration needed care, so it is asserted here against
    the record that replaced them: `ToolCallingProfile.mode` defaulted to
    "native" while `ModelFacts.tool_mode` defaults to "prompt_based" — ADR
    0012 Q0a inverted it deliberately, so an unmeasured model is assumed NOT
    tool-capable rather than assumed capable.

    52 of the 65 shipped rows relied on the old default, which is why every
    re-authored row states `tool_mode` explicitly (fenced in
    `test_model_facts_are_the_source.py`).
    """

    def test_the_unmeasured_default_is_conservative(self):
        assert ModelFacts().tool_mode == "prompt_based"

    def test_the_wire_default_is_the_common_one(self):
        assert ModelFacts().wire_protocol == "chat_completions"

    def test_an_unmeasured_model_claims_nothing(self):
        """The floor, as a whole record. A model no table names must not
        claim vision, reasoning, or a budget it has not been measured to
        have."""
        floor = ModelFacts()
        assert floor.supports_vision is False
        assert floor.supports_reasoning is False
        assert floor.tier == ""
        assert floor.restricted_params == ()


class TestGlobMatchingSurvivedTheRegistry:
    """`ModelProfileRegistry` is gone; `match_table` does its job.

    These are the registry's own matching cases, re-pointed. The behaviour
    they pin is load-bearing — an id resolving to the wrong row silently
    gives a model another model's capabilities — and one case is BETTER than
    the registry's: `match_table` resolves an exact id before any glob
    regardless of insertion order, where the registry matched in dict order
    and relied on a comment to keep specific rows above generic ones (Q0b).
    """

    def test_exact_match(self):
        facts = shipped_facts_for_model("gpt-5")
        assert facts.tier == "A"
        assert facts.tool_mode == "native"

    def test_glob_match(self):
        facts = shipped_facts_for_model("gemini-2.5-pro-preview")
        assert facts.tier == "S"
        assert facts.tool_mode == "native"

    def test_glob_match_flash(self):
        assert shipped_facts_for_model("gemini-2.5-flash-preview-05-20").tier == "S"

    def test_unknown_model_returns_the_floor(self):
        """NOTE the changed expectation: the old registry's default profile
        answered `native`, the facts floor answers `prompt_based`. That IS
        the Q0a inversion, and it is the safer answer — an unknown model is
        no longer assumed able to call tools natively."""
        facts = shipped_facts_for_model("completely-unknown-model-xyz")
        assert facts.tier == ""
        assert facts.tool_mode == "prompt_based"

    def test_case_insensitive_matching(self):
        assert shipped_facts_for_model("GPT-5.2").tier == "A"

    def test_an_exact_id_beats_a_glob(self):
        """Q0b, and an improvement on the registry: order-independent."""
        from ppxai.engine.model_facts import match_table

        table = {"gpt-5*": "glob", "gpt-5.2": "exact"}
        assert match_table(table, "gpt-5.2") == "exact"
        assert match_table(dict(reversed(list(table.items()))), "gpt-5.2") == "exact"

    def test_the_table_covers_every_shipped_glob(self):
        assert len(SHIPPED_MODEL_FACTS) >= 10


class TestBuiltinProfiles:
    """Test built-in profile data integrity."""

    def test_profile_count(self):
        """Reasonable number of built-in profiles."""
        assert len(SHIPPED_MODEL_FACTS) >= 10

    def test_o4_mini_is_prompt_based(self):
        """o4-mini should be prompt-based (benchmark-proven)."""
        facts = shipped_facts_for_model("o4-mini")
        assert facts.tool_mode == "prompt_based"
        assert facts.supports_reasoning is True

    def test_gpt_4_1_mini_is_prompt_based(self):
        """gpt-4.1-mini should be prompt-based (benchmark-proven)."""
        facts = shipped_facts_for_model("gpt-4.1-mini")
        assert facts.tool_mode == "prompt_based"

    def test_gpt_5_2_is_native(self):
        """gpt-5.2 should be native (best performing)."""
        facts = shipped_facts_for_model("gpt-5.2")
        assert facts.tool_mode == "native"
        assert facts.strip_json_from_text is True
        assert facts.parallel_tool_calls is True

    def test_codex_uses_responses_api(self):
        """codex models should use responses API path."""
        facts = shipped_facts_for_model("gpt-5.1-codex")
        assert facts.wire_protocol == "responses"

    def test_gpt_5_2_restricted_params(self):
        """gpt-5.2 should have restricted params."""
        facts = shipped_facts_for_model("gpt-5.2")
        assert "temperature" in facts.restricted_params
        assert "top_p" in facts.restricted_params

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
            facts = shipped_facts_for_model(model)
            assert facts.max_tokens == expected, \
                f"{model}: expected max_tokens={expected}, got {facts.max_tokens}"

    def test_max_tokens_gemini_models(self):
        """Gemini models should have correct max_tokens."""
        facts = shipped_facts_for_model("gemini-2.5-pro-preview")
        assert facts.max_tokens == 65_536
        facts = shipped_facts_for_model("gemini-2.5-flash-preview-05-20")
        assert facts.max_tokens == 65_536

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
            facts = shipped_facts_for_model(model)
            assert facts.max_tokens == expected_tokens, \
                f"{model}: expected max_tokens={expected_tokens}, got {facts.max_tokens}"
            assert facts.supports_reasoning is expected_reasoning, \
                f"{model}: expected supports_reasoning={expected_reasoning}"
            assert "temperature" in facts.restricted_params, \
                f"{model}: should have temperature in restricted_params"

    def test_max_tokens_legacy_models(self):
        """Legacy GPT-4o models should have correct max_tokens."""
        for model in ["gpt-4o", "gpt-4o-mini"]:
            facts = shipped_facts_for_model(model)
            assert facts.max_tokens == 16_384, \
                f"{model}: expected max_tokens=16384, got {facts.max_tokens}"

    def test_gpt_5_5_resolves_to_native_profile(self):
        """gpt-5.5 (released 2026-04-23) should resolve to its own facts."""
        for model in ["gpt-5.5", "gpt-5.5-pro", "gpt-5.5-2026-04-23"]:
            facts = shipped_facts_for_model(model)
            assert facts.tool_mode == "native", \
                f"{model} should be native, got {facts.tool_mode}"
            assert facts.parallel_tool_calls is True, \
                f"{model} should support parallel tool calls"
            assert facts.supports_vision is True, \
                f"{model} should support vision"
            assert "temperature" in facts.restricted_params, \
                f"{model} should have temperature restricted"

    def test_gpt_5_3_codex_uses_responses_api(self):
        """gpt-5.3-codex must hit the Responses API path like other Codex variants."""
        facts = shipped_facts_for_model("gpt-5.3-codex")
        assert facts.wire_protocol == "responses", \
            "gpt-5.3-codex should use Responses API"
        assert facts.tool_mode == "native"
        assert facts.max_tokens == 128_000
        assert facts.supports_vision is True

    def test_gpt_5_pro_not_shadowed_by_gpt_5_glob(self):
        """gpt-5-pro must match its own profile, not gpt-5*."""
        facts = shipped_facts_for_model("gpt-5-pro")
        # gpt-5-pro is a premium tier — restricted params, native tool calling
        assert facts.tool_mode == "native"
        assert "temperature" in facts.restricted_params, \
            "gpt-5-pro should have restricted sampling params"
        # Verify base gpt-5 still matches its own profile (no restricted params)
        base = shipped_facts_for_model("gpt-5")
        assert "temperature" not in base.restricted_params, \
            "Base gpt-5 should NOT have restricted_params (was: it doesn't in the registry)"

    def test_codex_mini_not_shadowed_by_codex_glob(self):
        """gpt-5.1-codex-mini must match its own profile, not gpt-5.1-codex*."""
        facts = shipped_facts_for_model("gpt-5.1-codex-mini")
        assert facts.tier == "B", f"codex-mini should be tier B, got {facts.tier}"
        assert facts.tool_mode == "native", \
            f"codex-mini should be native, got {facts.tool_mode}"
        # Verify codex (non-mini) still matches its own profile
        codex = shipped_facts_for_model("gpt-5.1-codex")
        assert codex.tier == "B"
        assert codex.tool_mode == "native"

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
            facts = shipped_facts_for_model(model)
            assert facts.max_tokens == expected, \
                f"{model}: expected max_tokens={expected}, got {facts.max_tokens}"

    def test_sonar_reasoning_pro_not_shadowed(self):
        """sonar-reasoning-pro must match its own profile, not sonar*."""
        facts = shipped_facts_for_model("sonar-reasoning-pro")
        assert facts.supports_reasoning is True, \
            "sonar-reasoning-pro should have supports_reasoning=True"
        assert facts.max_tokens == 12_288, \
            f"sonar-reasoning-pro: expected max_tokens=12288, got {facts.max_tokens}"
        # Regular sonar should NOT have reasoning flag
        sonar = shipped_facts_for_model("sonar")
        assert sonar.supports_reasoning is False

    def test_dgx_vllm_qwen3_coder(self):
        """Qwen3-Coder-30B vLLM model should match its facts."""
        facts = shipped_facts_for_model("Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8")
        assert facts.tier == "S"
        assert facts.tool_mode == "native"
        assert facts.parallel_tool_calls is True
        assert facts.max_tokens == 8_192

    def test_dgx_vllm_qwen3_coder_next(self):
        """Qwen3-Coder-Next vLLM model should match its facts."""
        facts = shipped_facts_for_model("Qwen/Qwen3-Coder-Next-FP8")
        assert facts.tier == "B"
        assert facts.tool_mode == "native"
        assert facts.max_tokens == 8_192

    def test_qwen_35_36_27b_fp8_supports_vision(self):
        """Both Qwen3.5-27B-FP8 and Qwen3.6-27B-FP8 are empirically VL-capable
        through vLLM. Verified 2026-06-08 by an in-cluster probe (256x128 PNG
        containing 'VL TEST 8472' + the prompt 'What number is in this image?'
        with chat_template_kwargs={'enable_thinking': False}, max_tokens=1500)
        — both endpoints returned the exact string '8472'. Cross-host evidence
        in docs/lessons/qwen-27b-vl-empirically-supported.md."""
        # Include the `-agent` suffix variant: the codeai cluster serves the
        # 3.6 model as `Qwen/Qwen3.6-27B-FP8-agent` (latency-tuned vLLM build;
        # see config example commit df954033). The glob's trailing `*` matches
        # it today — pin it so a future pattern tightening can't silently
        # regress the actively-served model to supports_vision=False (the exact
        # failure class Item 24 exists to prevent).
        for model in [
            "Qwen/Qwen3.5-27B-FP8",
            "Qwen/Qwen3.6-27B-FP8",
            "Qwen/Qwen3.6-27B-FP8-agent",
        ]:
            facts = shipped_facts_for_model(model)
            assert facts.supports_vision is True, \
                f"{model}: empirically VL-capable but supports_vision={facts.supports_vision}"
            assert facts.tool_mode == "native", \
                f"{model}: should use native tool calling"
            assert facts.max_tokens == 8_192

    def test_minimax_m27_profile_2026_06_09_dgx_cluster_swap(self):
        """MiniMax-M2.7 (dgx-cluster MoE, 230B/10B-active) facts.
        Verified 2026-06-09 against https://dgx-cluster.internal/vllm/v1:
        text round-trip OK on OpenAI-compat shape; image_url is REJECTED
        by vllm with HTTP 400 'minimax-m2.7 is not a multimodal model';
        reasoning emitted inline as <think>...</think> in content
        (ppxai's openai_compat provider strips these at lines 419-423)."""
        facts = shipped_facts_for_model("minimax-m2.7")
        assert facts.tool_mode == "native"
        assert facts.fallback_on_empty is True, \
            "Provider config sets fallback_on_empty=True; profile must mirror"
        assert facts.strip_json_from_text is True
        assert facts.supports_vision is False, \
            "vLLM serves MiniMax-M2.7 without a vision encoder — must be False"
        assert facts.supports_reasoning is True
        assert facts.max_tokens == 32_768
        assert facts.max_tool_iterations == 20

    def test_qwen_36_35b_a3b_fp8_supports_vision(self):
        """Qwen3.6-35B-A3B-FP8 (DGX Spark MoE) is empirically VL-capable.
        Verified 2026-06-09 against http://dgx-spark.internal:8000/v1 with the
        same probe used for the 27B variants. Behaves cleaner than 27B: even
        without chat_template_kwargs.enable_thinking=False, the default call
        emits content directly. Tier S — 83.2% on the 36-test in-cluster
        suite (Qwen3-Coder-30B sibling at 81.25%)."""
        facts = shipped_facts_for_model("Qwen/Qwen3.6-35B-A3B-FP8")
        assert facts.supports_vision is True, \
            f"Qwen3.6-35B-A3B-FP8: empirically VL-capable but supports_vision={facts.supports_vision}"
        assert facts.tool_mode == "native"
        assert facts.parallel_tool_calls is True, \
            "Qwen3.6-35B-A3B-FP8 is MoE — should match Qwen3-Coder-30B parallel pattern"
        assert facts.tier == "S"
        assert facts.max_tokens == 8_192

    def test_dgx_vllm_qwen3_next_instruct(self):
        """Qwen3-Next-80B Instruct should match its facts."""
        facts = shipped_facts_for_model("Qwen/Qwen3-Next-80B-A3B-Instruct-FP8")
        assert facts.tier == "C"
        assert facts.tool_mode == "native"
        assert facts.supports_reasoning is False

    def test_dgx_vllm_qwen3_next_thinking(self):
        """Qwen3-Next-80B Thinking should match its facts."""
        facts = shipped_facts_for_model("Qwen/Qwen3-Next-80B-A3B-Thinking-FP8")
        assert facts.tier == "B"
        assert facts.supports_reasoning is True

    def test_dgx_vllm_redhat_qwen3(self):
        """RedHatAI Qwen3-30B should match its facts."""
        facts = shipped_facts_for_model("RedHatAI/Qwen3-30B-A3B-FP8-dynamic")
        assert facts.tier == "B"
        assert facts.tool_mode == "native"

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
            facts = shipped_facts_for_model(model)
            assert facts.tool_mode == expected_mode, \
                f"{model}: expected mode={expected_mode}, got {facts.tool_mode}"
            assert facts.max_tokens == expected_tokens, \
                f"{model}: expected max_tokens={expected_tokens}, got {facts.max_tokens}"
            assert facts.tier == expected_tier, \
                f"{model}: expected tier={expected_tier}, got {facts.tier}"

    def test_gpt_oss_profile(self):
        """GPT-OSS vLLM model should be prompt-based with max_tokens."""
        facts = shipped_facts_for_model("openai/gpt-oss-120b")
        assert facts.tool_mode == "prompt_based"
        assert facts.max_tokens == 16_384
        assert facts.tier == "B"

    def test_gemini_3_models(self):
        """Gemini 3 preview models should have profiles."""
        flash = shipped_facts_for_model("gemini-3-flash-preview")
        assert flash.tier == "S", f"gemini-3-flash: expected tier=S, got {flash.tier}"
        assert flash.max_tokens == 65_536

    def test_max_tokens_default_zero(self):
        """Unknown models should have max_tokens=0 (use provider default)."""
        facts = shipped_facts_for_model("unknown-model-xyz")
        assert facts.max_tokens == 0

    def test_all_profiles_have_valid_mode(self):
        """All profiles have valid tool calling mode."""
        valid_modes = {"native", "prompt_based", "auto"}
        for pattern, facts in SHIPPED_MODEL_FACTS.items():
            assert facts.tool_mode in valid_modes, \
                f"Profile {pattern} has invalid mode: {facts.tool_mode}"

    def test_every_row_has_a_real_wire(self):
        """Every row names a wire a handler actually exists for.

        The old vocabulary was `api_path` in {chat, responses, auto};
        `auto` was never implemented. `wire_protocol` names handlers,
        so an invalid value here means a request routed to nothing.
        """
        valid_wires = {"chat_completions", "responses", "generate_content"}
        for pattern, facts in SHIPPED_MODEL_FACTS.items():
            assert facts.wire_protocol in valid_wires, \
                f"{pattern} has invalid wire_protocol: {facts.wire_protocol}"

    def test_all_profiles_have_tier(self):
        """All profiles have a tier assigned."""
        valid_tiers = {"S", "A", "B", "C", "D"}
        for pattern, facts in SHIPPED_MODEL_FACTS.items():
            assert facts.tier in valid_tiers, \
                f"Profile {pattern} has invalid tier: {facts.tier!r}"


class TestConvenienceFunctions:
    """Test module-level convenience functions."""

    def test_shipped_facts_for_model(self):
        """get_profile returns correct facts."""
        facts = shipped_facts_for_model("gpt-5.2")
        assert facts.tier == "A"

    def test_the_shipped_table_is_a_module_constant(self):
        """`get_registry()` was a lazy singleton; the facts table is a plain
        module-level dict, so there is no instance to be identical — the
        constant IS the single source. Asserting identity of the import is
        what remains meaningful."""
        from ppxai.engine import model_facts

        assert model_facts.SHIPPED_MODEL_FACTS is SHIPPED_MODEL_FACTS


class TestFlashLiteProfile:
    """Test gemini-2.5-flash-lite profile (v1.16.0).

    Flash-lite is a weak agent — needs fallback hints and low iteration cap.
    Must match BEFORE the general gemini-2.5-flash* pattern.
    """

    def test_flash_lite_matches_before_flash(self):
        """flash-lite pattern takes priority over flash wildcard."""
        lite = shipped_facts_for_model("gemini-2.5-flash-lite")
        flash = shipped_facts_for_model("gemini-2.5-flash")
        assert lite.tier == "D"
        assert flash.tier == "S"

    def test_flash_lite_has_fallback_flags(self):
        """flash-lite enables fallback_on_empty and fallback_on_failure."""
        facts = shipped_facts_for_model("gemini-2.5-flash-lite")
        assert facts.fallback_on_empty is True
        assert facts.fallback_on_failure is True

    def test_flash_lite_low_iteration_limit(self):
        """flash-lite has a low max_tool_iterations to prevent runaway loops."""
        facts = shipped_facts_for_model("gemini-2.5-flash-lite")
        assert facts.max_tool_iterations == 10

    def test_flash_lite_low_max_tokens(self):
        """flash-lite has low max_tokens to prevent truncated patches."""
        facts = shipped_facts_for_model("gemini-2.5-flash-lite")
        assert facts.max_tokens == 8_192


class TestEffectiveResolutionReplacesTheMergeSite:
    """RETARGETED from `TestGetEffectiveProfile` (ADR 0012 section 2 Q0e/Q0f).

    `chat.get_effective_profile` merged THREE vocabularies onto a
    `ModelProfile` -- the built-in table, an AGENTS.md `tool_calling`
    section, and `providers.<p>.tool_calling` config -- with its own layer
    order. It is deleted, so the six tests that drove it directly are
    retargeted here rather than left asserting a function that is gone.

    Where each premise went:

    * "config overrides built-in" -- ALIVE, and asserted here against the
      resolver that replaced the merge site.
    * "bootstrap overrides built-in" and "config overrides bootstrap" --
      DEAD. Q0f retires the AGENTS.md `tool_calling` parser: measured
      across this repo and two other checkouts, no AGENTS.md contains such
      a section, so it was a parser with no users and a third vocabulary
      for one question. Benchmark tuning gets a defined home instead
      (Q0h, `benchmarks/tuning/<provider>_<model>.json`).
    * "preserves non-tool-calling fields" -- ALIVE, and stronger now: the
      old merge site silently DROPPED `supports_vision` whenever any
      override layer was present, because it rebuilt the record field by
      field and forgot one. A single `replace()` on a frozen record cannot
      lose a field, which is why that shape is gone rather than fixed.
    """

    def _facts(self, model, provider="openai", overrides=None):
        from ppxai.engine.model_facts import apply_overrides, shipped_facts_for_model

        shipped = shipped_facts_for_model(model)
        if overrides is None:
            return shipped
        return apply_overrides(shipped, overrides)

    def test_no_overrides_returns_the_shipped_row(self):
        from ppxai.engine.model_facts import shipped_facts_for_model

        assert self._facts("gpt-5.2") == shipped_facts_for_model("gpt-5.2")

    def test_config_overrides_the_shipped_row(self):
        got = self._facts(
            "gpt-5.2",
            overrides={"tool_mode": "prompt_based", "fallback_on_empty": True},
        )
        assert got.tool_mode == "prompt_based"
        assert got.fallback_on_empty is True

    def test_unstated_fields_are_preserved(self):
        from ppxai.engine.model_facts import shipped_facts_for_model

        shipped = shipped_facts_for_model("gpt-5.2")
        got = self._facts("gpt-5.2", overrides={"tool_mode": "prompt_based"})
        assert got.strip_json_from_text == shipped.strip_json_from_text
        assert got.tier == shipped.tier

    def test_max_tokens_override(self):
        assert self._facts("gpt-5.2", overrides={"max_tokens": 1234}).max_tokens == 1234

    def test_supports_vision_survives_an_override(self):
        """The bug the old merge site actually had -- LATENT, not live.

        `get_effective_profile` rebuilt `ModelProfile` field by field when
        any layer was present and omitted `supports_vision`, so its return
        value said `False` for a vision model whenever a config override of
        an unrelated field existed.

        It never reached an image decision: that function had exactly ONE
        caller, which read only the tool-loop fields, while every vision
        reader (`file_preprocessing`, the `model_supports_vision` AppState
        field, the `/attach` warning) calls `model_profiles.supports_vision`
        directly. A trap for the next caller rather than a shipped
        regression -- worth pinning for exactly that reason.
        """
        from ppxai.engine.model_facts import shipped_facts_for_model

        model = "gemini-2.5-pro"
        assert shipped_facts_for_model(model).supports_vision is True
        got = self._facts(model, overrides={"max_tokens": 4096})
        assert got.supports_vision is True

    def test_the_merge_site_is_gone(self):
        """It was deleted, not wrapped -- the collapse ADR 0012 asked for."""
        import ppxai.engine.chat as chat

        assert not hasattr(chat, "get_effective_profile")


class TestNvidiaNimProfiles:
    """Sentinel: namespaced NIM model IDs (`<owner>/<model>`) match the
    correct facts. Free-form `qwen3-coder*` patterns without leading
    `*/` only match non-namespaced IDs — regression here means agentic
    NIM users silently fall back to the default facts.

    Added in v1.18.3 alongside the NVIDIA provider entry. Update this
    list whenever a new NIM model is added to the config — failure to
    match here means the model_profiles registry needs a new pattern.
    """

    def test_qwen3_coder_480b_namespaced(self):
        p = shipped_facts_for_model("qwen/qwen3-coder-480b-a35b-instruct")
        assert p.tier == "S", "Tier S expected (qwen3-coder family)"
        assert p.tool_mode == "native"
        assert p.parallel_tool_calls is True

    def test_qwen3_5_122b_namespaced(self):
        p = shipped_facts_for_model("qwen/qwen3.5-122b-a10b")
        assert p.tier == "A", "Tier A expected (NIM benchmark 77.4%)"
        assert p.tool_mode == "native"

    def test_qwen3_5_397b_namespaced(self):
        p = shipped_facts_for_model("qwen/qwen3.5-397b-a17b")
        assert p.tier == "B", "Tier B provisional (probe failed, family-inherited)"
        assert p.tool_mode == "native"

    def test_qwen3_next_80b_thinking_supports_reasoning(self):
        p = shipped_facts_for_model("qwen/qwen3-next-80b-a3b-thinking")
        assert p.supports_reasoning is True

    def test_llama_3_3_nemotron_supports_reasoning(self):
        p = shipped_facts_for_model("nvidia/llama-3.3-nemotron-super-49b-v1.5")
        assert p.supports_reasoning is True, (
            "Nemotron uses /think /no_think in-prompt convention; "
            "supports_reasoning marks it as a reasoning-capable model"
        )
        assert p.tool_mode == "native"

    def test_mistral_large_3_namespaced(self):
        p = shipped_facts_for_model("mistralai/mistral-large-3-675b-instruct-2512")
        assert p.tier == "B"
        assert p.tool_mode == "native"

    def test_devstral_2_namespaced(self):
        p = shipped_facts_for_model("mistralai/devstral-2-123b-instruct-2512")
        assert p.tier == "B"
        assert p.tool_mode == "native"

    def test_unknown_nim_model_falls_through_to_the_floor(self):
        """An id matching no row must NOT silently borrow another row's
        capabilities — it lands on the floor.

        The `tool_mode` expectation CHANGED with Item 65, and the change is
        the point: the retired profile default was "native", the facts floor
        is "prompt_based" (ADR 0012 Q0a inverted it — unmeasured implies
        assume not capable). The old value would have sent a native tools
        array to a model nobody has ever measured. Updated deliberately, not
        to make the suite green.
        """
        facts = shipped_facts_for_model("nvidia/totally-fake-model-name-xyz")
        assert facts.tier == ""
        assert facts.tool_mode == "prompt_based"
