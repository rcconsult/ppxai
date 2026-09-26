"""Perplexity deprecated as a CHAT provider, kept as a web_search backend.

Owner decision 2026-09-27 (option B), phase 1: nothing is removed. Gemini
becomes the default chat provider everywhere a default is shipped, selecting
Perplexity for chat warns but never raises, and the web_search backend no
longer depends on the chat provider class, so phase 2 can delete it.

"Never raises" is a contract with ppxai-sre: its `initialize()` calls
`EngineClient.set_provider()` on whatever the operator's config resolves to,
so a raise would fail start-up on every host still defaulting to Perplexity.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import ppxai.config.providers as providers_mod
import ppxai.server.session_manager as session_manager_mod
from ppxai.commands.doctor import deprecated_default_provider
from ppxai.config import DEPRECATED_CHAT_PROVIDERS, FALLBACK_PROVIDER
from ppxai.engine import EngineClient
from ppxai.engine.tools.builtin import web_premium
from ppxai.engine.types import EventType

REPO = Path(__file__).resolve().parent.parent


def _with_config(monkeypatch, config: dict) -> None:
    store = SimpleNamespace(config=config)
    monkeypatch.setattr(providers_mod.ConfigStore, "get_instance", staticmethod(lambda: store))


class TestTheDeprecationTable:

    def test_perplexity_is_deprecated_for_chat(self):
        assert "perplexity" in DEPRECATED_CHAT_PROVIDERS
        assert "web_search" in DEPRECATED_CHAT_PROVIDERS["perplexity"]

    def test_the_fallback_is_not_itself_deprecated(self):
        assert FALLBACK_PROVIDER == "gemini"
        assert FALLBACK_PROVIDER not in DEPRECATED_CHAT_PROVIDERS


class TestDefaultProviderFallback:

    def test_no_default_configured_lands_on_gemini(self, monkeypatch):
        monkeypatch.delenv("MODEL_PROVIDER", raising=False)
        _with_config(monkeypatch, {"providers": {"perplexity": {}, "gemini": {}}})
        assert providers_mod.get_default_provider() == "gemini"

    def test_an_unconfigured_default_never_falls_back_to_perplexity(self, monkeypatch):
        monkeypatch.delenv("MODEL_PROVIDER", raising=False)
        _with_config(monkeypatch, {
            "default_provider": "missing",
            "providers": {"openai": {}, "perplexity": {}},
        })
        assert providers_mod.get_default_provider() == "openai"

    def test_an_explicit_perplexity_default_is_still_honoured(self, monkeypatch):
        """Deprecated, not removed: an operator's explicit choice still works."""
        monkeypatch.delenv("MODEL_PROVIDER", raising=False)
        _with_config(monkeypatch, {
            "default_provider": "perplexity",
            "providers": {"perplexity": {}, "gemini": {}},
        })
        assert providers_mod.get_default_provider() == "perplexity"

    def test_an_unknown_provider_config_is_empty_not_perplexitys(self, monkeypatch):
        _with_config(monkeypatch, {"providers": {"perplexity": {"name": "P"}}})
        assert providers_mod.get_provider_config("nonexistent") == {}


class TestShippedDefaultsAreGemini:
    """Every place that ships a default chat provider names gemini."""

    @pytest.mark.parametrize("name", ["ppxai-config.json", "ppxai-config.example.json"])
    def test_shipped_configs(self, name):
        assert json.loads((REPO / name).read_text(encoding="utf-8"))["default_provider"] == "gemini"

    @pytest.mark.parametrize("name", ["install.sh", "scripts/install.ps1"])
    def test_installers_generate_a_gemini_default(self, name):
        text = (REPO / name).read_text(encoding="utf-8")
        assert re.findall(r'"default_provider":\s*"(\w+)"', text) == ["gemini"]

    def test_vscode_built_in_config(self):
        text = (REPO / "vscode-extension/src/config.ts").read_text(encoding="utf-8")
        assert re.findall(r'default_provider:\s*"(\w+)"', text) == ["gemini"]

    def test_vscode_setting_default(self):
        pkg = json.loads((REPO / "vscode-extension/package.json").read_text(encoding="utf-8"))
        props = pkg["contributes"]["configuration"]["properties"]
        assert props["ppxai.defaultProvider"]["default"] == "gemini"


class TestSelectingPerplexityWarnsAndNeverRaises:

    @pytest.fixture
    def engine(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "test-not-a-key")
        monkeypatch.setenv("GEMINI_API_KEY", "test-not-a-key")
        return EngineClient()

    def test_set_provider_succeeds_and_queues_one_notice(self, engine):
        assert engine.set_provider("perplexity") is True
        assert engine._pending_provider_notice == DEPRECATED_CHAT_PROVIDERS["perplexity"]

    def test_switching_away_clears_the_notice(self, engine):
        engine.set_provider("perplexity")
        engine.set_provider("gemini")
        assert engine._pending_provider_notice is None

    def test_the_next_chat_turn_leads_with_the_notice_once(self, engine):
        engine.set_provider("perplexity")

        async def first_event():
            agen = engine.chat("hi")
            try:
                return await agen.__anext__()
            finally:
                await agen.aclose()

        event = asyncio.run(first_event())
        assert event.type == EventType.INFO
        assert event.metadata == {"notice": "provider_deprecated", "provider": "perplexity"}
        assert engine._pending_provider_notice is None


class TestDoctorFlagsADeprecatedDefault:

    def test_config_default(self, monkeypatch):
        monkeypatch.delenv("MODEL_PROVIDER", raising=False)
        assert deprecated_default_provider({"default_provider": "perplexity"}) == "perplexity"
        assert deprecated_default_provider({"default_provider": "gemini"}) is None
        assert deprecated_default_provider(None) is None

    def test_model_provider_env_wins_over_the_file(self, monkeypatch):
        monkeypatch.setenv("MODEL_PROVIDER", "gemini")
        assert deprecated_default_provider({"default_provider": "perplexity"}) is None


def test_web_search_no_longer_depends_on_the_chat_provider_class():
    """Phase 2 deletes `PerplexityProvider`; the web_search backend must survive it."""
    assert not hasattr(web_premium, "PerplexityProvider")
    source = Path(web_premium.__file__).read_text(encoding="utf-8")
    assert "providers.perplexity import" not in source


class TestTheServerStartsOnTheConfiguredDefault:
    """`SessionManager` used `get_available_providers()[0]`, so the server
    started on whichever provider block came first in the file (Perplexity)
    regardless of `default_provider`. Found by the 2026-09-27 live check."""

    class _Engine:
        def __init__(self, usable):
            self.usable, self.tried = usable, []

        def set_provider(self, name):
            self.tried.append(name)
            return name in self.usable

    def _patch(self, monkeypatch, default, available):
        monkeypatch.setattr(session_manager_mod, "get_default_provider", lambda: default)
        monkeypatch.setattr(session_manager_mod, "get_available_providers", lambda: available)

    def test_the_default_wins_over_file_order(self, monkeypatch):
        self._patch(monkeypatch, "gemini", ["perplexity", "gemini", "openai"])
        engine = self._Engine({"perplexity", "gemini", "openai"})
        session_manager_mod._select_default_provider(engine)
        assert engine.tried == ["gemini"]

    def test_a_default_without_a_key_falls_back_in_file_order(self, monkeypatch):
        self._patch(monkeypatch, "gemini", ["perplexity", "gemini", "openai"])
        engine = self._Engine({"openai"})
        session_manager_mod._select_default_provider(engine)
        assert engine.tried == ["gemini", "perplexity", "openai"]
