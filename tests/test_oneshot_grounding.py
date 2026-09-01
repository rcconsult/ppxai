"""Tests for Option A — config-driven native web search on the oneshot tiers.

See docs/archive/plan-oneshot-grounding.md. The contract under test:

1. `tools.web_search.oneshot_grounding` (default OFF) gates everything.
2. When ON, a SEARCH-CAPABLE provider (capabilities.web_search=true) is switched
   into native grounding at construction (Gemini: enable_grounding=True).
3. When ON, a NON-search provider (OpenAI/NVIDIA, web_search=false) is a NO-OP —
   the flag must never be mistaken for tool exposure.
4. PERIMETER LOCK: no `web_search`/`fetch_url`/`get_weather` tool is ever
   registered on the oneshot path. This is the negative test that bites if the
   change ever drifts toward Option B (handing the model a web tool).

These are unit tests on the construction helpers — no provider SDK is exercised.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ppxai.server.routes import oneshot as oneshot_mod

# ---------------------------------------------------------------------------
# Flag plumbing
# ---------------------------------------------------------------------------


class TestGroundingFlag:
    """F2 (ADR 0011 Q5): the flag now reads `execution.run.grounding` via
    get_execution_run_config (which itself dual-reads the legacy key —
    covered in TestExecutionRunConfig below)."""

    def test_default_off(self):
        """No config => grounding disabled (byte-identical legacy behavior)."""
        with patch.object(
            oneshot_mod, "get_execution_run_config",
            return_value={"web_search": False, "grounding": False},
        ):
            assert oneshot_mod._oneshot_grounding_enabled() is False

    def test_explicit_on(self):
        with patch.object(
            oneshot_mod, "get_execution_run_config",
            return_value={"web_search": False, "grounding": True},
        ):
            assert oneshot_mod._oneshot_grounding_enabled() is True

    def test_config_error_fails_to_off(self):
        with patch.object(
            oneshot_mod, "get_execution_run_config",
            side_effect=RuntimeError("boom"),
        ):
            assert oneshot_mod._oneshot_grounding_enabled() is False


class TestExecutionRunConfig:
    """The `execution.run.*` reader (config axis, ADR 0010/0011) — defaults,
    explicit values, and the grounding dual-read from the legacy key."""

    @staticmethod
    def _read(config: dict, legacy_tool_cfg: dict | None = None):
        from ppxai.config import execution as exec_mod
        from ppxai.config import tools as tools_cfg

        with patch.object(exec_mod, "get_config", return_value=config), \
             patch.object(
                 tools_cfg, "get_tool_config",
                 return_value=legacy_tool_cfg or {},
             ):
            return exec_mod.get_execution_run_config()

    def test_defaults_both_off(self):
        assert self._read({}) == {"web_search": False, "grounding": False}

    def test_web_search_explicit_on(self):
        cfg = {"execution": {"run": {"web_search": True}}}
        assert self._read(cfg)["web_search"] is True

    def test_grounding_dual_reads_legacy_key(self):
        # No execution.run.grounding → the shipped v1.19.0 key still works.
        got = self._read({}, legacy_tool_cfg={"oneshot_grounding": True})
        assert got["grounding"] is True

    def test_explicit_grounding_wins_over_legacy(self):
        cfg = {"execution": {"run": {"grounding": False}}}
        got = self._read(cfg, legacy_tool_cfg={"oneshot_grounding": True})
        assert got["grounding"] is False

    def test_config_error_fails_to_defaults(self):
        from ppxai.config import execution as exec_mod

        with patch.object(
            exec_mod, "get_config", side_effect=RuntimeError("boom")
        ):
            assert exec_mod.get_execution_run_config() == {
                "web_search": False, "grounding": False,
            }

    def test_config_error_defeats_the_legacy_grounding_dual_read(self):
        """An unreadable config must not leave `grounding` enabled via the
        LEGACY key.

        `get_execution_run_config` reads two sources: the `execution` block
        and — only when `execution.run.grounding` is absent — the legacy
        `tools.web_search.oneshot_grounding`. Patching the first still left
        the second readable, so a box whose config failed to load kept
        native search ON. This test pins the fail-safe by making the legacy
        key TRUE while the config source is broken; the old code returned
        `grounding: True` here.

        (It also made `test_config_error_fails_to_defaults` order-dependent:
        it passed only while no earlier test had left the legacy key set in
        the shared ConfigStore.)
        """
        from ppxai.config import execution as exec_mod

        with patch.object(
            exec_mod, "get_config", side_effect=RuntimeError("boom")
        ), patch(
            "ppxai.config.tools.get_tool_config",
            return_value={"oneshot_grounding": True},
        ):
            assert exec_mod.get_execution_run_config() == {
                "web_search": False, "grounding": False,
            }

    def test_loader_passes_execution_block_through(self, tmp_path, monkeypatch):
        """REGRESSION (caught live in the F3 trial): load_config()'s return
        dict is a top-level WHITELIST. The execution block parsed fine in the
        JSON but never reached get_config() — and the grounding dual-read
        fallback masked the drop, so only a loader-level test can catch it.
        Same trap as file_tree (v1.18.7) and the get_agent_config whitelist
        (spawn_consent). No get_config mocking here — the real loader runs."""
        import json as _json

        from ppxai.config.loader import load_config

        cfg_file = tmp_path / "cfg.json"
        cfg_file.write_text(_json.dumps({
            "providers": {},
            "execution": {"run": {"web_search": True, "grounding": False}},
        }), encoding="utf-8")
        monkeypatch.setenv("PPXAI_CONFIG_FILE", str(cfg_file))
        loaded = load_config()
        assert loaded["execution"] == {
            "run": {"web_search": True, "grounding": False}
        }


class TestUsageCaptureChannel:
    """F4: the per-call ContextVar holder replaces the process-global
    reset-on-read handoff (ADR 0009 §4's named concurrency bug)."""

    def test_concurrent_captures_do_not_cross_attribute(self):
        import asyncio

        from ppxai.engine.tools.builtin import web_premium
        from ppxai.engine.types import ToolUsage

        async def one_call(tag: str, record_delay: float, linger: float):
            holder = web_premium.begin_usage_capture()

            async def tool():
                await asyncio.sleep(record_delay)
                web_premium._record_usage(ToolUsage(call_count=1, provider=tag))

            task = asyncio.create_task(tool())
            await task
            # Linger so the OTHER call records (and overwrites the legacy
            # global) before this call inspects its holder — the exact
            # interleaving that misattributed under the old channel.
            await asyncio.sleep(linger)
            return holder

        async def main():
            return await asyncio.gather(
                one_call("A", 0.001, 0.05), one_call("B", 0.02, 0.0)
            )

        a, b = asyncio.run(main())
        assert [u.provider for u in a] == ["A"]
        assert [u.provider for u in b] == ["B"]

    def test_legacy_global_still_maintained(self):
        from ppxai.engine.tools.builtin import web_premium
        from ppxai.engine.types import ToolUsage

        web_premium.begin_usage_capture()
        web_premium._record_usage(ToolUsage(call_count=1, provider="x"))
        got = web_premium.get_last_tool_usage()
        assert got is not None and got.provider == "x"
        assert web_premium.get_last_tool_usage() is None  # reset-on-read


class _StubProvider:
    """Stands in for a registered provider class in the gate tests."""

    from ppxai.engine.types import ProviderCapabilities as _PC

    default_capabilities = _PC()
    shipped_model_facts: dict = {}


class TestEffectivePath:
    """The ADR 0009 section 4 gating truth table.

    F5: the logic lives on the config axis
    (`config.execution.get_effective_oneshot_path`) so `/doctor` shares the
    exact decision the route makes.

    **Retargeted for ADR 0012 section 2 Q0e.** The two inputs used to come
    from two vocabularies — `get_provider_config()["capabilities"]` for
    endpoint search and `get_tool_calling_config()` for tool mode, with a
    hand-written "native OR an explicit tool_calling block" rule bridging
    them. They are now two disjoint records read through one resolver each,
    so the patches target `ProviderCapabilities` (endpoint) and
    `ModelFacts` (model). The truth table itself is unchanged — this is
    the same decision, asked once instead of twice.
    """

    @staticmethod
    def _path(*, grounding=False, enrichment=False, web_capable=False,
              tool_mode="prompt_based"):
        from ppxai.config import execution as exec_mod
        from ppxai.engine.model_facts import ModelFacts
        from ppxai.engine.types import ProviderCapabilities

        with patch.object(
            exec_mod, "get_execution_run_config",
            return_value={"web_search": enrichment, "grounding": grounding},
        ), patch(
            "ppxai.engine.providers.get_provider_class",
            # A real class, so the endpoint branch is reached at all — the
            # test provider "p" is not registered, and the resolver treats
            # an unknown provider as "no endpoint record", which silently
            # made both grounding cases fall through to closed-book.
            return_value=_StubProvider,
        ), patch(
            "ppxai.engine.facts_resolver.apply_provider_overrides",
            return_value=ProviderCapabilities(web_search=web_capable),
        ), patch(
            "ppxai.engine.facts_resolver.facts_without_an_instance",
            return_value=ModelFacts(tool_mode=tool_mode),
        ):
            return oneshot_mod._oneshot_effective_path("p", "m")

    def test_both_off_is_closed_book(self):
        assert self._path() == "closed-book"

    def test_grounding_on_capable_is_native(self):
        assert self._path(grounding=True, web_capable=True) == "native"

    def test_grounding_on_incapable_falls_closed_book(self):
        """An endpoint with no search index cannot ground natively."""
        assert self._path(grounding=True, web_capable=False) == "closed-book"

    def test_enrichment_on_tool_capable_is_search_loop(self):
        assert self._path(enrichment=True, tool_mode="native") == "search-loop"

    def test_enrichment_off_is_closed_book_whatever_the_model(self):
        """CORRECTED. This asserted that a `prompt_based` model made the
        gate closed-book, which was my own misreading — see
        `test_prompt_based_still_drives_the_search_loop` below. What is
        actually true is the simpler thing: with enrichment off, no model
        reaches the search loop."""
        assert self._path(enrichment=False, tool_mode="native") == "closed-book"
        assert self._path(enrichment=False, tool_mode="prompt_based") == (
            "closed-book"
        )

    def test_native_beats_search_loop_xor(self):
        """Both enabled: native grounding wins, exactly as before."""
        assert self._path(
            grounding=True, enrichment=True, web_capable=True,
            tool_mode="native",
        ) == "native"

    def test_auto_mode_counts_as_capable(self):
        """`auto` carries "native with a prompt-based fallback"."""
        assert self._path(enrichment=True, tool_mode="auto") == "search-loop"

    def test_prompt_based_still_drives_the_search_loop(self):
        """RESTORED — deleting this hid a `/v1/oneshot` regression.

        Its predecessor (`test_prompt_based_tool_calling_counts_as_capable`)
        asserted that an explicit `tool_calling` block made a model capable
        for this gate even at `mode: prompt_based`, because the ADR 0009
        search loop runs fine on prompt-based calling — `chat.py` parses
        tool JSON out of the response text, which is what `prompt_based`
        MEANS. I dropped it while retargeting and replaced it with the
        opposite assertion, which took `execution.run.web_search`
        enrichment away from o4-mini, gpt-4.1-mini, sonar and every local
        model.

        The gate's question is "can this model drive a tool loop at all",
        not "should we send a native tools array". Pre-ADR it asked
        `mode != "none"`, and `"none"` has no successor in `ToolMode`.
        """
        assert self._path(enrichment=True, tool_mode="prompt_based") == (
            "search-loop"
        )

    @pytest.mark.parametrize("tool_mode", ["native", "prompt_based", "auto"])
    def test_every_tool_mode_can_drive_the_loop(self, tool_mode):
        """Parametrised so a new `ToolMode` value cannot silently default
        to incapable — it fails here until someone decides."""
        assert self._path(enrichment=True, tool_mode=tool_mode) == "search-loop"

    def test_the_capability_question_is_not_the_send_path_question(self):
        """The two questions are distinct and must stay distinct."""
        from ppxai.engine.model_facts import ModelFacts, can_drive_a_tool_loop

        facts = ModelFacts(tool_mode="prompt_based")
        assert can_drive_a_tool_loop(facts) is True
        assert (facts.tool_mode != "prompt_based") is False


class TestTypeBasedProviders:
    """openai_compat-TYPE providers reach the gate too (openrouter, nvidia,
    every vLLM/Ollama box) — and `get_provider_class` returns None for all
    of them, because they are configured by name rather than registered.

    Reading `get_provider_class(p).default_capabilities` therefore raised
    `AttributeError` and the gate silently concluded "no endpoint record",
    so provider-native grounding never resolved for any of them. The truth
    table above never caught it because it only ever instantiated a
    registered provider.
    """

    def test_an_unregistered_provider_resolves_to_openai_compat(self):
        from ppxai.engine.facts_resolver import provider_class_for
        from ppxai.engine.providers import get_provider_class
        from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider

        assert get_provider_class("myrouter") is None
        assert provider_class_for("myrouter") is OpenAICompatibleProvider

    def test_grounding_resolves_native_for_a_type_based_provider(
        self, tmp_path, monkeypatch
    ):
        import json

        import ppxai.config.facts_config as fc
        from ppxai.config import execution as exec_mod

        cfg = tmp_path / "ppxai-config.json"
        cfg.write_text(
            json.dumps(
                {
                    "providers": {
                        "myrouter": {
                            "name": "MR",
                            "base_url": "https://example.invalid",
                            "api_key_env": "K",
                            "facts": {"web_search": True},
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(fc, "find_config_file", lambda: cfg)
        with patch.object(
            exec_mod,
            "get_execution_run_config",
            return_value={"web_search": False, "grounding": True},
        ):
            assert (
                exec_mod.get_effective_oneshot_path("myrouter", "some-model")
                == "native"
            )


class TestApplyGrounding:
    def test_gemini_grounding_turned_on(self):
        """Search-capable provider with an enable_grounding hook gets it set."""
        provider = MagicMock()
        provider.enable_grounding = False
        with patch.object(
            oneshot_mod, "get_provider_config",
            return_value={"capabilities": {"web_search": True}},
        ):
            oneshot_mod._apply_oneshot_grounding(provider, "gemini")
        assert provider.enable_grounding is True

    def test_non_search_provider_is_noop(self):
        """OpenAI/NVIDIA (web_search=false) must NOT be touched — the flag is
        not a back-door to search on a provider that has none."""
        provider = MagicMock()
        provider.enable_grounding = False
        with patch.object(
            oneshot_mod, "get_provider_config",
            return_value={"capabilities": {"web_search": False}},
        ):
            oneshot_mod._apply_oneshot_grounding(provider, "openai")
        # Untouched.
        assert provider.enable_grounding is False

    def test_search_provider_without_hook_is_noop(self):
        """Perplexity has web_search but no enable_grounding attr (sonar models
        search intrinsically) — no crash, nothing to flip."""
        class _Bare:
            pass

        provider = _Bare()
        with patch.object(
            oneshot_mod, "get_provider_config",
            return_value={"capabilities": {"web_search": True}},
        ):
            # Must not raise and must not invent the attribute.
            oneshot_mod._apply_oneshot_grounding(provider, "perplexity")
        assert not hasattr(provider, "enable_grounding")

    def test_config_error_is_noop(self):
        provider = MagicMock()
        provider.enable_grounding = False
        with patch.object(
            oneshot_mod, "get_provider_config",
            side_effect=RuntimeError("boom"),
        ):
            oneshot_mod._apply_oneshot_grounding(provider, "gemini")
        assert provider.enable_grounding is False


# ---------------------------------------------------------------------------
# _build_provider integration: flag OFF leaves provider alone, ON applies
# ---------------------------------------------------------------------------


def _patch_construction(monkeypatch, provider):
    """Stub config + create_provider so _build_provider returns `provider`
    without needing real keys/SDKs."""
    monkeypatch.setattr(
        oneshot_mod, "get_available_providers", lambda: ["gemini"]
    )
    monkeypatch.setattr(
        oneshot_mod, "get_provider_config",
        lambda name=None: {"capabilities": {"web_search": True}, "models": {}},
    )
    monkeypatch.setattr(oneshot_mod, "get_api_key", lambda name: "key")
    monkeypatch.setattr(oneshot_mod, "get_base_url", lambda name: "https://x")
    monkeypatch.setattr(
        oneshot_mod, "create_provider", lambda *a, **k: provider
    )


class TestBuildProviderWiring:
    def test_flag_off_does_not_ground(self, monkeypatch):
        provider = MagicMock()
        provider.enable_grounding = False
        _patch_construction(monkeypatch, provider)
        monkeypatch.setattr(
            oneshot_mod, "get_execution_run_config",
            lambda: {"web_search": False, "grounding": False},
        )
        oneshot_mod._build_provider("gemini")
        assert provider.enable_grounding is False

    def test_flag_off_forces_off_even_when_provider_defaults_on(self, monkeypatch):
        # Regression: a Gemini provider is constructed with enable_grounding=True
        # (the config/__init__ default). With the oneshot flag OFF, the oneshot
        # perimeter must FORCE grounding off — otherwise every oneshot silently
        # performs live Google Search, breaking the default-OFF guarantee.
        provider = MagicMock()
        provider.enable_grounding = True
        _patch_construction(monkeypatch, provider)
        monkeypatch.setattr(
            oneshot_mod, "get_execution_run_config",
            lambda: {"web_search": False, "grounding": False},
        )
        oneshot_mod._build_provider("gemini")
        assert provider.enable_grounding is False

    def test_flag_on_grounds_search_provider(self, monkeypatch):
        provider = MagicMock()
        provider.enable_grounding = False
        _patch_construction(monkeypatch, provider)
        monkeypatch.setattr(
            oneshot_mod, "get_execution_run_config",
            lambda: {"web_search": False, "grounding": True},
        )
        oneshot_mod._build_provider("gemini")
        assert provider.enable_grounding is True


# ---------------------------------------------------------------------------
# PERIMETER LOCK — no web tool is registered on the oneshot path
# ---------------------------------------------------------------------------


class TestPerimeterLock:
    def test_oneshot_module_does_not_register_web_tools(self):
        """Option A must NEVER hand the model a web tool. The oneshot route
        builds a provider and calls provider.oneshot() — it must not import or
        invoke web_search/fetch_url registration. If a future change wires a
        tool onto this path (drift to Option B), this test should fail.

        We walk the AST (not raw source) so the guard bites on real CODE
        references — imported names, attribute accesses, call targets — while
        ignoring the docstring/comments, which legitimately MENTION these names
        when explaining what oneshot deliberately does NOT do."""
        import ast
        import inspect

        forbidden = {
            "register_tools",
            "web_search_premium",
            "fetch_url",
            "ScopedToolManager",
        }
        tree = ast.parse(inspect.getsource(oneshot_mod))
        offenders = set()
        for node in ast.walk(tree):
            # Imported symbols: `from x import fetch_url`
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in forbidden:
                        offenders.add(alias.name)
            # Bare name use: `register_tools(...)`
            elif isinstance(node, ast.Name) and node.id in forbidden:
                offenders.add(node.id)
            # Attribute use: `web.fetch_url(...)`, `mod.register_tools`
            elif isinstance(node, ast.Attribute) and node.attr in forbidden:
                offenders.add(node.attr)

        assert not offenders, (
            f"oneshot route references web/exfil tool symbol(s) {offenders} in "
            f"CODE — that would expose a web tool on the tool-free tier "
            f"(Option B). Option A keeps retrieval provider-side only."
        )
