"""Perplexity removed as a CHAT provider; kept as the web_search backend.

ADR 0015 (v1.19.3). The provider class and its gateway models are gone. The
contract that matters is what happens to a config or a session that still
names Perplexity:

- a `providers.perplexity` block is ignored, never rewritten, and never
  served through the generic OpenAI-compatible fallback (which would "work"
  against the retired chat-completions endpoint and 400 on every turn);
- `set_provider("perplexity")` returns False and never raises, because
  ppxai-sre's `initialize()` selects the configured default at start-up;
- a restored Perplexity session keeps its history and says, once, that it
  continues on the current provider;
- `/doctor`, `/provider`, `/v1/oneshot` and the task tier name the fix.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import ppxai.config as config_pkg
import ppxai.config.providers as providers_mod
import ppxai.server.http as http_module
import ppxai.server.session_manager as session_manager_mod
from ppxai.commands.doctor import (
    _extract_provider_models,
    _format_removed_provider_section,
    _format_web_search_backend_section,
    removed_chat_providers,
)
from ppxai.commands.provider import handle_provider
from ppxai.config import FALLBACK_PROVIDER, REMOVED_CHAT_PROVIDERS
from ppxai.engine import EngineClient, session_ops
from ppxai.engine.providers import create_provider, get_provider_class
from ppxai.engine.search import perplexity as search_backend
from ppxai.engine.task_authorizer import TaskAuthorizationError, validate_provider_or_error
from ppxai.engine.types import EventType

REPO = Path(__file__).resolve().parent.parent

#: A config an operator upgrading from v1.19.2 may still have.
LEFTOVER = {
    "default_provider": "perplexity",
    "providers": {
        "perplexity": {
            "name": "Perplexity AI",
            "base_url": "https://api.perplexity.ai",
            "api_key_env": "PERPLEXITY_API_KEY",
            "default_model": "perplexity/sonar",
            "models": {
                "perplexity/sonar": {},
                "openai/gpt-5.6-terra": {},
                "anthropic/claude-sonnet-5": {},
                "__comment_x": "not a model",
            },
        },
        "gemini": {"name": "Gemini", "api_key_env": "GEMINI_API_KEY", "default_model": "g"},
    },
}


def _with_config(monkeypatch, config: dict) -> None:
    store = SimpleNamespace(config=config)
    monkeypatch.setattr(providers_mod.ConfigStore, "get_instance", staticmethod(lambda: store))


class TestTheRemovalTable:

    def test_perplexity_is_removed_and_the_message_names_the_fix(self):
        message = REMOVED_CHAT_PROVIDERS["perplexity"]
        assert "web_search" in message
        assert "providers.perplexity" in message
        assert "gemini" in message

    def test_the_fallback_is_not_itself_removed(self):
        assert FALLBACK_PROVIDER == "gemini"
        assert FALLBACK_PROVIDER not in REMOVED_CHAT_PROVIDERS

    def test_no_provider_class_is_registered(self):
        assert get_provider_class("perplexity") is None
        assert create_provider("perplexity", api_key="k") is None

    def test_the_module_is_gone(self):
        assert not (REPO / "ppxai/engine/providers/perplexity.py").exists()


class TestALeftoverBlockIsIgnored:

    def test_it_is_not_an_available_provider(self, monkeypatch):
        _with_config(monkeypatch, LEFTOVER)
        assert providers_mod.get_available_providers() == ["gemini"]
        assert providers_mod.get_provider_config("perplexity") == {}

    def test_it_is_named_as_a_leftover(self, monkeypatch):
        _with_config(monkeypatch, LEFTOVER)
        assert providers_mod.removed_providers_in_config() == ["perplexity"]

    def test_a_perplexity_default_falls_back(self, monkeypatch):
        monkeypatch.delenv("MODEL_PROVIDER", raising=False)
        _with_config(monkeypatch, LEFTOVER)
        assert providers_mod.get_default_provider() == "gemini"

    def test_model_provider_perplexity_falls_back(self, monkeypatch):
        monkeypatch.setenv("MODEL_PROVIDER", "perplexity")
        _with_config(monkeypatch, LEFTOVER)
        assert providers_mod.get_default_provider() == "gemini"

    def test_the_engine_provider_table_excludes_it(self, monkeypatch):
        _with_config(monkeypatch, LEFTOVER)
        config_pkg._refresh_module_dicts()
        try:
            assert "perplexity" not in config_pkg.PROVIDERS
            assert "gemini" in config_pkg.PROVIDERS
        finally:
            monkeypatch.undo()
            config_pkg._refresh_module_dicts()

    def test_an_unknown_provider_config_is_empty(self, monkeypatch):
        _with_config(monkeypatch, LEFTOVER)
        assert providers_mod.get_provider_config("nonexistent") == {}

    def test_startup_warns_once(self, monkeypatch):
        _with_config(monkeypatch, LEFTOVER)
        warnings: list[str] = []
        monkeypatch.setattr(config_pkg, "_initialized", False)
        monkeypatch.setattr(config_pkg._config_logger, "warning", warnings.append)
        monkeypatch.setattr(config_pkg, "_loader_initialize", lambda: False)
        config_pkg.initialize()
        config_pkg.initialize()
        assert warnings == [REMOVED_CHAT_PROVIDERS["perplexity"]]
        monkeypatch.undo()
        config_pkg._refresh_module_dicts()


class TestSetProviderRefuses:

    @pytest.fixture
    def engine(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "test-not-a-key")
        monkeypatch.setenv("GEMINI_API_KEY", "test-not-a-key")
        return EngineClient()

    def test_returns_false_and_leaves_the_provider_alone(self, engine):
        assert engine.set_provider("gemini") is True
        before = engine.provider
        assert engine.set_provider("perplexity") is False
        assert engine.provider is before and engine.provider_name == "gemini"

    def test_never_builds_the_generic_fallback_even_with_a_block(self, engine, monkeypatch):
        """The trap ADR 0015 closes: a leftover block used to reach the
        OpenAI-compatible fallback when no class was registered."""
        monkeypatch.setitem(engine.providers_config, "perplexity", LEFTOVER["providers"]["perplexity"])
        assert engine.set_provider("perplexity") is False
        assert engine.provider_name != "perplexity"

    def test_logs_the_fix(self, engine, monkeypatch):
        seen: list[str] = []
        monkeypatch.setattr("ppxai.engine.provider_ops.logger.warning", seen.append)
        engine.set_provider("perplexity")
        assert seen == [REMOVED_CHAT_PROVIDERS["perplexity"]]


class TestARestoredPerplexitySession:

    def _engine(self, stored_provider):
        calls: dict = {"set_model": []}
        session = SimpleNamespace(
            load=lambda name: True,
            metadata={"provider": stored_provider, "model": "perplexity/sonar"},
            tools_enabled=False, working_dir=None, messages=[1, 2, 3],
        )
        engine = SimpleNamespace(
            reload_config=lambda: None, session=session,
            state=SimpleNamespace(update=lambda **kw: None),
            set_provider=lambda name: False, provider="current", provider_name="gemini",
            model="g", set_model=lambda *a, **k: calls["set_model"].append(a) or True,
            enable_tools=lambda: None, disable_tools=lambda: None, tools_enabled=False,
            get_working_dir=lambda: "/w", set_working_dir=lambda wd: None,
            _pending_provider_notice=None,
        )
        return engine, calls

    def test_keeps_history_and_says_so_once(self):
        engine, calls = self._engine("perplexity")
        result = session_ops.restore_session(engine, "s")
        assert result["success"] and result["message_count"] == 3
        assert result["provider"] == "gemini"
        assert "continuing on gemini" in result["notice"]
        assert engine._pending_provider_notice == result["notice"]
        # The recorded Perplexity model is not forced onto the current provider.
        assert calls["set_model"] == []

    def test_an_ordinary_session_carries_no_notice(self):
        engine, _ = self._engine("gemini")
        result = session_ops.restore_session(engine, "s")
        assert "notice" not in result and engine._pending_provider_notice is None

    def test_the_next_chat_turn_leads_with_the_notice(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-not-a-key")
        engine = EngineClient()
        engine.set_provider("gemini")
        engine._pending_provider_notice = "recorded on perplexity"

        async def first_event():
            agen = engine.chat("hi")
            try:
                return await agen.__anext__()
            finally:
                await agen.aclose()

        event = asyncio.run(first_event())
        assert event.type == EventType.INFO and event.data == "recorded on perplexity"
        assert event.metadata == {"notice": "provider_removed", "provider": "gemini"}
        assert engine._pending_provider_notice is None


class TestTheSearchModelIsOnTheSurvivingWire:
    """The shipped config's `tools.web_search.perplexity_model` was bare
    `sonar` (chat-completions only, retired 2026-09-27) until v1.19.3, so
    every Perplexity search from a shipped config failed. /doctor flags it."""

    def test_doctor_flags_a_bare_sonar_id(self, monkeypatch):
        monkeypatch.setattr(config_pkg, "get_tool_config", lambda name: {"perplexity_model": "sonar"})
        text = "\n".join(_format_web_search_backend_section())
        assert "retired chat-completions wire" in text and "perplexity/sonar" in text

    def test_doctor_is_quiet_for_the_responses_id(self, monkeypatch):
        monkeypatch.setattr(config_pkg, "get_tool_config", lambda name: {"perplexity_model": "perplexity/sonar"})
        text = "\n".join(_format_web_search_backend_section())
        assert "retired chat-completions wire" not in text


class TestTheSurfacesNameTheFix:

    def test_the_task_tier(self):
        with pytest.raises(TaskAuthorizationError) as exc:
            validate_provider_or_error("perplexity")
        assert exc.value.status == 400 and "ADR 0015" in exc.value.detail

    def test_v1_oneshot(self):
        with TestClient(http_module.app, raise_server_exceptions=False) as client:
            r = client.post("/v1/oneshot", json={"prompt": "hi", "provider": "perplexity"})
        assert r.status_code == 400
        assert "ADR 0015" in r.json()["detail"]

    def test_the_provider_command(self):
        context = SimpleNamespace(engine_client=None, get_provider=lambda: "gemini")
        result = handle_provider(context, "perplexity")
        assert "no longer a chat provider" in result.message
        assert "providers.perplexity" in result.error_details


class TestDoctor:

    def test_default_and_block_are_both_reported(self, monkeypatch):
        monkeypatch.delenv("MODEL_PROVIDER", raising=False)
        [finding] = removed_chat_providers(LEFTOVER)
        assert finding["selected_by"] == "default_provider" and finding["has_block"]
        assert finding["models"] == {
            "perplexity/sonar": "no chat replacement; Perplexity stays the web_search and grounding backend",
            "openai/gpt-5.6-terra": "openai",
            "anthropic/claude-sonnet-5": "anthropic (opt-in [anthropic] extra; untested against the live API)",
        }

    def test_model_provider_is_reported_without_a_block(self, monkeypatch):
        monkeypatch.setenv("MODEL_PROVIDER", "perplexity")
        [finding] = removed_chat_providers({"providers": {}})
        assert finding["selected_by"] == "MODEL_PROVIDER" and not finding["has_block"]

    def test_a_clean_config_reports_nothing(self, monkeypatch):
        monkeypatch.delenv("MODEL_PROVIDER", raising=False)
        assert removed_chat_providers({"default_provider": "gemini", "providers": {"gemini": {}}}) == []
        assert _format_removed_provider_section({"providers": {}})[-1] == "   ✓ none configured"

    def test_the_section_names_the_replacements(self, monkeypatch):
        monkeypatch.delenv("MODEL_PROVIDER", raising=False)
        text = "\n".join(_format_removed_provider_section(LEFTOVER))
        assert "default_provider is 'perplexity'" in text
        assert "providers.perplexity block is present (ignored)" in text
        assert "openai/gpt-5.6-terra  ->  openai" in text

    def test_the_block_is_not_audited_model_by_model(self):
        assert "perplexity" not in _extract_provider_models(LEFTOVER)


class TestShippedConfigs:
    """No shipped or generated config offers Perplexity for chat; the
    search backend's settings stay."""

    @pytest.mark.parametrize("name", ["ppxai-config.json", "ppxai-config.example.json"])
    def test_shipped_configs(self, name):
        data = json.loads((REPO / name).read_text(encoding="utf-8"))
        assert data["default_provider"] == "gemini"
        assert "perplexity" not in data["providers"]
        assert data["tools"]["web_search"]["perplexity_model"] == "perplexity/sonar"

    @pytest.mark.parametrize("name", ["install.sh", "scripts/install.ps1"])
    def test_installers(self, name):
        text = (REPO / name).read_text(encoding="utf-8")
        assert re.findall(r'"default_provider":\s*"(\w+)"', text) == ["gemini"]
        assert '"perplexity": {' not in text

    def test_vscode_built_in_config(self):
        text = (REPO / "vscode-extension/src/config.ts").read_text(encoding="utf-8")
        assert re.findall(r'default_provider:\s*"(\w+)"', text) == ["gemini"]
        assert '"perplexity": {' not in text

    def test_vscode_setting_default(self):
        pkg = json.loads((REPO / "vscode-extension/package.json").read_text(encoding="utf-8"))
        props = pkg["contributes"]["configuration"]["properties"]
        assert props["ppxai.defaultProvider"]["default"] == "gemini"


class TestTheServerStartsOnTheConfiguredDefault:
    """`SessionManager` used `get_available_providers()[0]`, so the server
    started on whichever provider block came first in the file. Found by the
    2026-09-27 live check; kept from the phase-1 tests."""

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
        self._patch(monkeypatch, "gemini", ["openai", "gemini", "nvidia"])
        engine = self._Engine({"openai", "gemini", "nvidia"})
        session_manager_mod._select_default_provider(engine)
        assert engine.tried == ["gemini"]

    def test_a_default_without_a_key_falls_back_in_file_order(self, monkeypatch):
        self._patch(monkeypatch, "gemini", ["openai", "gemini", "nvidia"])
        engine = self._Engine({"nvidia"})
        session_manager_mod._select_default_provider(engine)
        assert engine.tried == ["gemini", "openai", "nvidia"]


def test_web_search_does_not_depend_on_a_chat_provider():
    assert search_backend.PerplexityBackend
    source = (REPO / "ppxai/engine/search/perplexity.py").read_text(encoding="utf-8")
    assert "providers.perplexity" not in source
