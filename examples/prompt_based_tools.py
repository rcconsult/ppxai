"""
Prompt-Based Tool Calling with vLLM/GPT-OSS-120B

This approach bypasses vLLM's native tool parsing (which can cause HarmonyError)
by injecting tool definitions into the system prompt and parsing tool calls
from the model's text response.

Why use this approach?
- Avoids HarmonyError: "unexpected tokens remaining in message header"
- Works with any vLLM configuration (with or without --enable-auto-tool-choice)
- Model-agnostic: works with GPT-OSS, Llama, Qwen, etc.

Requirements:
    pip install openai

Usage:
    export VLLM_BASE_URL=http://your-vllm-endpoint:8000/v1
    export VLLM_API_KEY=your-api-key  # or "none" if no auth required
    python prompt_based_tools.py

See also:
    docs/vllm-tool-calling-guide.md - Full documentation on tool calling approaches
"""

import json
import re
import os
from typing import Any, Callable, Optional
from openai import OpenAI

# =============================================================================
# Configuration
# =============================================================================

VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "http://localhost:8000/v1")
VLLM_MODEL = os.getenv("VLLM_MODEL", "openai/gpt-oss-120b")
VLLM_API_KEY = os.getenv("VLLM_API_KEY", "none")

# =============================================================================
# Tool Definitions
# =============================================================================

TOOLS = [
    {
        "name": "get_weather",
        "description": "Get current weather for a location",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "City name, e.g. 'Berlin'"},
            },
            "required": ["location"]
        }
    },
    {
        "name": "read_file",
        "description": "Read contents of a file",
        "parameters": {
            "type": "object",
            "properties": {
                "filepath": {"type": "string", "description": "Path to the file"},
                "max_lines": {"type": "integer", "description": "Max lines to read (optional)"}
            },
            "required": ["filepath"]
        }
    },
    {
        "name": "execute_command",
        "description": "Execute a shell command",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The command to execute"},
            },
            "required": ["command"]
        }
    },
    {
        "name": "web_search",
        "description": "Search the web for information",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "num_results": {"type": "integer", "description": "Number of results (default: 5)"}
            },
            "required": ["query"]
        }
    },
]

# =============================================================================
# Tool Implementations
# =============================================================================

def get_weather(location: str) -> str:
    """Mock weather implementation - replace with real API call."""
    # In production, use a real weather API like OpenWeatherMap
    return f"Weather in {location}: 18°C, partly cloudy, humidity 65%"


def read_file(filepath: str, max_lines: Optional[int] = None) -> str:
    """Read file contents."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            if max_lines:
                lines = lines[:max_lines]
            return ''.join(lines)
    except FileNotFoundError:
        return f"Error: File not found: {filepath}"
    except PermissionError:
        return f"Error: Permission denied: {filepath}"
    except Exception as e:
        return f"Error reading file: {e}"


def execute_command(command: str) -> str:
    """Execute shell command - be careful with this in production!"""
    import subprocess

    # Basic safety check - customize for your environment
    dangerous_patterns = ['rm -rf', 'mkfs', 'dd if=', ':(){', 'fork bomb']
    for pattern in dangerous_patterns:
        if pattern in command.lower():
            return f"Error: Potentially dangerous command blocked: {pattern}"

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=os.getcwd()
        )
        output = result.stdout or result.stderr or "(no output)"
        return output[:4000]  # Truncate long outputs
    except subprocess.TimeoutExpired:
        return "Error: Command timed out after 30 seconds"
    except Exception as e:
        return f"Error: {e}"


def web_search(query: str, num_results: int = 5) -> str:
    """Mock web search - replace with real search API."""
    # In production, use a real search API like SerpAPI, Tavily, or DuckDuckGo
    return f"Search results for '{query}':\n1. Example result 1\n2. Example result 2\n(Mock data - implement real search API)"


TOOL_HANDLERS: dict[str, Callable] = {
    "get_weather": get_weather,
    "read_file": read_file,
    "execute_command": execute_command,
    "web_search": web_search,
}

# =============================================================================
# System Prompt Generation
# =============================================================================

def generate_tool_prompt(tools: list[dict]) -> str:
    """
    Generate system prompt with tool definitions.

    The prompt instructs the model to output tool calls as JSON blocks
    that can be parsed from the response text.
    """
    prompt = """# Tool Usage Instructions

You have access to tools. To use a tool, respond with ONLY a JSON block in this exact format:

```json
{"tool": "tool_name", "arguments": {"param": "value"}}
```

## Available Tools:

"""
    for tool in tools:
        prompt += f"### {tool['name']}\n{tool['description']}\n"
        props = tool['parameters'].get('properties', {})
        required = tool['parameters'].get('required', [])
        if props:
            prompt += "Parameters:\n"
            for param, info in props.items():
                req = "required" if param in required else "optional"
                prompt += f"  - `{param}` ({req}): {info.get('description', '')}\n"
        prompt += "\n"

    prompt += """## Rules:
1. When calling a tool, output ONLY the JSON block - no other text
2. After receiving tool results, continue the conversation or call another tool
3. You CAN access files and run commands - use tools proactively!
4. Complete ALL parts of user requests before giving final response
5. Don't say "I can't access..." - you have tools to do it!
"""
    return prompt

# =============================================================================
# Tool Call Parser (Multi-Strategy)
# =============================================================================

def parse_tool_call(text: str, tools: list[dict]) -> Optional[dict]:
    """
    Parse tool call from model response using multiple strategies.

    This handles various output formats from different models:
    - GPT-OSS: May output nested structures or use different param names
    - Llama/Qwen: Usually cleaner JSON output
    - All models: May wrap JSON in markdown code blocks

    Strategies (in order):
    1. Entire response as JSON
    2. JSON in markdown code blocks
    3. Brace-based extraction (find {"tool" pattern)

    Args:
        text: Model response text
        tools: List of tool definitions

    Returns:
        Dict with 'tool' and 'arguments' keys, or None if no tool call found
    """
    tool_names = {t['name'] for t in tools}

    # Strategy 1: Entire response is JSON
    text_stripped = text.strip()
    if text_stripped.startswith('{') and text_stripped.endswith('}'):
        result = _try_parse_json(text_stripped, tool_names)
        if result:
            return result

    # Strategy 2: JSON in markdown code blocks
    code_block_pattern = r'```(?:json)?\s*([\s\S]*?)```'
    for match in re.findall(code_block_pattern, text):
        match_stripped = match.strip()
        if match_stripped.startswith('{'):
            result = _try_parse_json(match_stripped, tool_names)
            if result:
                return result

    # Strategy 3: Find {"tool" pattern with brace matching
    for pattern in ['{"tool"', "{'tool'"]:
        start_idx = 0
        while True:
            start = text.find(pattern, start_idx)
            if start == -1:
                break

            # Find matching closing brace by counting depth
            depth = 0
            end = start
            for i, char in enumerate(text[start:], start):
                if char == '{':
                    depth += 1
                elif char == '}':
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break

            if depth == 0 and end > start:
                result = _try_parse_json(text[start:end], tool_names)
                if result:
                    return result

            start_idx = end if end > start else start + 1

    return None


def _try_parse_json(json_str: str, tool_names: set) -> Optional[dict]:
    """
    Try to parse JSON and normalize the tool call.

    Handles:
    - Standard JSON
    - Single-quoted JSON (Python dict style)
    - Nested GPT-OSS structures
    - Parameter name aliases
    """
    # Try standard JSON first
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        # Try single quotes -> double quotes (some models output Python dict style)
        try:
            data = json.loads(json_str.replace("'", '"'))
        except json.JSONDecodeError:
            return None

    # Get tool name (support both 'tool' and 'name' keys)
    tool_name = data.get('tool') or data.get('name')
    if not tool_name or tool_name not in tool_names:
        return None

    args = data.get('arguments', {})

    # Handle GPT-OSS nested structure:
    # {"tool": "x", "arguments": {"tool": "x", "arguments": {...}}}
    # This happens when GPT-OSS double-wraps tool calls
    if isinstance(args, dict) and 'tool' in args and 'arguments' in args:
        args = args['arguments']

    # Normalize parameter aliases (different models use different names)
    args = _normalize_params(args)

    return {'tool': tool_name, 'arguments': args}


def _normalize_params(args: dict) -> dict:
    """
    Normalize parameter names to handle model variations.

    Different models may use different parameter names for the same thing:
    - filepath vs file_path vs file vs path
    - command vs cmd vs shell_command
    - query vs search_query
    """
    aliases = {
        # File operations
        'filepath': ['file_path', 'filePath', 'file', 'path'],
        # Shell commands
        'command': ['cmd', 'shell_command'],
        # Weather/location
        'location': ['city', 'place'],
        # Search
        'query': ['search_query', 'query_text'],
        'num_results': ['top_n', 'count', 'limit', 'max_results'],
    }

    normalized = args.copy()
    for canonical, alias_list in aliases.items():
        for alias in alias_list:
            if alias in normalized and canonical not in normalized:
                normalized[canonical] = normalized.pop(alias)
                break

    return normalized

# =============================================================================
# Chat Loop with Tool Execution
# =============================================================================

def chat_with_tools(
    client: OpenAI,
    user_message: str,
    tools: list[dict],
    tool_handlers: dict[str, Callable],
    system_prompt: Optional[str] = None,
    max_iterations: int = 10,
    verbose: bool = True
) -> str:
    """
    Send a message and handle tool calls in a loop.

    This is the main entry point for prompt-based tool calling.

    Args:
        client: OpenAI client configured for vLLM
        user_message: The user's question/request
        tools: List of tool definitions
        tool_handlers: Dict mapping tool names to handler functions
        system_prompt: Optional additional system prompt (appended to tool prompt)
        max_iterations: Max tool call iterations (prevent infinite loops)
        verbose: Print debug info

    Returns:
        Final response text from the model
    """
    # Build messages with tool prompt in system message
    tool_prompt = generate_tool_prompt(tools)
    if system_prompt:
        tool_prompt = tool_prompt + "\n\n" + system_prompt

    messages = [
        {"role": "system", "content": tool_prompt},
        {"role": "user", "content": user_message}
    ]

    for iteration in range(max_iterations):
        if verbose:
            print(f"\n--- Iteration {iteration + 1} ---")

        # Call the model
        # IMPORTANT: No 'tools' parameter - this is prompt-based mode
        # vLLM will not attempt Harmony parsing without the tools parameter
        response = client.chat.completions.create(
            model=VLLM_MODEL,
            messages=messages,
            stream=True,
            max_tokens=4096,
        )

        # Collect streaming response
        full_response = ""
        for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                full_response += content
                if verbose:
                    print(content, end="", flush=True)

        if verbose:
            print()  # Newline after streaming

        # Check for tool call in the response
        tool_call = parse_tool_call(full_response, tools)

        if tool_call:
            tool_name = tool_call['tool']
            tool_args = tool_call['arguments']

            if verbose:
                print(f"\n>> Tool call detected: {tool_name}")
                print(f">> Arguments: {json.dumps(tool_args, indent=2)}")

            # Execute the tool
            handler = tool_handlers.get(tool_name)
            if handler:
                try:
                    result = handler(**tool_args)
                except TypeError as e:
                    result = f"Error: Invalid arguments for {tool_name}: {e}"
                except Exception as e:
                    result = f"Error executing {tool_name}: {e}"
            else:
                result = f"Error: Unknown tool '{tool_name}'"

            if verbose:
                preview = result[:200] + ('...' if len(result) > 200 else '')
                print(f">> Result: {preview}")

            # Add assistant message and tool result to conversation history
            messages.append({"role": "assistant", "content": full_response})
            messages.append({
                "role": "user",
                "content": f"Tool result for {tool_name}:\n{result}"
            })

            continue  # Next iteration - model will process tool result

        # No tool call found - this is the final response
        return full_response

    # Max iterations reached
    if verbose:
        print(f"\n>> Warning: Max iterations ({max_iterations}) reached")
    return full_response

# =============================================================================
# Non-Streaming Version (simpler, for testing)
# =============================================================================

def chat_with_tools_sync(
    client: OpenAI,
    user_message: str,
    tools: list[dict],
    tool_handlers: dict[str, Callable],
    max_iterations: int = 10,
) -> str:
    """Non-streaming version for simpler use cases."""
    tool_prompt = generate_tool_prompt(tools)
    messages = [
        {"role": "system", "content": tool_prompt},
        {"role": "user", "content": user_message}
    ]

    for _ in range(max_iterations):
        response = client.chat.completions.create(
            model=VLLM_MODEL,
            messages=messages,
            max_tokens=4096,
        )

        full_response = response.choices[0].message.content or ""
        tool_call = parse_tool_call(full_response, tools)

        if tool_call:
            handler = tool_handlers.get(tool_call['tool'])
            if handler:
                result = handler(**tool_call['arguments'])
            else:
                result = f"Unknown tool: {tool_call['tool']}"

            messages.append({"role": "assistant", "content": full_response})
            messages.append({"role": "user", "content": f"Tool result:\n{result}"})
            continue

        return full_response

    return full_response

# =============================================================================
# Main - Demo
# =============================================================================

def main():
    """Demo the prompt-based tool calling approach."""

    # Create OpenAI client pointing to vLLM
    client = OpenAI(
        base_url=VLLM_BASE_URL,
        api_key=VLLM_API_KEY,
    )

    print("=" * 60)
    print("Prompt-Based Tool Calling with vLLM")
    print("=" * 60)
    print(f"Endpoint: {VLLM_BASE_URL}")
    print(f"Model: {VLLM_MODEL}")
    print(f"Tools: {[t['name'] for t in TOOLS]}")
    print("=" * 60)

    # Test queries
    queries = [
        "What's the weather in Berlin?",
        "List the files in the current directory using ls -la",
        "What is 2 + 2? Just answer directly.",  # Should NOT trigger tool call
    ]

    for query in queries:
        print(f"\n{'='*60}")
        print(f"USER: {query}")
        print("=" * 60)

        response = chat_with_tools(
            client=client,
            user_message=query,
            tools=TOOLS,
            tool_handlers=TOOL_HANDLERS,
            verbose=True
        )

        print(f"\n>> FINAL RESPONSE:\n{response}")
        print()


if __name__ == "__main__":
    main()
