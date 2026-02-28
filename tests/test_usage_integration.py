"""Integration tests for /usage command across all client paths.

Tests that the /usage command produces correct results when called through:
1. CommandFactory directly (shared handler — TUI path)
2. ServerCommandContext (server path — used by web app and VSCode)
3. FastAPI POST /command/usage endpoint (HTTP path)

All tests call a real AI provider endpoint to generate actual usage data,
then verify the usage counters are non-zero, correctly structured, and
that the formatted table rows match the raw session data.

Run with: pytest tests/test_usage_integration.py -v -s
NOTE: Requires ~/.ppxai/.env with valid API keys and ~/.ppxai/ppxai-config.json.
      These tests modify global config state and should be run in isolation.
"""

import asyncio
import os
import pytest
from unittest.mock import MagicMock, AsyncMock
from dotenv import load_dotenv

# Skip tests if server dependencies not installed
pytest.importorskip("fastapi")
pytest.importorskip("httpx")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def load_env():
    """Ensure env vars are loaded for this module.

    conftest.py already loads ~/.ppxai/.env in pytest_configure and calls
    initialize(). This fixture adds the project .env as fallback.
    """
    # Load user's .ppxai/.env for API keys and SSL settings
    user_env_path = os.path.expanduser("~/.ppxai/.env")
    if os.path.exists(user_env_path):
        load_dotenv(dotenv_path=user_env_path, override=True)

    # Also load project .env as fallback
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        load_dotenv(dotenv_path=env_path, override=True)

    from ppxai.config import initialize
    initialize()

    yield


def _create_engine(provider_id: str):
    """Create a real EngineClient for the given provider.

    Returns (engine, model_id) or calls pytest.skip if provider unavailable.
    conftest.py already loads ~/.ppxai/.env and calls initialize() before collection.
    """
    from ppxai.config import PROVIDERS, initialize
    from ppxai.engine import EngineClient

    # Ensure config is initialized (conftest does this but be safe)
    initialize()

    if provider_id not in PROVIDERS:
        pytest.skip(f"Provider '{provider_id}' not configured")

    provider_cfg = PROVIDERS[provider_id]
    api_key_env = provider_cfg.get("api_key_env", f"{provider_id.upper()}_API_KEY")
    api_key = os.getenv(api_key_env, "")
    if not api_key:
        pytest.skip(f"{api_key_env} not set")

    engine = EngineClient()
    engine.set_provider(provider_id)

    # Pick default model for the provider
    models = provider_cfg.get("models", {})
    default_model = provider_cfg.get("default_model")
    if not default_model and models:
        default_model = next(iter(models))
    if default_model:
        engine.set_model(default_model)

    return engine, default_model or "unknown"


@pytest.fixture
def perplexity_engine():
    """Create a real EngineClient connected to Perplexity."""
    engine, model = _create_engine("perplexity")
    yield engine, model


@pytest.fixture
def gemini_engine():
    """Create a real EngineClient connected to Gemini."""
    engine, model = _create_engine("gemini")
    yield engine, model


@pytest.fixture
def openai_engine():
    """Create a real EngineClient connected to OpenAI."""
    engine, model = _create_engine("openai")
    yield engine, model


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chat_and_get_usage(engine):
    """Send one chat message and return usage from the session."""
    response = engine.chat_sync("Say 'pong' and nothing else.")
    assert response is not None
    assert len(response) > 0
    return engine.session.get_usage()


def _parse_comma_int(s: str) -> int:
    """Parse a comma-formatted integer string like '1,234' → 1234."""
    return int(s.replace(",", ""))


def _parse_cost(s: str) -> float:
    """Parse a cost string like '$0.0013' → 0.0013."""
    return float(s.lstrip("$"))


def _get_usage_result(engine, args: str = "") -> dict:
    """Run /usage through CommandFactory and return to_dict() result."""
    from ppxai.commands.factory import CommandFactory
    from ppxai.commands.context import ServerCommandContext

    context = ServerCommandContext(engine)
    return CommandFactory.get("usage").handler(context, args).to_dict()


def _get_usage_result_via_http(engine, args: str = "") -> dict:
    """Run /usage through POST /command/usage and return JSON result."""
    from fastapi.testclient import TestClient
    import ppxai.server.http as http_module

    manager = _create_test_client_with_engine(engine)

    with TestClient(http_module.app, raise_server_exceptions=False) as client:
        original = http_module.session_manager
        http_module.session_manager = manager

        resp = client.post("/command/usage", json={"args": args})
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        result = resp.json()

        http_module.session_manager = original

    return result


def _assert_table_matches_raw_usage(result_dict: dict, raw_usage: dict, provider_id: str, model_id: str):
    """Assert table rows accurately reflect raw session.get_usage() data.

    Verifies:
    - Table type and columns
    - Provider/model row matches what was used for chat
    - Token counts in table match raw session data
    - Cost in table matches raw session data
    - TOTAL row arithmetic (prompt + completion = total)
    """
    assert result_dict["type"] == "TableResult"
    assert result_dict["status"] == "success"
    assert result_dict["columns"] == ["Provider", "Model", "In", "Out", "Cost"]

    rows = result_dict["rows"]
    assert len(rows) >= 2, f"Expected at least model row + TOTAL row, got {rows}"

    # Last row is TOTAL
    total_row = rows[-1]
    assert total_row[0] == "TOTAL"
    assert total_row[1] == ""

    # Parse TOTAL row values
    total_in = _parse_comma_int(total_row[2])
    total_out = _parse_comma_int(total_row[3])
    total_cost = _parse_cost(total_row[4])

    # TOTAL must match raw session counters
    assert total_in == raw_usage["prompt_tokens"], \
        f"TOTAL In={total_in} != raw prompt_tokens={raw_usage['prompt_tokens']}"
    assert total_out == raw_usage["completion_tokens"], \
        f"TOTAL Out={total_out} != raw completion_tokens={raw_usage['completion_tokens']}"
    assert abs(total_cost - raw_usage["estimated_cost"]) < 0.0001, \
        f"TOTAL Cost={total_cost} != raw estimated_cost={raw_usage['estimated_cost']}"

    # Arithmetic check: prompt + completion = total
    assert total_in + total_out == raw_usage["total_tokens"], \
        f"In({total_in}) + Out({total_out}) != total_tokens({raw_usage['total_tokens']})"

    # Find the model row matching our provider
    model_rows = [r for r in rows[:-1] if r[0] == provider_id]
    assert len(model_rows) >= 1, \
        f"No row for provider '{provider_id}' in {rows}"

    # The model row should reference the model we used
    model_row = model_rows[0]
    # model_id may have provider prefix (e.g. "openai/gpt-5-mini" → model part is "gpt-5-mini")
    # The table splits on "/" so model_row[1] is the model part
    expected_model = model_id.split("/", 1)[-1] if "/" in model_id else model_id
    assert model_row[1] == expected_model, \
        f"Model row shows '{model_row[1]}', expected '{expected_model}'"

    # Model row token counts should be > 0
    model_in = _parse_comma_int(model_row[2])
    model_out = _parse_comma_int(model_row[3])
    assert model_in > 0, f"Model In tokens should be > 0, got {model_in}"
    assert model_out > 0, f"Model Out tokens should be > 0, got {model_out}"

    # Per-model row must match the by_model data
    by_model = raw_usage.get("by_model", {})
    model_key = f"{provider_id}/{expected_model}"
    if model_key in by_model:
        bm = by_model[model_key]
        assert model_in == bm["prompt_tokens"], \
            f"Model In={model_in} != by_model prompt_tokens={bm['prompt_tokens']}"
        assert model_out == bm["completion_tokens"], \
            f"Model Out={model_out} != by_model completion_tokens={bm['completion_tokens']}"

    # Message should contain the total cost and token count
    message = result_dict["message"]
    assert f"${raw_usage['estimated_cost']:.4f}" in message or f"${total_cost:.4f}" in message, \
        f"Message should contain cost, got: {message}"
    assert f"{raw_usage['total_tokens']:,}" in message, \
        f"Message should contain total tokens, got: {message}"


def _create_test_client_with_engine(engine):
    """Create a mock SessionManager wired to a real EngineClient.

    Uses MagicMock(spec=SessionManager) so properties work correctly.
    """
    from ppxai.server.session_manager import SessionManager

    manager = MagicMock(spec=SessionManager)
    manager.is_initialized = True
    manager._default_engine = engine
    manager.default_engine = engine
    manager.session_count = 0
    manager.last_activity = 0.0
    manager.shutdown_requested = False

    mock_lock = asyncio.Lock()
    manager.get_or_create_session = AsyncMock(
        return_value=("test-session", engine, mock_lock)
    )

    return manager


# ---------------------------------------------------------------------------
# Test 1: CommandFactory direct — counter values match raw session data
# ---------------------------------------------------------------------------

class TestUsageCountersViaFactory:
    """Test /usage through CommandFactory — verify counter VALUES, not just types."""

    def test_counters_match_raw_session_data(self, perplexity_engine):
        """Chat with Perplexity → verify table rows match session.get_usage()."""
        engine, model_id = perplexity_engine

        # Reset to start clean
        engine.session.reset_usage()

        raw_usage = _chat_and_get_usage(engine)
        result_dict = _get_usage_result(engine)

        _assert_table_matches_raw_usage(result_dict, raw_usage, "perplexity", model_id)

        print(f"\n[Factory/Perplexity] Raw: in={raw_usage['prompt_tokens']} "
              f"out={raw_usage['completion_tokens']} cost=${raw_usage['estimated_cost']:.4f}")
        print(f"  Table TOTAL row: {result_dict['rows'][-1]}")

    def test_counters_accumulate_over_multiple_chats(self, perplexity_engine):
        """Two chats accumulate tokens — total is sum of both."""
        engine, model_id = perplexity_engine

        # Reset to start clean
        engine.session.reset_usage()

        # First chat
        _chat_and_get_usage(engine)
        usage_after_1 = engine.session.get_usage()
        tokens_1 = usage_after_1["total_tokens"]
        assert tokens_1 > 0

        # Second chat
        _chat_and_get_usage(engine)
        usage_after_2 = engine.session.get_usage()
        tokens_2 = usage_after_2["total_tokens"]
        assert tokens_2 > tokens_1, \
            f"After 2 chats, total_tokens={tokens_2} should be > after 1 chat={tokens_1}"

        # Table should show accumulated totals
        result_dict = _get_usage_result(engine)
        total_row = result_dict["rows"][-1]
        table_total_in = _parse_comma_int(total_row[2])
        table_total_out = _parse_comma_int(total_row[3])
        assert table_total_in == usage_after_2["prompt_tokens"]
        assert table_total_out == usage_after_2["completion_tokens"]

        print(f"\n[Factory] Accumulated: 1st={tokens_1} tokens, 2nd={tokens_2} tokens")

    def test_reset_zeroes_all_counters(self, perplexity_engine):
        """After /usage reset, raw counters AND table show zero."""
        engine, _ = perplexity_engine

        # Chat to populate counters
        _chat_and_get_usage(engine)
        usage_before = engine.session.get_usage()
        assert usage_before["total_tokens"] > 0

        # Reset
        reset_dict = _get_usage_result(engine, "reset")
        assert reset_dict["type"] == "ConfirmationResult"
        assert reset_dict["status"] == "success"

        # Raw counters must be zero
        usage_after = engine.session.get_usage()
        assert usage_after["total_tokens"] == 0
        assert usage_after["prompt_tokens"] == 0
        assert usage_after["completion_tokens"] == 0
        assert usage_after["estimated_cost"] == 0.0
        assert len(usage_after.get("by_model", {})) == 0, \
            f"by_model should be empty after reset: {usage_after.get('by_model')}"

        # Table should show no model rows (empty by_model → no rows)
        table_dict = _get_usage_result(engine)
        assert table_dict["type"] == "TableResult"
        assert len(table_dict["rows"]) == 0, \
            f"Table should have no rows after reset, got: {table_dict['rows']}"

        # Message should contain 0 tokens
        assert "0 tokens" in table_dict["message"], \
            f"Message should say 0 tokens: {table_dict['message']}"

        print(f"\n[Factory] Before reset: {usage_before['total_tokens']} tokens")
        print(f"  After reset: raw={usage_after['total_tokens']}, rows={table_dict['rows']}")

    def test_provider_and_model_shown_correctly(self, gemini_engine):
        """Table row shows correct provider and model name."""
        engine, model_id = gemini_engine

        engine.session.reset_usage()
        _chat_and_get_usage(engine)
        result_dict = _get_usage_result(engine)

        rows = result_dict["rows"]
        # Find the gemini row
        gemini_rows = [r for r in rows if r[0] == "gemini"]
        assert len(gemini_rows) == 1, f"Expected 1 gemini row, got {gemini_rows}"

        row = gemini_rows[0]
        expected_model = model_id.split("/", 1)[-1] if "/" in model_id else model_id
        assert row[1] == expected_model, \
            f"Model column shows '{row[1]}', expected '{expected_model}'"

        print(f"\n[Factory/Gemini] Row: {row}")

    def test_cost_format_is_dollar_4_decimals(self, perplexity_engine):
        """Cost column uses $x.xxxx format."""
        engine, _ = perplexity_engine

        engine.session.reset_usage()
        _chat_and_get_usage(engine)
        result_dict = _get_usage_result(engine)

        for row in result_dict["rows"]:
            cost_str = row[4]
            assert cost_str.startswith("$"), f"Cost should start with $: {cost_str}"
            # Should have exactly 4 decimal places
            parts = cost_str.lstrip("$").split(".")
            assert len(parts) == 2 and len(parts[1]) == 4, \
                f"Cost should have 4 decimal places: {cost_str}"


# ---------------------------------------------------------------------------
# Test 2: /usage show mode — values are correct
# ---------------------------------------------------------------------------

class TestUsageShowMode:
    """Test /usage show subcommands return correct values."""

    def test_show_returns_current_mode(self, perplexity_engine):
        """'/usage show' returns KeyValueResult with correct current mode."""
        engine, _ = perplexity_engine

        # Set to model mode
        set_dict = _get_usage_result(engine, "show model")
        assert set_dict["type"] == "ConfirmationResult"

        # Now query — should report 'model'
        show_dict = _get_usage_result(engine, "show")
        assert show_dict["type"] == "KeyValueResult"
        assert show_dict["pairs"]["Current mode"] == "model"

        # Restore default
        _get_usage_result(engine, "show session")

        # Verify restored
        show_dict = _get_usage_result(engine, "show")
        assert show_dict["pairs"]["Current mode"] == "session"

    def test_show_invalid_mode_returns_error_with_suggestions(self, perplexity_engine):
        """'/usage show bananas' returns ErrorResult with valid mode list."""
        engine, _ = perplexity_engine

        err_dict = _get_usage_result(engine, "show bananas")
        assert err_dict["type"] == "ErrorResult"
        assert err_dict["status"] == "error"
        assert "suggestions" in err_dict
        assert len(err_dict["suggestions"]) > 0
        # Suggestions should list valid modes
        suggestion_text = " ".join(err_dict["suggestions"])
        for mode in ["session", "provider", "model", "off"]:
            assert mode in suggestion_text, \
                f"Suggestion should mention '{mode}': {suggestion_text}"

    def test_unknown_subcommand_returns_error(self, perplexity_engine):
        """'/usage bananas' returns ErrorResult with valid subcommands."""
        engine, _ = perplexity_engine

        err_dict = _get_usage_result(engine, "bananas")
        assert err_dict["type"] == "ErrorResult"
        assert err_dict["status"] == "error"
        assert "suggestions" in err_dict
        suggestion_text = " ".join(err_dict["suggestions"])
        for cmd in ["24h", "week", "reset"]:
            assert cmd in suggestion_text, \
                f"Suggestion should mention '{cmd}': {suggestion_text}"


# ---------------------------------------------------------------------------
# Test 3: HTTP endpoint — counter values match raw session data
# ---------------------------------------------------------------------------

class TestUsageCountersViaHttp:
    """Test /usage via POST /command/usage — verify counter VALUES."""

    def test_http_counters_match_raw_session(self, openai_engine):
        """POST /command/usage table rows match session.get_usage()."""
        engine, model_id = openai_engine

        engine.session.reset_usage()
        raw_usage = _chat_and_get_usage(engine)
        result_dict = _get_usage_result_via_http(engine)

        _assert_table_matches_raw_usage(result_dict, raw_usage, "openai", model_id)

        print(f"\n[HTTP/OpenAI] Raw: in={raw_usage['prompt_tokens']} "
              f"out={raw_usage['completion_tokens']} cost=${raw_usage['estimated_cost']:.4f}")
        print(f"  Table TOTAL row: {result_dict['rows'][-1]}")

    def test_http_reset_zeroes_counters(self, openai_engine):
        """POST /command/usage reset → raw counters zero."""
        engine, _ = openai_engine

        _chat_and_get_usage(engine)
        assert engine.session.get_usage()["total_tokens"] > 0

        reset_dict = _get_usage_result_via_http(engine, "reset")
        assert reset_dict["type"] == "ConfirmationResult"

        usage_after = engine.session.get_usage()
        assert usage_after["total_tokens"] == 0
        assert usage_after["prompt_tokens"] == 0
        assert usage_after["completion_tokens"] == 0

    def test_http_show_mode_reflects_state(self, openai_engine):
        """POST /command/usage show returns correct display mode."""
        engine, _ = openai_engine

        # Set mode via HTTP
        _get_usage_result_via_http(engine, "show provider")

        # Query mode via HTTP
        show_dict = _get_usage_result_via_http(engine, "show")
        assert show_dict["type"] == "KeyValueResult"
        assert show_dict["pairs"]["Current mode"] == "provider"

        # Restore
        _get_usage_result_via_http(engine, "show session")

    def test_http_unknown_command_returns_404(self, openai_engine):
        """POST /command/nonexistent returns 404."""
        engine, _ = openai_engine

        from fastapi.testclient import TestClient
        import ppxai.server.http as http_module

        manager = _create_test_client_with_engine(engine)

        with TestClient(http_module.app, raise_server_exceptions=False) as client:
            original = http_module.session_manager
            http_module.session_manager = manager

            resp = client.post("/command/nonexistent", json={"args": ""})
            assert resp.status_code == 404

            http_module.session_manager = original


# ---------------------------------------------------------------------------
# Test 4: Cross-client consistency — same numbers everywhere
# ---------------------------------------------------------------------------

class TestUsageCrossClientConsistency:
    """Verify all client paths produce identical usage data from same session."""

    def test_factory_and_http_show_same_counters(self, perplexity_engine):
        """CommandFactory and HTTP endpoint return identical counter values."""
        engine, _ = perplexity_engine

        engine.session.reset_usage()
        raw_usage = _chat_and_get_usage(engine)

        # Path 1: CommandFactory direct
        factory_dict = _get_usage_result(engine)

        # Path 2: HTTP endpoint (same engine, no chat in between)
        http_dict = _get_usage_result_via_http(engine)

        # Both must produce identical output
        assert factory_dict["type"] == http_dict["type"]
        assert factory_dict["status"] == http_dict["status"]
        assert factory_dict["columns"] == http_dict["columns"]
        assert factory_dict["rows"] == http_dict["rows"], \
            f"Rows differ!\n  Factory: {factory_dict['rows']}\n  HTTP: {http_dict['rows']}"
        assert factory_dict["message"] == http_dict["message"]

        # Both must match raw session data
        total_row = factory_dict["rows"][-1]
        assert _parse_comma_int(total_row[2]) == raw_usage["prompt_tokens"]
        assert _parse_comma_int(total_row[3]) == raw_usage["completion_tokens"]
        assert abs(_parse_cost(total_row[4]) - raw_usage["estimated_cost"]) < 0.0001

        print(f"\n[Cross-client] Raw: {raw_usage['total_tokens']} tokens")
        print(f"  Factory TOTAL: {factory_dict['rows'][-1]}")
        print(f"  HTTP TOTAL:    {http_dict['rows'][-1]}")

    def test_show_mode_consistent_across_paths(self, perplexity_engine):
        """Setting mode via Factory is visible via HTTP and vice versa."""
        engine, _ = perplexity_engine

        # Set via Factory
        _get_usage_result(engine, "show model")

        # Read via HTTP
        http_show = _get_usage_result_via_http(engine, "show")
        assert http_show["pairs"]["Current mode"] == "model"

        # Set via HTTP
        _get_usage_result_via_http(engine, "show provider")

        # Read via Factory
        factory_show = _get_usage_result(engine, "show")
        assert factory_show["pairs"]["Current mode"] == "provider"

        # Restore
        _get_usage_result(engine, "show session")


# ---------------------------------------------------------------------------
# Test 5: to_dict() serialization — all fields present for renderers
# ---------------------------------------------------------------------------

class TestResultSerialization:
    """Test that CommandResult.to_dict() produces valid JSON for renderers."""

    def test_table_result_has_renderer_fields(self, perplexity_engine):
        """TableResult.to_dict() has all fields renderCommandResult() needs."""
        engine, _ = perplexity_engine
        engine.session.reset_usage()
        _chat_and_get_usage(engine)

        d = _get_usage_result(engine)

        assert d["type"] == "TableResult"
        assert d["status"] == "success"
        assert isinstance(d["message"], str) and len(d["message"]) > 0
        assert isinstance(d["columns"], list) and len(d["columns"]) == 5
        assert isinstance(d["rows"], list)
        assert all(isinstance(r, list) and len(r) == 5 for r in d["rows"])

    def test_key_value_result_has_pairs(self, perplexity_engine):
        """KeyValueResult.to_dict() has non-empty pairs dict."""
        engine, _ = perplexity_engine

        d = _get_usage_result(engine, "show")

        assert d["type"] == "KeyValueResult"
        assert isinstance(d["pairs"], dict)
        assert len(d["pairs"]) > 0
        assert "Current mode" in d["pairs"]

    def test_confirmation_result_has_details(self, perplexity_engine):
        """ConfirmationResult.to_dict() has details dict."""
        engine, _ = perplexity_engine

        d = _get_usage_result(engine, "reset")

        assert d["type"] == "ConfirmationResult"
        assert d["status"] == "success"
        assert isinstance(d["details"], dict)
        assert d["details"]["counters_reset"] is True

    def test_error_result_has_suggestions_list(self, perplexity_engine):
        """ErrorResult.to_dict() has non-empty suggestions list."""
        engine, _ = perplexity_engine

        d = _get_usage_result(engine, "bananas")

        assert d["type"] == "ErrorResult"
        assert d["status"] == "error"
        assert isinstance(d["suggestions"], list)
        assert len(d["suggestions"]) > 0
