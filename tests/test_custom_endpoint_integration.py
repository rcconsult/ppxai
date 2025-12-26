"""Integration test for custom vLLM endpoint.

This test actually connects to the custom endpoint to verify it works.
Run with: pytest tests/test_custom_endpoint_integration.py -v -s

NOTE: These tests require a running vLLM/Ollama server with CUSTOM_* env vars configured.
"""
import os
import pytest
from dotenv import load_dotenv


@pytest.fixture(scope="module", autouse=True)
def load_env():
    """Load environment variables before any tests in this module."""
    # Load environment variables from the ppxai/.env file
    # Use override=True to reload even if already loaded/cleared by other tests
    env_path = os.path.join(os.path.dirname(__file__), '..', 'ppxai', '.env')
    load_dotenv(dotenv_path=env_path, override=True)
    yield
    # Reload again after tests in case they were cleared
    load_dotenv(dotenv_path=env_path, override=True)


@pytest.fixture
def custom_engine():
    """Create a real EngineClient connected to the custom endpoint.

    This fixture requires a custom vLLM/Ollama server to be running
    and configured via CUSTOM_* env vars or ppxai-config.json.
    """
    import importlib

    # Reload dotenv to ensure we have fresh environment variables
    # This is needed because test_config.py may clear environment
    env_path = os.path.join(os.path.dirname(__file__), '..', 'ppxai', '.env')
    load_dotenv(dotenv_path=env_path, override=True)

    # Reload config module to pick up new environment variables
    import ppxai.config
    importlib.reload(ppxai.config)

    from ppxai.config import PROVIDERS
    from ppxai.engine import EngineClient

    # Check if "custom" provider is explicitly configured (not a fallback)
    if "custom" not in PROVIDERS:
        pytest.skip("Custom provider not configured in PROVIDERS")

    # Verify it has a custom base_url (not the Perplexity URL)
    custom_config = PROVIDERS.get("custom", {})
    base_url = custom_config.get("base_url", "")
    if "perplexity.ai" in base_url:
        pytest.skip("Custom provider base_url is Perplexity (fallback) - need real custom endpoint")

    # Check for custom API key
    api_key_env = custom_config.get("api_key_env", "CUSTOM_API_KEY")
    api_key = os.getenv(api_key_env, "")
    if not api_key:
        pytest.skip(f"{api_key_env} not configured")

    engine = EngineClient()
    engine.set_provider("custom")
    return engine


@pytest.fixture
def custom_model_id():
    """Get the custom model ID from environment."""
    return os.getenv("CUSTOM_MODEL_ID", "gpt-oss-120b")


class TestCustomEndpointIntegration:
    """Integration tests for custom vLLM endpoint."""

    def test_simple_chat_request(self, custom_engine, custom_model_id):
        """Test a simple chat request to the custom endpoint."""
        custom_engine.set_model(custom_model_id)

        # Send a simple message using sync chat
        response = custom_engine.chat_sync("Say 'hello' and nothing else.")

        assert response is not None
        assert len(response) > 0
        assert "hello" in response.lower()
        print(f"\nResponse: {response}")

    def test_streaming_chat_request(self, custom_engine, custom_model_id):
        """Test a streaming chat request to the custom endpoint."""
        import asyncio
        from ppxai.engine.types import EventType

        custom_engine.set_model(custom_model_id)

        async def stream_chat():
            chunks = []
            async for event in custom_engine.chat("Count from 1 to 5, one number per line."):
                if event.type == EventType.STREAM_CHUNK:
                    chunks.append(event.data)
                elif event.type == EventType.STREAM_END:
                    return event.data
            return "".join(chunks)

        response = asyncio.get_event_loop().run_until_complete(stream_chat())

        assert response is not None
        assert len(response) > 0
        # Should contain at least some numbers
        assert any(str(i) in response for i in range(1, 6))
        print(f"\nStreaming Response: {response}")

    def test_conversation_history(self, custom_engine, custom_model_id):
        """Test that conversation history works."""
        custom_engine.set_model(custom_model_id)

        # First message
        custom_engine.chat_sync("Remember the word 'banana'.")

        # Second message referencing the first
        response = custom_engine.chat_sync("What word did I ask you to remember?")

        assert response is not None
        assert "banana" in response.lower()
        print(f"\nMemory test response: {response}")

    def test_usage_tracking(self, custom_engine, custom_model_id):
        """Test that usage is tracked (tokens counted)."""
        custom_engine.set_model(custom_model_id)

        initial_usage = custom_engine.get_usage()
        initial_tokens = initial_usage.get("total_tokens", 0)

        custom_engine.chat_sync("Hello!")

        final_usage = custom_engine.get_usage()
        final_tokens = final_usage.get("total_tokens", 0)

        # Token count should have increased
        print(f"\nTokens used: {final_tokens - initial_tokens}")
        # Note: Some vLLM configs may not return usage stats, so we just check it doesn't error


class TestCustomEndpointConnectionOnly:
    """Quick connection test - just verifies the endpoint is reachable."""

    def test_endpoint_reachable(self, custom_engine, custom_model_id):
        """Test that the custom endpoint is reachable and responds."""
        custom_engine.set_model(custom_model_id)

        try:
            response = custom_engine.chat_sync("Hi")
            print(f"\n[OK] Endpoint reachable! Response: {response[:100]}...")
            assert True
        except Exception as e:
            pytest.fail(f"Failed to connect to custom endpoint: {e}")


class TestCustomEndpointCodingTask:
    """Test coding tasks with custom LLM endpoint."""

    def test_fibonacci_code_generation(self, custom_model_id):
        """Test that custom LLM can generate Python code for Fibonacci problem."""
        import httpx
        from openai import OpenAI
        from ppxai.config import PROVIDERS, get_api_key, get_base_url

        # Check if "custom" provider is explicitly configured (not a fallback)
        if "custom" not in PROVIDERS:
            pytest.skip("Custom provider not configured in PROVIDERS")

        # Verify it has a custom base_url (not the Perplexity URL)
        custom_config = PROVIDERS.get("custom", {})
        provider_base_url = custom_config.get("base_url", "")
        if "perplexity.ai" in provider_base_url:
            pytest.skip("Custom provider base_url is Perplexity (fallback) - need real custom endpoint")

        # Create client directly to bypass Rich console output issues
        api_key = get_api_key("custom")
        base_url = get_base_url("custom")

        if not api_key:
            pytest.skip("CUSTOM_API_KEY not configured")

        http_client = httpx.Client(verify=False)
        client = OpenAI(api_key=api_key, base_url=base_url, http_client=http_client)

        prompt = """Write a Python function to calculate the nth Fibonacci number.
Include both an iterative and recursive solution with memoization.
Add docstrings and type hints."""

        print(f"\n{'='*70}")
        print("Testing Fibonacci Code Generation")
        print(f"{'='*70}")
        print(f"Prompt: {prompt}")
        print(f"{'-'*70}")

        response = client.chat.completions.create(
            model=custom_model_id,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1500
        )

        assistant_message = response.choices[0].message.content

        assert assistant_message is not None
        assert len(assistant_message) > 0

        # Check that the response contains expected Python code elements
        response_lower = assistant_message.lower()
        assert "def " in response_lower, "Response should contain function definition"
        assert "fibonacci" in response_lower or "fib" in response_lower, "Response should mention fibonacci"

        # Print the response (safe for Windows console)
        safe_response = assistant_message.encode('ascii', 'replace').decode('ascii')
        print(f"\nResponse from {custom_model_id}:")
        print(f"{'-'*70}")
        print(safe_response)
        print(f"{'-'*70}")

        # Print token usage
        print(f"Tokens used: prompt={response.usage.prompt_tokens}, completion={response.usage.completion_tokens}, total={response.usage.total_tokens}")
        print(f"{'='*70}")
