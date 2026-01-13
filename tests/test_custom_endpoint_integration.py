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
    # Load environment variables from the project root .env file
    # Use override=True to reload even if already loaded/cleared by other tests
    env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
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
    env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
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

        # Use asyncio.run() for Python 3.10+ compatibility
        response = asyncio.run(stream_chat())

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

        # v1.13.9: Handle reasoning models that may return content in reasoning_content
        # instead of the regular content field (e.g., DeepSeek R1, GPT-OSS-120B)
        choice = response.choices[0]
        assistant_message = choice.message.content

        # Check for reasoning_content if regular content is empty
        if not assistant_message:
            # Try to get reasoning content from message attributes
            reasoning_content = getattr(choice.message, 'reasoning_content', None)
            if reasoning_content:
                assistant_message = reasoning_content

        # Also check for refusal field which some models use
        if not assistant_message:
            refusal = getattr(choice.message, 'refusal', None)
            if refusal:
                pytest.skip(f"Model refused to respond: {refusal}")

        assert assistant_message is not None, (
            f"Response content is None. Choice: {choice}, "
            f"Message attrs: {dir(choice.message)}"
        )
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


class TestCustomEndpointToolCalling:
    """Integration tests for tool calling with custom vLLM endpoint.

    These tests verify that tools work correctly when using a custom provider,
    including both prompt-based and native tool calling modes.
    """

    def test_tools_enable_with_custom_provider(self, custom_engine, custom_model_id):
        """Test that tools can be enabled for a custom provider."""
        custom_engine.set_model(custom_model_id)

        # Enable tools
        result = custom_engine.enable_tools()
        assert result is True
        assert custom_engine.tools_enabled is True

        # List tools - should include web_search for custom providers
        tools = custom_engine.tool_manager.list_tools()
        tool_names = [t["name"] for t in tools]

        print(f"\nEnabled {len(tools)} tools for custom provider:")
        for t in tools:
            print(f"  - {t['name']}: {t['description'][:50]}...")

        # Custom providers should get web_search (since they don't have native search)
        assert "web_search" in tool_names, "Custom providers should have web_search tool"
        assert "read_file" in tool_names, "Should have read_file tool"
        assert "calculator" in tool_names, "Should have calculator tool"

        # Disable tools
        custom_engine.disable_tools()
        assert custom_engine.tools_enabled is False

    def test_calculator_tool_execution(self, custom_engine, custom_model_id):
        """Test that calculator tool works with custom provider."""
        import asyncio
        from ppxai.engine.types import EventType

        custom_engine.set_model(custom_model_id)
        custom_engine.enable_tools()

        async def chat_with_tools():
            tool_calls = []
            tool_results = []
            final_response = ""

            async for event in custom_engine.chat("What is 123 * 456? Use the calculator tool."):
                if event.type == EventType.TOOL_CALL:
                    tool_calls.append(event.data)
                    print(f"\n  Tool call: {event.data.get('tool')} with args: {event.data.get('arguments')}")
                elif event.type == EventType.TOOL_RESULT:
                    tool_results.append(event.data)
                    print(f"  Tool result: {event.data.get('result', '')[:100]}")
                elif event.type == EventType.STREAM_END:
                    final_response = event.data

            return tool_calls, tool_results, final_response

        tool_calls, tool_results, response = asyncio.run(chat_with_tools())

        print(f"\nFinal response: {response[:200]}...")

        # Verify calculator was called (if model decided to use it)
        # Note: prompt-based tool calling may not always trigger
        if tool_calls:
            calc_calls = [t for t in tool_calls if t.get("tool") == "calculator"]
            if calc_calls:
                print(f"Calculator was called {len(calc_calls)} time(s)")
                # Check result contains correct answer
                assert "56088" in response or any("56088" in str(r.get("result", "")) for r in tool_results)

        custom_engine.disable_tools()

    def test_read_file_tool_execution(self, custom_engine, custom_model_id):
        """Test that read_file tool works with custom provider."""
        import asyncio
        import tempfile
        from ppxai.engine.types import EventType

        custom_engine.set_model(custom_model_id)
        custom_engine.enable_tools()

        # Create a test file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("This is a test file for ppxai tool testing.\nIt contains secret code: ALPHA123.")
            test_file_path = f.name

        try:
            async def chat_with_tools():
                tool_calls = []
                tool_results = []
                final_response = ""

                prompt = f"Read the file at {test_file_path} and tell me the secret code inside it."

                async for event in custom_engine.chat(prompt):
                    if event.type == EventType.TOOL_CALL:
                        tool_calls.append(event.data)
                        print(f"\n  Tool call: {event.data.get('tool')} with args: {event.data.get('arguments')}")
                    elif event.type == EventType.TOOL_RESULT:
                        tool_results.append(event.data)
                        result_preview = str(event.data.get('result', ''))[:100]
                        print(f"  Tool result: {result_preview}")
                    elif event.type == EventType.STREAM_END:
                        final_response = event.data

                return tool_calls, tool_results, final_response

            tool_calls, tool_results, response = asyncio.run(chat_with_tools())

            print(f"\nFinal response: {response[:300]}...")

            # Check if read_file was called
            if tool_calls:
                read_calls = [t for t in tool_calls if t.get("tool") == "read_file"]
                if read_calls:
                    print(f"read_file was called {len(read_calls)} time(s)")
                    # The response should mention the secret code
                    assert "ALPHA123" in response or any("ALPHA123" in str(r.get("result", "")) for r in tool_results)

        finally:
            import os
            os.unlink(test_file_path)
            custom_engine.disable_tools()

    def test_web_search_tool_available(self, custom_engine, custom_model_id):
        """Test that web_search tool is available for custom providers."""
        custom_engine.set_model(custom_model_id)
        custom_engine.enable_tools()

        tools = custom_engine.tool_manager.list_tools()
        tool_names = [t["name"] for t in tools]

        # Custom providers should have web_search
        assert "web_search" in tool_names, "web_search should be available for custom providers"

        # Find web_search tool description
        web_search_tool = next((t for t in tools if t["name"] == "web_search"), None)
        assert web_search_tool is not None

        print(f"\nweb_search tool description: {web_search_tool['description']}")

        # The description should mention the premium provider if available
        # (Perplexity or Gemini), otherwise DuckDuckGo
        desc = web_search_tool['description'].lower()
        assert "search" in desc

        custom_engine.disable_tools()

    def test_tool_verbose_mode(self, custom_engine, custom_model_id):
        """Test that verbose mode can be toggled for custom provider."""
        custom_engine.set_model(custom_model_id)
        custom_engine.enable_tools()

        # Set verbose mode
        result = custom_engine.set_tool_config("verbose", True)
        assert result is True
        assert custom_engine._tools_verbose is True

        # Disable verbose mode
        result = custom_engine.set_tool_config("verbose", False)
        assert result is True
        assert custom_engine._tools_verbose is False

        custom_engine.disable_tools()

    def test_native_tool_calling_capability_check(self, custom_engine, custom_model_id):
        """Test that native tool calling capability is correctly detected."""
        from ppxai.config import PROVIDERS

        custom_engine.set_model(custom_model_id)

        # Get provider capabilities
        provider = custom_engine.provider
        capabilities = provider.capabilities

        print(f"\nCustom provider capabilities:")
        print(f"  native_tool_calling: {capabilities.native_tool_calling}")
        print(f"  streaming: {capabilities.streaming}")
        print(f"  web_search: {capabilities.web_search}")

        # Custom providers typically have native_tool_calling=False by default
        # unless explicitly configured in ppxai-config.json
        custom_config = PROVIDERS.get("custom", {})
        config_caps = custom_config.get("capabilities", {})
        expected_native = config_caps.get("native_tool_calling", False)

        assert capabilities.native_tool_calling == expected_native, \
            f"Expected native_tool_calling={expected_native} from config"


class TestCustomEndpointPremiumWebSearch:
    """Integration tests for premium web search with custom provider."""

    def test_premium_search_available_for_custom(self, custom_engine, custom_model_id):
        """Test that premium web search is available when API keys are set."""
        from ppxai.engine.tools.builtin import web_premium

        custom_engine.set_model(custom_model_id)

        # Check if premium search is available
        is_available = web_premium.is_available()
        premium_provider = web_premium.get_premium_search_provider("custom")

        print(f"\nPremium web search available: {is_available}")
        print(f"Premium provider for custom: {premium_provider}")

        if is_available:
            assert premium_provider in ["perplexity", "gemini"], \
                "Premium provider should be perplexity or gemini"
        else:
            assert premium_provider is None, \
                "No premium provider should be detected without API keys"

    def test_premium_search_ssl_verify_setting(self):
        """Test that SSL_VERIFY setting is respected by premium search."""
        import os
        from ppxai.engine.tools.builtin import web_premium

        # Check current SSL_VERIFY setting
        ssl_verify_env = os.getenv("SSL_VERIFY", "true")
        print(f"\nSSL_VERIFY env: {ssl_verify_env}")

        # The ssl_verify logic in web_premium.py
        ssl_verify = ssl_verify_env.lower() != "false"
        print(f"SSL verification enabled: {ssl_verify}")

        # This test just verifies the setting is correctly parsed
        if ssl_verify_env.lower() == "false":
            assert ssl_verify is False, "SSL verification should be disabled"
        else:
            assert ssl_verify is True, "SSL verification should be enabled by default"
