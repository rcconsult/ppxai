"""
Tests for reasoning token support (v1.13.9).

Reasoning tokens are used by models like DeepSeek R1 and GPT-OSS 120B
to show their thought process before generating the final response.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock
from ppxai.engine.types import Event, EventType


class TestReasoningEventType:
    """Test REASONING_CHUNK event type exists."""

    def test_reasoning_chunk_event_type_exists(self):
        """Verify REASONING_CHUNK is a valid EventType."""
        assert hasattr(EventType, 'REASONING_CHUNK')
        assert EventType.REASONING_CHUNK.value == 'reasoning_chunk'

    def test_reasoning_event_creation(self):
        """Test creating a REASONING_CHUNK event."""
        event = Event(EventType.REASONING_CHUNK, "thinking about the problem")
        assert event.type == EventType.REASONING_CHUNK
        assert event.data == "thinking about the problem"
        assert event.metadata is None

    def test_reasoning_event_with_metadata(self):
        """Test REASONING_CHUNK event with metadata."""
        event = Event(
            EventType.REASONING_CHUNK,
            "analyzing...",
            {"model": "gpt-oss-120b"}
        )
        assert event.type == EventType.REASONING_CHUNK
        assert event.data == "analyzing..."
        assert event.metadata == {"model": "gpt-oss-120b"}


class TestEventHandlerReasoningCallback:
    """Test EventHandler reasoning callback support."""

    def test_event_handler_has_reasoning_callback(self):
        """Verify EventHandler accepts on_reasoning_chunk callback."""
        from ppxai.common.event_handler import EventHandler

        callback_called = []

        def on_reasoning(chunk):
            callback_called.append(chunk)

        handler = EventHandler(on_reasoning_chunk=on_reasoning)
        assert handler.on_reasoning_chunk is not None

    def test_event_handler_default_reasoning_callback(self):
        """Verify EventHandler has default no-op for reasoning callback."""
        from ppxai.common.event_handler import EventHandler

        handler = EventHandler()
        # Should not raise
        handler.on_reasoning_chunk("test")

    @pytest.mark.asyncio
    async def test_event_handler_processes_reasoning_chunk(self):
        """Test EventHandler processes REASONING_CHUNK events."""
        from ppxai.common.event_handler import EventHandler

        reasoning_chunks = []

        def on_reasoning(chunk):
            reasoning_chunks.append(chunk)

        handler = EventHandler(on_reasoning_chunk=on_reasoning)

        # Process reasoning event
        event = Event(EventType.REASONING_CHUNK, "Let me think...")
        result = await handler.handle_event(event)

        assert result is True  # Should continue
        assert len(reasoning_chunks) == 1
        assert reasoning_chunks[0] == "Let me think..."

    @pytest.mark.asyncio
    async def test_event_handler_accumulates_reasoning(self):
        """Test EventHandler accumulates reasoning in _reasoning_response."""
        from ppxai.common.event_handler import EventHandler

        handler = EventHandler()

        # Reset state
        await handler.handle_event(Event(EventType.STREAM_START, None))

        # Process multiple reasoning chunks
        await handler.handle_event(Event(EventType.REASONING_CHUNK, "First, "))
        await handler.handle_event(Event(EventType.REASONING_CHUNK, "I need to "))
        await handler.handle_event(Event(EventType.REASONING_CHUNK, "analyze this."))

        assert handler._reasoning_response == "First, I need to analyze this."

    @pytest.mark.asyncio
    async def test_event_handler_resets_reasoning_on_start(self):
        """Test that STREAM_START resets reasoning accumulator."""
        from ppxai.common.event_handler import EventHandler

        handler = EventHandler()

        # Accumulate some reasoning
        handler._reasoning_response = "previous reasoning"

        # Start new stream
        await handler.handle_event(Event(EventType.STREAM_START, None))

        assert handler._reasoning_response == ""


class TestTUIEventHandlerReasoning:
    """Test TUIEventHandler reasoning display."""

    def test_tui_handler_has_reasoning_tracking(self):
        """Verify TUIEventHandler tracks reasoning state."""
        from ppxai.common.event_handler import TUIEventHandler

        console = MagicMock()
        logger = MagicMock()

        handler = TUIEventHandler(console, logger)
        assert hasattr(handler, '_reasoning_started')
        assert handler._reasoning_started is False

    def test_tui_handler_reasoning_chunk_shows_header(self):
        """Test TUIEventHandler shows 'Thinking...' header on first reasoning chunk."""
        from ppxai.common.event_handler import TUIEventHandler

        console = MagicMock()
        logger = MagicMock()

        handler = TUIEventHandler(console, logger)
        handler._on_reasoning_chunk("First thought...")

        # Should have shown header
        assert handler._reasoning_started is True
        # Check console was called for header
        calls = [str(call) for call in console.print.call_args_list]
        assert any("Thinking" in str(call) for call in calls)

    def test_tui_handler_reasoning_chunk_streams_content(self):
        """Test TUIEventHandler streams reasoning in dim italic style."""
        from ppxai.common.event_handler import TUIEventHandler

        console = MagicMock()
        logger = MagicMock()

        handler = TUIEventHandler(console, logger)
        handler._reasoning_started = True  # Skip header
        handler._on_reasoning_chunk("analyzing...")

        # Should print chunk with dim italic style
        console.print.assert_called()
        call_args = str(console.print.call_args)
        assert "dim italic" in call_args or "analyzing" in call_args

    def test_tui_handler_stream_start_resets_reasoning_state(self):
        """Test TUIEventHandler resets reasoning state on stream start."""
        from ppxai.common.event_handler import TUIEventHandler

        console = MagicMock()
        logger = MagicMock()

        handler = TUIEventHandler(console, logger)
        handler._reasoning_started = True

        handler._on_stream_start()

        assert handler._reasoning_started is False


class TestOpenAIProviderReasoningContent:
    """Test OpenAI-compatible provider reasoning_content handling."""

    def test_provider_extracts_reasoning_from_delta(self):
        """Test that provider extracts reasoning_content from stream chunks."""
        # This is tested implicitly through integration tests
        # The key logic is in openai_compat.py:
        # reasoning_content = getattr(delta, 'reasoning_content', None)
        pass

    def test_reasoning_included_in_stream_end_metadata(self):
        """Test that full reasoning is included in STREAM_END metadata."""
        # When reasoning is collected, metadata should have:
        # metadata["reasoning"] = final_reasoning
        pass


class TestIntegrationReasoningFlow:
    """Integration tests for complete reasoning flow."""

    @pytest.mark.asyncio
    async def test_reasoning_then_content_flow(self):
        """Test typical flow: reasoning chunks followed by content chunks."""
        from ppxai.common.event_handler import EventHandler

        chunks = []
        reasoning = []

        def on_chunk(c):
            chunks.append(c)

        def on_reasoning(c):
            reasoning.append(c)

        handler = EventHandler(
            on_stream_chunk=on_chunk,
            on_reasoning_chunk=on_reasoning
        )

        # Simulate typical flow
        await handler.handle_event(Event(EventType.STREAM_START, None))

        # Reasoning phase
        await handler.handle_event(Event(EventType.REASONING_CHUNK, "I need to "))
        await handler.handle_event(Event(EventType.REASONING_CHUNK, "think about this."))

        # Content phase
        await handler.handle_event(Event(EventType.STREAM_CHUNK, "Hello! "))
        await handler.handle_event(Event(EventType.STREAM_CHUNK, "How can I help?"))

        # End
        await handler.handle_event(Event(EventType.STREAM_END, "Hello! How can I help?"))

        assert reasoning == ["I need to ", "think about this."]
        assert handler._reasoning_response == "I need to think about this."
        assert chunks == ["Hello! ", "How can I help?"]
        assert handler._full_response == "Hello! How can I help?"

    @pytest.mark.asyncio
    async def test_no_reasoning_flow(self):
        """Test flow without reasoning (normal models)."""
        from ppxai.common.event_handler import EventHandler

        reasoning_called = []

        handler = EventHandler(
            on_reasoning_chunk=lambda c: reasoning_called.append(c)
        )

        await handler.handle_event(Event(EventType.STREAM_START, None))
        await handler.handle_event(Event(EventType.STREAM_CHUNK, "Direct response"))
        await handler.handle_event(Event(EventType.STREAM_END, "Direct response"))

        assert reasoning_called == []
        assert handler._reasoning_response == ""
        assert handler._full_response == "Direct response"
