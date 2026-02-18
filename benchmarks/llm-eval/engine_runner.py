"""
Engine-based benchmark runner using ppxai's EngineClient.

This runner uses the ppxai Engine layer instead of direct OpenAI API calls,
enabling benchmarking of all providers through their native implementations
(Perplexity, Gemini, OpenRouter, vLLM/GPT-OSS, etc.).
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# Add parent directory to path for ppxai imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Initialize ppxai config system (loads .env, config, directories)
from ppxai.config import initialize
initialize()

# Clean up invalid SSL_CERT_FILE from .env (e.g., Windows paths on WSL)
import os
env_cert = os.environ.get("SSL_CERT_FILE", "")
if env_cert and not os.path.exists(env_cert):
    os.environ.pop("SSL_CERT_FILE", None)

from ppxai.engine.client import EngineClient
from ppxai.engine.types import EventType, Message
from ppxai.engine.bootstrap import BootstrapContext
from ppxai.engine.context import ScopedBootstrapSource

from test_cases import ALL_TESTS, TestCase, get_categories, TOOLS
from results import BenchmarkResult


class EngineClientWrapper:
    """
    Wrapper that adapts ppxai's EngineClient to the benchmark test interface.

    Test cases expect a `client.chat()` method that:
    - Takes messages, tools (optional), and other kwargs
    - Returns a dict with 'content', 'tool_calls', 'finish_reason'

    This wrapper provides that interface using EngineClient's async generator API.
    """

    def __init__(
        self,
        provider: str,
        model: str,
        verbose: bool = False,
        debug: bool = False,
        debug_dir: Optional[Path] = None,
    ):
        self.provider = provider
        self.model = model
        self.verbose = verbose
        self.debug = debug
        self.debug_dir = debug_dir
        self._client: Optional[EngineClient] = None
        self._initialized = False
        self._request_count = 0
        self._response_samples = []  # For model fingerprinting

    async def initialize(self) -> bool:
        """Initialize the EngineClient with provider and model."""
        try:
            self._client = EngineClient()

            # Load AGENTS.md from all scopes (global ~/.ppxai/, project root, cwd)
            # Use the same merged loading as the real ppxai client (v1.14.2)
            project_root = Path(__file__).parent.parent.parent
            self._client.context_injector.working_dir = str(project_root)
            try:
                loaded = self._client.load_bootstrap_context()
                if loaded and self.verbose:
                    status = self._client.get_bootstrap_status()
                    source_count = len(status.get("sources", []))
                    hints = self._client._bootstrap_context.get_active_hints_for(self.provider, self.model)
                    hint_count = len(hints.get("provider_hints", [])) + len(hints.get("model_hints", []))
                    if hint_count > 0:
                        scopes = [s["scope"] for s in status.get("sources", [])]
                        print(f"  [INFO] Loaded {hint_count} hints from {source_count} AGENTS.md file(s) ({', '.join(scopes)})")
            except Exception as e:
                if self.verbose:
                    print(f"  [WARN] Failed to load AGENTS.md: {e}")

            # Set provider
            if not self._client.set_provider(self.provider):
                if self.verbose:
                    print(f"  [ERROR] Failed to set provider: {self.provider}")
                return False

            # Set model
            if not self._client.set_model(self.model):
                if self.verbose:
                    print(f"  [ERROR] Failed to set model: {self.model}")
                return False

            # Enable tools for tool-calling tests
            self._client.enable_tools()

            self._initialized = True
            return True

        except Exception as e:
            if self.verbose:
                print(f"  [ERROR] Failed to initialize EngineClient: {e}")
            return False

    async def chat(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        **kwargs,
    ) -> dict:
        """
        Send chat completion request using EngineClient.

        Converts from benchmark test format to EngineClient format and back.
        """
        if not self._initialized:
            if not await self.initialize():
                return {"content": "", "tool_calls": [], "error": "Client not initialized"}

        # Reset session for each test (fresh context)
        self._client.session.clear()

        # Build the conversation
        # Extract system message if present
        system_content = ""
        user_messages = []

        for msg in messages:
            if msg["role"] == "system":
                system_content = msg["content"]
            else:
                user_messages.append(msg)

        # Add system message to session if present
        if system_content:
            self._client.session.add_message(Message(role="system", content=system_content))

        # Add conversation history (excluding the last user message which we'll send via chat)
        for i, msg in enumerate(user_messages[:-1] if user_messages else []):
            role = msg["role"]
            content = msg.get("content") or ""

            # Handle tool calls in assistant messages
            if role == "assistant" and msg.get("tool_calls"):
                # For now, just add as assistant message
                # The engine handles tool call history internally
                if content:
                    self._client.session.add_message(Message(role="assistant", content=content))
            elif role == "tool":
                # Tool results - add as assistant message with context
                tool_result = msg.get("content", "")
                self._client.session.add_message(Message(role="assistant", content=f"Tool result: {tool_result}"))
            else:
                self._client.session.add_message(Message(role=role, content=content))

        # Get the last user message to send
        last_message = ""
        if user_messages:
            last_msg = user_messages[-1]
            if last_msg["role"] == "user":
                last_message = last_msg["content"]
            elif last_msg["role"] == "tool":
                # If last message is a tool result, we need to prompt for continuation
                tool_result = last_msg.get("content", "")
                self._client.session.add_message(Message(role="assistant", content=f"Tool result: {tool_result}"))
                last_message = "Please continue based on the tool result."
            else:
                last_message = last_msg.get("content", "")

        if not last_message:
            return {"content": "", "tool_calls": [], "error": "No message to send"}

        # Inject tool definitions into system prompt if tools provided
        if tools:
            tool_prompt = self._build_tool_prompt(tools)
            # Prepend to last message or add as context
            last_message = f"{tool_prompt}\n\nUser request: {last_message}"

        # Call the engine
        result = {
            "content": "",
            "tool_calls": [],
            "finish_reason": "stop",
        }

        # Debug logging: Save request details
        if self.debug and self.debug_dir:
            self._request_count += 1
            debug_log = {
                "request_id": self._request_count,
                "provider": self.provider,
                "model": self.model,
                "messages": messages,
                "tools_provided": len(tools) if tools else 0,
                "tools": [t.get("function", {}).get("name") for t in tools] if tools else [],
                "last_message": last_message,
            }

        try:
            async for event in self._client.chat(last_message, stream=False):
                if self.verbose:
                    print(f"  [DEBUG] Event: {event.type} - {str(event.data)[:100]}")

                if event.type == EventType.STREAM_END:
                    result["content"] = event.data or ""

                elif event.type == EventType.STREAM_CHUNK:
                    # For non-streaming, shouldn't get chunks
                    result["content"] += event.data or ""

                elif event.type == EventType.TOOL_CALL:
                    # Engine detected a tool call
                    tool_data = event.data
                    if isinstance(tool_data, dict):
                        tool_call = {
                            "id": tool_data.get("id", f"call_{len(result['tool_calls'])}"),
                            "type": "function",
                            "function": {
                                "name": tool_data.get("tool", tool_data.get("name", "")),
                                "arguments": json.dumps(tool_data.get("arguments", {})),
                            }
                        }
                        result["tool_calls"].append(tool_call)
                        result["finish_reason"] = "tool_calls"

                elif event.type == EventType.ERROR:
                    result["error"] = event.data
                    break

            # Try to extract tool calls from content if none were captured via events
            # (handles prompt-based tool calling)
            if not result["tool_calls"] and result["content"]:
                extracted = self._extract_tool_calls_from_content(result["content"], tools)
                if extracted:
                    result["tool_calls"] = extracted
                    result["finish_reason"] = "tool_calls"

            # Collect response samples for model fingerprinting (first 3 only)
            if len(self._response_samples) < 3 and result["content"]:
                self._response_samples.append(result["content"][:500])  # First 500 chars

            # Debug logging: Save response details
            if self.debug and self.debug_dir:
                debug_log["response"] = {
                    "content": result["content"],
                    "tool_calls": result["tool_calls"],
                    "finish_reason": result["finish_reason"],
                    "error": result.get("error"),
                }
                log_file = self.debug_dir / f"request_{self._request_count:03d}.json"
                with open(log_file, "w") as f:
                    json.dump(debug_log, f, indent=2)

            return result

        except Exception as e:
            if self.verbose:
                print(f"  [ERROR] Chat exception: {e}")

            # Debug logging: Save exception details
            if self.debug and self.debug_dir:
                debug_log["exception"] = {
                    "type": type(e).__name__,
                    "message": str(e),
                    "traceback": __import__("traceback").format_exc(),
                }
                log_file = self.debug_dir / f"request_{self._request_count:03d}_EXCEPTION.json"
                with open(log_file, "w") as f:
                    json.dump(debug_log, f, indent=2)

            return {"content": "", "tool_calls": [], "error": str(e)}

    def _build_tool_prompt(self, tools: list[dict]) -> str:
        """Build a tool prompt for providers that don't support native tool calling."""
        lines = [
            "You have access to the following tools. To use a tool, output a JSON object with 'tool' and 'arguments' keys.",
            "Call tools directly without explanation. Output ONLY the JSON, no markdown code blocks.",
            "",
            "Available tools:",
        ]

        for tool in tools:
            if tool.get("type") == "function":
                func = tool.get("function", {})
                name = func.get("name", "")
                desc = func.get("description", "")
                params = func.get("parameters", {})
                lines.append(f"\n- {name}: {desc}")
                if params.get("properties"):
                    lines.append(f"  Parameters: {json.dumps(params['properties'], indent=2)}")

        return "\n".join(lines)

    def _extract_tool_calls_from_content(
        self,
        content: str,
        tools: Optional[list[dict]] = None
    ) -> list[dict]:
        """
        Extract tool calls from response content.

        Handles cases where models output tool calls as JSON in the response
        instead of using native tool calling.
        """
        import re

        tool_calls = []
        tool_names = set()

        if tools:
            for tool in tools:
                if tool.get("type") == "function":
                    name = tool.get("function", {}).get("name", "")
                    if name:
                        tool_names.add(name)

        # Try to find JSON objects in content
        # Pattern 1: {"tool": "name", "arguments": {...}}
        pattern1 = r'\{\s*"tool"\s*:\s*"([^"]+)"\s*,\s*"arguments"\s*:\s*(\{[^}]+\})\s*\}'

        for match in re.finditer(pattern1, content, re.DOTALL):
            tool_name = match.group(1)
            try:
                args = json.loads(match.group(2))
                if not tool_names or tool_name in tool_names:
                    tool_calls.append({
                        "id": f"call_{len(tool_calls)}",
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": json.dumps(args),
                        }
                    })
            except json.JSONDecodeError:
                pass

        # Pattern 2: {"name": "tool_name", ...} (OpenAI-style)
        if not tool_calls:
            pattern2 = r'\{\s*"name"\s*:\s*"([^"]+)"[^}]*"arguments"\s*:\s*(\{[^}]+\}|\[[^\]]+\]|"[^"]*")[^}]*\}'

            for match in re.finditer(pattern2, content, re.DOTALL):
                tool_name = match.group(1)
                try:
                    args_str = match.group(2)
                    if args_str.startswith('"'):
                        args = json.loads(args_str)
                        if isinstance(args, str):
                            args = json.loads(args)
                    else:
                        args = json.loads(args_str)

                    if not tool_names or tool_name in tool_names:
                        tool_calls.append({
                            "id": f"call_{len(tool_calls)}",
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": json.dumps(args) if isinstance(args, dict) else args,
                            }
                        })
                except json.JSONDecodeError:
                    pass

        return tool_calls


class EngineBenchmarkRunner:
    """
    Runs benchmark tests using ppxai's EngineClient.

    This allows benchmarking all providers supported by ppxai, including those
    with native APIs (Perplexity, Gemini) that don't support OpenAI-style tool calling.
    """

    def __init__(
        self,
        provider: str,
        model: str,
        timeout: int = 120,
        retries: int = 1,
        verbose: bool = False,
        debug: bool = False,
    ):
        self.provider = provider
        self.model = model
        self.timeout = timeout
        self.retries = retries
        self.verbose = verbose
        self.debug = debug

        # Setup debug logging directory
        self.debug_dir = None
        if debug:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.debug_dir = Path(__file__).parent / "debug" / f"{provider}_{model}_{timestamp}"
            self.debug_dir.mkdir(parents=True, exist_ok=True)
            print(f"Debug logs will be saved to: {self.debug_dir}")

        # Configure logging for debug mode or if PPXAI_LOG_LEVEL is set
        if debug or os.getenv("PPXAI_LOG_LEVEL"):
            try:
                import logging

                # Set root logger to DEBUG
                logging.basicConfig(
                    level=logging.DEBUG,
                    format='[%(name)s] %(levelname)s: %(message)s'
                )

                if verbose:
                    print("  [INFO] Logging configured at DEBUG level")
            except Exception as e:
                if verbose:
                    print(f"  [WARN] Failed to configure logging: {e}")

        self.client = EngineClientWrapper(
            provider=provider,
            model=model,
            verbose=verbose,
            debug=debug,
            debug_dir=self.debug_dir,
        )

    def _get_sdk_versions(self) -> dict:
        """Get SDK versions for provider-specific packages."""
        versions = {}

        # Try to get google-genai version
        try:
            import google.genai
            versions["google-genai"] = getattr(google.genai, "__version__", "unknown")
        except (ImportError, AttributeError):
            pass

        # Try to get openai version
        try:
            import openai
            versions["openai"] = openai.__version__
        except (ImportError, AttributeError):
            pass

        # Try to get anthropic version
        try:
            import anthropic
            versions["anthropic"] = anthropic.__version__
        except (ImportError, AttributeError):
            pass

        return versions

    def _compute_model_fingerprint(self) -> str:
        """Compute a fingerprint from first 3 test responses.

        This helps detect when model behavior changes (e.g., Google updates the model).
        Uses MD5 hash of concatenated response content.
        """
        if not self.client._response_samples:
            return "no-samples"

        import hashlib
        # Concatenate first 3 responses (or fewer if less available)
        combined = "\n".join(self.client._response_samples[:3])
        return hashlib.md5(combined.encode()).hexdigest()[:12]

    def _detect_tool_calling_method(self) -> str:
        """Detect if provider uses native or prompt-based tool calling.

        Returns:
            "native" if provider supports native function calling API
            "prompt_based" if tools are injected via system prompt
        """
        from ppxai.config import PROVIDERS
        provider_config = PROVIDERS.get(self.provider, {})
        capabilities = provider_config.get("capabilities", {})
        return "native" if capabilities.get("native_tool_calling") else "prompt_based"

    def run(self, categories: Optional[list[str]] = None) -> BenchmarkResult:
        """Run benchmark synchronously."""
        return asyncio.run(self.run_async(categories))

    async def run_async(self, categories: Optional[list[str]] = None) -> BenchmarkResult:
        """Run benchmark tests."""
        start_time = time.time()

        # Initialize client
        if not await self.client.initialize():
            print(f"ERROR: Failed to initialize client for {self.provider}/{self.model}")
            return BenchmarkResult(
                provider=self.provider,
                model=self.model,
                timestamp=datetime.utcnow().isoformat(),
                overall_score=0.0,
                tests_passed=0,
                tests_total=len(ALL_TESTS) if not categories else len([t for t in ALL_TESTS if t.category in categories]),
                duration_seconds=0.0,
                category_scores={},
                test_results=[{
                    "name": "initialization",
                    "category": "system",
                    "passed": False,
                    "details": {"error": "Client initialization failed"},
                    "weight": 0,
                }],
                metadata={"error": "Client initialization failed"},
            )

        # Filter tests by category if specified
        tests = ALL_TESTS
        if categories:
            tests = [t for t in tests if t.category in categories]

        test_results = []
        category_results = {}  # category -> list of (passed, weight)

        print(f"Running {len(tests)} tests using ppxai Engine...")
        print(f"Provider: {self.provider}, Model: {self.model}")
        print()

        for i, test in enumerate(tests, 1):
            print(f"[{i}/{len(tests)}] {test.category}/{test.name}...", end=" ", flush=True)

            passed = False
            details = {}

            # Debug logging: Save test start
            if self.debug and self.debug_dir:
                test_log_file = self.debug_dir / f"test_{i:03d}_{test.category}_{test.name}.json"
                test_log = {
                    "test_number": i,
                    "test_name": test.name,
                    "category": test.category,
                    "weight": test.weight,
                    "attempts": [],
                }

            for attempt in range(self.retries):
                try:
                    passed, details = await asyncio.wait_for(
                        test.run(self.client),
                        timeout=self.timeout,
                    )
                    if self.debug and self.debug_dir:
                        test_log["attempts"].append({
                            "attempt": attempt + 1,
                            "passed": passed,
                            "details": details,
                        })
                    if passed:
                        break
                except asyncio.TimeoutError:
                    details = {"error": "Timeout"}
                    if self.debug and self.debug_dir:
                        test_log["attempts"].append({
                            "attempt": attempt + 1,
                            "passed": False,
                            "error": "Timeout",
                        })
                except Exception as e:
                    details = {"error": str(e)}
                    if self.debug and self.debug_dir:
                        test_log["attempts"].append({
                            "attempt": attempt + 1,
                            "passed": False,
                            "error": str(e),
                            "traceback": __import__("traceback").format_exc(),
                        })

                if attempt < self.retries - 1:
                    print("(retry)", end=" ", flush=True)

            status = "PASS" if passed else "FAIL"
            print(status)

            # Debug logging: Save test result
            if self.debug and self.debug_dir:
                test_log["final_result"] = {
                    "passed": passed,
                    "details": details,
                }
                with open(test_log_file, "w") as f:
                    json.dump(test_log, f, indent=2)

            if self.verbose and not passed:
                error = details.get("error", "Unknown error")
                print(f"      Error: {error[:80]}")

            # Record result
            test_results.append({
                "name": test.name,
                "category": test.category,
                "passed": passed,
                "details": details,
                "weight": test.weight,
            })

            # Track by category
            if test.category not in category_results:
                category_results[test.category] = []
            category_results[test.category].append((passed, test.weight))

        # Calculate scores
        total_weight = sum(t.weight for t in tests)
        passed_weight = sum(r["weight"] for r in test_results if r["passed"])
        overall_score = (passed_weight / total_weight * 100) if total_weight > 0 else 0

        category_scores = {}
        for category, results in category_results.items():
            cat_total = sum(w for _, w in results)
            cat_passed = sum(w for p, w in results if p)
            category_scores[category] = (cat_passed / cat_total * 100) if cat_total > 0 else 0

        duration = time.time() - start_time

        # Debug logging: Create summary file
        if self.debug and self.debug_dir:
            summary = {
                "provider": self.provider,
                "model": self.model,
                "timestamp": datetime.utcnow().isoformat(),
                "overall_score": overall_score,
                "tests_passed": sum(1 for r in test_results if r["passed"]),
                "tests_total": len(test_results),
                "duration_seconds": duration,
                "category_scores": category_scores,
                "failed_tests": [
                    {
                        "name": r["name"],
                        "category": r["category"],
                        "error": r["details"].get("error", "Unknown"),
                        "log_file": f"test_{i+1:03d}_{r['category']}_{r['name']}.json"
                    }
                    for i, r in enumerate(test_results) if not r["passed"]
                ],
                "debug_directory": str(self.debug_dir),
            }
            summary_file = self.debug_dir / "SUMMARY.json"
            with open(summary_file, "w") as f:
                json.dump(summary, f, indent=2)
            print(f"\nDebug logs saved to: {self.debug_dir}")
            print(f"Summary: {summary_file}")

        # Get SDK versions and model fingerprint
        sdk_versions = self._get_sdk_versions()
        model_fingerprint = self._compute_model_fingerprint()

        return BenchmarkResult(
            provider=self.provider,
            model=self.model,
            timestamp=datetime.utcnow().isoformat(),
            overall_score=overall_score,
            tests_passed=sum(1 for r in test_results if r["passed"]),
            tests_total=len(test_results),
            duration_seconds=duration,
            category_scores=category_scores,
            test_results=test_results,
            metadata={
                "runner": "engine",
                "timeout": self.timeout,
                "retries": self.retries,
                "sdk_versions": sdk_versions,
                "model_fingerprint": model_fingerprint,
                "tool_calling_method": self._detect_tool_calling_method(),
            },
        )
