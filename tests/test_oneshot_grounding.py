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
    def test_default_off(self):
        """No config => grounding disabled (byte-identical legacy behavior)."""
        with patch.object(oneshot_mod, "get_tool_config", return_value={}):
            assert oneshot_mod._oneshot_grounding_enabled() is False

    def test_explicit_on(self):
        with patch.object(
            oneshot_mod, "get_tool_config",
            return_value={"oneshot_grounding": True},
        ):
            assert oneshot_mod._oneshot_grounding_enabled() is True

    def test_explicit_off(self):
        with patch.object(
            oneshot_mod, "get_tool_config",
            return_value={"oneshot_grounding": False},
        ):
            assert oneshot_mod._oneshot_grounding_enabled() is False

    def test_config_error_fails_to_off(self):
        with patch.object(
            oneshot_mod, "get_tool_config", side_effect=RuntimeError("boom")
        ):
            assert oneshot_mod._oneshot_grounding_enabled() is False


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
            oneshot_mod, "get_tool_config", lambda name: {}
        )
        oneshot_mod._build_provider("gemini")
        assert provider.enable_grounding is False

    def test_flag_on_grounds_search_provider(self, monkeypatch):
        provider = MagicMock()
        provider.enable_grounding = False
        _patch_construction(monkeypatch, provider)
        monkeypatch.setattr(
            oneshot_mod, "get_tool_config",
            lambda name: {"oneshot_grounding": True},
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
