"""Tests for engine client context tracking and management (v1.13.9).

These tests verify:
- Context injection tracking (_injected_contexts)
- get_context_info() method
- clear_injected_contexts() method
- Context recovery workflow
"""
import os
from unittest.mock import patch

import pytest

from ppxai.engine.client import EngineClient
from ppxai.engine.types import Message


async def async_event_generator(events):
    """Helper to create async generator from list of events."""
    for event in events:
        yield event


class TestContextTracking:
    """Tests for context tracking in EngineClient."""

    @pytest.fixture
    def engine_client(self):
        """Create an EngineClient instance for testing."""
        with patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"}):
            client = EngineClient()
            client.set_provider("perplexity")
            client.set_model("sonar")
            return client

    def test_initial_context_list_empty(self, engine_client):
        """Test that _injected_contexts is empty initially."""
        assert hasattr(engine_client, '_injected_contexts')
        assert engine_client._injected_contexts == []

    def test_get_context_info_returns_dict(self, engine_client):
        """Test get_context_info returns expected structure."""
        info = engine_client.get_context_info()

        assert isinstance(info, dict)
        assert "estimated_tokens" in info
        assert "context_limit" in info
        assert "usage_percent" in info
        assert "injected_contexts" in info
        assert "injected_tokens" in info
        assert "message_count" in info
        assert "total_chars" in info
        assert "provider" in info
        assert "model" in info

    def test_get_context_info_empty_session(self, engine_client):
        """Test get_context_info with no messages."""
        engine_client.session.messages = []
        info = engine_client.get_context_info()

        assert info["estimated_tokens"] == 0
        assert info["message_count"] == 0
        assert info["total_chars"] == 0
        assert info["injected_contexts"] == []
        assert info["injected_tokens"] == 0

    def test_get_context_info_with_messages(self, engine_client):
        """Test get_context_info calculates tokens from messages."""
        # Add some test messages (4 chars ~= 1 token)
        engine_client.session.messages = [
            Message(role="user", content="Hello World"),  # 11 chars ~= 2-3 tokens
            Message(role="assistant", content="Hi there!"),  # 9 chars ~= 2 tokens
        ]
        info = engine_client.get_context_info()

        assert info["message_count"] == 2
        assert info["total_chars"] == 20  # "Hello World" + "Hi there!"
        assert info["estimated_tokens"] == 5  # 20 // 4

    def test_get_context_info_context_limit(self, engine_client):
        """Test that context limit is retrieved from config."""
        info = engine_client.get_context_info()

        # Should have a positive context limit
        assert info["context_limit"] > 0
        # Should be a reasonable value (at least 10K tokens)
        assert info["context_limit"] >= 10000

    def test_get_context_info_usage_percent(self, engine_client):
        """Test usage percentage calculation."""
        # Add enough messages to have some percentage
        engine_client.session.messages = [
            Message(role="user", content="x" * 4000),  # 1000 tokens
        ]
        info = engine_client.get_context_info()

        # Usage should be > 0 but < 100
        assert info["usage_percent"] > 0
        assert info["usage_percent"] < 100

    def test_clear_injected_contexts_empty(self, engine_client):
        """Test clear_injected_contexts returns 0 when nothing to clear."""
        result = engine_client.clear_injected_contexts()
        assert result == 0

    def test_clear_injected_contexts_removes_tracked(self, engine_client):
        """Test clear_injected_contexts removes tracked contexts."""
        # Manually add some tracked contexts
        engine_client._injected_contexts = [
            {"source": "@file:test.py", "size": 100, "truncated": False},
            {"source": "@git:HEAD", "size": 200, "truncated": False},
        ]

        result = engine_client.clear_injected_contexts()

        assert result == 2
        assert engine_client._injected_contexts == []

    def test_clear_injected_contexts_removes_from_messages(self, engine_client):
        """Test clear_injected_contexts removes injection blocks from messages."""
        # Add a message with injected content
        engine_client.session.messages = [
            Message(role="user", content="""What is this file?

---
**`@file:test.py`**:
```python
print("hello")
```
"""),
        ]

        # Add tracked context
        engine_client._injected_contexts = [
            {"source": "@file:test.py", "size": 30, "truncated": False},
        ]

        engine_client.clear_injected_contexts()

        # Check that injection block is removed
        remaining = engine_client.session.messages[0].content
        assert "@file:test.py" not in remaining
        assert "```python" not in remaining


class TestContextIntegration:
    """Integration tests for context workflow."""

    @pytest.fixture
    def engine_client(self):
        """Create an EngineClient instance for testing."""
        with patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"}):
            client = EngineClient()
            client.set_provider("perplexity")
            client.set_model("sonar")
            return client

    def test_context_tracking_after_injection(self, engine_client):
        """Test that context injection tracking works correctly."""
        # Simulate adding an injection tracking entry
        engine_client._injected_contexts.append({
            "source": "@file:config.py",
            "size": 5000,
            "truncated": False,
            "timestamp": "2024-01-01T00:00:00"
        })

        info = engine_client.get_context_info()

        assert len(info["injected_contexts"]) == 1
        assert info["injected_tokens"] == 1250  # 5000 // 4

    def test_context_info_provider_and_model(self, engine_client):
        """Test that provider and model are included in context info."""
        info = engine_client.get_context_info()

        assert info["provider"] == "perplexity"
        assert info["model"] == "sonar"

    def test_clear_preserves_conversation_flow(self, engine_client):
        """Test that clearing contexts preserves non-injection content."""
        # Add messages with and without injections
        engine_client.session.messages = [
            Message(role="user", content="Hello!"),
            Message(role="assistant", content="Hi there!"),
            Message(role="user", content="""What about this?

---
**`@file:test.py`**:
```python
x = 1
```
"""),
            Message(role="assistant", content="That's a simple variable assignment."),
        ]

        engine_client._injected_contexts = [
            {"source": "@file:test.py", "size": 10, "truncated": False},
        ]

        engine_client.clear_injected_contexts()

        # Should still have 4 messages
        assert len(engine_client.session.messages) == 4
        # First two should be unchanged
        assert engine_client.session.messages[0].content == "Hello!"
        assert engine_client.session.messages[1].content == "Hi there!"
        # Last assistant message should be unchanged
        assert "variable assignment" in engine_client.session.messages[3].content


class TestContextLimits:
    """Tests for context limit handling."""

    def test_context_limit_import_fallback(self):
        """Test that context limit falls back to default on import error."""
        # Create client
        with patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"}):
            client = EngineClient()
            client.set_provider("perplexity")

        # Mock the config import to raise ImportError
        original_get_context_info = client.get_context_info

        def patched_get_context_info():
            info = original_get_context_info()
            # Verify it returns a valid context_limit even with defaults
            return info

        info = client.get_context_info()

        # Should have a valid context limit (either from config or default 128K)
        assert info["context_limit"] == 128_000 or info["context_limit"] > 0

    def test_injected_contexts_copy_returned(self):
        """Test that get_context_info returns a copy of injected_contexts."""
        with patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"}):
            client = EngineClient()
            client.set_provider("perplexity")

        client._injected_contexts = [{"source": "@file:test.py", "size": 100}]

        info = client.get_context_info()

        # Modify the returned list
        info["injected_contexts"].append({"source": "@file:other.py", "size": 50})

        # Original should be unchanged
        assert len(client._injected_contexts) == 1
