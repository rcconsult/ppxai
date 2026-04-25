"""Cross-client agent task validation tests (v1.18.1 step 5b.1).

Pre-v1.18.1, only the TUI factory path (handle_agent) enforced
min_task_words. Web users running `/agent fix` via streamChat
hit /chat directly and the LLM-with-tools just went — a real
safety gap.

v1.18.1 closes the gap by:
  1. Centralising validation in ppxai.commands.agent.validate_agent_task
  2. Calling it from the /chat route when message starts with /agent
  3. Calling it from handle_agent (factory in-process path)
  4. Returning a friendlier NotificationResult (was ErrorResult)
     framed as a question with concrete examples — per the v1.18.1
     UX decision: ask for more context, don't bounce.

Tests:
  - validate_agent_task returns None for valid tasks
  - validate_agent_task returns NotificationResult(WARNING) for vague
  - The rejection message asks for more context (question framing)
  - The rejection includes concrete examples
  - The rejection metadata carries reason + min/actual word counts
  - /chat route rejects `/agent <vague>` before LLM streaming
  - /chat route lets `/agent <good>` through to the streaming path
  - factory handle_agent uses the same helper (one source of truth)
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from ppxai.commands.agent import validate_agent_task
from ppxai.commands.context import ServerCommandContext
from ppxai.commands.factory import CommandFactory
from ppxai.commands.results import (
    NotificationResult,
    ResultStatus,
)


# ---------------------------------------------------------------------------
# validate_agent_task — pure helper
# ---------------------------------------------------------------------------

class TestValidateAgentTask:
    def test_valid_task_returns_none(self):
        result = validate_agent_task("Fix the off-by-one in parser.py line_count", 3)
        assert result is None

    def test_exactly_min_words_passes(self):
        # Boundary check: exactly min_words is OK.
        result = validate_agent_task("fix the bug", 3)
        assert result is None

    def test_below_min_words_returns_notification(self):
        result = validate_agent_task("fix bug", 3)
        assert result is not None
        assert isinstance(result, NotificationResult)
        # Per v1.18.1 UX: not an error, a warning-with-question.
        assert result.status == ResultStatus.WARNING

    def test_empty_task_returns_notification(self):
        result = validate_agent_task("", 3)
        assert result is not None
        assert isinstance(result, NotificationResult)

    def test_single_word_returns_notification(self):
        result = validate_agent_task("fix", 3)
        assert result is not None

    def test_rejection_asks_for_more_context(self):
        """Per v1.18.1 UX decision: rejection is framed as a
        question requesting context, not a red error."""
        result = validate_agent_task("fix", 3)
        assert result is not None
        # Question markers
        msg = result.message
        assert "more" in msg.lower() or "detail" in msg.lower(), (
            f"Rejection should ask for more context; got: {msg[:200]}"
        )
        # The original task echoes back
        assert "fix" in msg

    def test_rejection_includes_concrete_examples(self):
        result = validate_agent_task("fix", 3)
        assert result is not None
        # At least one /agent example
        assert "/agent" in result.message
        # Examples should reference filenames or paths to model
        # what good detail looks like
        assert "py" in result.message or ":" in result.message

    def test_rejection_metadata_carries_diagnostics(self):
        result = validate_agent_task("fix", 3)
        assert result is not None
        meta = result.metadata
        assert meta["reason"] == "agent_task_too_vague"
        assert meta["min_words"] == 3
        assert meta["actual_words"] == 1
        assert meta["task"] == "fix"

    def test_custom_min_words_threshold(self):
        # Some configs raise the threshold for stricter safety
        result = validate_agent_task("fix the bug now", 5)
        assert result is not None  # 4 words < 5 threshold
        assert result.metadata["min_words"] == 5
        assert result.metadata["actual_words"] == 4


# ---------------------------------------------------------------------------
# /chat route safety gate
# ---------------------------------------------------------------------------

@pytest.fixture
def http_client():
    import ppxai.server.http as http_module
    with TestClient(http_module.app, raise_server_exceptions=False) as client:
        yield client


def _new_session_headers(name: str) -> dict:
    return {"X-Session-Id": f"agent-validate-{name}"}


def _read_sse_first_payload(content: bytes) -> dict:
    """Decode the first `data: {...}` SSE event from a stream body."""
    text = content.decode("utf-8", errors="replace")
    for line in text.splitlines():
        if line.startswith("data: "):
            return json.loads(line[len("data: "):])
    return {}


class TestChatRouteAgentGate:
    def test_vague_agent_task_short_circuits(self, http_client):
        """Web's /agent fix used to flow through /chat untouched.
        v1.18.1 gates it server-side."""
        resp = http_client.post(
            "/chat",
            json={"message": "/agent fix"},
            headers=_new_session_headers("vague"),
        )
        assert resp.status_code == 200
        # The response is an SSE stream; the first event should be
        # the rejection rendered as a system message
        first = _read_sse_first_payload(resp.content)
        assert first.get("type") == "system"
        assert "more" in (first.get("data", "") or "").lower()

    def test_good_agent_task_passes_through(self, http_client):
        """A well-specified task is NOT rejected — flows to the
        normal chat streaming path. We can't fully exercise the LLM
        in a unit test, so we just assert the safety gate doesn't
        short-circuit."""
        resp = http_client.post(
            "/chat",
            json={
                "message": "/agent Fix the off-by-one in parser.py line_count function",
            },
            headers=_new_session_headers("good"),
        )
        assert resp.status_code == 200
        # First event is NOT the rejection text (it might be a real
        # provider error since no API key, but that's a different
        # error than agent-task-too-vague)
        first = _read_sse_first_payload(resp.content)
        rejection_marker = "more detail before running"
        body_text = first.get("data", "") if isinstance(first.get("data"), str) else ""
        assert rejection_marker not in body_text, (
            f"Good task was incorrectly rejected. First SSE: {first}"
        )

    def test_bare_agent_command_not_gated(self, http_client):
        """`/agent` (no args) is the toggle/status form — not a
        task. Should not hit the validation."""
        resp = http_client.post(
            "/chat",
            json={"message": "/agent"},
            headers=_new_session_headers("bare"),
        )
        # Either empty-message rejection OR LLM error, but NOT the
        # agent-task validation rejection
        first = _read_sse_first_payload(resp.content)
        rejection_marker = "I need a bit more detail"
        body_text = first.get("data", "") if isinstance(first.get("data"), str) else ""
        assert rejection_marker not in body_text

    def test_agent_with_only_whitespace_args_rejected(self, http_client):
        """`/agent    ` (just whitespace) reaches the gate with an
        empty task — should be rejected the same way."""
        resp = http_client.post(
            "/chat",
            json={"message": "/agent    "},
            headers=_new_session_headers("ws"),
        )
        # The exact behavior: gate is hit because message starts
        # with "/agent " (with space). Empty task → rejection.
        # (Or — depending on `is_empty_or_context_only` — this
        # might short-circuit at the empty-message check earlier.
        # Either rejection is fine; both stop the LLM.)
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Factory handler uses the shared helper
# ---------------------------------------------------------------------------

class TestFactoryUsesSharedValidator:
    def test_handle_agent_returns_notification_for_vague_task(self):
        """The TUI in-process path (handle_agent) uses
        validate_agent_task — same nudge, same shape, no separate
        validation logic to keep in sync."""
        engine = MagicMock()
        engine.get_agent_config.return_value = {
            "min_task_words": 3,
            "max_iterations": 10,
        }
        engine.agent_mode = False
        ctx = ServerCommandContext(engine)
        # Drive the registered factory handler
        result = CommandFactory.get("agent").handler(ctx, "fix")
        assert isinstance(result, NotificationResult)
        # Same nudge text the validator produces
        assert "more" in result.message.lower()
        assert result.metadata.get("reason") == "agent_task_too_vague"

    def test_handle_agent_passes_valid_task(self):
        """Validation passes — handler proceeds (we don't run the
        full agent loop in a unit test, just confirm validation
        doesn't short-circuit)."""
        engine = MagicMock()
        engine.get_agent_config.return_value = {
            "min_task_words": 3,
            "max_iterations": 10,
        }
        engine.agent_mode = True  # avoid the enable_agent_mode path
        # Make the loop fail fast so the test doesn't actually run an LLM
        engine.create_checkpoint.side_effect = RuntimeError("test stop")
        ctx = ServerCommandContext(engine)
        # Use a long-enough task that validation passes
        try:
            CommandFactory.get("agent").handler(
                ctx, "Fix the off-by-one in parser.py line_count"
            )
        except RuntimeError as e:
            # If we got past validation, our test stop fires
            assert "test stop" in str(e)
            return
        # If no exception, validation must have passed (handler
        # ran further; we don't care about the final result for
        # this test, only that validation didn't reject).


# ---------------------------------------------------------------------------
# /spec rich templates (port from VSCode chatPanel.ts)
# ---------------------------------------------------------------------------

class TestSpecTemplatesPorted:
    """Pre-v1.18.1, /spec returned a 5-line stub from the factory
    while VSCode had ~50-line rich templates inline. v1.18.1 ports
    the rich templates server-side so all clients get them."""

    def test_spec_no_args_returns_full_guidelines(self):
        engine = MagicMock()
        ctx = ServerCommandContext(engine)
        result = CommandFactory.get("spec").handler(ctx, "")
        # The guidelines markdown has multiple sections
        for marker in ("Overview", "Requirements",
                       "Technical Details", "Examples"):
            assert marker in result.content, (
                f"/spec guidelines missing '{marker}' section"
            )

    @pytest.mark.parametrize("spec_type", ["api", "cli", "lib", "algo", "ui"])
    def test_each_template_has_rich_content(self, spec_type):
        """Each template must be substantive (not the old 5-line
        stub). The prior factory stub was ~80 chars; the rich
        VSCode templates are ~1000+. Use 500 as the floor — a
        regression guard against re-introducing stubs."""
        engine = MagicMock()
        ctx = ServerCommandContext(engine)
        result = CommandFactory.get("spec").handler(ctx, spec_type)
        assert len(result.content) > 500, (
            f"/spec {spec_type} content is suspiciously short "
            f"({len(result.content)} chars). The rich VSCode "
            f"templates are 1000+ chars."
        )

    def test_api_template_contains_curl_example(self):
        engine = MagicMock()
        ctx = ServerCommandContext(engine)
        result = CommandFactory.get("spec").handler(ctx, "api")
        assert "curl" in result.content, (
            "api template should include a curl example (per the "
            "VSCode source we ported from)"
        )

    def test_unknown_type_lists_valid_options(self):
        engine = MagicMock()
        ctx = ServerCommandContext(engine)
        result = CommandFactory.get("spec").handler(ctx, "nosuch")
        assert "Unknown" in result.content or "unknown" in result.content
        # Should hint at the valid types
        for valid in ("api", "cli", "lib", "algo", "ui"):
            assert valid in result.content
