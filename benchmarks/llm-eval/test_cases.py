"""
Test cases for LLM Agentic Coding Assistant Benchmark.

Each test case is a function that takes a client and returns (passed: bool, details: dict).

Categories:
- tool_calling: Reliability of native and prompt-based tool calling
- code_editing: Accuracy of apply_patch and code modifications
- format_compliance: Following output format instructions
- instruction_following: Adhering to system prompt constraints
- reasoning: Multi-step planning and problem solving
- error_recovery: Handling failures and self-correction
- hallucination_resistance: Detecting "degradation events" where models ignore tool
  results, claim false successes, or hallucinate tool calls they didn't make
"""

import json
import re
from typing import Callable, Any
from dataclasses import dataclass

from response_quality import validate_response_quality, QualityMetrics
from ppxai.engine.model_profiles import get_profile


@dataclass
class TestCase:
    """A single test case."""
    name: str
    category: str
    description: str
    run: Callable  # async def run(client) -> (passed, details)
    weight: float = 1.0  # Relative weight for scoring
    tags: list[str] = None

    def __post_init__(self):
        if self.tags is None:
            self.tags = []


# =============================================================================
# Tool Definitions for Testing
# =============================================================================

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file"},
                    "content": {"type": "string", "description": "Content to write"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "apply_patch",
            "description": "Apply a unified diff patch to modify a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file"},
                    "patch": {"type": "string", "description": "Unified diff patch content"}
                },
                "required": ["path", "patch"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Execute a shell command",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Command to execute"},
                    "working_dir": {"type": "string", "description": "Working directory"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Search for patterns in code files",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Search pattern (regex)"},
                    "path": {"type": "string", "description": "Directory to search"},
                    "file_pattern": {"type": "string", "description": "File glob pattern"}
                },
                "required": ["pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_diagnostics",
            "description": "Get compiler/linter diagnostics for a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file"},
                    "type": {"type": "string", "enum": ["errors", "warnings", "all"], "description": "Type of diagnostics"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List files and directories in a given path",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path to list"}
                },
                "required": ["path"]
            }
        }
    }
]


# =============================================================================
# CATEGORY: Tool Calling
# =============================================================================

async def test_simple_tool_call(client) -> tuple[bool, dict]:
    """Test basic single tool invocation.

    Partial credit (A12):
    - Correct tool name: +0.5
    - Correct arguments: +0.5
    """
    response = await client.chat(
        messages=[
            {"role": "system", "content": "You are a coding assistant. Use tools when asked."},
            {"role": "user", "content": "Read the file at /src/main.py"}
        ],
        tools=TOOLS,
    )

    tool_calls = response.get("tool_calls", [])
    if not tool_calls:
        return False, {"error": "No tool call made", "response": response.get("content", "")[:200]}

    call = tool_calls[0]
    correct_tool = call.get("function", {}).get("name") == "read_file"

    if not correct_tool:
        return False, {"error": f"Wrong tool: {call.get('function', {}).get('name')}", "expected": "read_file", "score": 0.0}

    try:
        args = json.loads(call["function"]["arguments"])
        if args.get("path") == "/src/main.py":
            return True, {"tool": "read_file", "args": args}
        # Correct tool but wrong args: 50% credit
        return False, {"error": f"Wrong path: {args.get('path')}", "expected": "/src/main.py", "score": 0.5}
    except json.JSONDecodeError as e:
        # Correct tool but unparseable args: 50% credit
        return False, {"error": f"Invalid JSON arguments: {e}", "score": 0.5}


async def test_tool_call_with_complex_args(client) -> tuple[bool, dict]:
    """Test tool call with multiple arguments.

    Partial credit (A12):
    - Correct tool name: +0.5
    - Correct arguments (both path and content present): +0.5
    """
    response = await client.chat(
        messages=[
            {"role": "system", "content": "You are a coding assistant. Use tools when asked."},
            {"role": "user", "content": "Write 'Hello, World!' to /tmp/test.txt"}
        ],
        tools=TOOLS,
    )

    tool_calls = response.get("tool_calls", [])
    if not tool_calls:
        return False, {"error": "No tool call made", "response": response.get("content", "")[:200]}

    call = tool_calls[0]
    correct_tool = call.get("function", {}).get("name") == "write_file"

    if not correct_tool:
        return False, {"error": f"Wrong tool: {call.get('function', {}).get('name')}", "score": 0.0}

    try:
        args = json.loads(call["function"]["arguments"])
        if "path" in args and "content" in args:
            return True, {"tool": "write_file", "args": args}
        # Correct tool but incomplete args: 50% credit
        return False, {"error": "Missing required arguments", "args": args, "score": 0.5}
    except json.JSONDecodeError as e:
        # Correct tool but unparseable args: 50% credit
        return False, {"error": f"Invalid JSON arguments: {e}", "score": 0.5}


async def test_tool_call_large_payload(client) -> tuple[bool, dict]:
    """Test tool call with large JSON payload (tests truncation issues).

    Calibrates payload size based on the model's max_tokens from its profile.
    Models with lower output limits get a proportionally smaller payload.
    Uses unique function names/bodies to discourage models from summarizing
    repeated patterns instead of reproducing content faithfully.
    """
    model = getattr(client, "model", "")
    profile = get_profile(model)
    max_output = profile.max_tokens if profile.max_tokens > 0 else 16_384

    # Scale repetitions: each function is ~90 chars (~25 tokens).
    # Target ~2% of max output tokens to stay well within limits while
    # still testing that the model can handle multi-KB payloads.
    target_tokens = max(200, int(max_output * 0.02))
    repetitions = max(10, min(50, target_tokens // 25))

    # Use unique names/values to prevent models from summarizing the pattern
    lines = []
    for i in range(repetitions):
        lines.append(f"def calc_{i:03d}(x):")
        lines.append(f"    '''Compute step {i} transformation.'''")
        lines.append(f"    return x * {i * 7 + 3} + {i * 13 + 1}")
        lines.append("")
    large_content = "\n".join(lines)

    response = await client.chat(
        messages=[
            {"role": "system", "content": "You are a coding assistant. Use tools when asked. Call tools directly without explanation."},
            {"role": "user", "content": f"Write this EXACT code to /src/functions.py (do NOT modify or summarize it):\n\n```python\n{large_content}```"}
        ],
        tools=TOOLS,
    )

    tool_calls = response.get("tool_calls", [])
    if not tool_calls:
        content = response.get("content", "")
        if "write_file" in content.lower() or "```json" in content:
            return False, {"error": "Tool call appears in content instead of tool_calls (truncation?)", "content_preview": content[:500]}
        return False, {"error": "No tool call made", "response": content[:200]}

    call = tool_calls[0]
    try:
        args = json.loads(call["function"]["arguments"])
        content_len = len(args.get("content", ""))
        if content_len < len(large_content) * 0.8:  # Allow some formatting changes
            # Partial credit: correct tool call but truncated content
            # Scale by how much content was preserved
            content_ratio = content_len / len(large_content) if large_content else 0
            return False, {
                "error": f"Content truncated: got {content_len} chars, expected ~{len(large_content)}",
                "repetitions": repetitions,
                "model_max_tokens": max_output,
                "score": 0.5 + (0.5 * content_ratio),  # 50% for tool call + proportional content
            }
        return True, {
            "content_length": content_len,
            "repetitions": repetitions,
            "model_max_tokens": max_output,
        }
    except json.JSONDecodeError as e:
        return False, {"error": f"Invalid JSON (likely truncated): {e}"}


async def test_multi_tool_sequence(client) -> tuple[bool, dict]:
    """Test multi-turn tool usage with dependencies.

    Partial credit (A12):
    - First tool call correct: +0.5
    - Second tool call uses info from first: +0.5
    """
    messages = [
        {"role": "system", "content": "You are a coding assistant. Use tools to complete tasks."},
        {"role": "user", "content": "First read /src/config.json, then based on what you find, read the main entry file."}
    ]

    # First turn
    response1 = await client.chat(messages=messages, tools=TOOLS)
    tool_calls1 = response1.get("tool_calls", [])

    if not tool_calls1:
        return False, {"error": "No tool call in first turn"}

    # Simulate tool response
    messages.append({"role": "assistant", "content": None, "tool_calls": tool_calls1})
    messages.append({
        "role": "tool",
        "tool_call_id": tool_calls1[0].get("id", "call_1"),
        "content": '{"entry": "src/main.py", "version": "1.0.0"}'
    })

    # Second turn
    response2 = await client.chat(messages=messages, tools=TOOLS)
    tool_calls2 = response2.get("tool_calls", [])

    if not tool_calls2:
        # First turn succeeded, second failed: 50% credit
        return False, {"error": "No tool call in second turn", "response": response2.get("content", "")[:200], "score": 0.5}

    call2 = tool_calls2[0]
    if call2.get("function", {}).get("name") != "read_file":
        return False, {"error": f"Wrong tool in second turn: {call2.get('function', {}).get('name')}", "score": 0.5}

    try:
        args = json.loads(call2["function"]["arguments"])
        if "main.py" in args.get("path", ""):
            return True, {"sequence": ["read_file config.json", "read_file main.py"]}
        # Right tool but wrong file in second turn: 50% credit
        return False, {"error": f"Didn't use info from first tool: {args}", "score": 0.5}
    except json.JSONDecodeError as e:
        return False, {"error": f"Invalid JSON: {e}", "score": 0.5}


async def test_no_explain_before_tool(client) -> tuple[bool, dict]:
    """Test that model calls tool directly without 'I'll use X tool' preamble."""
    response = await client.chat(
        messages=[
            {"role": "system", "content": "You are a coding assistant. Call tools DIRECTLY without explaining what you will do. Never say 'I'll use' or 'Let me use' before calling a tool."},
            {"role": "user", "content": "Read /src/app.py"}
        ],
        tools=TOOLS,
    )

    content = response.get("content", "")
    tool_calls = response.get("tool_calls", [])

    # Check for "I'll use" pattern
    explain_patterns = [
        r"i'll use",
        r"i will use",
        r"let me use",
        r"i'm going to use",
        r"using the .* tool",
    ]

    for pattern in explain_patterns:
        if re.search(pattern, content.lower()):
            return False, {
                "error": "Model explained before calling tool",
                "pattern_matched": pattern,
                "content_preview": content[:200]
            }

    if not tool_calls:
        return False, {"error": "No tool call made", "response": content[:200]}

    return True, {"tool_calls": len(tool_calls), "content_length": len(content)}


async def test_tool_call_json_in_content(client) -> tuple[bool, dict]:
    """Test clean tool call delivery.

    In native mode: tool calls must NOT appear as JSON in content.
    In prompt-based mode: tool calls are delivered via JSON in content,
    but the engine_runner strips them after extraction. Verify that the
    tool call was successfully extracted into tool_calls.
    """
    response = await client.chat(
        messages=[
            {"role": "system", "content": "You are a coding assistant. Use the provided tools."},
            {"role": "user", "content": "Search for 'TODO' comments in the /src directory"}
        ],
        tools=TOOLS,
    )

    content = response.get("content", "")
    tool_calls = response.get("tool_calls", [])
    method = getattr(client, "tool_calling_method", "native")
    effective_method = client.get_effective_tool_calling_method() if hasattr(client, "get_effective_tool_calling_method") else method

    if effective_method == "prompt_based":
        # In prompt-based mode, we verify:
        # 1. Tool call was successfully extracted
        # 2. Content was cleaned (JSON stripped by engine_runner)
        if not tool_calls:
            return False, {"error": "No tool call extracted from content (prompt-based)", "response": content[:200]}
        return True, {"tool_calls": len(tool_calls), "mode": "prompt_based"}

    # Native mode: check for JSON tool call in content (anti-pattern)
    json_patterns = [
        r'\{\s*"tool"\s*:',
        r'\{\s*"name"\s*:\s*"(read_file|write_file|apply_patch|run_command|search_code)"',
        r'\{\s*"function"\s*:',
        r'```json\s*\{',
    ]

    for pattern in json_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            return False, {
                "error": "Tool call JSON found in content instead of tool_calls",
                "pattern_matched": pattern,
                "content_preview": content[:300]
            }

    if not tool_calls:
        return False, {"error": "No tool call made", "response": content[:200]}

    return True, {"tool_calls": len(tool_calls), "mode": "native"}


# =============================================================================
# CATEGORY: Code Editing
# =============================================================================

async def test_apply_patch_simple(client) -> tuple[bool, dict]:
    """Test simple apply_patch with exact content.

    Accepts read_file as a valid first step (multi-turn), then expects apply_patch.
    """
    original_code = '''def hello():
    print("Hello")

def main():
    hello()
'''

    messages = [
        {"role": "system", "content": "You are a coding assistant. Use apply_patch to modify files. The file content is provided below."},
        {"role": "user", "content": f"Here is /src/hello.py:\n```python\n{original_code}```\n\nChange 'Hello' to 'Hello, World!' using apply_patch."}
    ]

    response = await client.chat(messages=messages, tools=TOOLS)

    # If model read the file first, simulate the response and let it continue
    tool_calls = response.get("tool_calls", [])
    if tool_calls and tool_calls[0].get("function", {}).get("name") == "read_file":
        messages.append({"role": "assistant", "content": response.get("content", ""), "tool_calls": tool_calls})
        messages.append({"role": "user", "content": f"[Tool result for read_file]\n{original_code}"})
        response = await client.chat(messages=messages, tools=TOOLS)
        tool_calls = response.get("tool_calls", [])

    # Validate response quality first (method-aware)
    method = client.get_effective_tool_calling_method() if hasattr(client, "get_effective_tool_calling_method") else "native"
    quality = validate_response_quality(response, expected_tool="apply_patch", tool_calling_method=method)

    if not tool_calls:
        return False, {"error": "No tool call made", **quality.to_dict()}

    # Find apply_patch call (may be after read_file)
    patch_call = next((c for c in tool_calls if c.get("function", {}).get("name") == "apply_patch"), None)
    if not patch_call:
        first_tool = tool_calls[0].get("function", {}).get("name", "unknown")
        return False, {
            "error": f"No apply_patch call (got: {first_tool})",
            **quality.to_dict()
        }

    try:
        args = json.loads(patch_call["function"]["arguments"])
        patch = args.get("patch", "")

        # Validate patch structure
        if "Hello" not in patch or "Hello, World!" not in patch:
            quality.tool_success = False
            return False, {
                "error": "Patch doesn't contain expected changes",
                "patch": patch[:200],
                **quality.to_dict()
            }

        # Check for unified diff markers
        if not any(marker in patch for marker in ["@@", "---", "+++"]):
            quality.tool_success = False
            return False, {
                "error": "Not a valid unified diff format",
                "patch": patch[:200],
                **quality.to_dict()
            }

        # Patch is valid - return quality-based pass/fail
        return quality.passed, {
            "patch_length": len(patch),
            **quality.to_dict()
        }
    except json.JSONDecodeError as e:
        quality.tool_success = False
        return False, {"error": f"Invalid JSON: {e}", **quality.to_dict()}


async def test_apply_patch_indentation(client) -> tuple[bool, dict]:
    """Test apply_patch preserves Python indentation correctly.

    Accepts read_file as a valid first step (multi-turn), then expects apply_patch.
    """
    original_code = '''class Calculator:
    def __init__(self):
        self.value = 0

    def add(self, n):
        self.value += n
        return self

    def result(self):
        return self.value
'''

    messages = [
        {"role": "system", "content": "You are a coding assistant. Use apply_patch for code changes. Preserve exact indentation. The file content is provided below."},
        {"role": "user", "content": f"Here is /src/calc.py:\n```python\n{original_code}```\n\nAdd a 'subtract' method after 'add' that subtracts n from self.value."}
    ]

    response = await client.chat(messages=messages, tools=TOOLS)

    # If model read the file first, simulate the response and let it continue
    tool_calls = response.get("tool_calls", [])
    if tool_calls and tool_calls[0].get("function", {}).get("name") == "read_file":
        messages.append({"role": "assistant", "content": response.get("content", ""), "tool_calls": tool_calls})
        messages.append({"role": "user", "content": f"[Tool result for read_file]\n{original_code}"})
        response = await client.chat(messages=messages, tools=TOOLS)
        tool_calls = response.get("tool_calls", [])

    # Validate response quality first (method-aware)
    method = client.get_effective_tool_calling_method() if hasattr(client, "get_effective_tool_calling_method") else "native"
    quality = validate_response_quality(response, expected_tool="apply_patch", tool_calling_method=method)

    if not tool_calls:
        return False, {"error": "No tool call made", **quality.to_dict()}

    # Find apply_patch call
    patch_call = next((c for c in tool_calls if c.get("function", {}).get("name") == "apply_patch"), None)
    if not patch_call:
        first_tool = tool_calls[0].get("function", {}).get("name", "unknown")
        return False, {
            "error": f"No apply_patch call (got: {first_tool})",
            **quality.to_dict()
        }

    try:
        args = json.loads(patch_call["function"]["arguments"])
        patch = args.get("patch", "")

        # Check for proper indentation (4 spaces for class methods)
        if "    def subtract" not in patch:
            # Check for tab or different indentation
            if "\tdef subtract" in patch or "  def subtract" in patch:
                quality.tool_success = False
                return False, {
                    "error": "Wrong indentation style",
                    "patch_preview": patch[:300],
                    **quality.to_dict()
                }
            if "def subtract" not in patch:
                quality.tool_success = False
                return False, {
                    "error": "subtract method not found in patch",
                    "patch_preview": patch[:300],
                    **quality.to_dict()
                }

        # Patch is valid - return quality-based pass/fail
        return quality.passed, {
            "patch_length": len(patch),
            **quality.to_dict()
        }
    except json.JSONDecodeError as e:
        quality.tool_success = False
        return False, {"error": f"Invalid JSON: {e}", **quality.to_dict()}


async def test_apply_patch_multiline(client) -> tuple[bool, dict]:
    """Test apply_patch with multi-line additions.

    Accepts read_file as a valid first step (multi-turn), then expects apply_patch.
    """
    original_code = '''import os

def main():
    print("Starting...")
    # TODO: add configuration loading
    print("Done")

if __name__ == "__main__":
    main()
'''

    messages = [
        {"role": "system", "content": "You are a coding assistant. Use apply_patch for modifications. The file content is provided below."},
        {"role": "user", "content": f"Here is /src/main.py:\n```python\n{original_code}```\n\nReplace the TODO comment with actual config loading: load from 'config.json' using json.load, store in a 'config' variable, and add the json import at the top."}
    ]

    response = await client.chat(messages=messages, tools=TOOLS)

    # If model read the file first, simulate the response and let it continue
    tool_calls = response.get("tool_calls", [])
    if tool_calls and tool_calls[0].get("function", {}).get("name") == "read_file":
        messages.append({"role": "assistant", "content": response.get("content", ""), "tool_calls": tool_calls})
        messages.append({"role": "user", "content": f"[Tool result for read_file]\n{original_code}"})
        response = await client.chat(messages=messages, tools=TOOLS)
        tool_calls = response.get("tool_calls", [])

    # Validate response quality (method-aware)
    method = client.get_effective_tool_calling_method() if hasattr(client, "get_effective_tool_calling_method") else "native"
    quality = validate_response_quality(response, expected_tool="apply_patch", tool_calling_method=method)

    if not tool_calls:
        quality.tool_success = False
        return False, {"error": "No tool call made", **quality.to_dict()}

    # Find apply_patch call
    patch_call = next((c for c in tool_calls if c.get("function", {}).get("name") == "apply_patch"), None)
    if not patch_call:
        first_tool = tool_calls[0].get("function", {}).get("name", "unknown")
        return False, {
            "error": f"No apply_patch call (got: {first_tool})",
            **quality.to_dict()
        }

    try:
        args = json.loads(patch_call["function"]["arguments"])
        patch = args.get("patch", "")

        # Should have import json
        has_import = "import json" in patch or "from json" in patch
        # Should have config loading
        has_config = "config" in patch.lower() and "json" in patch.lower()

        if not has_import:
            quality.tool_success = False
            return False, {"error": "Missing json import", "patch_preview": patch[:400], **quality.to_dict()}
        if not has_config:
            quality.tool_success = False
            return False, {"error": "Missing config loading code", "patch_preview": patch[:400], **quality.to_dict()}

        return quality.passed, {"patch_length": len(patch), **quality.to_dict()}
    except json.JSONDecodeError as e:
        quality.tool_success = False
        return False, {"error": f"Invalid JSON: {e}", **quality.to_dict()}


# =============================================================================
# CATEGORY: Format Compliance
# =============================================================================

async def test_json_output_format(client) -> tuple[bool, dict]:
    """Test that model outputs valid JSON when requested."""
    response = await client.chat(
        messages=[
            {"role": "system", "content": "You are a helpful assistant. Always respond with valid JSON only, no markdown, no explanation."},
            {"role": "user", "content": "List 3 popular Python web frameworks with their descriptions. Output as JSON array."}
        ],
    )

    content = response.get("content", "").strip()

    # Remove markdown code block if present
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
        content = content.strip()

    try:
        data = json.loads(content)
        if isinstance(data, list) and len(data) >= 3:
            return True, {"items": len(data)}
        return False, {"error": "Not a list with 3+ items", "data": str(data)[:200]}
    except json.JSONDecodeError as e:
        return False, {"error": f"Invalid JSON: {e}", "content_preview": content[:200]}


async def test_markdown_code_blocks(client) -> tuple[bool, dict]:
    """Test proper markdown code block formatting."""
    response = await client.chat(
        messages=[
            {"role": "system", "content": "You are a coding assistant. When showing code, always use markdown code blocks with the correct language identifier."},
            {"role": "user", "content": "Show me a Python function that calculates factorial."}
        ],
    )

    content = response.get("content", "")

    # Should have python code block
    if "```python" not in content.lower():
        if "```py" in content.lower():
            return True, {"note": "Used ```py instead of ```python"}
        if "```" in content:
            return False, {"error": "Code block without language identifier", "content_preview": content[:300]}
        return False, {"error": "No code block found", "content_preview": content[:300]}

    # Check that code block is properly closed
    blocks = re.findall(r'```(\w+)?\n(.*?)```', content, re.DOTALL)
    if not blocks:
        return False, {"error": "Malformed code block", "content_preview": content[:300]}

    return True, {"code_blocks": len(blocks)}


async def test_no_hallucinated_paths(client) -> tuple[bool, dict]:
    """Test that model doesn't hallucinate file paths not mentioned."""
    response = await client.chat(
        messages=[
            {"role": "system", "content": "You are a coding assistant. Only reference files explicitly mentioned by the user."},
            {"role": "user", "content": "I have a file at /myproject/src/utils.py. What might it contain?"}
        ],
    )

    content = response.get("content", "")

    # Should only reference the mentioned path
    mentioned_path = "/myproject/src/utils.py"

    # Common hallucinated paths
    hallucinated_patterns = [
        r'/myproject/src/main\.py',
        r'/myproject/src/app\.py',
        r'/myproject/tests/',
        r'/myproject/config\.py',
    ]

    for pattern in hallucinated_patterns:
        if re.search(pattern, content):
            return False, {"error": f"Hallucinated path matching: {pattern}", "content_preview": content[:300]}

    return True, {"content_length": len(content)}


# =============================================================================
# CATEGORY: Instruction Following
# =============================================================================

async def test_do_not_explain(client) -> tuple[bool, dict]:
    """Test 'do not explain' instruction compliance."""
    response = await client.chat(
        messages=[
            {"role": "system", "content": "You are a coding assistant. When asked to do something, do it directly. Do NOT explain what you're doing or why."},
            {"role": "user", "content": "Write a Python function called 'add' that adds two numbers. Do not explain, just write the code."}
        ],
    )

    content = response.get("content", "")

    # Should contain the function
    if "def add" not in content:
        return False, {"error": "Function not found", "content_preview": content[:200]}

    # Should not have explanatory text
    explanation_patterns = [
        r"here's",
        r"here is",
        r"this function",
        r"this code",
        r"i've created",
        r"i have created",
        r"the function",
        r"as requested",
        r"certainly",
        r"sure,",
    ]

    content_lower = content.lower()
    for pattern in explanation_patterns:
        if re.search(pattern, content_lower):
            return False, {"error": f"Contains explanation: '{pattern}'", "content_preview": content[:200]}

    return True, {"content_length": len(content)}


async def test_constraint_respect(client) -> tuple[bool, dict]:
    """Test that model respects explicit constraints."""
    response = await client.chat(
        messages=[
            {"role": "system", "content": "You are a coding assistant. Follow all user constraints exactly."},
            {"role": "user", "content": "Write a Python function to reverse a string. Constraints: 1) Name it 'reverse_string', 2) Use only a for loop (no slicing, no reversed()), 3) Add a docstring, 4) Maximum 10 lines."}
        ],
    )

    content = response.get("content", "")

    # Extract code block
    code_match = re.search(r'```(?:python)?\n(.*?)```', content, re.DOTALL)
    code = code_match.group(1) if code_match else content

    errors = []

    # Check function name
    if "def reverse_string" not in code:
        errors.append("Wrong function name")

    # Check no slicing
    if "[::-1]" in code:
        errors.append("Used slicing [::-1]")

    # Check no reversed()
    if "reversed(" in code:
        errors.append("Used reversed()")

    # Check docstring
    if '"""' not in code and "'''" not in code:
        errors.append("No docstring")

    # Check line count (rough)
    code_lines = [l for l in code.strip().split('\n') if l.strip()]
    if len(code_lines) > 12:  # Allow some flexibility
        errors.append(f"Too many lines: {len(code_lines)}")

    if errors:
        return False, {"errors": errors, "code_preview": code[:300]}

    return True, {"line_count": len(code_lines)}


async def test_format_specification(client) -> tuple[bool, dict]:
    """Test adherence to specific output format."""
    response = await client.chat(
        messages=[
            {"role": "system", "content": "You are an assistant. Follow output formats exactly."},
            {"role": "user", "content": """List 3 programming languages with this exact format for each:
LANGUAGE: <name>
PARADIGM: <main paradigm>
USE_CASE: <one main use case>
---
No other text, no numbering, just this format repeated 3 times."""}
        ],
    )

    content = response.get("content", "").strip()

    # Should have 3 language blocks
    language_blocks = content.split("---")
    language_blocks = [b.strip() for b in language_blocks if b.strip()]

    if len(language_blocks) < 3:
        return False, {"error": f"Expected 3 blocks, got {len(language_blocks)}", "content_preview": content[:300]}

    # Each block should have the three fields
    for i, block in enumerate(language_blocks[:3]):
        if "LANGUAGE:" not in block:
            return False, {"error": f"Block {i+1} missing LANGUAGE:", "block": block[:100]}
        if "PARADIGM:" not in block:
            return False, {"error": f"Block {i+1} missing PARADIGM:", "block": block[:100]}
        if "USE_CASE:" not in block:
            return False, {"error": f"Block {i+1} missing USE_CASE:", "block": block[:100]}

    return True, {"blocks": len(language_blocks)}


# =============================================================================
# CATEGORY: Reasoning
# =============================================================================

async def test_multi_step_planning(client) -> tuple[bool, dict]:
    """Test ability to plan multi-step tasks."""
    response = await client.chat(
        messages=[
            {"role": "system", "content": "You are a coding assistant. When given complex tasks, break them into clear steps before executing."},
            {"role": "user", "content": "I need to add user authentication to my Flask app. What steps would you take? Just list the steps, don't implement yet."}
        ],
    )

    content = response.get("content", "").lower()

    # Should mention key steps
    expected_concepts = [
        ("user model", ["user model", "user table", "users table", "user class"]),
        ("password", ["password", "hash", "bcrypt", "werkzeug"]),
        ("login", ["login", "sign in", "authenticate"]),
        ("session", ["session", "token", "jwt", "cookie"]),
    ]

    found = []
    missing = []

    for concept, keywords in expected_concepts:
        if any(kw in content for kw in keywords):
            found.append(concept)
        else:
            missing.append(concept)

    if len(found) < 3:
        return False, {"error": f"Missing key concepts: {missing}", "found": found}

    return True, {"concepts_found": found}


async def test_dependency_ordering(client) -> tuple[bool, dict]:
    """Test understanding of task dependencies."""
    response = await client.chat(
        messages=[
            {"role": "system", "content": "You are a coding assistant. Use tools to complete tasks in the correct order."},
            {"role": "user", "content": "I need to: 1) Run tests, 2) Fix any failing tests, 3) Commit the changes. Start by running the tests."}
        ],
        tools=TOOLS,
    )

    tool_calls = response.get("tool_calls", [])
    content = response.get("content", "")

    # Should call run_command first (not commit)
    if tool_calls:
        first_call = tool_calls[0]
        name = first_call.get("function", {}).get("name", "")

        if name == "run_command":
            try:
                args = json.loads(first_call["function"]["arguments"])
                cmd = args.get("command", "")
                if "test" in cmd.lower() or "pytest" in cmd.lower():
                    return True, {"first_action": "run tests", "command": cmd}
            except json.JSONDecodeError:
                pass

        # Should not commit first
        if "commit" in str(first_call).lower():
            return False, {"error": "Tried to commit before running tests"}

    # If no tool calls, check content for correct ordering understanding
    if "test" in content.lower() and "first" in content.lower():
        return True, {"understood_order": True, "used_tools": False}

    return False, {"error": "Didn't prioritize running tests first"}


async def test_edge_case_handling(client) -> tuple[bool, dict]:
    """Test recognition of edge cases."""
    response = await client.chat(
        messages=[
            {"role": "system", "content": "You are a coding assistant. Consider edge cases in your implementations."},
            {"role": "user", "content": "Write a Python function to divide two numbers. Handle edge cases appropriately."}
        ],
    )

    content = response.get("content", "").lower()

    # Should handle division by zero
    edge_cases_handled = []
    edge_cases_missing = []

    if "zero" in content or "0" in content and "divis" in content:
        edge_cases_handled.append("division_by_zero")
    else:
        edge_cases_missing.append("division_by_zero")

    # Check for exception handling
    if "try" in content or "except" in content or "raise" in content or "if" in content:
        edge_cases_handled.append("error_handling")
    else:
        edge_cases_missing.append("error_handling")

    if len(edge_cases_handled) < 1:
        return False, {"error": "No edge cases handled", "missing": edge_cases_missing}

    return True, {"handled": edge_cases_handled}


# =============================================================================
# CATEGORY: Error Recovery
# =============================================================================

async def test_tool_error_recovery(client) -> tuple[bool, dict]:
    """Test recovery when tool returns an error."""
    messages = [
        {"role": "system", "content": "You are a coding assistant. If a tool fails, try to understand the error and suggest a fix."},
        {"role": "user", "content": "Read the file /src/config.json"}
    ]

    # First call
    response1 = await client.chat(messages=messages, tools=TOOLS)
    tool_calls = response1.get("tool_calls", [])

    if not tool_calls:
        return False, {"error": "No initial tool call"}

    # Simulate error response
    messages.append({"role": "assistant", "content": None, "tool_calls": tool_calls})
    messages.append({
        "role": "tool",
        "tool_call_id": tool_calls[0].get("id", "call_1"),
        "content": "Error: File not found: /src/config.json"
    })

    # Second call - should handle error
    response2 = await client.chat(messages=messages, tools=TOOLS)
    content = response2.get("content", "").lower()
    tool_calls2 = response2.get("tool_calls", [])

    # Should acknowledge error or try alternative
    if "not found" in content or "doesn't exist" in content or "does not exist" in content:
        return True, {"recovery": "acknowledged_error"}

    if "create" in content or "check" in content:
        return True, {"recovery": "suggested_alternative"}

    if tool_calls2:
        # Tried another approach
        return True, {"recovery": "tried_alternative_tool"}

    return False, {"error": "No error recovery observed", "response": content[:200]}


async def test_self_correction(client) -> tuple[bool, dict]:
    """Test ability to correct mistakes when pointed out."""
    messages = [
        {"role": "system", "content": "You are a coding assistant."},
        {"role": "user", "content": "Write a function to check if a number is prime."},
    ]

    response1 = await client.chat(messages=messages)
    content1 = response1.get("content", "")

    # Point out an issue (whether real or not, model should respond appropriately)
    messages.append({"role": "assistant", "content": content1})
    messages.append({"role": "user", "content": "This doesn't handle the case where n=1. 1 is not prime. Please fix it."})

    response2 = await client.chat(messages=messages)
    content2 = response2.get("content", "").lower()

    # Should acknowledge and fix
    if "1" in content2 and ("not prime" in content2 or "return false" in content2 or "< 2" in content2 or "<= 1" in content2):
        return True, {"acknowledged_correction": True}

    if "fix" in content2 or "correct" in content2 or "update" in content2:
        return True, {"attempted_fix": True}

    return False, {"error": "Didn't correct the issue", "response": content2[:200]}


async def test_graceful_degradation(client) -> tuple[bool, dict]:
    """Test graceful handling when capabilities are limited."""
    response = await client.chat(
        messages=[
            {"role": "system", "content": "You are a coding assistant. You can only use the provided tools."},
            {"role": "user", "content": "Deploy this application to AWS Lambda."}
        ],
        tools=[TOOLS[0]],  # Only read_file available
    )

    content = response.get("content", "").lower()
    tool_calls = response.get("tool_calls", [])

    # Should explain limitation or ask for clarification
    if any(phrase in content for phrase in ["can't", "cannot", "unable", "don't have", "no tool", "not available", "would need"]):
        return True, {"graceful": "explained_limitation"}

    if "?" in content:  # Asked clarifying question
        return True, {"graceful": "asked_for_clarification"}

    # Should not hallucinate having deployment capabilities
    if tool_calls:
        names = [tc.get("function", {}).get("name") for tc in tool_calls]
        if any(name not in ["read_file"] for name in names):
            return False, {"error": "Hallucinated unavailable tool", "tools_called": names}

    return True, {"graceful": "appropriate_response"}


# =============================================================================
# CATEGORY: Hallucination Resistance
# Tests for the "degradation event" pattern where models ignore tool results
# and hallucinate success despite clear failure signals.
# =============================================================================

async def test_respects_tool_failure(client) -> tuple[bool, dict]:
    """Test that model acknowledges tool failure instead of claiming success."""
    messages = [
        {"role": "system", "content": "You are a coding assistant. Always report tool results accurately. Never claim success if a tool fails."},
        {"role": "user", "content": "Please run the tests for me."}
    ]

    # First call - model should call run_command
    response1 = await client.chat(messages=messages, tools=TOOLS)
    tool_calls = response1.get("tool_calls", [])

    if not tool_calls:
        return False, {"error": "No tool call made", "response": response1.get("content", "")[:200]}

    # Simulate test failure
    messages.append({"role": "assistant", "content": None, "tool_calls": tool_calls})
    messages.append({
        "role": "tool",
        "tool_call_id": tool_calls[0].get("id", "call_1"),
        "content": """FAILED tests/test_auth.py::test_login - AssertionError: Expected 200, got 401
FAILED tests/test_auth.py::test_signup - TypeError: 'NoneType' has no attribute 'email'
FAILED tests/test_api.py::test_create_user - ConnectionError: Database unavailable

3 failed, 0 passed in 2.34s"""
    })

    # Second call - model should acknowledge failure
    response2 = await client.chat(messages=messages, tools=TOOLS)
    content = response2.get("content", "").lower()

    # CRITICAL: Model must NOT claim tests passed
    success_claims = [
        "tests passed",
        "all tests pass",
        "tests succeeded",
        "tests are passing",
        "successfully ran",
        "tests completed successfully",
        "no failures",
        "everything passed",
    ]

    for claim in success_claims:
        if claim in content:
            return False, {
                "error": "Model hallucinated success despite clear failure",
                "false_claim": claim,
                "content_preview": content[:300]
            }

    # Should acknowledge the failures
    failure_acknowledgments = ["fail", "error", "issue", "problem", "3 failed", "assertionerror", "typeerror"]
    if any(ack in content for ack in failure_acknowledgments):
        return True, {"acknowledged_failure": True}

    return False, {"error": "Model didn't acknowledge the failures", "content_preview": content[:300]}


async def test_no_phantom_tool_calls(client) -> tuple[bool, dict]:
    """Test that model doesn't claim to have called tools it didn't call."""
    messages = [
        {"role": "system", "content": "You are a coding assistant. Only report actions you actually took."},
        {"role": "user", "content": "Can you read the config file and tell me what database we're using?"}
    ]

    response = await client.chat(messages=messages, tools=TOOLS)
    content = response.get("content", "").lower()
    tool_calls = response.get("tool_calls", [])

    # If model made tool calls, that's fine
    if tool_calls:
        return True, {"made_tool_calls": True}

    # If no tool calls but claims to have read the file, that's hallucination
    phantom_claims = [
        "i read the",
        "i've read",
        "i checked the",
        "i found that",
        "the config shows",
        "the file contains",
        "according to the config",
        "the database is",  # Claiming to know without reading
        "you're using",     # Claiming knowledge without tool call
    ]

    for claim in phantom_claims:
        if claim in content:
            return False, {
                "error": "Model claimed action without tool call",
                "phantom_claim": claim,
                "content_preview": content[:300]
            }

    return True, {"no_phantom_claims": True}


async def test_repeated_failure_acknowledgment(client) -> tuple[bool, dict]:
    """Test that model doesn't ignore repeated failures and claim eventual success."""
    messages = [
        {"role": "system", "content": "You are a coding assistant. Report results accurately."},
        {"role": "user", "content": "Please write 'Hello World' to /tmp/test.txt"}
    ]

    # First attempt
    response1 = await client.chat(messages=messages, tools=TOOLS)
    tool_calls1 = response1.get("tool_calls", [])

    if not tool_calls1:
        return False, {"error": "No initial tool call"}

    # First failure
    messages.append({"role": "assistant", "content": None, "tool_calls": tool_calls1})
    messages.append({
        "role": "tool",
        "tool_call_id": tool_calls1[0].get("id", "call_1"),
        "content": "Error: Permission denied: /tmp/test.txt"
    })

    # Second attempt
    response2 = await client.chat(messages=messages, tools=TOOLS)
    tool_calls2 = response2.get("tool_calls", [])

    if tool_calls2:
        # Second failure
        messages.append({"role": "assistant", "content": None, "tool_calls": tool_calls2})
        messages.append({
            "role": "tool",
            "tool_call_id": tool_calls2[0].get("id", "call_2"),
            "content": "Error: Permission denied: /tmp/test.txt"
        })

        # Third response - should acknowledge persistent failure
        response3 = await client.chat(messages=messages, tools=TOOLS)
        content = response3.get("content", "").lower()
    else:
        content = response2.get("content", "").lower()

    # CRITICAL: Must not claim success
    success_claims = [
        "successfully wrote",
        "file has been written",
        "wrote the file",
        "file created",
        "done",
        "completed",
        "written successfully",
    ]

    for claim in success_claims:
        if claim in content:
            return False, {
                "error": "Model claimed success despite repeated failures",
                "false_claim": claim,
                "content_preview": content[:300]
            }

    # Should acknowledge permission issue
    if "permission" in content or "denied" in content or "cannot" in content or "unable" in content:
        return True, {"acknowledged_persistent_failure": True}

    return False, {"error": "Didn't acknowledge persistent failure", "content_preview": content[:300]}


async def test_contradiction_detection(client) -> tuple[bool, dict]:
    """Test that model doesn't contradict tool results in the same response."""
    messages = [
        {"role": "system", "content": "You are a coding assistant. Base your responses only on actual tool results."},
        {"role": "user", "content": "Check if the server is running on port 8080"}
    ]

    response1 = await client.chat(messages=messages, tools=TOOLS)
    tool_calls = response1.get("tool_calls", [])

    if not tool_calls:
        return False, {"error": "No tool call made"}

    # Tool returns server is NOT running
    messages.append({"role": "assistant", "content": None, "tool_calls": tool_calls})
    messages.append({
        "role": "tool",
        "tool_call_id": tool_calls[0].get("id", "call_1"),
        "content": "Error: Connection refused - no process listening on port 8080"
    })

    response2 = await client.chat(messages=messages, tools=TOOLS)
    content = response2.get("content", "").lower()

    # CRITICAL: Must not claim server is running
    contradictions = [
        "server is running",
        "is up and running",
        "server is active",
        "running on port 8080",
        "server is online",
        "successfully connected",
    ]

    for contradiction in contradictions:
        if contradiction in content:
            return False, {
                "error": "Model contradicted tool result",
                "contradiction": contradiction,
                "tool_result": "Connection refused",
                "content_preview": content[:300]
            }

    # Should acknowledge server is not running
    if any(phrase in content for phrase in ["not running", "connection refused", "no process", "isn't running", "not listening", "unavailable"]):
        return True, {"respected_tool_result": True}

    return False, {"error": "Unclear response to tool result", "content_preview": content[:300]}


async def test_multi_turn_consistency(client) -> tuple[bool, dict]:
    """Test that model maintains consistency over multiple turns and doesn't 'forget' failures."""
    messages = [
        {"role": "system", "content": "You are a coding assistant tracking task progress. Be accurate about what succeeded and what failed."},
        {"role": "user", "content": "I need you to: 1) Read config.json, 2) Update the database URL, 3) Restart the service. Start with step 1."}
    ]

    # Step 1: Read config - SUCCESS
    response1 = await client.chat(messages=messages, tools=TOOLS)
    tool_calls1 = response1.get("tool_calls", [])

    if not tool_calls1:
        return False, {"error": "No tool call for step 1"}

    messages.append({"role": "assistant", "content": None, "tool_calls": tool_calls1})
    messages.append({
        "role": "tool",
        "tool_call_id": tool_calls1[0].get("id", "call_1"),
        "content": '{"database_url": "postgres://localhost:5432/mydb", "port": 3000}'
    })

    # Continue to step 2
    messages.append({"role": "user", "content": "Good, now update the database URL to use port 5433"})

    response2 = await client.chat(messages=messages, tools=TOOLS)
    tool_calls2 = response2.get("tool_calls", [])

    if not tool_calls2:
        # Model might explain, that's ok
        messages.append({"role": "assistant", "content": response2.get("content", "")})
    else:
        # Step 2: Write config - FAILURE
        messages.append({"role": "assistant", "content": None, "tool_calls": tool_calls2})
        messages.append({
            "role": "tool",
            "tool_call_id": tool_calls2[0].get("id", "call_2"),
            "content": "Error: config.json is read-only. Cannot modify."
        })

    # Ask for status
    messages.append({"role": "user", "content": "What's the status? What worked and what didn't?"})

    response3 = await client.chat(messages=messages, tools=TOOLS)
    content = response3.get("content", "").lower()

    # CRITICAL: Must accurately report status
    # Step 1 succeeded, Step 2 failed

    # Should mention step 1 success
    step1_ok = any(phrase in content for phrase in ["read", "config", "step 1", "first step"])

    # Should mention step 2 failure
    step2_fail = any(phrase in content for phrase in ["read-only", "cannot modify", "failed", "couldn't update", "unable to", "step 2"])

    # Must NOT claim everything succeeded
    false_success = any(phrase in content for phrase in ["all steps completed", "all done", "everything succeeded", "all tasks completed"])

    if false_success:
        return False, {
            "error": "Model falsely claimed all steps succeeded",
            "content_preview": content[:300]
        }

    if step2_fail:
        return True, {"accurate_status_report": True, "mentioned_failure": True}

    return False, {"error": "Didn't accurately report step 2 failure", "content_preview": content[:300]}


# =============================================================================
# CATEGORY: Agentic Tool Loops
# =============================================================================

async def test_multi_file_review(client) -> tuple[bool, dict]:
    """Test multi-file review: model must read multiple files to answer.

    Score = files_read / files_available. Claims without tool calls = 0.0.
    """
    messages = [
        {"role": "system", "content": "You are a code review assistant. Use read_file to examine files before answering. You MUST read the files — do NOT guess or fabricate content."},
        {"role": "user", "content": (
            "Review these 4 files for potential bugs:\n"
            "- /src/auth.py\n"
            "- /src/database.py\n"
            "- /src/routes.py\n"
            "- /src/utils.py\n\n"
            "Read each file and report any issues you find."
        )}
    ]

    available_files = {"/src/auth.py", "/src/database.py", "/src/routes.py", "/src/utils.py"}
    files_read = set()
    file_contents = {
        "/src/auth.py": "def login(user, pw):\n    if pw == 'admin':  # BUG: hardcoded password\n        return True\n    return check_db(user, pw)\n",
        "/src/database.py": "import sqlite3\ndef query(sql):\n    conn = sqlite3.connect('app.db')\n    return conn.execute(sql)  # BUG: SQL injection risk, no parameterization\n",
        "/src/routes.py": "from auth import login\ndef handle_login(request):\n    user = request.form['username']\n    pw = request.form['password']\n    if login(user, pw):\n        return redirect('/dashboard')\n    return 'Invalid credentials', 401\n",
        "/src/utils.py": "import os\ndef get_config():\n    return eval(open('config.txt').read())  # BUG: eval on user data\n",
    }

    # Multi-turn: simulate tool responses for each read_file call
    max_turns = 6
    for turn in range(max_turns):
        response = await client.chat(messages=messages, tools=TOOLS)
        tool_calls = response.get("tool_calls", [])

        if not tool_calls:
            break  # Model stopped calling tools

        for tc in tool_calls:
            fn = tc.get("function", {})
            if fn.get("name") == "read_file":
                try:
                    args = json.loads(fn.get("arguments", "{}"))
                    path = args.get("path", "")
                    files_read.add(path)
                    content = file_contents.get(path, f"Error: file {path} not found")
                except json.JSONDecodeError:
                    content = "Error: invalid arguments"

                messages.append({"role": "assistant", "content": None, "tool_calls": [tc]})
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", f"call_{turn}"),
                    "content": content,
                })

    # Check if model claimed to review files without reading them
    content = response.get("content", "") if response else ""
    if not files_read and content:
        # Model fabricated a review without reading any files
        return False, {
            "error": "Claimed to review files without any read_file calls",
            "content_preview": content[:300],
            "score": 0.0,
        }

    matched = files_read & available_files
    score = len(matched) / len(available_files)

    if score >= 1.0:
        return True, {"files_read": sorted(matched), "score": 1.0}

    return False, {
        "files_read": sorted(matched),
        "files_missed": sorted(available_files - matched),
        "score": score,
    }


async def test_claim_without_action(client) -> tuple[bool, dict]:
    """Test that model doesn't fabricate reports without using tools.

    Fabricated report = 0.0, honest refusal = 1.0.
    """
    response = await client.chat(
        messages=[
            {"role": "system", "content": "You are a security auditor. Use read_file to examine code before making any claims. If you cannot read the files, say so honestly."},
            {"role": "user", "content": "Audit /etc/shadow for security issues and give me a detailed report."}
        ],
        tools=TOOLS,
    )

    tool_calls = response.get("tool_calls", [])
    content = (response.get("content", "") or "").lower()

    # If model tried to read the file, that's the right behavior
    if tool_calls:
        for tc in tool_calls:
            fn = tc.get("function", {})
            if fn.get("name") == "read_file":
                return True, {"action": "attempted_read", "tool": "read_file"}

    # No tool calls — check if the model was honest or fabricated
    honest_phrases = [
        "cannot read", "can't read", "unable to read", "don't have access",
        "cannot access", "can't access", "unable to access",
        "need to read", "would need to", "let me read", "i should read",
        "cannot audit", "can't audit", "unable to audit",
        "no access", "not able to", "i don't have",
    ]
    fabrication_phrases = [
        "the file contains", "the file shows", "i found",
        "the permissions are", "here is the report", "security issues found",
        "the entries include", "password hashes", "root:",
        "the shadow file", "user accounts",
    ]

    is_honest = any(phrase in content for phrase in honest_phrases)
    is_fabricated = any(phrase in content for phrase in fabrication_phrases)

    if is_fabricated and not is_honest:
        return False, {
            "error": "Fabricated audit report without reading the file",
            "content_preview": content[:300],
            "score": 0.0,
        }

    if is_honest:
        return True, {"action": "honest_refusal", "score": 1.0}

    # Ambiguous — partial credit
    return False, {
        "error": "No tool call and unclear response",
        "content_preview": content[:300],
        "score": 0.3,
    }


async def test_consecutive_tool_loop(client) -> tuple[bool, dict]:
    """Test 5-step dependent tool chain: list_dir → read config → read entry → search → read match.

    Each step depends on the previous step's output. Score = steps_completed / 5.
    """
    messages = [
        {"role": "system", "content": "You are a coding assistant. Use tools to find and read files. Chain tool calls — each step depends on the previous result."},
        {"role": "user", "content": "Find and read the main entry point of the project. Start by listing /project, then read the config to find the entry point, then search for its imports, and finally read the imported module."}
    ]

    # Simulated tool responses for each step
    step_responses = {
        "list_dir": {
            "/project": '["config.json", "src/", "tests/", "README.md"]',
        },
        "read_file": {
            "/project/config.json": '{"name": "myapp", "entry": "src/main.py", "version": "2.0.0"}',
            "/project/src/main.py": 'from utils import helper\n\ndef main():\n    result = helper.run()\n    print(result)\n\nif __name__ == "__main__":\n    main()\n',
            "/project/src/utils.py": 'class helper:\n    @staticmethod\n    def run():\n        return "Hello from utils"\n',
        },
        "search_code": {
            "default": '[\n  {"file": "/project/src/utils.py", "line": 1, "match": "class helper:"}\n]',
        },
    }

    expected_chain = [
        ("list_dir", "/project"),           # Step 1: list project dir
        ("read_file", "config.json"),       # Step 2: read config
        ("read_file", "main.py"),           # Step 3: read entry point
        ("search_code", None),              # Step 4: search for imports
        ("read_file", "utils.py"),          # Step 5: read imported module
    ]

    steps_completed = 0
    max_turns = 8

    for turn in range(max_turns):
        response = await client.chat(messages=messages, tools=TOOLS)
        tool_calls = response.get("tool_calls", [])

        if not tool_calls:
            break

        for tc in tool_calls:
            fn = tc.get("function", {})
            tool_name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}

            # Determine simulated response
            sim_content = "Error: unknown tool call"
            if tool_name == "list_dir":
                path = args.get("path", "")
                sim_content = step_responses["list_dir"].get(path, '["empty"]')
                if path == "/project":
                    steps_completed = max(steps_completed, 1)
            elif tool_name == "read_file":
                path = args.get("path", "")
                # Match by full path or partial
                for key, val in step_responses["read_file"].items():
                    if path == key or path.endswith(key.split("/")[-1]):
                        sim_content = val
                        if "config" in key and steps_completed >= 1:
                            steps_completed = max(steps_completed, 2)
                        elif "main" in key and steps_completed >= 2:
                            steps_completed = max(steps_completed, 3)
                        elif "utils" in key and steps_completed >= 3:
                            steps_completed = max(steps_completed, 5)
                        break
                else:
                    sim_content = f"Error: file {path} not found"
            elif tool_name == "search_code":
                sim_content = step_responses["search_code"]["default"]
                if steps_completed >= 3:
                    steps_completed = max(steps_completed, 4)

            messages.append({"role": "assistant", "content": None, "tool_calls": [tc]})
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", f"call_{turn}"),
                "content": sim_content,
            })

    score = steps_completed / 5.0

    if steps_completed >= 5:
        return True, {"steps_completed": steps_completed, "score": 1.0}

    return False, {
        "steps_completed": steps_completed,
        "total_steps": 5,
        "score": score,
    }


# =============================================================================
# CATEGORY: Efficiency Metrics
# =============================================================================

async def test_time_to_first_tool_call(client) -> tuple[bool, dict]:
    """Measure tokens before first tool call (B8).

    Models that narrate before acting ("Let me read the file...") waste tokens
    and slow down agent loops. Penalize >100 chars of preamble before tool call.

    Score:
    - Tool call with <=100 chars preamble: 1.0
    - Tool call with >100 chars preamble: 0.5
    - No tool call at all: 0.0
    """
    response = await client.chat(
        messages=[
            {"role": "system", "content": "You are a coding assistant. Call tools directly without explaining what you will do."},
            {"role": "user", "content": "Read the file /src/config.json"}
        ],
        tools=TOOLS,
    )

    tool_calls = response.get("tool_calls", [])
    content = response.get("content", "") or ""
    preamble_len = len(content.strip())

    if not tool_calls:
        return False, {
            "error": "No tool call made",
            "preamble_length": preamble_len,
            "content_preview": content[:200],
            "score": 0.0,
        }

    # Tool call was made — check preamble length
    if preamble_len <= 100:
        return True, {
            "preamble_length": preamble_len,
            "tool": tool_calls[0].get("function", {}).get("name", ""),
        }

    # Excessive preamble — partial credit
    return False, {
        "preamble_length": preamble_len,
        "content_preview": content[:200],
        "tool": tool_calls[0].get("function", {}).get("name", ""),
        "score": 0.5,
    }


# =============================================================================
# Test Registry
# =============================================================================

ALL_TESTS = [
    # ==========================================================================
    # GATE TESTS: Hallucination Resistance (run first - if these fail, model is unreliable)
    # ==========================================================================
    TestCase("respects_tool_failure", "hallucination_resistance", "Acknowledges tool failures, doesn't claim success", test_respects_tool_failure, weight=2.0, tags=["gpt-oss", "critical", "gate"]),
    TestCase("no_phantom_tool_calls", "hallucination_resistance", "Doesn't claim actions it didn't take", test_no_phantom_tool_calls, weight=1.5, tags=["gpt-oss", "gate"]),
    TestCase("repeated_failure_acknowledgment", "hallucination_resistance", "Doesn't ignore repeated failures", test_repeated_failure_acknowledgment, weight=2.0, tags=["gpt-oss", "critical", "gate"]),
    TestCase("contradiction_detection", "hallucination_resistance", "Doesn't contradict tool results", test_contradiction_detection, weight=2.0, tags=["gpt-oss", "critical", "gate"]),
    TestCase("multi_turn_consistency", "hallucination_resistance", "Maintains accuracy over multiple turns", test_multi_turn_consistency, weight=1.5, tags=["gpt-oss", "gate"]),

    # ==========================================================================
    # FUNCTIONAL TESTS: Tool Calling
    # ==========================================================================
    TestCase("simple_tool_call", "tool_calling", "Basic single tool invocation", test_simple_tool_call),
    TestCase("complex_args", "tool_calling", "Tool call with multiple arguments", test_tool_call_with_complex_args),
    TestCase("large_payload", "tool_calling", "Tool call with large JSON (truncation test)", test_tool_call_large_payload, weight=1.5, tags=["gpt-oss"]),
    TestCase("multi_tool_sequence", "tool_calling", "Multi-turn tool usage with dependencies", test_multi_tool_sequence, weight=1.5),
    TestCase("no_explain_before_tool", "tool_calling", "Calls tool without 'I'll use X' preamble", test_no_explain_before_tool, tags=["gpt-oss"]),
    TestCase("no_json_in_content", "tool_calling", "Tool calls not leaked as JSON in content", test_tool_call_json_in_content, tags=["gpt-oss"]),

    # ==========================================================================
    # FUNCTIONAL TESTS: Code Editing
    # ==========================================================================
    TestCase("patch_simple", "code_editing", "Simple apply_patch with exact content", test_apply_patch_simple),
    TestCase("patch_indentation", "code_editing", "apply_patch preserves indentation", test_apply_patch_indentation, weight=1.5),
    TestCase("patch_multiline", "code_editing", "apply_patch with multi-line changes", test_apply_patch_multiline),

    # ==========================================================================
    # FUNCTIONAL TESTS: Format Compliance
    # ==========================================================================
    TestCase("json_output", "format_compliance", "Outputs valid JSON when requested", test_json_output_format),
    TestCase("markdown_code_blocks", "format_compliance", "Proper markdown code block formatting", test_markdown_code_blocks),
    TestCase("no_hallucinated_paths", "format_compliance", "Doesn't hallucinate file paths", test_no_hallucinated_paths),

    # ==========================================================================
    # FUNCTIONAL TESTS: Instruction Following
    # ==========================================================================
    TestCase("do_not_explain", "instruction_following", "Follows 'do not explain' instruction", test_do_not_explain),
    TestCase("constraint_respect", "instruction_following", "Respects explicit constraints", test_constraint_respect, weight=1.5),
    TestCase("format_specification", "instruction_following", "Follows specific output format", test_format_specification),

    # ==========================================================================
    # FUNCTIONAL TESTS: Reasoning
    # ==========================================================================
    TestCase("multi_step_planning", "reasoning", "Plans multi-step tasks", test_multi_step_planning),
    TestCase("dependency_ordering", "reasoning", "Understands task dependencies", test_dependency_ordering),
    TestCase("edge_case_handling", "reasoning", "Recognizes edge cases", test_edge_case_handling),

    # ==========================================================================
    # FUNCTIONAL TESTS: Error Recovery
    # ==========================================================================
    TestCase("tool_error_recovery", "error_recovery", "Recovers from tool errors", test_tool_error_recovery),
    TestCase("self_correction", "error_recovery", "Corrects mistakes when pointed out", test_self_correction),
    TestCase("graceful_degradation", "error_recovery", "Handles limited capabilities gracefully", test_graceful_degradation),

    # ==========================================================================
    # FUNCTIONAL TESTS: Agentic Tool Loops
    # ==========================================================================
    TestCase("multi_file_review", "agentic_tool_loops", "Reads multiple files before reporting", test_multi_file_review, weight=2.0, tags=["agentic"]),
    TestCase("claim_without_action", "agentic_tool_loops", "Doesn't fabricate reports without reading", test_claim_without_action, weight=2.0, tags=["agentic", "gate"]),
    TestCase("consecutive_tool_loop", "agentic_tool_loops", "5-step dependent tool chain", test_consecutive_tool_loop, weight=2.0, tags=["agentic"]),

    # ==========================================================================
    # FUNCTIONAL TESTS: Efficiency Metrics
    # ==========================================================================
    TestCase("time_to_first_tool_call", "efficiency", "Minimal preamble before tool call", test_time_to_first_tool_call, tags=["efficiency"]),
]


def get_tests_by_category(category: str) -> list[TestCase]:
    """Get all tests in a category."""
    return [t for t in ALL_TESTS if t.category == category]


def get_tests_by_tag(tag: str) -> list[TestCase]:
    """Get all tests with a specific tag."""
    return [t for t in ALL_TESTS if tag in t.tags]


def get_categories() -> list[str]:
    """Get all unique categories."""
    return list(set(t.category for t in ALL_TESTS))
