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
"""

import json
import re
from typing import Callable, Any
from dataclasses import dataclass


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
    }
]


# =============================================================================
# CATEGORY: Tool Calling
# =============================================================================

async def test_simple_tool_call(client) -> tuple[bool, dict]:
    """Test basic single tool invocation."""
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
    if call.get("function", {}).get("name") != "read_file":
        return False, {"error": f"Wrong tool: {call.get('function', {}).get('name')}", "expected": "read_file"}

    try:
        args = json.loads(call["function"]["arguments"])
        if args.get("path") == "/src/main.py":
            return True, {"tool": "read_file", "args": args}
        return False, {"error": f"Wrong path: {args.get('path')}", "expected": "/src/main.py"}
    except json.JSONDecodeError as e:
        return False, {"error": f"Invalid JSON arguments: {e}"}


async def test_tool_call_with_complex_args(client) -> tuple[bool, dict]:
    """Test tool call with multiple arguments."""
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
    if call.get("function", {}).get("name") != "write_file":
        return False, {"error": f"Wrong tool: {call.get('function', {}).get('name')}"}

    try:
        args = json.loads(call["function"]["arguments"])
        if "path" in args and "content" in args:
            return True, {"tool": "write_file", "args": args}
        return False, {"error": "Missing required arguments", "args": args}
    except json.JSONDecodeError as e:
        return False, {"error": f"Invalid JSON arguments: {e}"}


async def test_tool_call_large_payload(client) -> tuple[bool, dict]:
    """Test tool call with large JSON payload (tests truncation issues)."""
    # Generate a large but valid code block
    large_content = "def function_{i}():\n    '''Function {i} docstring.'''\n    return {i}\n\n" * 50

    response = await client.chat(
        messages=[
            {"role": "system", "content": "You are a coding assistant. Use tools when asked. Call tools directly without explanation."},
            {"role": "user", "content": f"Write this code to /src/functions.py:\n\n```python\n{large_content}```"}
        ],
        tools=TOOLS,
    )

    tool_calls = response.get("tool_calls", [])
    if not tool_calls:
        # Check for truncated tool call in content
        content = response.get("content", "")
        if "write_file" in content.lower() or "```json" in content:
            return False, {"error": "Tool call appears in content instead of tool_calls (truncation?)", "content_preview": content[:500]}
        return False, {"error": "No tool call made", "response": content[:200]}

    call = tool_calls[0]
    try:
        args = json.loads(call["function"]["arguments"])
        content_len = len(args.get("content", ""))
        if content_len < len(large_content) * 0.8:  # Allow some formatting changes
            return False, {"error": f"Content truncated: got {content_len} chars, expected ~{len(large_content)}"}
        return True, {"content_length": content_len}
    except json.JSONDecodeError as e:
        return False, {"error": f"Invalid JSON (likely truncated): {e}"}


async def test_multi_tool_sequence(client) -> tuple[bool, dict]:
    """Test multi-turn tool usage with dependencies."""
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
        return False, {"error": "No tool call in second turn", "response": response2.get("content", "")[:200]}

    call2 = tool_calls2[0]
    if call2.get("function", {}).get("name") != "read_file":
        return False, {"error": f"Wrong tool in second turn: {call2.get('function', {}).get('name')}"}

    try:
        args = json.loads(call2["function"]["arguments"])
        if "main.py" in args.get("path", ""):
            return True, {"sequence": ["read_file config.json", "read_file main.py"]}
        return False, {"error": f"Didn't use info from first tool: {args}"}
    except json.JSONDecodeError as e:
        return False, {"error": f"Invalid JSON: {e}"}


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
    """Test that tool calls don't appear as JSON in content (GPT-OSS failure mode)."""
    response = await client.chat(
        messages=[
            {"role": "system", "content": "You are a coding assistant. Use the provided tools."},
            {"role": "user", "content": "Search for 'TODO' comments in the /src directory"}
        ],
        tools=TOOLS,
    )

    content = response.get("content", "")
    tool_calls = response.get("tool_calls", [])

    # Check for JSON tool call in content
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

    return True, {"tool_calls": len(tool_calls)}


# =============================================================================
# CATEGORY: Code Editing
# =============================================================================

async def test_apply_patch_simple(client) -> tuple[bool, dict]:
    """Test simple apply_patch with exact content."""
    original_code = '''def hello():
    print("Hello")

def main():
    hello()
'''

    response = await client.chat(
        messages=[
            {"role": "system", "content": "You are a coding assistant. Use apply_patch to modify files."},
            {"role": "user", "content": f"Here is /src/hello.py:\n```python\n{original_code}```\n\nChange 'Hello' to 'Hello, World!' using apply_patch."}
        ],
        tools=TOOLS,
    )

    tool_calls = response.get("tool_calls", [])
    if not tool_calls:
        return False, {"error": "No tool call made"}

    call = tool_calls[0]
    if call.get("function", {}).get("name") != "apply_patch":
        return False, {"error": f"Wrong tool: {call.get('function', {}).get('name')}"}

    try:
        args = json.loads(call["function"]["arguments"])
        patch = args.get("patch", "")

        # Validate patch structure
        if "Hello" not in patch or "Hello, World!" not in patch:
            return False, {"error": "Patch doesn't contain expected changes", "patch": patch[:200]}

        # Check for unified diff markers
        if not any(marker in patch for marker in ["@@", "---", "+++"]):
            return False, {"error": "Not a valid unified diff format", "patch": patch[:200]}

        return True, {"patch_length": len(patch)}
    except json.JSONDecodeError as e:
        return False, {"error": f"Invalid JSON: {e}"}


async def test_apply_patch_indentation(client) -> tuple[bool, dict]:
    """Test apply_patch preserves Python indentation correctly."""
    original_code = '''class Calculator:
    def __init__(self):
        self.value = 0

    def add(self, n):
        self.value += n
        return self

    def result(self):
        return self.value
'''

    response = await client.chat(
        messages=[
            {"role": "system", "content": "You are a coding assistant. Use apply_patch for code changes. Preserve exact indentation."},
            {"role": "user", "content": f"Here is /src/calc.py:\n```python\n{original_code}```\n\nAdd a 'subtract' method after 'add' that subtracts n from self.value."}
        ],
        tools=TOOLS,
    )

    tool_calls = response.get("tool_calls", [])
    if not tool_calls:
        return False, {"error": "No tool call made"}

    call = tool_calls[0]
    try:
        args = json.loads(call["function"]["arguments"])
        patch = args.get("patch", "")

        # Check for proper indentation (4 spaces for class methods)
        if "    def subtract" not in patch:
            # Check for tab or different indentation
            if "\tdef subtract" in patch or "  def subtract" in patch:
                return False, {"error": "Wrong indentation style", "patch_preview": patch[:300]}
            if "def subtract" not in patch:
                return False, {"error": "subtract method not found in patch", "patch_preview": patch[:300]}

        return True, {"patch_length": len(patch)}
    except json.JSONDecodeError as e:
        return False, {"error": f"Invalid JSON: {e}"}


async def test_apply_patch_multiline(client) -> tuple[bool, dict]:
    """Test apply_patch with multi-line additions."""
    original_code = '''import os

def main():
    print("Starting...")
    # TODO: add configuration loading
    print("Done")

if __name__ == "__main__":
    main()
'''

    response = await client.chat(
        messages=[
            {"role": "system", "content": "You are a coding assistant. Use apply_patch for modifications."},
            {"role": "user", "content": f"Here is /src/main.py:\n```python\n{original_code}```\n\nReplace the TODO comment with actual config loading: load from 'config.json' using json.load, store in a 'config' variable, and add the json import at the top."}
        ],
        tools=TOOLS,
    )

    tool_calls = response.get("tool_calls", [])
    if not tool_calls:
        return False, {"error": "No tool call made"}

    call = tool_calls[0]
    try:
        args = json.loads(call["function"]["arguments"])
        patch = args.get("patch", "")

        # Should have import json
        has_import = "import json" in patch or "from json" in patch
        # Should have config loading
        has_config = "config" in patch.lower() and "json" in patch.lower()

        if not has_import:
            return False, {"error": "Missing json import", "patch_preview": patch[:400]}
        if not has_config:
            return False, {"error": "Missing config loading code", "patch_preview": patch[:400]}

        return True, {"patch_length": len(patch)}
    except json.JSONDecodeError as e:
        return False, {"error": f"Invalid JSON: {e}"}


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
# Test Registry
# =============================================================================

ALL_TESTS = [
    # Tool Calling
    TestCase("simple_tool_call", "tool_calling", "Basic single tool invocation", test_simple_tool_call),
    TestCase("complex_args", "tool_calling", "Tool call with multiple arguments", test_tool_call_with_complex_args),
    TestCase("large_payload", "tool_calling", "Tool call with large JSON (truncation test)", test_tool_call_large_payload, weight=1.5, tags=["gpt-oss"]),
    TestCase("multi_tool_sequence", "tool_calling", "Multi-turn tool usage with dependencies", test_multi_tool_sequence, weight=1.5),
    TestCase("no_explain_before_tool", "tool_calling", "Calls tool without 'I'll use X' preamble", test_no_explain_before_tool, tags=["gpt-oss"]),
    TestCase("no_json_in_content", "tool_calling", "Tool calls not leaked as JSON in content", test_tool_call_json_in_content, tags=["gpt-oss"]),

    # Code Editing
    TestCase("patch_simple", "code_editing", "Simple apply_patch with exact content", test_apply_patch_simple),
    TestCase("patch_indentation", "code_editing", "apply_patch preserves indentation", test_apply_patch_indentation, weight=1.5),
    TestCase("patch_multiline", "code_editing", "apply_patch with multi-line changes", test_apply_patch_multiline),

    # Format Compliance
    TestCase("json_output", "format_compliance", "Outputs valid JSON when requested", test_json_output_format),
    TestCase("markdown_code_blocks", "format_compliance", "Proper markdown code block formatting", test_markdown_code_blocks),
    TestCase("no_hallucinated_paths", "format_compliance", "Doesn't hallucinate file paths", test_no_hallucinated_paths),

    # Instruction Following
    TestCase("do_not_explain", "instruction_following", "Follows 'do not explain' instruction", test_do_not_explain),
    TestCase("constraint_respect", "instruction_following", "Respects explicit constraints", test_constraint_respect, weight=1.5),
    TestCase("format_specification", "instruction_following", "Follows specific output format", test_format_specification),

    # Reasoning
    TestCase("multi_step_planning", "reasoning", "Plans multi-step tasks", test_multi_step_planning),
    TestCase("dependency_ordering", "reasoning", "Understands task dependencies", test_dependency_ordering),
    TestCase("edge_case_handling", "reasoning", "Recognizes edge cases", test_edge_case_handling),

    # Error Recovery
    TestCase("tool_error_recovery", "error_recovery", "Recovers from tool errors", test_tool_error_recovery),
    TestCase("self_correction", "error_recovery", "Corrects mistakes when pointed out", test_self_correction),
    TestCase("graceful_degradation", "error_recovery", "Handles limited capabilities gracefully", test_graceful_degradation),
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
