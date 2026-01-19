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


class TestErrorRollback:
    """Tests for user message rollback when errors occur during chat.

    Regression test for bug where errors during chat_with_tools didn't
    rollback the user message, causing message alternation errors on retry.
    """

    @pytest.mark.asyncio
    async def test_error_on_first_iteration_rolls_back_user_message(self):
        """Test that errors on first tool iteration rollback the user message.

        This is the critical fix for the bug where:
        1. User sends message with tools enabled
        2. API call fails (connection error, auth error, etc.)
        3. User message was NOT removed from session
        4. Next message caused "messages must alternate" error

        The fix ensures remove_last_message() is called when iteration == 1
        (the first iteration after increment).
        """
        with patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"}):
            client = EngineClient()
            client.set_provider("perplexity")
            client.set_model("sonar")

        # Enable tools to exercise chat_with_tools path
        client.tools_enabled = True

        with patch.object(client.provider, 'chat') as mock_chat:
            # Simulate error on first API call
            mock_chat.return_value = async_event_generator([
                Event(EventType.STREAM_START, {"model": "sonar"}),
                Event(EventType.ERROR, "Connection failed: Unable to reach server"),
            ])

            client.session.messages = []

            # First message fails
            events = []
            async for event in client.chat("test message", stream=True):
                events.append(event)

            # Should have received ERROR event
            assert any(e.type == EventType.ERROR for e in events)

            # Session should be empty - user message should have been rolled back
            assert len(client.session.messages) == 0, \
                f"Expected 0 messages after error rollback, got {len(client.session.messages)}"

    @pytest.mark.asyncio
    async def test_error_rollback_allows_retry(self):
        """Test that after error rollback, a retry succeeds without alternation errors."""
        with patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"}):
            client = EngineClient()
            client.set_provider("perplexity")
            client.set_model("sonar")

        client.tools_enabled = True
        client.session.messages = []

        with patch.object(client.provider, 'chat') as mock_chat:
            # First call fails
            mock_chat.return_value = async_event_generator([
                Event(EventType.STREAM_START, {"model": "sonar"}),
                Event(EventType.ERROR, "Connection failed"),
            ])

            async for event in client.chat("first try", stream=True):
                pass

            # After error, session should be clean
            assert len(client.session.messages) == 0

            # Second call succeeds
            mock_chat.return_value = async_event_generator([
                Event(EventType.STREAM_START, {"model": "sonar"}),
                Event(EventType.STREAM_END, "Success!"),
            ])

            async for event in client.chat("second try", stream=True):
                pass

            # Should have proper user/assistant pair now
            assert len(client.session.messages) == 2
            assert client.session.messages[0].role == "user"
            assert client.session.messages[1].role == "assistant"

    @pytest.mark.asyncio
    async def test_multiple_errors_dont_corrupt_session(self):
        """Test that multiple consecutive errors don't leave orphan messages."""
        with patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"}):
            client = EngineClient()
            client.set_provider("perplexity")
            client.set_model("sonar")

        client.tools_enabled = True
        client.session.messages = []

        with patch.object(client.provider, 'chat') as mock_chat:
            # Fail three times in a row
            for i in range(3):
                mock_chat.return_value = async_event_generator([
                    Event(EventType.STREAM_START, {"model": "sonar"}),
                    Event(EventType.ERROR, f"Error {i+1}"),
                ])

                async for event in client.chat(f"attempt {i+1}", stream=True):
                    pass

                # Session should always be empty after each error
                assert len(client.session.messages) == 0, \
                    f"Session should be empty after error {i+1}, got {len(client.session.messages)}"


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


class TestSessionAlternationFix:
    """Tests for session validate_and_fix_alternation method (v1.14.1)."""

    def test_fix_consecutive_user_messages(self):
        """Test that consecutive user messages are fixed."""
        from ppxai.engine.session import SessionManager

        session = SessionManager()
        session.messages = [
            Message("user", "Hello"),
            Message("assistant", "Hi"),
            Message("user", "First question"),
            Message("user", "Second question"),  # Invalid - consecutive user
            Message("assistant", "Answer"),
        ]

        removed = session.validate_and_fix_alternation()

        assert removed == 1
        assert len(session.messages) == 4
        # Should keep first user message in the consecutive pair
        assert session.messages[2].content == "First question"
        assert session.messages[3].content == "Answer"

    def test_fix_trailing_user_message(self):
        """Test that trailing user message (orphan) is removed."""
        from ppxai.engine.session import SessionManager

        session = SessionManager()
        session.messages = [
            Message("user", "Hello"),
            Message("assistant", "Hi"),
            Message("user", "Orphan message"),  # Invalid - no assistant response
        ]

        removed = session.validate_and_fix_alternation()

        assert removed == 1
        assert len(session.messages) == 2
        assert session.messages[-1].role == "assistant"

    def test_fix_multiple_issues(self):
        """Test fixing multiple alternation issues at once."""
        from ppxai.engine.session import SessionManager

        session = SessionManager()
        session.messages = [
            Message("user", "Hello"),
            Message("user", "Hello again"),  # Invalid
            Message("assistant", "Hi"),
            Message("user", "Question 1"),
            Message("user", "Question 2"),  # Invalid
            Message("user", "Question 3"),  # Invalid
            Message("assistant", "Answer"),
            Message("user", "Final orphan"),  # Invalid - trailing
        ]

        removed = session.validate_and_fix_alternation()

        assert removed == 4
        assert len(session.messages) == 4
        # Verify proper alternation
        for i in range(len(session.messages) - 1):
            assert session.messages[i].role != session.messages[i + 1].role

    def test_valid_session_unchanged(self):
        """Test that valid sessions are not modified."""
        from ppxai.engine.session import SessionManager

        session = SessionManager()
        session.messages = [
            Message("user", "Hello"),
            Message("assistant", "Hi"),
            Message("user", "How are you?"),
            Message("assistant", "I'm good!"),
        ]

        removed = session.validate_and_fix_alternation()

        assert removed == 0
        assert len(session.messages) == 4

    def test_empty_session_unchanged(self):
        """Test that empty sessions don't cause errors."""
        from ppxai.engine.session import SessionManager

        session = SessionManager()
        session.messages = []

        removed = session.validate_and_fix_alternation()

        assert removed == 0
        assert len(session.messages) == 0

    def test_single_user_message_removed(self):
        """Test that a single trailing user message is removed.

        A session with just a user message (no assistant response) would cause
        alternation errors when the next message is sent.
        """
        from ppxai.engine.session import SessionManager

        session = SessionManager()
        session.messages = [Message("user", "Hello")]

        removed = session.validate_and_fix_alternation()

        # Single user message is an orphan - removed
        assert removed == 1
        assert len(session.messages) == 0

    def test_single_assistant_message_removed(self):
        """Test that a single leading assistant message is removed.

        Sessions starting with assistant break alternation when system prompt
        is prepended (API requires user/tool after system).
        """
        from ppxai.engine.session import SessionManager

        session = SessionManager()
        session.messages = [Message("assistant", "Welcome!")]

        removed = session.validate_and_fix_alternation()

        # Leading assistant message is removed
        assert removed == 1
        assert len(session.messages) == 0

    def test_leading_assistant_messages_removed(self):
        """Test that leading assistant messages are stripped.

        This is the case that caused the Perplexity alternation bug:
        - Tool-use session saved with assistant message first
        - On restore, system prompt prepended
        - API error: "after system, user/tool must follow"
        """
        from ppxai.engine.session import SessionManager

        session = SessionManager()
        session.messages = [
            Message("assistant", "I'll use the tool"),  # Leading - remove
            Message("user", "Tool result here"),
            Message("assistant", "Based on the result..."),
            Message("user", "Thanks"),
            Message("assistant", "You're welcome"),
        ]

        removed = session.validate_and_fix_alternation()

        assert removed == 1
        assert len(session.messages) == 4
        assert session.messages[0].role == "user"
        assert session.messages[0].content == "Tool result here"

    def test_multiple_leading_assistant_messages_removed(self):
        """Test that multiple leading assistant messages are all removed."""
        from ppxai.engine.session import SessionManager

        session = SessionManager()
        session.messages = [
            Message("assistant", "First assistant"),  # Remove
            Message("assistant", "Second assistant"),  # Remove (consecutive)
            Message("user", "Hello"),
            Message("assistant", "Hi there"),
        ]

        removed = session.validate_and_fix_alternation()

        # Both leading assistants removed, then consecutive check removes one more
        # Actually: first two are leading assistants, removed. Then user, assistant - valid.
        # Wait, after removing leading, we have [user, assistant] which is valid
        # But original had assistant, assistant at start - first pass removes leading
        # Actually the loop removes LEADING assistants first, then the main loop handles rest
        assert removed == 2  # Both leading assistants
        assert len(session.messages) == 2
        assert session.messages[0].role == "user"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
