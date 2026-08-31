"""
Engine-based benchmark runner using ppxai's EngineClient.

This runner uses the ppxai Engine layer instead of direct OpenAI API calls,
enabling benchmarking of all providers through their native implementations
(Perplexity, Gemini, OpenAI, vLLM/GPT-OSS, etc.).
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
        tool_calling_method: str = "auto",
        skip_agents_md: bool = False,
    ):
        self.provider = provider
        self.model = model
        self.verbose = verbose
        self.debug = debug
        self.debug_dir = debug_dir
        self.tool_calling_method = tool_calling_method
        self.skip_agents_md = skip_agents_md
        self._client: Optional[EngineClient] = None
        self._initialized = False
        self._request_count = 0
        self._response_samples = []  # For model fingerprinting
        # Per-chat() call counters, reset each call
        self._turn_tokens = 0
        self._turn_tool_calls = 0
        # Cumulative counters across all chat() calls
        self.total_tokens = 0
        self.total_tool_calls = 0

    def get_effective_tool_calling_method(self) -> str:
        """Return the resolved tool calling method ("native" or "prompt_based").

        Resolves "auto" to the actual method based on provider capabilities.
        Test cases can use this to adapt validation logic.
        """
        if self.tool_calling_method in ("native", "prompt_based"):
            return self.tool_calling_method
        # auto: resolve based on _use_native_tools()
        return "native" if self._use_native_tools() else "prompt_based"

    def _use_native_tools(self) -> bool:
        """Check if the provider supports native tool calling.

        Respects the --tool-calling-method override:
        - "native": Force native tool calling regardless of provider caps
        - "prompt_based": Force prompt-based, never send native tools
        - "auto": Detect from provider capabilities (original behavior)
        """
        if self.tool_calling_method == "native":
            return True
        if self.tool_calling_method == "prompt_based":
            return False
        # auto: ask the provider's per-model facts (ADR 0012).
        #
        # This branch used to call `get_capabilities_for_model()` and read
        # `capabilities.native_tool_calling` — BOTH DELETED by ADR 0012 W1.
        # `hasattr` was False and `getattr(..., False)` swallowed the rest, so
        # the branch silently returned False for every model and every `auto`
        # run measured prompt-based tool calling regardless of the model's
        # real capability. Found 2026-08-31; see debt Item 55.
        if not self._client or not self._client.provider:
            return False
        provider = self._client.provider
        if hasattr(provider, "get_facts_for_model"):
            return provider.get_facts_for_model(self.model).tool_mode != "prompt_based"
        return False

    async def initialize(self) -> bool:
        """Initialize the EngineClient with provider and model."""
        try:
            self._client = EngineClient()

            # Load AGENTS.md from all scopes (global ~/.ppxai/, project root, cwd)
            # Use the same merged loading as the real ppxai client (v1.14.2)
            # Skip when running in "without AGENTS.md" mode for delta testing.
            project_root = Path(__file__).parent.parent.parent
            self._client.context_injector.working_dir = str(project_root)
            if self.skip_agents_md:
                if self.verbose:
                    print("  [INFO] Skipping AGENTS.md loading (--agents-md without)")
            else:
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

            # NOTE: We intentionally do NOT call self._client.enable_tools().
            # Engine tools (read_file(filepath), apply_patch(file_path, unified_diff))
            # conflict with benchmark tools (read_file(path), apply_patch(path, patch)).
            # Instead, we pass benchmark tools directly to the provider in chat().

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
        Send chat completion request by calling the provider directly.

        Bypasses the engine's tool execution pipeline so that benchmark tools
        (read_file(path), apply_patch(path, patch)) are the ONLY tools the model
        sees — no conflict with engine's built-in tools.

        For native tool calling providers: benchmark tools are passed as the
        `tools=` parameter to provider.chat().
        For prompt-based providers: benchmark tools are injected as text in the
        system prompt.
        """
        if not self._initialized:
            if not await self.initialize():
                return {"content": "", "tool_calls": [], "error": "Client not initialized"}

        # Reset per-turn counters
        self._turn_tokens = 0
        self._turn_tool_calls = 0

        # Build message list from benchmark format
        use_native = self._use_native_tools()

        system_content = ""
        user_messages = []

        for msg in messages:
            if msg["role"] == "system":
                system_content = msg["content"]
            else:
                user_messages.append(msg)

        # Build Message objects for the provider
        provider_messages = []

        # System message: AGENTS.md hints (provider + model) + test system prompt.
        #
        # HISTORY: commit d334453 (2026-02-19) switched this runner from calling
        # `self._client.chat()` to calling `self._client.provider.chat()` directly,
        # to avoid engine-registered tools (read_file(filepath)) colliding with
        # benchmark tools (read_file(path)) on parameter names. That fix was
        # necessary for Codex scoring (37.5% → 64.1%) but had a hidden side
        # effect: by bypassing `engine/chat.py` it also bypassed the
        # `ctx.get_bootstrap_prompt()` injection that puts AGENTS.md hints into
        # the system message. From 2026-02-19 until this fix, every benchmark
        # run was measured against a 103-char adversarial system prompt with
        # NO AGENTS.md hints — regardless of --agents-md=with/without — making
        # the A/B delta pure noise and making the shipped stub hints untestable.
        #
        # FIX: explicitly call `get_bootstrap_prompt()` (which reads the
        # already-loaded bootstrap context resolved for this provider/model)
        # and prepend it to the system message. Keeps the direct `provider.chat()`
        # call (preserving d334453's tool-isolation fix) while restoring the
        # hint-injection signal that commit accidentally broke.
        #
        # In --agents-md=without mode, initialize() skipped load_bootstrap_context,
        # so get_bootstrap_prompt() returns "" and only the test system prompt
        # is sent. The A/B delta is restored to measure real hint effect.
        bootstrap_prompt = ""
        if self._client is not None:
            try:
                bootstrap_prompt = self._client.get_bootstrap_prompt() or ""
            except Exception as exc:
                if self.verbose:
                    print(f"  [WARN] get_bootstrap_prompt failed: {exc}")
                bootstrap_prompt = ""

        if bootstrap_prompt and system_content:
            full_system = f"{bootstrap_prompt}\n\n---\n\n{system_content}"
        elif bootstrap_prompt:
            full_system = bootstrap_prompt
        else:
            full_system = system_content

        if full_system:
            provider_messages.append(Message(role="system", content=full_system))

        # Add conversation history (excluding last message).
        # Collapse assistant(tool_calls) + tool(result) pairs into a single
        # user message "Tool result: ..." to maintain strict user/assistant
        # alternation required by Perplexity and other providers.
        history = user_messages[:-1] if user_messages else []
        i = 0
        while i < len(history):
            msg = history[i]
            role = msg["role"]
            content = msg.get("content") or ""

            if role == "assistant" and msg.get("tool_calls"):
                # Assistant made tool call(s) — collect the following tool result(s)
                tool_results = []
                if content:
                    tool_results.append(content)
                j = i + 1
                while j < len(history) and history[j]["role"] == "tool":
                    tool_results.append(f"[Tool result]: {history[j].get('content', '')}")
                    j += 1
                # Present as assistant action + user-role tool results
                if tool_results:
                    # The assistant's action (tool call) is implicit.
                    # Present tool results as a user message so alternation holds.
                    provider_messages.append(Message(
                        role="user",
                        content="\n\n".join(tool_results),
                    ))
                i = j
                continue

            if role == "tool":
                # Orphan tool result (no preceding assistant) — wrap as user
                provider_messages.append(Message(role="user", content=f"[Tool result]: {content}"))
            else:
                provider_messages.append(Message(role=role, content=content))
            i += 1

        # Get the last user message
        last_message = ""
        if user_messages:
            last_msg = user_messages[-1]
            if last_msg["role"] == "user":
                last_message = last_msg["content"]
            elif last_msg["role"] == "tool":
                tool_result = last_msg.get("content", "")
                last_message = f"[Tool result]: {tool_result}\n\nContinue based on the tool result above."
            else:
                last_message = last_msg.get("content", "")

        if not last_message:
            return {"content": "", "tool_calls": [], "error": "No user message to send"}

        # Inject tool definitions into user message text (always, as fallback).
        # Even with native tools, the text prompt ensures models that don't reliably
        # use native function calls can still output JSON tool calls in content.
        if tools:
            tool_prompt = self._build_tool_prompt(tools)
            last_message = f"{tool_prompt}\n\nUser request: {last_message}"

        provider_messages.append(Message(role="user", content=last_message))

        # Deduplicate consecutive same-role messages (merge into one).
        # Run AFTER all messages are built (including the last user message)
        # to ensure no consecutive same-role messages slip through.
        if provider_messages:
            merged = [provider_messages[0]]
            for pm in provider_messages[1:]:
                if pm.role == merged[-1].role:
                    merged[-1] = Message(role=pm.role, content=merged[-1].content + "\n\n" + pm.content)
                else:
                    merged.append(pm)
            provider_messages = merged

        # Prepare native tools for the provider (if supported)
        native_tools = tools if (tools and use_native) else None

        # Result container
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
                "use_native_tools": use_native,
                # v1.17.4 post-regression fix: debug logs now capture the FULL
                # system message (bootstrap hints + test prompt) and each
                # component's length separately, so you can see at a glance
                # whether AGENTS.md hints reached the provider.
                "system_prompt_length": len(system_content),
                "bootstrap_prompt_length": len(bootstrap_prompt),
                "full_system_prompt_length": len(full_system),
                "full_system_prompt": full_system,
            }

        try:
            # Call provider directly — no engine tool execution pipeline
            async for event in self._client.provider.chat(
                provider_messages, self.model, stream=False, tools=native_tools
            ):
                if self.verbose:
                    print(f"  [DEBUG] Event: {event.type} - {str(event.data)[:100]}")

                if event.type == EventType.STREAM_END:
                    result["content"] = event.data or ""

                elif event.type == EventType.STREAM_CHUNK:
                    result["content"] += event.data or ""

                elif event.type == EventType.TOOL_CALL:
                    self._turn_tool_calls += 1
                    # Provider detected a native tool call — capture it, don't execute
                    tool_data = event.data
                    if isinstance(tool_data, dict):
                        tool_call = {
                            "id": tool_data.get("tool_call_id", tool_data.get("id", f"call_{len(result['tool_calls'])}")),
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

            # Fallback: extract tool calls from content (prompt-based mode)
            if not result["tool_calls"] and result["content"]:
                extracted = self._extract_tool_calls_from_content(result["content"], tools)
                if extracted:
                    result["tool_calls"] = extracted
                    result["finish_reason"] = "tool_calls"
                    # Strip extracted tool JSON from content so downstream
                    # validators don't penalize expected prompt-based behavior
                    result["content"] = self._strip_tool_json_from_content(result["content"])

            # Also count tool calls extracted from content (prompt-based)
            if result["tool_calls"]:
                # Native tool calls already counted via TOOL_CALL events.
                # For prompt-based extraction, count if _turn_tool_calls is still 0.
                if self._turn_tool_calls == 0:
                    self._turn_tool_calls = len(result["tool_calls"])

            # Update cumulative counters
            self.total_tokens += self._turn_tokens
            self.total_tool_calls += self._turn_tool_calls

            # Attach per-turn stats to result
            result["tokens_used"] = self._turn_tokens
            result["tool_calls_made"] = self._turn_tool_calls

            # Collect response samples for model fingerprinting (first 3 only)
            if len(self._response_samples) < 3 and result["content"]:
                self._response_samples.append(result["content"][:500])

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
        instead of using native tool calling. Uses brace-counting to handle
        nested JSON (e.g., apply_patch with unified diff content).
        """
        tool_calls = []
        tool_names = set()

        if tools:
            for tool in tools:
                if tool.get("type") == "function":
                    name = tool.get("function", {}).get("name", "")
                    if name:
                        tool_names.add(name)

        # Extract JSON objects using brace-counting (handles nested braces)
        json_objects = self._find_json_objects(content)

        for obj in json_objects:
            # Pattern 1: {"tool": "name", "arguments": {...}}
            if "tool" in obj and "arguments" in obj:
                tool_name = obj["tool"]
                args = obj["arguments"]
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"raw": args}
                if not tool_names or tool_name in tool_names:
                    tool_calls.append({
                        "id": f"call_{len(tool_calls)}",
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": json.dumps(args) if isinstance(args, dict) else json.dumps({"raw": args}),
                        }
                    })

            # Pattern 2: {"name": "tool_name", "arguments": {...}} (OpenAI-style)
            elif "name" in obj and "arguments" in obj:
                tool_name = obj["name"]
                args = obj["arguments"]
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"raw": args}
                if not tool_names or tool_name in tool_names:
                    tool_calls.append({
                        "id": f"call_{len(tool_calls)}",
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": json.dumps(args) if isinstance(args, dict) else json.dumps({"raw": args}),
                        }
                    })

        return tool_calls

    @staticmethod
    def _strip_tool_json_from_content(content: str) -> str:
        """Strip tool call JSON objects from content text.

        After extracting tool calls from content in prompt-based mode,
        remove the JSON blocks so downstream validators see clean text.
        Only strips objects that look like tool calls (contain "tool"/"name"
        key with "arguments" key). Preserves surrounding text.
        """
        if not content or '{' not in content:
            return content

        spans_to_remove = []
        i = 0
        while i < len(content):
            if content[i] == '{':
                depth = 0
                in_string = False
                escape = False
                start = i
                for j in range(i, len(content)):
                    c = content[j]
                    if escape:
                        escape = False
                        continue
                    if c == '\\' and in_string:
                        escape = True
                        continue
                    if c == '"' and not escape:
                        in_string = not in_string
                        continue
                    if in_string:
                        continue
                    if c == '{':
                        depth += 1
                    elif c == '}':
                        depth -= 1
                        if depth == 0:
                            candidate = content[start:j + 1]
                            try:
                                obj = json.loads(candidate)
                                if isinstance(obj, dict):
                                    has_tool_key = "tool" in obj or "name" in obj
                                    has_args = "arguments" in obj
                                    if has_tool_key and has_args:
                                        spans_to_remove.append((start, j + 1))
                            except json.JSONDecodeError:
                                pass
                            i = j + 1
                            break
                else:
                    i += 1
            else:
                i += 1

        if not spans_to_remove:
            return content

        # Remove spans in reverse order to preserve indices
        result = content
        for start, end in reversed(spans_to_remove):
            pre = result[:start].rstrip()
            post = result[end:].lstrip()
            # Strip surrounding markdown code fences
            if pre.endswith('```json') or pre.endswith('```'):
                fence_start = pre.rfind('```')
                pre = pre[:fence_start].rstrip()
            if post.startswith('```'):
                post = post[3:].lstrip()
            result = pre + '\n' + post

        while '\n\n\n' in result:
            result = result.replace('\n\n\n', '\n\n')

        return result.strip()

    @staticmethod
    def _find_json_objects(text: str) -> list[dict]:
        """Find JSON objects in text using brace-counting.

        Handles nested braces, escaped characters, and string literals.
        """
        objects = []
        i = 0
        while i < len(text):
            if text[i] == '{':
                # Try to find matching closing brace
                depth = 0
                in_string = False
                escape = False
                start = i
                for j in range(i, len(text)):
                    c = text[j]
                    if escape:
                        escape = False
                        continue
                    if c == '\\' and in_string:
                        escape = True
                        continue
                    if c == '"' and not escape:
                        in_string = not in_string
                        continue
                    if in_string:
                        continue
                    if c == '{':
                        depth += 1
                    elif c == '}':
                        depth -= 1
                        if depth == 0:
                            candidate = text[start:j+1]
                            try:
                                obj = json.loads(candidate)
                                if isinstance(obj, dict):
                                    objects.append(obj)
                            except json.JSONDecodeError:
                                pass
                            i = j + 1
                            break
                else:
                    i += 1
            else:
                i += 1
        return objects


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
        tool_calling_method: str = "auto",
        skip_agents_md: bool = False,
    ):
        self.provider = provider
        self.model = model
        self.timeout = timeout
        self.retries = retries
        self.verbose = verbose
        self.debug = debug
        self.tool_calling_method = tool_calling_method
        self.skip_agents_md = skip_agents_md

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
            tool_calling_method=tool_calling_method,
            skip_agents_md=skip_agents_md,
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
        """What the PROVIDER actually did — not what was requested.

        This used to return the `--tool-calling-method` flag verbatim, so a
        run recorded `method=native` whenever native was ASKED FOR, even when
        the provider then declined to attach a tools array. Measured
        2026-08-31 on gpt-5.6-terra: recorded `native`, actually prompt-based,
        because the runner calls `provider.chat()` directly and the provider
        gates the tools array on `ModelFacts.tool_mode` — which the CLI flag
        does not reach.

        A metadata field that reports the request rather than the outcome
        makes every historical comparison unfalsifiable: two runs labelled
        `native` may have exercised different code paths. So the provider's
        own resolution wins, and the request is recorded beside it when they
        disagree.
        """
        requested = self.tool_calling_method
        actual = None
        try:
            provider = self.client._client.provider if self.client._client else None
            if provider is not None and hasattr(provider, "get_facts_for_model"):
                mode = provider.get_facts_for_model(self.model).tool_mode
                actual = "prompt_based" if mode == "prompt_based" else "native"
        except Exception:  # noqa: BLE001 — never fail a run over metadata
            actual = None

        if actual is None:
            # Cannot resolve the provider's answer; fall back to the request
            # but SAY so rather than presenting it as the outcome.
            return f"{requested}(unverified)" if requested != "auto" else "auto(unverified)"
        if requested in ("native", "prompt_based") and requested != actual:
            return f"{actual}(requested:{requested})"
        return actual

    #: Substrings that mark an INFRASTRUCTURE failure rather than a wrong
    #: answer. A provider 400/401/429 arrives as ordinary event TEXT — nothing
    #: raises — so without this the harness scores "the API refused to talk to
    #: us" identically to "the model answered badly".
    #:
    #: Not hypothetical: 34 historical runs in results/ sit at exactly 0, 8.1
    #: or 10.9 — three discrete floors, not a quality distribution — and
    #: identical models spread up to 89 points across repeat runs. Those are
    #: infrastructure failures wearing a score, and they have been corrupting
    #: comparisons since 2026-02. Measured 2026-08-31 while sizing the Phase C
    #: benchmark; see debt Item 55.
    INFRA_ERROR_MARKERS = (
        "error code: 4",
        "error code: 5",
        "invalid_request_error",
        "authentication",
        "rate limit",
        "insufficient_quota",
        "connection error",
        "timeout",
        "not supported",
        "has reached its end of life",
    )

    @classmethod
    def is_infrastructure_failure(cls, details) -> bool:
        """True when a failed test failed because the API would not serve us.

        Deliberately conservative: it matches the API's own error vocabulary,
        so a model that merely answers badly is never excused. A false
        NEGATIVE costs one mis-scored test; a false POSITIVE would hide a real
        quality regression, which is worse.
        """
        if not isinstance(details, dict):
            return False
        blob = str(details.get("error") or "").lower()
        if not blob:
            return False
        return any(marker in blob for marker in cls.INFRA_ERROR_MARKERS)

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

        #: Tests that failed because the API would not serve us. Kept apart
        #: from scores — see `is_infrastructure_failure`.
        infra_failures: list[dict] = []

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

            # Support partial credit: test can return float score in details
            # True = 1.0, False = 0.0, or details["score"] = 0.0-1.0
            if isinstance(passed, (int, float)) and not isinstance(passed, bool):
                score = float(max(0.0, min(1.0, passed)))
                passed = score > 0.0
            elif passed:
                score = float(details.get("score", 1.0))
            else:
                score = float(details.get("score", 0.0))

            # ADR-adjacent (debt Item 55, 2026-08-31): an infrastructure
            # failure is NOT a score. Counted separately so it can never be
            # averaged into a quality number, and surfaced per test so a
            # contaminated run is visible while it happens rather than
            # inferred from a suspiciously round total afterwards.
            if not passed and self.is_infrastructure_failure(details):
                infra_failures.append(
                    {
                        "test": f"{test.category}/{test.name}",
                        "error": str(details.get("error"))[:200],
                    }
                )

            if score == 1.0:
                status = "PASS"
            elif score > 0.0:
                status = f"PARTIAL ({score:.0%})"
            else:
                status = "FAIL"
            print(status)

            # Debug logging: Save test result
            if self.debug and self.debug_dir:
                test_log["final_result"] = {
                    "passed": passed,
                    "score": score,
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
                "score": score,
                "details": details,
                "weight": test.weight,
            })

            # Track by category
            if test.category not in category_results:
                category_results[test.category] = []
            category_results[test.category].append((score, test.weight))

        # Calculate scores (supports partial credit via score field)
        total_weight = sum(t.weight for t in tests)
        scored_weight = sum(r["score"] * r["weight"] for r in test_results)
        overall_score = (scored_weight / total_weight * 100) if total_weight > 0 else 0

        # FAIL LOUD on a contaminated run (debt Item 55, 2026-08-31).
        #
        # This score is only a QUALITY measurement if every test actually
        # reached the model. When some did not, the number is a blend of
        # quality and availability, and nothing downstream can separate them —
        # which is how 34 runs came to sit at 0 / 8.1 / 10.9 and get compared
        # against real scores for six months.
        #
        # Printed rather than raised: a partial run still carries information
        # for whoever is watching, and killing it would discard the tests that
        # DID reach the model. But it can no longer be read as clean.
        if infra_failures:
            pct = len(infra_failures) / max(len(tests), 1) * 100
            print()
            print("=" * 72)
            print(
                f"  ⚠ CONTAMINATED RUN — {len(infra_failures)}/{len(tests)} tests "
                f"({pct:.0f}%) failed on INFRASTRUCTURE, not quality."
            )
            print(
                f"  overall_score={overall_score:.1f} is NOT a quality measurement "
                "and must not be compared against a clean run."
            )
            for f in infra_failures[:5]:
                print(f"    {f['test']}: {f['error'][:90]}")
            if len(infra_failures) > 5:
                print(f"    ... and {len(infra_failures) - 5} more")
            print("=" * 72)
            print()

        category_scores = {}
        for category, results in category_results.items():
            cat_total = sum(w for _, w in results)
            cat_scored = sum(s * w for s, w in results)
            category_scores[category] = (cat_scored / cat_total * 100) if cat_total > 0 else 0

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
                "total_tokens": self.client.total_tokens,
                "total_tool_calls": self.client.total_tool_calls,
                # Debt Item 55: persisted so a LATER comparison can exclude
                # contaminated runs. Printing the warning helps whoever is
                # watching the run; only the recorded flag helps the person
                # who reads results/ six months later — which is the case
                # that actually went wrong.
                "infrastructure_failures": len(infra_failures),
                "infrastructure_failure_detail": infra_failures[:10],
                "is_clean_run": not infra_failures,
            },
        )
