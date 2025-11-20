# Two Approaches to Tool Integration

## TL;DR

**Perplexity doesn't support OpenAI function calling** (as of now), so we provide two implementations:

1. **Native Function Calling** (`perplexity_with_tools.py`) - For APIs that support it (OpenAI, Anthropic, etc.)
2. **Prompt-Based** (`perplexity_tools_prompt_based.py`) - **Use this for Perplexity** ✅

## The Problem

When we tested the demo, Perplexity returned:
```
Error code: 400 - {'error': {'message': 'Tool calling is not supported for this model'}}
```

This means Perplexity's API, while OpenAI-compatible for basic chat, doesn't support the `tools` parameter for function calling.

## Solution: Two Implementations

### Approach 1: Native Function Calling (Future-Ready)

**File**: `perplexity_with_tools.py`

**How it works:**
```python
# Send tools in OpenAI format
response = client.chat.completions.create(
    model="gpt-4",
    messages=[...],
    tools=[
        {
            "type": "function",
            "function": {
                "name": "search_files",
                "parameters": {...}
            }
        }
    ],
    tool_choice="auto"
)

# API returns structured tool calls
tool_calls = response.choices[0].message.tool_calls
```

**Pros:**
- Most reliable (API enforces format)
- Model trained specifically for this
- Structured, parseable responses
- Best developer experience

**Cons:**
- ❌ **Not supported by Perplexity** (yet)
- Limited to specific API providers

**Use with:**
- OpenAI (GPT-4, GPT-3.5)
- Anthropic Claude (via their tools API)
- Google Gemini
- Mistral AI
- Any future Perplexity models that add support

---

### Approach 2: Prompt-Based Tool Calling (Works Now)

**File**: `perplexity_tools_prompt_based.py` ✅

**How it works:**
```python
# 1. Add tool instructions to system prompt
system_prompt = """
You have access to these tools:

**search_files**: Search for files
  Parameters:
  - pattern: Glob pattern to search for

To use a tool, respond with:
```json
{
  "tool": "tool_name",
  "arguments": {"param": "value"}
}
```
"""

# 2. Model responds with JSON in text
response = """
I'll search for Python files.

```json
{
  "tool": "search_files",
  "arguments": {"pattern": "*.py"}
}
```
"""

# 3. We parse the JSON and execute
# 4. Feed result back to conversation
# 5. Model continues with final answer
```

**Pros:**
- ✅ **Works with Perplexity right now**
- Works with any LLM (even those without function calling)
- No API limitations
- Portable across providers

**Cons:**
- Less reliable (model might not follow format)
- Requires careful prompt engineering
- JSON parsing can fail
- Not as clean as native support

**Use with:**
- Perplexity (Sonar models)
- Any LLM without native function calling
- Custom/local models
- Experimental setups

## Comparison

| Feature | Native Function Calling | Prompt-Based |
|---------|------------------------|--------------|
| **Reliability** | High (API enforced) | Medium (model dependent) |
| **Perplexity Support** | ❌ No | ✅ Yes |
| **OpenAI Support** | ✅ Yes | ✅ Yes (but unnecessary) |
| **Ease of Use** | Easier (structured) | Harder (parsing needed) |
| **Flexibility** | API-dependent | Works anywhere |
| **Error Handling** | Better | More edge cases |
| **Performance** | Faster | Slightly slower |

## Integration into ppxai

### For Current Perplexity Usage (Recommended)

Use the prompt-based approach:

```python
from perplexity_tools_prompt_based import PerplexityClientPromptTools

# In main()
client = PerplexityClientPromptTools(
    api_key=api_key,
    enable_tools=True
)

await client.initialize_tools(mcp_servers=[])

# In message loop
if isinstance(client, PerplexityClientPromptTools) and client.enable_tools:
    response = asyncio.run(client.chat_with_tools(user_input, current_model))
else:
    response = client.chat(user_input, current_model, stream=True)
```

### For Future / Multi-Provider Support

Support both approaches:

```python
# Detect which approach to use
if provider == "perplexity":
    from perplexity_tools_prompt_based import PerplexityClientPromptTools as Client
elif provider in ["openai", "anthropic"]:
    from perplexity_with_tools import PerplexityClientWithTools as Client

client = Client(api_key=api_key, enable_tools=True)
```

## Example: Prompt-Based Tool Usage

```bash
$ python demo_tools_working.py
```

**User Input:**
```
Use the search_files tool to find all Python files.
```

**System Prompt** (added automatically):
```
You have access to these tools:

**search_files**: Search for files matching a glob pattern
  Parameters:
  - pattern (required): Glob pattern (e.g., '*.py')
  - directory (optional): Directory to search (default: '.')

To use a tool, respond with:
```json
{
  "tool": "tool_name",
  "arguments": {"param": "value"}
}
```
```

**Model Response:**
```
I'll search for Python files in the current directory.

```json
{
  "tool": "search_files",
  "arguments": {
    "pattern": "*.py",
    "directory": "."
  }
}
```
```

**System Execution:**
```
[Calling tool: search_files({'pattern': '*.py', 'directory': '.'})]
[Tool result: ppxai.py
tool_manager.py
perplexity_tools_prompt_based.py]
```

**System adds to conversation:**
```
[Tool Result for search_files]
```
ppxai.py
tool_manager.py
perplexity_tools_prompt_based.py
```

Now provide your final answer based on this result.
```

**Model Final Response:**
```
I found 3 Python files in the current directory:
1. ppxai.py
2. tool_manager.py
3. perplexity_tools_prompt_based.py
```

## MCP Integration

**Both approaches work with MCP!**

The tool discovery and execution layer (MCP) is separate from how the model invokes tools:

```
┌─────────────────────────────────────────┐
│         MCP Tool Manager                │
│  (Discovers tools from MCP servers)     │
└─────────────────────────────────────────┘
                   ↓
         ┌─────────────────┐
         │ Unified Catalog │
         └─────────────────┘
                   ↓
    ┌──────────────┴──────────────┐
    ↓                             ↓
┌─────────────┐          ┌──────────────┐
│  Native     │          │   Prompt     │
│  Function   │          │   Based      │
│  Calling    │          │              │
│             │          │              │
│ (OpenAI)    │          │ (Perplexity) │
└─────────────┘          └──────────────┘
```

Both can use MCP servers for tool discovery and execution. The only difference is HOW the model is told about tools and HOW it invokes them.

## Recommendations

### For ppxai (Perplexity-focused)

1. **Use prompt-based approach** (`perplexity_tools_prompt_based.py`)
2. **Start without MCP** (built-in tools are simpler)
3. **Add MCP later** if you need specific integrations

### For Multi-Provider Tool

If you want to support multiple AI providers:

1. **Abstract the interface**
2. **Detect provider capabilities**
3. **Route to appropriate implementation**

```python
class UniversalToolClient:
    def __init__(self, provider: str, api_key: str):
        if provider == "openai":
            self.client = OpenAIWithNativeTools(api_key)
        elif provider == "perplexity":
            self.client = PerplexityWithPromptTools(api_key)
        # ... etc

    async def chat_with_tools(self, message, model):
        return await self.client.chat_with_tools(message, model)
```

## Testing

### Test Native Function Calling
```bash
# Won't work with Perplexity, but will work with OpenAI
OPENAI_API_KEY=sk-... python perplexity_with_tools.py
```

### Test Prompt-Based (Perplexity)
```bash
# Works with Perplexity!
python demo_tools_working.py
```

## Future: When Perplexity Adds Function Calling

If/when Perplexity adds native function calling support:

1. **Keep both implementations** for backward compatibility
2. **Detect capability** in the API response
3. **Prefer native** when available:

```python
def create_client(api_key):
    # Try native function calling first
    try:
        client = PerplexityClientWithTools(api_key, enable_tools=True)
        # Test if it works
        test_response = client.test_function_calling()
        return client
    except FunctionCallingNotSupported:
        # Fall back to prompt-based
        return PerplexityClientPromptTools(api_key, enable_tools=True)
```

## Summary

| What You Need | Use This File |
|--------------|---------------|
| **Tools with Perplexity NOW** | `perplexity_tools_prompt_based.py` ✅ |
| **Tools with OpenAI/Claude** | `perplexity_with_tools.py` |
| **Universal tool support** | Both (with abstraction layer) |
| **MCP integration** | Both work with `tool_manager.py` |
| **Quick demo** | `demo_tools_working.py` |

## Next Steps

1. ✅ **Run the working demo**: `python demo_tools_working.py`
2. ✅ **Integrate prompt-based tools** into ppxai.py
3. ✅ **Test with your use cases**
4. 🔮 **Monitor Perplexity docs** for native function calling support
5. 🔮 **Switch to native** when available (for better reliability)

---

**Bottom Line**: Use `perplexity_tools_prompt_based.py` for Perplexity. It works today, no API changes needed!
