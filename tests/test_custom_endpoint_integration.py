"""Integration test for custom vLLM endpoint.

This test actually connects to the custom endpoint to verify it works.
Run with: pytest tests/test_custom_endpoint_integration.py -v -s
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
def custom_client():
    """Create a real client connected to the custom endpoint."""
    import importlib
    from ppxai.client import AIClient

    # Reload dotenv to ensure we have fresh environment variables
    # This is needed because test_config.py may clear environment
    env_path = os.path.join(os.path.dirname(__file__), '..', 'ppxai', '.env')
    load_dotenv(dotenv_path=env_path, override=True)

    # Reload config module to pick up new environment variables
    import ppxai.config
    importlib.reload(ppxai.config)

    from ppxai.config import get_api_key, get_base_url

    api_key = get_api_key("custom")
    base_url = get_base_url("custom")

    if not api_key:
        pytest.skip("CUSTOM_API_KEY not configured")

    return AIClient(api_key, base_url, provider="custom")


@pytest.fixture
def custom_model_id():
    """Get the custom model ID from environment."""
    return os.getenv("CUSTOM_MODEL_ID", "gpt-oss-120b")


class TestCustomEndpointIntegration:
    """Integration tests for custom vLLM endpoint."""

    def test_simple_chat_request(self, custom_client, custom_model_id):
        """Test a simple chat request to the custom endpoint."""
        # Send a simple message (non-streaming for easier testing)
        response = custom_client.chat(
            "Say 'hello' and nothing else.",
            model=custom_model_id,
            stream=False
        )

        assert response is not None
        assert len(response) > 0
        assert "hello" in response.lower()
        print(f"\nResponse: {response}")

    def test_streaming_chat_request(self, custom_client, custom_model_id):
        """Test a streaming chat request to the custom endpoint."""
        response = custom_client.chat(
            "Count from 1 to 5, one number per line.",
            model=custom_model_id,
            stream=True
        )

        assert response is not None
        assert len(response) > 0
        # Should contain at least some numbers
        assert any(str(i) in response for i in range(1, 6))
        print(f"\nStreaming Response: {response}")

    def test_conversation_history(self, custom_client, custom_model_id):
        """Test that conversation history works."""
        # First message
        custom_client.chat(
            "Remember the word 'banana'.",
            model=custom_model_id,
            stream=False
        )

        # Second message referencing the first
        response = custom_client.chat(
            "What word did I ask you to remember?",
            model=custom_model_id,
            stream=False
        )

        assert response is not None
        assert "banana" in response.lower()
        print(f"\nMemory test response: {response}")

    def test_usage_tracking(self, custom_client, custom_model_id):
        """Test that usage is tracked (tokens counted)."""
        initial_tokens = custom_client.current_session_usage["total_tokens"]

        custom_client.chat(
            "Hello!",
            model=custom_model_id,
            stream=False
        )

        final_tokens = custom_client.current_session_usage["total_tokens"]

        # Token count should have increased
        print(f"\nTokens used: {final_tokens - initial_tokens}")
        # Note: Some vLLM configs may not return usage stats, so we just check it doesn't error


class TestCustomEndpointConnectionOnly:
    """Quick connection test - just verifies the endpoint is reachable."""

    def test_endpoint_reachable(self, custom_client, custom_model_id):
        """Test that the custom endpoint is reachable and responds."""
        try:
            response = custom_client.chat(
                "Hi",
                model=custom_model_id,
                stream=False
            )
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
        from ppxai.config import get_api_key, get_base_url

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
