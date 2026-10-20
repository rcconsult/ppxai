"""A provider switch that loads a provider module tells the user (ADR 0016 §5).

Since step 3 a provider's module (and SDK) is imported the first time the
provider is used. A switch to one not loaded yet queues
`STATUS "Loading the <name> provider…"` (metadata `kind: provider_loading`)
and, after the import, `STATUS "Loaded …"` (`kind: provider_loaded`, with
`seconds`). A failed import queues an ERROR naming the missing module and
the switch returns False. The first provider of a session loads silently:
the owner chose to prewarm the default, not announce it.

Every client shows them: web and VSCode from the `events` of `/command/*`
and `POST /providers`, the two TUIs from the engine queue at their
`set_provider`.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from rich.console import Console

from ppxai.commands import handler as rich_handler
from ppxai.commands.handler import CommandHandler
from ppxai.engine import provider_ops
from ppxai.engine import providers as registry
from ppxai.engine.app_state import AppState
from ppxai.engine.types import Event, EventType
from ppxai.server.routes.providers import router as providers_router
from ppxai.server.state import Session, get_session
from ppxai.tui.app import PPXAIDEApp

REPO = Path(__file__).resolve().parents[1]


class _Engine:
    """The two attributes `_load_provider_module` touches."""

    def __init__(self, provider=None):
        self.provider = provider
        self.events: list[Event] = []

    def enqueue_event(self, event: Event) -> None:
        self.events.append(event)


@pytest.fixture
def not_loaded(monkeypatch):
    """Every provider reads as not loaded yet; loading it succeeds."""
    loads = []
    monkeypatch.setattr(registry, "is_loaded", lambda name: False)
    monkeypatch.setattr(registry, "load_provider_class", lambda name: loads.append(name))
    monkeypatch.setattr(provider_ops, "ANNOUNCE_LOAD_AFTER_S", 0.0)
    return loads


class TestTheEngineQueuesTheLoad:
    def test_a_switch_announces_loading_and_loaded(self, not_loaded):
        engine = _Engine(provider=object())

        assert provider_ops._load_provider_module(engine, "gemini") is True

        assert not_loaded == ["gemini"]
        loading, loaded = engine.events
        assert loading.type is EventType.STATUS
        assert loading.data == "Loading the gemini provider…"
        assert loading.metadata == {"kind": "provider_loading", "provider": "gemini"}
        assert loaded.type is EventType.STATUS
        assert loaded.data.startswith("Loaded the gemini provider (")
        assert loaded.metadata["kind"] == "provider_loaded"
        assert loaded.metadata["provider"] == "gemini"
        assert isinstance(loaded.metadata["seconds"], float)

    def test_a_quick_load_is_not_announced(self, not_loaded, monkeypatch):
        """Its SDK was already in memory; "Loaded (0.0 s)" would be noise."""
        monkeypatch.setattr(provider_ops, "ANNOUNCE_LOAD_AFTER_S", 60.0)
        engine = _Engine(provider=object())

        assert provider_ops._load_provider_module(engine, "openrouter") is True

        assert not_loaded == ["openrouter"]
        assert engine.events == []

    def test_the_first_provider_loads_silently(self, not_loaded):
        engine = _Engine(provider=None)

        assert provider_ops._load_provider_module(engine, "gemini") is True

        assert not_loaded == ["gemini"]
        assert engine.events == []

    def test_an_already_loaded_provider_says_nothing(self, monkeypatch):
        monkeypatch.setattr(registry, "is_loaded", lambda name: True)
        monkeypatch.setattr(registry, "load_provider_class",
                            lambda name: pytest.fail("must not import again"))
        engine = _Engine(provider=object())

        assert provider_ops._load_provider_module(engine, "openai") is True
        assert engine.events == []

    @pytest.mark.parametrize("first", [True, False])
    def test_a_failed_import_is_an_error_naming_the_module(self, monkeypatch, first):
        def boom(name):
            raise ModuleNotFoundError("No module named 'ppxai.engine.providers.gemini'",
                                      name="ppxai.engine.providers.gemini")
        monkeypatch.setattr(registry, "is_loaded", lambda name: False)
        monkeypatch.setattr(registry, "load_provider_class", boom)
        engine = _Engine(provider=None if first else object())

        assert provider_ops._load_provider_module(engine, "gemini") is False

        error = engine.events[-1]
        assert error.type is EventType.ERROR
        assert "ppxai.engine.providers.gemini" in error.data
        assert "uv sync --extra gemini" in error.data  # install_extra_hint
        assert error.metadata == {"kind": "provider_load_failed", "provider": "gemini",
                                  "module": "ppxai.engine.providers.gemini"}

    def test_a_provider_without_an_extra_gets_no_install_hint(self, monkeypatch):
        def boom(name):
            raise ModuleNotFoundError("x", name="ppxai.engine.providers.openai_compat")
        monkeypatch.setattr(registry, "is_loaded", lambda name: False)
        monkeypatch.setattr(registry, "load_provider_class", boom)
        engine = _Engine(provider=object())

        assert provider_ops._load_provider_module(engine, "openrouter") is False
        assert "extra" not in engine.events[-1].data

    def test_set_provider_stops_on_a_failed_load(self, monkeypatch):
        """Nothing is switched: the old provider stays."""
        monkeypatch.setattr(provider_ops, "_load_provider_module", lambda engine, name: False)
        old = object()
        engine = SimpleNamespace(
            state=AppState(initial={"provider": "openai"}),
            providers_config={"gemini": {}},
            _get_api_key=lambda name: "k",
            provider=old,
        )

        assert provider_ops.set_provider(engine, "gemini") is False
        assert engine.provider is old


class TestIsLoaded:
    def test_a_registered_provider_reads_its_module(self, monkeypatch):
        """No real module is re-imported: that would mint a second class object."""
        monkeypatch.setattr(registry, "_PROVIDER_MODULES", {"x": ("ppxai_test_never_imported", "C")})
        monkeypatch.setattr(registry, "_loaded", {})
        assert registry.is_loaded("x") is False
        monkeypatch.setitem(sys.modules, "ppxai_test_never_imported", SimpleNamespace(C=object))
        assert registry.is_loaded("x") is True

    def test_an_unregistered_name_reads_the_fallback_module(self):
        registry.fallback_provider_class()
        assert registry.is_loaded("openrouter") is True


class TestPostProviders:
    @pytest.fixture
    def session(self):
        engine = MagicMock()
        engine.state = AppState(initial={"provider": "openai", "model": "gpt-4"})
        engine.last_model_switch_reset = 0
        return Session(id="test", engine=engine, lock=asyncio.Lock())

    @pytest.fixture
    def client(self, session):
        app = FastAPI()
        app.include_router(providers_router)
        app.dependency_overrides[get_session] = lambda: session
        return TestClient(app)

    def test_the_notices_ride_on_the_response(self, client, session):
        session.engine.set_provider.return_value = True
        session.engine.drain_events.return_value = [
            Event(EventType.STATUS, "Loading the gemini provider…",
                  {"kind": "provider_loading", "provider": "gemini"}),
        ]

        resp = client.post("/providers", json={"provider": "gemini"})

        assert resp.status_code == 200
        assert resp.json()["events"] == [{
            "type": "status", "data": "Loading the gemini provider…",
            "metadata": {"kind": "provider_loading", "provider": "gemini"},
        }]

    def test_a_failed_load_is_the_400_detail(self, client, session):
        session.engine.set_provider.return_value = False
        session.engine.drain_events.return_value = [
            Event(EventType.STATUS, "Loading the gemini provider…"),
            Event(EventType.ERROR, "Could not load the gemini provider: module x is missing."),
        ]

        resp = client.post("/providers", json={"provider": "gemini"})

        assert resp.status_code == 400
        assert resp.json()["detail"] == "Could not load the gemini provider: module x is missing."

    def test_any_other_failure_keeps_the_old_detail(self, client, session):
        session.engine.set_provider.return_value = False
        session.engine.drain_events.return_value = []

        resp = client.post("/providers", json={"provider": "nope"})

        assert resp.status_code == 400
        assert resp.json()["detail"] == "Failed to set provider: nope"


def _queued(*events):
    engine = MagicMock()
    engine.drain_events.return_value = list(events)
    return engine


NOTICES = (
    Event(EventType.STATUS, "Loading the gemini provider…"),
    Event(EventType.STATE_SYNC, {"provider": "gemini"}),
    Event(EventType.ERROR, "Could not load [x]"),
)


class TestTheTuisShowThem:
    def test_rich(self, monkeypatch):
        console = Console(record=True, width=200)
        monkeypatch.setattr(rich_handler, "console", console)
        fake = SimpleNamespace(engine_client=_queued(*NOTICES))

        CommandHandler.set_provider(fake, "gemini")

        fake.engine_client.set_provider.assert_called_once_with("gemini")
        out = console.export_text()
        assert "Loading the gemini provider…" in out
        assert "Could not load [x]" in out  # printed as text, not markup
        assert "provider" not in out.replace("Loading the gemini provider…", "")

    def test_textual(self):
        chat_view = MagicMock()
        fake = SimpleNamespace(_engine_client=_queued(*NOTICES), _chat_view=chat_view,
                               notify=MagicMock())

        PPXAIDEApp.set_provider(fake, "gemini")

        shown = [c.args[0] for c in chat_view.add_system_message.call_args_list]
        assert shown == ["Loading the gemini provider…", "[red]Could not load \\[x][/red]"]


class TestTheJsClientsShowThem:
    """Static checks, as the other state-sync piggyback tests are."""

    def test_web_provider_dropdown_drains_the_response_events(self):
        src = (REPO / "ppxai/web/app.js").read_text(encoding="utf-8")
        body = src[src.index("async handleProviderChange()"):]
        body = body[:body.index("\n    }\n")]
        assert re.search(r"this\.commandDispatcher\._drainEvents\(data\.events\)", body)

    def test_web_renders_status_and_error_from_events(self):
        src = (REPO / "ppxai/web/app.js").read_text(encoding="utf-8")
        assert "case 'status':" in src and "case 'error':" in src

    def test_vscode_envelope_drain_handles_status_and_error(self):
        src = (REPO / "vscode-extension/src/chatPanel.ts").read_text(encoding="utf-8")
        body = src[src.index("public _drainEnvelopeEvents("):]
        body = body[:body.index("\n    }\n")]
        assert "ev.type === 'status' || ev.type === 'error'" in body
        assert "'stream:status'" in body and "'stream:error'" in body

    def test_vscode_provider_picker_passes_the_events(self):
        http = (REPO / "vscode-extension/src/httpClient.ts").read_text(encoding="utf-8")
        assert "events: data.events ?? []" in http
        ext = (REPO / "vscode-extension/src/extension.ts").read_text(encoding="utf-8")
        assert "chatViewProvider._drainEnvelopeEvents(success.events)" in ext
