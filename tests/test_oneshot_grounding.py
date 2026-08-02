"""Tests for Option A — config-driven native web search on the oneshot tiers.

See docs/plan-oneshot-grounding.md. The contract under test:

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

from unittest.mock import patch, MagicMock

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


class TestEffectivePath:
    """The ADR 0009 §4 gating truth table (F2: computed + logged only)."""

    @staticmethod
    def _path(*, grounding=False, enrichment=False, web_capable=False,
              native_tools=False, tc_mode=None):
        with patch.object(
            oneshot_mod, "get_execution_run_config",
            return_value={"web_search": enrichment, "grounding": grounding},
        ), patch.object(
            oneshot_mod, "get_provider_config",
            return_value={"capabilities": {
                "web_search": web_capable,
                "native_tool_calling": native_tools,
            }},
        ), patch.object(
            oneshot_mod, "get_tool_calling_config",
            return_value={"mode": tc_mode} if tc_mode else {},
        ):
            return oneshot_mod._oneshot_effective_path("p", "m")

    def test_both_off_is_closed_book(self):
        assert self._path() == "closed-book"

    def test_grounding_on_capable_is_native(self):
        assert self._path(grounding=True, web_capable=True) == "native"

    def test_grounding_on_incapable_falls_closed_book(self):
        assert self._path(grounding=True, web_capable=False) == "closed-book"

    def test_enrichment_on_tool_capable_is_search_loop(self):
        assert self._path(enrichment=True, native_tools=True) == "search-loop"

    def test_enrichment_on_tool_incapable_is_closed_book(self):
        assert self._path(enrichment=True) == "closed-book"

    def test_native_beats_search_loop_xor(self):
        # Enrichment XOR native — never both; native wins when effective.
        assert self._path(
            grounding=True, enrichment=True,
            web_capable=True, native_tools=True,
        ) == "native"

    def test_prompt_based_tool_calling_counts_as_capable(self):
        assert self._path(enrichment=True, tc_mode="prompt") == "search-loop"

    def test_tc_mode_none_is_incapable(self):
        assert self._path(enrichment=True, tc_mode="none") == "closed-book"


# ---------------------------------------------------------------------------
# _apply_oneshot_grounding — capability gate + per-provider mechanism
# ---------------------------------------------------------------------------


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
