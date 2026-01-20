# vLLM/GPT-OSS Tool Calling Developer Guide

This guide explains how ppxai implements tool calling for vLLM backends (including GPT-OSS-120B) and provides a working approach that avoids the `HarmonyError` issues.

**Quick Start:** See [examples/prompt_based_tools.py](../examples/prompt_based_tools.py) for a complete standalone example.

## The Problem

When using vLLM with `--enable-auto-tool-choice` and GPT-OSS models, you may encounter:

```
openai_harmony.HarmonyError: unexpected tokens remaining in message header
```

This error occurs because GPT-OSS model outputs don't consistently follow the Harmony response format that vLLM attempts to parse. See [vLLM issue #23567](https://github.com/vllm-project/vllm/issues/23567).

## ppxai's Solution: Two Tool Calling Modes

ppxai supports two distinct approaches:

| Mode | Config Flag | vLLM Flags Required | Reliability |
|------|-------------|---------------------|-------------|
| **Prompt-Based** | `native_tool_calling: false` | None | ✅ High |
| **Native** | `native_tool_calling: true` | `--enable-auto-tool-choice` | ⚠️ May hit HarmonyError |

### Recommended: Prompt-Based Tool Calling

**This mode bypasses vLLM's Harmony parsing entirely.**

```json
{
  "providers": {
    "vllm-gpt-oss": {
      "name": "GPT-OSS 120B (vLLM)",
      "base_url": "http://your-vllm-endpoint:8000/v1",
      "api_key_env": "VLLM_API_KEY",
      "default_model": "openai/gpt-oss-120b",
      "capabilities": {
        "native_tool_calling": false
      }
    }
  }
}
```

---

## How Prompt-Based Tool Calling Works

### 1. System Prompt Injection

When `native_tool_calling: false`, ppxai injects tool definitions into the system prompt:

```python
# From ppxai/engine/tools/manager.py (lines 290-359)

def get_tools_prompt(self) -> str:
    prompt = "# IMPORTANT: You Have Access to Tools\n\n"
    prompt += "## How to Call a Tool\n\n"
    prompt += "To use a tool, respond ONLY with a JSON code block:\n\n"
    prompt += "```json\n{\"tool\": \"tool_name\", \"arguments\": {\"param\": \"value\"}}\n```\n\n"
    prompt += "## Available Tools:\n\n"

    for tool in tools:
        prompt += f"### {tool.name}\n{tool.description}\n"
        # ... parameter descriptions
```

### 2. Multi-Strategy Response Parsing

ppxai parses tool calls from text using multiple strategies (in order):

```python
# From ppxai/engine/tools/parser.py (lines 212-308)

def parse_tool_call(text: str, get_tool: ToolLookupFunc) -> Optional[Dict[str, Any]]:
    """
    Parsing strategies:
    1. Entire response as JSON
    2. JSON in markdown code blocks (```json ... ```)
    3. Brace-based extraction (find {"tool" patterns)
    4. Tool inference from arguments (for models without 'tool' key)
    """
```

#### Strategy 1: Entire Response as JSON
```python
text_stripped = text.strip()
if text_stripped.startswith('{') and text_stripped.endswith('}'):
    data = _try_parse_json(text_stripped)
    if data:
        normalized = _normalize_tool_call(data, get_tool)
```

#### Strategy 2: Markdown Code Blocks
```python
code_block_pattern = r'```(?:json)?\s*([\s\S]*?)```'
matches = re.findall(code_block_pattern, text)
for match in matches:
    # Parse JSON from code block
```

#### Strategy 3: Brace-Based Extraction
```python
for pattern in ['{"tool"', "{'tool'"]:
    start = text.find(pattern, start_idx)
    # Count braces to find complete JSON object
    depth = 0
    for char in text[start:]:
        if char == '{': depth += 1
        elif char == '}': depth -= 1
        if depth == 0: break
```

#### Strategy 4: Tool Inference (No 'tool' Key)
For models that output raw arguments without a tool name:

```python
# From ppxai/engine/tools/parser.py (lines 34-81)

TOOL_INFERENCE_RULES = [
    {
        "tool": "web_search",
        "required": ["query"],
        "allowed": {"query", "num_results", "top_n", "count", "limit"},
        "aliases": {"num_results": ["top_n", "count", "limit"]}
    },
    {
        "tool": "read_file",
        "required": ["path", "filepath"],
        "allowed": {"path", "filepath", "line_start", "line_end"},
        "aliases": {"filepath": ["path"]}
    },
    # ... more rules
]
```

### 3. Handling GPT-OSS Nested Tool Calls

GPT-OSS 120B sometimes outputs double-wrapped structures:

```json
{
  "tool": "apply_patch",
  "arguments": {
    "tool": "apply_patch",
    "arguments": {
      "file_path": "/path",
      "unified_diff": "..."
    }
  }
}
```

ppxai unwraps this automatically:

```python
# From ppxai/engine/tools/parser.py (lines 129-135)

if isinstance(args, dict) and "tool" in args and "arguments" in args:
    # Nested tool call - unwrap it
    args = args["arguments"]
```

### 4. Parameter Name Normalization

Different models use different parameter names. ppxai normalizes them:

```python
# From ppxai/engine/tools/manager.py (lines 179-203)

PARAM_ALIAS_GROUPS = [
    {"filepath", "file_path", "filePath", "file"},
    {"path", "directory", "dir_path", "dir", "folder"},
    {"command", "cmd", "shell_command"},
    {"query", "query_text", "search_query"},
    {"unified_diff", "diff", "patch"},
    {"url", "link", "webpage", "uri"},
    {"location", "city", "place"},
]
```

Example: Model outputs `{"file": "/path"}` → normalized to `{"filepath": "/path"}`

---

## Implementation for Your Application

### Step 1: Define Tool Schema

```python
tools = [
    {
        "name": "read_file",
        "description": "Read contents of a file",
        "parameters": {
            "type": "object",
            "properties": {
                "filepath": {"type": "string", "description": "Path to file"}
            },
            "required": ["filepath"]
        }
    }
]
```

### Step 2: Generate System Prompt

```python
def generate_tool_prompt(tools):
    prompt = """# Tool Usage Instructions

To use a tool, respond with ONLY a JSON block:

```json
{"tool": "tool_name", "arguments": {"param": "value"}}
```

## Available Tools:

"""
    for tool in tools:
        prompt += f"### {tool['name']}\n{tool['description']}\n"
        for param, info in tool['parameters']['properties'].items():
            required = "required" if param in tool['parameters'].get('required', []) else "optional"
            prompt += f"- `{param}` ({required}): {info.get('description', '')}\n"
        prompt += "\n"

    prompt += """## Rules:
1. Output ONLY the JSON block when calling a tool
2. After receiving results, continue or respond to user
3. You CAN access files and run commands - use tools proactively!
"""
    return prompt
```

### Step 3: Parse Tool Calls from Response

```python
import json
import re

def parse_tool_call(text, tools):
    """Parse tool call from model response."""
    tool_names = {t['name'] for t in tools}

    # Strategy 1: Entire response is JSON
    text_stripped = text.strip()
    if text_stripped.startswith('{') and text_stripped.endswith('}'):
        try:
            data = json.loads(text_stripped)
            if data.get('tool') in tool_names:
                return normalize_tool_call(data)
        except json.JSONDecodeError:
            pass

    # Strategy 2: JSON in code blocks
    pattern = r'```(?:json)?\s*(\{[\s\S]*?\})\s*```'
    for match in re.findall(pattern, text):
        try:
            data = json.loads(match)
            if data.get('tool') in tool_names:
                return normalize_tool_call(data)
        except json.JSONDecodeError:
            pass

    # Strategy 3: Find {"tool" pattern
    start = text.find('{"tool"')
    if start != -1:
        depth = 0
        for i, char in enumerate(text[start:]):
            if char == '{': depth += 1
            elif char == '}': depth -= 1
            if depth == 0:
                try:
                    data = json.loads(text[start:start+i+1])
                    if data.get('tool') in tool_names:
                        return normalize_tool_call(data)
                except json.JSONDecodeError:
                    pass
                break

    return None

def normalize_tool_call(data):
    """Unwrap nested structures and normalize parameters."""
    tool = data.get('tool') or data.get('name')
    args = data.get('arguments', {})

    # Unwrap GPT-OSS nested structure
    if isinstance(args, dict) and 'tool' in args and 'arguments' in args:
        args = args['arguments']

    # Normalize parameter names
    aliases = {
        'filepath': ['file_path', 'filePath', 'file', 'path'],
        'command': ['cmd', 'shell_command'],
        'query': ['search_query', 'query_text'],
    }
    for canonical, alias_list in aliases.items():
        for alias in alias_list:
            if alias in args and canonical not in args:
                args[canonical] = args.pop(alias)
                break

    return {'tool': tool, 'arguments': args}
```

### Step 4: Chat Loop with Tool Execution

```python
async def chat_with_tools(client, messages, tools, max_iterations=10):
    tool_prompt = generate_tool_prompt(tools)

    # Prepend tool prompt to system message
    if messages[0]['role'] == 'system':
        messages[0]['content'] = tool_prompt + "\n\n" + messages[0]['content']
    else:
        messages.insert(0, {'role': 'system', 'content': tool_prompt})

    for iteration in range(max_iterations):
        # Call model (no tools parameter - prompt-based mode)
        response = await client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=messages,
            stream=True
        )

        full_response = ""
        async for chunk in response:
            content = chunk.choices[0].delta.content or ""
            full_response += content
            print(content, end="", flush=True)

        # Check for tool call
        tool_call = parse_tool_call(full_response, tools)
        if tool_call:
            # Execute tool
            result = await execute_tool(tool_call['tool'], tool_call['arguments'])

            # Add assistant message and tool result to history
            messages.append({'role': 'assistant', 'content': full_response})
            messages.append({'role': 'user', 'content': f"Tool result:\n{result}"})

            continue  # Next iteration

        # No tool call - return final response
        return full_response

    return full_response
```

---

## Key Files in ppxai

| File | Purpose |
|------|---------|
| [ppxai/engine/tools/parser.py](../ppxai/engine/tools/parser.py) | Multi-strategy tool call parsing (309 lines) |
| [ppxai/engine/tools/manager.py](../ppxai/engine/tools/manager.py) | Tool registration, prompt generation, parameter normalization |
| [ppxai/engine/chat.py](../ppxai/engine/chat.py) | Chat loop with tool iteration |
| [tests/test_engine_tool_parsing.py](../tests/test_engine_tool_parsing.py) | Comprehensive test suite (896 lines) |

---

## Testing Your Implementation

Use these test cases from ppxai's test suite:

```python
# Test: Simple JSON tool call
text = '{"tool": "read_file", "arguments": {"filepath": "/etc/hosts"}}'
assert parse_tool_call(text, tools) == {
    "tool": "read_file",
    "arguments": {"filepath": "/etc/hosts"}
}

# Test: Code block format
text = '''Here's what I'll do:
```json
{"tool": "web_search", "arguments": {"query": "python asyncio"}}
```'''
assert parse_tool_call(text, tools)['tool'] == "web_search"

# Test: GPT-OSS nested structure
text = '''{"tool": "apply_patch", "arguments": {"tool": "apply_patch", "arguments": {"file_path": "/app.py", "unified_diff": "..."}}}'''
result = parse_tool_call(text, tools)
assert result['arguments']['file_path'] == "/app.py"  # Unwrapped

# Test: Parameter alias normalization
text = '{"tool": "read_file", "arguments": {"file": "/etc/hosts"}}'
result = parse_tool_call(text, tools)
assert 'filepath' in result['arguments']  # Normalized from 'file'
```

---

## Summary

1. **Use prompt-based mode** (`native_tool_calling: false`) to avoid HarmonyError
2. **Inject tool descriptions** into system prompt with JSON format instructions
3. **Parse responses** using multiple strategies (JSON, code blocks, brace matching)
4. **Handle GPT-OSS quirks**: nested structures, parameter name variations
5. **Normalize parameters** to match your tool schemas

This approach is model-agnostic and works reliably with GPT-OSS, Llama, Qwen, and other models served via vLLM or Ollama.
