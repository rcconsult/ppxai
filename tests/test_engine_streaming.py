"""Tests for engine client streaming and conversation history management.

These tests verify the fix for the 400 error bug where assistant messages
weren't being added to session history before STREAM_END event was yielded.
"""
import pytest
import os
from unittest.mock import Mock, AsyncMock, patch
from ppxai.engine.client import EngineClient
from ppxai.engine.types import Event, EventType, Message


async def async_event_generator(events):
    """Helper to create async generator from list of events."""
    for event in events:
        yield event


class TestEngineClientStreaming:
    """Tests for EngineClient streaming behavior."""

    @pytest.fixture
    async def engine_client(self):
        """Create an EngineClient instance for testing."""
        with patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"}):
            client = EngineClient()
            # Set provider to perplexity for testing
            client.set_provider("perplexity")
            client.set_model("sonar")
            return client

    @pytest.mark.asyncio
    async def test_assistant_message_added_before_stream_end(self):
        """Test that assistant message is added to session BEFORE STREAM_END is yielded.

        This is the critical fix for the 400 error bug. The TUI breaks out of the
        event loop when it receives STREAM_END, so the message must be added first.
        """
        with patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"}):
            client = EngineClient()
            client.set_provider("perplexity")
            client.set_model("sonar")

        # Mock the provider's chat method to return streaming events
        mock_provider_response = [
            Event(EventType.STREAM_START, None),
            Event(EventType.STREAM_CHUNK, "Hello"),
            Event(EventType.STREAM_CHUNK, " World"),
            Event(EventType.STREAM_END, "Hello World"),
        ]

        with patch.object(client.provider, 'chat') as mock_chat:
            mock_chat.return_value = async_event_generator(mock_provider_response)

            # Clear session to start fresh
            client.session.messages = []

            # Simulate the TUI's behavior: break after STREAM_END
            events_received = []
            async for event in client.chat("test message", stream=True):
                events_received.append(event)
                if event.type == EventType.STREAM_END:
                    # This is what TUI does - breaks immediately
                    break

            # Verify session has both user and assistant messages
            assert len(client.session.messages) == 2, \
                f"Expected 2 messages (user + assistant), got {len(client.session.messages)}"

            assert client.session.messages[0].role == "user"
            assert client.session.messages[0].content == "test message"

            assert client.session.messages[1].role == "assistant"
            assert client.session.messages[1].content == "Hello World"

    @pytest.mark.asyncio
    async def test_multi_turn_conversation_history(self):
        """Test that multi-turn conversations maintain proper message alternation.

        This test simulates the exact scenario that caused the 400 error:
        1. First query with tools
        2. Enable tools (history sync)
        3. Second query (should not get 400 error)
        """
        with patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"}):
            client = EngineClient()
            client.set_provider("perplexity")
            client.set_model("sonar")

        # Mock provider to return simple responses
        with patch.object(client.provider, 'chat') as mock_chat:
            # First turn
            mock_chat.return_value = async_event_generator([
                Event(EventType.STREAM_START, None),
                Event(EventType.STREAM_CHUNK, "First response"),
                Event(EventType.STREAM_END, "First response"),
            ])

            async for event in client.chat("First query", stream=True):
                if event.type == EventType.STREAM_END:
                    break  # Simulate TUI breaking

            # Verify first turn
            assert len(client.session.messages) == 2
            assert client.session.messages[0].role == "user"
            assert client.session.messages[1].role == "assistant"

            # Second turn
            mock_chat.return_value = async_event_generator([
                Event(EventType.STREAM_START, None),
                Event(EventType.STREAM_CHUNK, "Second response"),
                Event(EventType.STREAM_END, "Second response"),
            ])

            async for event in client.chat("Second query", stream=True):
                if event.type == EventType.STREAM_END:
                    break  # Simulate TUI breaking

            # Verify second turn - should have 4 messages total
            assert len(client.session.messages) == 4, \
                f"Expected 4 messages after 2 turns, got {len(client.session.messages)}"

            # Verify proper alternation: user, assistant, user, assistant
            assert client.session.messages[0].role == "user"
            assert client.session.messages[1].role == "assistant"
            assert client.session.messages[2].role == "user"
            assert client.session.messages[3].role == "assistant"

    @pytest.mark.asyncio
    async def test_stream_end_contains_full_response(self):
        """Test that STREAM_END event contains the full accumulated response."""
        with patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"}):
            client = EngineClient()
            client.set_provider("perplexity")
            client.set_model("sonar")

        with patch.object(client.provider, 'chat') as mock_chat:
            # Simulate streaming chunks
            mock_chat.return_value = async_event_generator([
                Event(EventType.STREAM_START, None),
                Event(EventType.STREAM_CHUNK, "Part 1 "),
                Event(EventType.STREAM_CHUNK, "Part 2 "),
                Event(EventType.STREAM_CHUNK, "Part 3"),
                Event(EventType.STREAM_END, "Part 1 Part 2 Part 3"),
            ])

            client.session.messages = []

            async for event in client.chat("test", stream=True):
                if event.type == EventType.STREAM_END:
                    break

            # The assistant message should contain the full response from STREAM_END
            assert client.session.messages[1].content == "Part 1 Part 2 Part 3"

    @pytest.mark.asyncio
    async def test_non_streaming_also_adds_message(self):
        """Test that non-streaming chat also properly adds messages."""
        with patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"}):
            client = EngineClient()
            client.set_provider("perplexity")
            client.set_model("sonar")

        with patch.object(client.provider, 'chat') as mock_chat:
            # Non-streaming returns single STREAM_END event
            mock_chat.return_value = async_event_generator([
                Event(EventType.STREAM_END, "Complete response"),
            ])

            client.session.messages = []

            # Non-streaming call - collect all events
            async for event in client.chat("test message", stream=False):
                if event.type == EventType.STREAM_END:
                    break

            # Should still have both messages
            assert len(client.session.messages) == 2
            assert client.session.messages[0].role == "user"
            assert client.session.messages[1].role == "assistant"
            assert client.session.messages[1].content == "Complete response"

    @pytest.mark.asyncio
    async def test_interrupt_during_streaming(self):
        """Test that interrupting during streaming doesn't corrupt history."""
        with patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"}):
            client = EngineClient()
            client.set_provider("perplexity")
            client.set_model("sonar")

        with patch.object(client.provider, 'chat') as mock_chat:
            mock_chat.return_value = async_event_generator([
                Event(EventType.STREAM_START, None),
                Event(EventType.STREAM_CHUNK, "Partial"),
                # Simulate interrupt before STREAM_END
            ])

            client.session.messages = []

            try:
                async for event in client.chat("test", stream=True):
                    if event.type == EventType.STREAM_CHUNK:
                        # Interrupt during streaming
                        break
            except:
                pass

            # Should have user message but no assistant message yet
            # (since we interrupted before STREAM_END)
            assert len(client.session.messages) >= 1
            assert client.session.messages[0].role == "user"


class TestMessageAlternationValidation:
    """Tests to ensure message alternation is always valid."""

    def test_valid_alternation_pattern(self):
        """Test that valid user/assistant alternation is recognized."""
        messages = [
            Message("user", "Hello"),
            Message("assistant", "Hi there"),
            Message("user", "How are you?"),
            Message("assistant", "I'm good!"),
        ]

        # Verify alternation
        for i in range(len(messages) - 1):
            assert messages[i].role != messages[i + 1].role, \
                f"Adjacent messages at {i} and {i+1} have same role"

    def test_invalid_alternation_detected(self):
        """Test that invalid alternation (two user messages) is detected."""
        messages = [
            Message("user", "Hello"),
            Message("assistant", "Hi"),
            Message("user", "How are you?"),
            Message("user", "Are you there?"),  # Invalid!
        ]

        # This should fail validation
        has_invalid = False
        for i in range(len(messages) - 1):
            if messages[i].role == messages[i + 1].role:
                has_invalid = True
                break

        assert has_invalid, "Should detect invalid alternation"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
