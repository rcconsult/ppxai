# Prompt-Based Tool Calling for vLLM/GPT-OSS

A general-purpose guide for implementing reliable tool calling with vLLM and GPT-OSS models, avoiding the `HarmonyError` issues that occur with native tool parsing.

**Standalone Example:** [examples/prompt_based_tools.py](../examples/prompt_based_tools.py)

## The Problem

When using vLLM with `--enable-auto-tool-choice` and GPT-OSS models, you may encounter:

```
openai_harmony.HarmonyError: unexpected tokens remaining in message header
```

This error occurs because GPT-OSS model outputs don't consistently follow the Harmony response format that vLLM attempts to parse. See [vLLM issue #23567](https://github.com/vllm-project/vllm/issues/23567).

**Related issues:**
- [harmony issue #80](https://github.com/openai/harmony/issues/80) - Refusal parsing failures
- [vLLM PR #30205](https://github.com/vllm-project/vllm/pull/30205) - Streaming fix (merged Dec 2025)

## The Solution: Prompt-Based Tool Calling

Instead of relying on vLLM's native tool parsing, inject tool definitions into the system prompt and parse tool calls from the model's text response.

**Key insight:** vLLM only triggers Harmony parsing when the `tools` parameter is present in the request. By omitting it, you bypass the problematic parsing entirely.

From [vLLM source code](https://github.com/vllm-project/vllm/blob/main/vllm/entrypoints/openai/chat_completion/serving.py):

```python
def _should_stream_with_auto_tool_parsing(self, request):
    return (
        request.tools           # <-- Must be non-empty
        and self.tool_parser
        and self.enable_auto_tools
        and request.tool_choice in ["auto", None]
    )
```

## Comparison: Native vs Prompt-Based

| Aspect | Native Tool Calling | Prompt-Based |
|--------|---------------------|--------------|
| **vLLM flags** | `--enable-auto-tool-choice --tool-call-parser openai` | None required |
| **API parameter** | `tools=[...]` sent | No `tools` parameter |
| **Stability** | HarmonyError risk | No parsing errors |
| **Token overhead** | Lower | Higher (tools in prompt) |
| **Parallel tools** | Supported by API | Depends on model |
| **Works with** | vLLM >= 0.10.2 | Any vLLM version |

## Implementation

### Step 1: Define Your Tools

```python
TOOLS = [
    {
        "name": "get_weather",
        "description": "Get current weather for a location",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "City name"}
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
        props = tool['parameters'].get('properties', {})
        required = tool['parameters'].get('required', [])
        for param, info in props.items():
            req = "required" if param in required else "optional"
            prompt += f"- `{param}` ({req}): {info.get('description', '')}\n"
        prompt += "\n"

    prompt += """## Rules:
1. Output ONLY the JSON block when calling a tool
2. After receiving results, continue or call another tool
3. You CAN access files and run commands - use tools!
"""
    return prompt
```

### Step 3: Parse Tool Calls (Multi-Strategy)

GPT-OSS and other models output tool calls in various formats. Use multiple parsing strategies:

```python
import json
import re

def parse_tool_call(text, tools):
    """Parse tool call from model response."""
    tool_names = {t['name'] for t in tools}

    # Strategy 1: Entire response is JSON
    text_stripped = text.strip()
    if text_stripped.startswith('{') and text_stripped.endswith('}'):
        result = try_parse(text_stripped, tool_names)
        if result:
            return result

    # Strategy 2: JSON in markdown code blocks
    for match in re.findall(r'```(?:json)?\s*([\s\S]*?)```', text):
        if match.strip().startswith('{'):
            result = try_parse(match.strip(), tool_names)
            if result:
                return result

    # Strategy 3: Find {"tool" pattern with brace matching
    start = text.find('{"tool"')
    if start != -1:
        depth = 0
        for i, char in enumerate(text[start:]):
            if char == '{': depth += 1
            elif char == '}': depth -= 1
            if depth == 0:
                result = try_parse(text[start:start+i+1], tool_names)
                if result:
                    return result
                break

    return None


def try_parse(json_str, tool_names):
    """Parse JSON and normalize tool call."""
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        try:
            data = json.loads(json_str.replace("'", '"'))
        except:
            return None

    tool = data.get('tool') or data.get('name')
    if not tool or tool not in tool_names:
        return None

    args = data.get('arguments', {})

    # Unwrap GPT-OSS nested structure
    if isinstance(args, dict) and 'tool' in args and 'arguments' in args:
        args = args['arguments']

    # Normalize parameter aliases
    aliases = {'filepath': ['file_path', 'file', 'path']}
    for canonical, alias_list in aliases.items():
        for alias in alias_list:
            if alias in args and canonical not in args:
                args[canonical] = args.pop(alias)

    return {'tool': tool, 'arguments': args}
```

### Step 4: Chat Loop with Tool Execution

```python
from openai import OpenAI

def chat_with_tools(client, user_message, tools, handlers, max_iter=10):
    messages = [
        {"role": "system", "content": generate_tool_prompt(tools)},
        {"role": "user", "content": user_message}
    ]

    for _ in range(max_iter):
        # IMPORTANT: No 'tools' parameter - prompt-based mode
        response = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=messages,
            stream=True,
        )

        full_response = ""
        for chunk in response:
            if chunk.choices[0].delta.content:
                full_response += chunk.choices[0].delta.content
                print(chunk.choices[0].delta.content, end="", flush=True)

        tool_call = parse_tool_call(full_response, tools)
        if tool_call:
            # Execute tool
            result = handlers[tool_call['tool']](**tool_call['arguments'])

            # Add to conversation
            messages.append({"role": "assistant", "content": full_response})
            messages.append({"role": "user", "content": f"Tool result:\n{result}"})
            continue

        return full_response  # No tool call = final response

    return full_response
```

### Step 5: Usage

```python
client = OpenAI(
    base_url="http://your-vllm-endpoint:8000/v1",
    api_key="none",  # or your API key
)

handlers = {
    "get_weather": lambda location: f"Weather in {location}: 18°C, cloudy",
    "read_file": lambda filepath: open(filepath).read(),
}

response = chat_with_tools(
    client,
    "What's the weather in Berlin?",
    TOOLS,
    handlers
)
```

## GPT-OSS Specific Handling

### Nested Tool Calls

GPT-OSS sometimes outputs double-wrapped structures:

```json
{
  "tool": "read_file",
  "arguments": {
    "tool": "read_file",
    "arguments": {
      "filepath": "/etc/hosts"
    }
  }
}
```

**Solution:** Unwrap nested structures:

```python
if isinstance(args, dict) and 'tool' in args and 'arguments' in args:
    args = args['arguments']
```

### Parameter Name Variations

GPT-OSS may use different parameter names:

| Tool expects | Model might output |
|--------------|-------------------|
| `filepath` | `file_path`, `file`, `path` |
| `command` | `cmd`, `shell_command` |
| `query` | `search_query` |

**Solution:** Normalize aliases:

```python
aliases = {
    'filepath': ['file_path', 'filePath', 'file', 'path'],
    'command': ['cmd', 'shell_command'],
    'query': ['search_query', 'query_text'],
}
```

## Environment Variables

```bash
export VLLM_BASE_URL=http://your-vllm-endpoint:8000/v1
export VLLM_MODEL=openai/gpt-oss-120b
export VLLM_API_KEY=none  # or your API key
```

## Testing

```python
# Test cases for parser
def test_parser():
    tools = [{"name": "read_file", "parameters": {"properties": {"filepath": {}}}}]

    # Simple JSON
    assert parse_tool_call('{"tool": "read_file", "arguments": {"filepath": "/x"}}', tools)

    # Code block
    assert parse_tool_call('```json\n{"tool": "read_file", "arguments": {"filepath": "/x"}}\n```', tools)

    # Nested (GPT-OSS)
    assert parse_tool_call('{"tool": "read_file", "arguments": {"tool": "read_file", "arguments": {"filepath": "/x"}}}', tools)

    # Parameter alias
    result = parse_tool_call('{"tool": "read_file", "arguments": {"file": "/x"}}', tools)
    assert result['arguments']['filepath'] == "/x"

    print("All tests passed!")
```

## Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| HarmonyError | `tools` parameter sent | Remove `tools` from API call |
| Empty tool calls | Model didn't follow format | Improve system prompt |
| Wrong parameters | Model used alias | Add to normalization |
| Infinite loop | Model keeps calling tools | Set `max_iterations` limit |

## References

- [vLLM Issue #23567](https://github.com/vllm-project/vllm/issues/23567) - HarmonyError discussion
- [vLLM GPT-OSS Recipe](https://github.com/vllm-project/recipes/blob/main/OpenAI/GPT-OSS.md) - Official guide
- [OpenAI Harmony Library](https://github.com/openai/harmony) - Token format spec
