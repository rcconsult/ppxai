"""A model or provider switch is REFUSED while a response is streaming.

v1.19.2. Measured 2026-09-13 on gemini-3.8-flash in the web UI: the user
switched models while a tool loop was running. `reset_for_model_switch`
stripped the in-flight assistant turn; 1.2 s later the loop appended its
tool result to a history whose matching assistant turn was gone, and Gemini
answered 400 on its turn-ordering rule. `sanitize_outbound` did not help:
it covers orphan `tool_calls` and empty assistants, not turn ordering.

Owner decision: do not race it. The switch is refused before anything is
mutated, and the user is told to wait for the run to finish or stop it.
Three layers are pinned here because each one turns the refusal into a
different user-facing shape:

    engine   provider_ops.set_model / set_provider  -> ModelSwitchInFlightError
    command  /model, /provider                      -> ErrorResult
    REST     POST /models, POST /providers          -> HTTP 409

`reset_context=False` switches are deliberately NOT refused: session
restore, the `/chat` request's own `model` field, the coding-mode toggle
and the provider-default assignment all take that form and some of them
run inside a stream on purpose.
"""

import asyncio
import os
from unittest.mock import MagicMock, Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ppxai.commands.provider import handle_model, handle_provider
from ppxai.commands.results import ErrorResult, ResultStatus
from ppxai.engine import provider_ops
from ppxai.engine.app_state import AppState
from ppxai.engine.client import EngineClient
from ppxai.engine.provider_ops import RUN_IN_FLIGHT_MESSAGE, ModelSwitchInFlightError
from ppxai.server.routes.providers import router as providers_router
from ppxai.server.state import Session, get_session

MODEL_REFUSAL = RUN_IN_FLIGHT_MESSAGE.format(what="the model")
PROVIDER_REFUSAL = RUN_IN_FLIGHT_MESSAGE.format(what="the provider")


def _engine(streaming: bool) -> MagicMock:
    """A MagicMock engine with a REAL AppState, as provider_ops sees it."""
    engine = MagicMock()
    engine.state = AppState()
    engine.state.set("is_streaming", streaming)
    engine.provider.list_models.return_value = []
    engine.session.messages = []
    engine.providers_config = {}
    return engine


# ---------------------------------------------------------------------------
# Engine layer
# ---------------------------------------------------------------------------

class TestEngineRefusesTheSwitchMidRun:

    def test_set_model_is_refused_while_streaming(self):
        engine = _engine(streaming=True)

        with pytest.raises(ModelSwitchInFlightError) as exc_info:
            provider_ops.set_model(engine, "other-model")

        assert str(exc_info.value) == MODEL_REFUSAL

    def test_a_refused_set_model_mutates_nothing(self):
        """The refusal fires BEFORE the strip -- that strip was the bug."""
        engine = _engine(streaming=True)
        model_before = engine.state.get("model")

        with pytest.raises(ModelSwitchInFlightError):
            provider_ops.set_model(engine, "other-model")

        engine.session.reset_for_model_switch.assert_not_called()
        engine.session.set_model.assert_not_called()
        assert engine.state.get("model") == model_before

    def test_set_model_without_context_reset_still_works_mid_run(self):
        """The internal, non-stripping form must keep working inside a run."""
        engine = _engine(streaming=True)

        assert provider_ops.set_model(engine, "other-model", reset_context=False) is True

        engine.session.set_model.assert_called_once_with("other-model")
        assert engine.state.get("model") == "other-model"

    def test_set_model_works_when_idle(self):
        engine = _engine(streaming=False)

        assert provider_ops.set_model(engine, "other-model") is True
        assert engine.state.get("model") == "other-model"

    def test_set_provider_is_refused_before_any_mutation(self):
        engine = _engine(streaming=True)
        engine.providers_config = {"gemini": {"name": "Gemini"}}
        provider_before = engine.state.get("provider")

        with pytest.raises(ModelSwitchInFlightError) as exc_info:
            provider_ops.set_provider(engine, "gemini")

        assert str(exc_info.value) == PROVIDER_REFUSAL
        engine.session.set_provider.assert_not_called()
        assert engine.state.get("provider") == provider_before

    def test_a_mocked_state_is_not_read_as_in_flight(self):
        """The guard checks `is True`: a MagicMock state (truthy) must not refuse."""
        engine = _engine(streaming=False)
        engine.state = MagicMock()

        assert provider_ops.set_model(engine, "other-model") is True

    def test_the_message_tells_the_user_what_to_do(self):
        assert "Wait for it to finish" in MODEL_REFUSAL
        assert "stop it" in MODEL_REFUSAL


class TestTheRealFacade:
    """EngineClient.set_model / set_provider are one-line delegates; pin that
    the refusal reaches a caller of the real facade and lifts once the
    stream ends (the flag is cleared in chat()'s finally)."""

    @pytest.fixture
    def engine(self):
        with patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"}):
            engine = EngineClient()
            engine.set_provider("perplexity")
            engine.set_model("sonar")
        return engine

    def test_the_facade_refuses_mid_run_and_recovers_after(self, engine):
        engine.state.update(is_streaming=True)

        with pytest.raises(ModelSwitchInFlightError):
            engine.set_model("sonar-pro")
        assert engine.model == "sonar"

        engine.state.update(is_streaming=False)
        assert engine.set_model("sonar-pro") is True
        assert engine.model == "sonar-pro"

    def test_the_facade_refuses_a_provider_switch_mid_run(self, engine):
        engine.state.update(is_streaming=True)

        with pytest.raises(ModelSwitchInFlightError):
            engine.set_provider("perplexity")
        assert engine.provider_name == "perplexity"
        assert engine.model == "sonar"


# ---------------------------------------------------------------------------
# Command layer
# ---------------------------------------------------------------------------

class TestCommandsReportTheRefusal:

    @pytest.fixture
    def ctx(self):
        ctx = Mock()
        ctx.get_provider.return_value = "perplexity"
        ctx.get_model.return_value = "sonar"
        ctx.engine_client = Mock()
        ctx.engine_client.last_model_switch_reset = 0
        ctx.engine_client.reload_config = Mock()
        ctx.set_provider = Mock()
        ctx.set_model = Mock()
        return ctx

    @patch("ppxai.commands.provider.get_provider_config", return_value={
        "models": {"1": {"id": "sonar-pro", "description": "x"}},
    })
    def test_model_switch_returns_an_error_result(self, _cfg, ctx):
        ctx.set_model.side_effect = ModelSwitchInFlightError(MODEL_REFUSAL)

        result = handle_model(ctx, "sonar-pro")

        assert isinstance(result, ErrorResult)
        assert result.status == ResultStatus.ERROR
        assert result.message == MODEL_REFUSAL
        assert any("stop" in s.lower() for s in result.suggestions)

    @patch("ppxai.commands.provider.PROVIDERS", {
        "perplexity": {"name": "Perplexity", "api_key_env": "PERPLEXITY_API_KEY",
                       "default_model": "sonar-pro"},
        "gemini": {"name": "Google Gemini", "api_key_env": "GEMINI_API_KEY",
                   "default_model": "gemini-3.8-flash"},
    })
    @patch("ppxai.commands.provider.get_api_key", return_value="test-key")
    @patch("ppxai.commands.provider.get_base_url", return_value="https://api.example.com")
    @patch("ppxai.commands.provider.get_provider_config", return_value={
        "name": "Google Gemini", "api_key_env": "GEMINI_API_KEY",
        "default_model": "gemini-3.8-flash",
    })
    def test_provider_switch_returns_an_error_result_and_never_sets_the_model(
        self, _cfg, _base, _key, ctx
    ):
        ctx.set_provider.side_effect = ModelSwitchInFlightError(PROVIDER_REFUSAL)

        result = handle_provider(ctx, "gemini")

        assert isinstance(result, ErrorResult)
        assert result.message == PROVIDER_REFUSAL
        # A refused provider switch must not go on to switch the model either.
        ctx.set_model.assert_not_called()


# ---------------------------------------------------------------------------
# REST layer
# ---------------------------------------------------------------------------

class TestRoutesAnswer409:

    @pytest.fixture
    def session(self):
        engine = MagicMock()
        engine.state = AppState(initial={"provider": "openai", "model": "gpt-4"})
        engine.last_model_switch_reset = 0
        engine.drain_events.return_value = []
        return Session(id="test", engine=engine, lock=asyncio.Lock())

    @pytest.fixture
    def client(self, session):
        app = FastAPI()
        app.include_router(providers_router)
        app.dependency_overrides[get_session] = lambda: session
        return TestClient(app)

    def test_post_models_is_409_with_the_reason(self, client, session):
        session.engine.set_model.side_effect = ModelSwitchInFlightError(MODEL_REFUSAL)

        resp = client.post("/models", json={"model": "other-model"})

        assert resp.status_code == 409
        assert resp.json()["detail"] == MODEL_REFUSAL

    def test_post_providers_is_409_with_the_reason(self, client, session):
        session.engine.set_provider.side_effect = ModelSwitchInFlightError(PROVIDER_REFUSAL)

        resp = client.post("/providers", json={"provider": "gemini"})

        assert resp.status_code == 409
        assert resp.json()["detail"] == PROVIDER_REFUSAL
        session.engine.set_model.assert_not_called()

    def test_post_models_still_succeeds_when_idle(self, client, session):
        """The 409 mapping must not swallow the normal path."""
        session.engine.set_model.return_value = True

        resp = client.post("/models", json={"model": "gpt-4"})

        assert resp.status_code == 200
        assert resp.json()["model"] == "gpt-4"
