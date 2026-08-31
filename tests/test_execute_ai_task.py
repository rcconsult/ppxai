"""Tests for ppxai.commands.coding._execute_ai_task.

This is the central path that 7 coding commands (/generate, /test,
/docs, /implement, /debug, /explain, /convert) all flow through. It
streams an LLM response, accumulates content, extracts code blocks,
and on auto-route swap-restores the engine model. The critique
flagged it as risk 0.85 / security-relevant / 7 callers / untested.

Tests cover all 7 sub-items from critique #4:
  a. missing engine client returns ErrorResult
  b. unknown task type returns ErrorResult
  c. autoroute switches model then restores original
  d. stream chunk accumulation correctness
  e. EventType.ERROR path restores original model
  f. async-context path does not deadlock
  g. code block extraction (multiple blocks, empty language)
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import MagicMock, patch

import pytest

from ppxai.commands.coding import _execute_ai_task
from ppxai.commands.results import (
    AIResponseResult,
    ErrorResult,
    ResultStatus,
)
from ppxai.engine.types import Event, EventType

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _async_event_stream(events: list[Event]):
    """Build an async-generator factory yielding the given events.

    Used to mock context.engine_client.chat(...) which returns an
    async iterable of Event objects.
    """
    async def gen(*args, **kwargs) -> AsyncIterator[Event]:
        for ev in events:
            yield ev

    return gen


def _make_context(
    *,
    has_engine: bool = True,
    current_model: str = "gpt-5.4-mini",
    auto_route: bool = False,
    provider: str = "openai",
    chat_events: list[Event] | None = None,
):
    """Build a mock CommandContext for _execute_ai_task tests."""
    ctx = MagicMock()
    if not has_engine:
        ctx.engine_client = None
        return ctx

    engine = MagicMock()
    engine.model = current_model
    engine.set_model = MagicMock()
    if chat_events is not None:
        engine.chat = _async_event_stream(chat_events)
    ctx.engine_client = engine

    ctx.get_provider.return_value = provider
    ctx.get_model.return_value = current_model
    ctx.get_auto_route.return_value = auto_route
    return ctx


def _suppress_console():
    """Patch ppxai.commands.coding.console to silence test output."""
    return patch("ppxai.commands.coding.console", MagicMock())


# ---------------------------------------------------------------------------
# Critique #4.a — missing engine client
# ---------------------------------------------------------------------------

class TestMissingEngineClient:
    def test_returns_error_result_when_engine_client_is_none(self):
        ctx = _make_context(has_engine=False)
        with _suppress_console():
            result = _execute_ai_task(ctx, "generate", "a function", "init")
        assert isinstance(result, ErrorResult)
        assert result.status == ResultStatus.ERROR
        assert "engine client not available" in result.message.lower()


# ---------------------------------------------------------------------------
# Critique #4.b — unknown task type
# ---------------------------------------------------------------------------

class TestUnknownTaskType:
    def test_returns_error_result_for_unknown_task_type(self):
        ctx = _make_context()
        with _suppress_console():
            result = _execute_ai_task(ctx, "not_a_real_task", "x", "init")
        assert isinstance(result, ErrorResult)
        assert result.status == ResultStatus.ERROR
        assert "unknown task type" in result.message.lower()
        assert "not_a_real_task" in result.message

    def test_engine_chat_not_called_for_unknown_task(self):
        ctx = _make_context()
        with _suppress_console():
            _execute_ai_task(ctx, "not_a_real_task", "x", "init")
        # chat is the bound generator, not a Mock — but set_model should
        # not be called either (no auto-route happened before the check
        # because the check comes before model swap).
        ctx.engine_client.set_model.assert_not_called()


# ---------------------------------------------------------------------------
# Critique #4.c — autoroute switches model and restores original
# ---------------------------------------------------------------------------

class TestAutorouteModelSwitch:
    def test_switches_to_coding_model_when_autoroute_enabled(self):
        ctx = _make_context(
            current_model="gpt-5.4-mini",
            auto_route=True,
            chat_events=[
                Event(type=EventType.STREAM_CHUNK, data="hello"),
            ],
        )
        with _suppress_console(), \
             patch("ppxai.commands.coding.get_coding_model",
                   return_value="gpt-5.5"):
            _execute_ai_task(ctx, "generate", "x", "init")

        # set_model called twice: once to switch, once to restore.
        calls = ctx.engine_client.set_model.call_args_list
        assert len(calls) == 2
        assert calls[0].args[0] == "gpt-5.5"
        assert calls[1].args[0] == "gpt-5.4-mini"

    def test_no_switch_when_already_on_coding_model(self):
        ctx = _make_context(
            current_model="gpt-5.4-mini",
            auto_route=True,
            chat_events=[Event(type=EventType.STREAM_CHUNK, data="x")],
        )
        with _suppress_console(), \
             patch("ppxai.commands.coding.get_coding_model",
                   return_value="gpt-5.4-mini"):
            _execute_ai_task(ctx, "generate", "x", "init")

        ctx.engine_client.set_model.assert_not_called()

    def test_no_switch_when_autoroute_disabled(self):
        ctx = _make_context(
            current_model="gpt-5.4",
            auto_route=False,
            chat_events=[Event(type=EventType.STREAM_CHUNK, data="x")],
        )
        with _suppress_console(), \
             patch("ppxai.commands.coding.get_coding_model",
                   return_value="gpt-5.4-mini"):
            _execute_ai_task(ctx, "generate", "x", "init")

        ctx.engine_client.set_model.assert_not_called()

    def test_restore_uses_reset_context_false(self):
        """Critical detail: restoring the model after streaming MUST
        use reset_context=False or the conversation history disappears."""
        ctx = _make_context(
            current_model="gpt-5.4",
            auto_route=True,
            chat_events=[Event(type=EventType.STREAM_CHUNK, data="x")],
        )
        with _suppress_console(), \
             patch("ppxai.commands.coding.get_coding_model",
                   return_value="gpt-5.4-mini"):
            _execute_ai_task(ctx, "generate", "x", "init")

        for call in ctx.engine_client.set_model.call_args_list:
            assert call.kwargs.get("reset_context") is False


# ---------------------------------------------------------------------------
# Critique #4.d — stream chunk accumulation
# ---------------------------------------------------------------------------

class TestStreamChunkAccumulation:
    def test_chunks_accumulate_in_order(self):
        ctx = _make_context(
            chat_events=[
                Event(type=EventType.STREAM_CHUNK, data="hello "),
                Event(type=EventType.STREAM_CHUNK, data="world"),
                Event(type=EventType.STREAM_CHUNK, data="!"),
            ],
        )
        with _suppress_console():
            result = _execute_ai_task(ctx, "generate", "x", "init")

        assert isinstance(result, AIResponseResult)
        assert result.content == "hello world!"
        assert result.status == ResultStatus.SUCCESS

    def test_empty_stream_returns_error_result(self):
        ctx = _make_context(chat_events=[])
        with _suppress_console():
            result = _execute_ai_task(ctx, "generate", "x", "init")
        assert isinstance(result, ErrorResult)
        assert "no response" in result.message.lower()

    def test_non_chunk_events_ignored_in_content(self):
        """Events of other types (e.g. STREAM_END) shouldn't end up in
        content. Only STREAM_CHUNK contributes."""
        ctx = _make_context(
            chat_events=[
                Event(type=EventType.STREAM_CHUNK, data="kept "),
                Event(type=EventType.STREAM_END, data="discarded"),
                Event(type=EventType.STREAM_CHUNK, data="kept2"),
            ],
        )
        with _suppress_console():
            result = _execute_ai_task(ctx, "generate", "x", "init")
        assert isinstance(result, AIResponseResult)
        assert result.content == "kept kept2"


# ---------------------------------------------------------------------------
# Critique #4.e — EventType.ERROR restores original model
# ---------------------------------------------------------------------------

class TestErrorPathRestoresModel:
    def test_error_event_returns_error_result(self):
        ctx = _make_context(
            chat_events=[
                Event(type=EventType.STREAM_CHUNK, data="partial"),
                Event(type=EventType.ERROR, data="provider blew up"),
            ],
        )
        with _suppress_console():
            result = _execute_ai_task(ctx, "generate", "x", "init")
        assert isinstance(result, ErrorResult)
        assert "provider blew up" in (result.error_details or "")

    def test_error_event_restores_model_via_finally(self):
        """The model swap is in a try/finally — even when the stream
        emits ERROR (and we early-return None), the finally block
        MUST run to restore the model."""
        ctx = _make_context(
            current_model="gpt-5.4",
            auto_route=True,
            chat_events=[
                Event(type=EventType.STREAM_CHUNK, data="partial"),
                Event(type=EventType.ERROR, data="provider error"),
            ],
        )
        with _suppress_console(), \
             patch("ppxai.commands.coding.get_coding_model",
                   return_value="gpt-5.4-mini"):
            _execute_ai_task(ctx, "generate", "x", "init")

        # Both the forward swap and the restore must have fired.
        calls = ctx.engine_client.set_model.call_args_list
        assert len(calls) == 2
        assert calls[0].args[0] == "gpt-5.4-mini"
        assert calls[1].args[0] == "gpt-5.4"  # restored

    def test_chat_exception_propagates_but_finally_restores(self):
        """If chat() itself raises (provider crash) the model still
        gets restored — finally is unconditional."""
        ctx = _make_context(
            current_model="gpt-5.4",
            auto_route=True,
        )

        async def boom(*a, **kw):
            yield Event(type=EventType.STREAM_CHUNK, data="ok")
            raise RuntimeError("network died")

        ctx.engine_client.chat = boom

        with _suppress_console(), \
             patch("ppxai.commands.coding.get_coding_model",
                   return_value="gpt-5.4-mini"):
            with pytest.raises(RuntimeError, match="network died"):
                _execute_ai_task(ctx, "generate", "x", "init")

        # finally still ran — model was restored before the raise propagated.
        calls = ctx.engine_client.set_model.call_args_list
        assert len(calls) == 2
        assert calls[1].args[0] == "gpt-5.4"


# ---------------------------------------------------------------------------
# Critique #4.f — async-context path uses ThreadPoolExecutor, no deadlock
# ---------------------------------------------------------------------------

class TestAsyncContextNoDeadlock:
    """When invoked from inside a running event loop (Textual TUI),
    _execute_ai_task uses ThreadPoolExecutor + asyncio.run in a
    worker thread to avoid the 'cannot be called when another loop
    is running' RuntimeError."""

    @pytest.mark.asyncio
    async def test_completes_inside_running_event_loop(self):
        """The pytest.mark.asyncio fixture means we're inside a
        running event loop. _execute_ai_task must complete without
        hanging or raising RuntimeError('asyncio.run cannot be
        called from a running event loop')."""
        ctx = _make_context(
            chat_events=[
                Event(type=EventType.STREAM_CHUNK, data="hello"),
                Event(type=EventType.STREAM_CHUNK, data=" world"),
            ],
        )
        with _suppress_console():
            result = _execute_ai_task(ctx, "generate", "x", "init")
        # Did NOT deadlock; got the streamed content back.
        assert isinstance(result, AIResponseResult)
        assert result.content == "hello world"

    @pytest.mark.asyncio
    async def test_async_context_still_restores_model(self):
        """Same async-context path, with auto-route on. The model
        restore must work through the thread-pool boundary too."""
        ctx = _make_context(
            current_model="gpt-5.4",
            auto_route=True,
            chat_events=[Event(type=EventType.STREAM_CHUNK, data="x")],
        )
        with _suppress_console(), \
             patch("ppxai.commands.coding.get_coding_model",
                   return_value="gpt-5.4-mini"):
            _execute_ai_task(ctx, "generate", "x", "init")

        calls = ctx.engine_client.set_model.call_args_list
        # set_model is called from the worker-thread async run loop,
        # but the context object is shared, so both calls land on
        # the same mock.
        assert len(calls) == 2
        assert calls[1].args[0] == "gpt-5.4"


# ---------------------------------------------------------------------------
# Critique #4.g — code block extraction
# ---------------------------------------------------------------------------

class TestCodeBlockExtraction:
    def test_single_code_block_with_language(self):
        content = "Here's the code:\n```python\ndef foo(): pass\n```"
        ctx = _make_context(
            chat_events=[Event(type=EventType.STREAM_CHUNK, data=content)],
        )
        with _suppress_console():
            result = _execute_ai_task(ctx, "generate", "x", "init")
        assert isinstance(result, AIResponseResult)
        assert len(result.code_blocks) == 1
        assert result.code_blocks[0]["language"] == "python"
        assert "def foo()" in result.code_blocks[0]["code"]

    def test_multiple_code_blocks_extracted_in_order(self):
        content = (
            "First:\n```python\nA = 1\n```\n"
            "Second:\n```javascript\nconst b = 2;\n```\n"
            "Third:\n```bash\necho hi\n```"
        )
        ctx = _make_context(
            chat_events=[Event(type=EventType.STREAM_CHUNK, data=content)],
        )
        with _suppress_console():
            result = _execute_ai_task(ctx, "generate", "x", "init")
        assert len(result.code_blocks) == 3
        assert result.code_blocks[0]["language"] == "python"
        assert result.code_blocks[1]["language"] == "javascript"
        assert result.code_blocks[2]["language"] == "bash"

    def test_empty_language_defaults_to_text(self):
        # Note: the regex requires \n after the optional language tag.
        # `\`\`\`\ncode\n\`\`\`` has no language; it defaults to "text".
        content = "Plain block:\n```\nsome code here\n```"
        ctx = _make_context(
            chat_events=[Event(type=EventType.STREAM_CHUNK, data=content)],
        )
        with _suppress_console():
            result = _execute_ai_task(ctx, "generate", "x", "init")
        assert len(result.code_blocks) == 1
        assert result.code_blocks[0]["language"] == "text"
        assert "some code here" in result.code_blocks[0]["code"]

    def test_no_code_blocks_yields_empty_list(self):
        content = "Just prose, no code."
        ctx = _make_context(
            chat_events=[Event(type=EventType.STREAM_CHUNK, data=content)],
        )
        with _suppress_console():
            result = _execute_ai_task(ctx, "generate", "x", "init")
        assert isinstance(result, AIResponseResult)
        assert result.code_blocks == []

    def test_code_block_strips_trailing_whitespace(self):
        content = "```python\ndef foo():\n    pass\n   \n```"
        ctx = _make_context(
            chat_events=[Event(type=EventType.STREAM_CHUNK, data=content)],
        )
        with _suppress_console():
            result = _execute_ai_task(ctx, "generate", "x", "init")
        # The regex captures up to ``` and the result is .strip()'d.
        assert len(result.code_blocks) == 1
        assert result.code_blocks[0]["code"].endswith("pass")
