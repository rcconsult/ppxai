# Tool Calling - Action Plan

**Status:** Ready to implement
**Priority:** High (affects benchmark accuracy and user understanding)
**Effort:** ~4 hours

---

## Summary

Tests confirm that **Perplexity does NOT support native function calling**, while **Gemini does**. ppxai correctly uses prompt-based tool calling as a fallback, but this needs to be documented and benchmarks need to distinguish between the two methods.

---

## Action Items

### 1. Add Capability Flags (30 min)

**File:** `ppxai/engine/providers/perplexity.py`

```python
# Line 56 - Update default_capabilities
default_capabilities = ProviderCapabilities(
    web_search=True,
    web_fetch=True,
    weather=True,
    citations=True,
    streaming=True,
    native_tool_calling=False,  # ← ADD: Sonar models don't support native API
)
```

**File:** `ppxai/config/loader.py` (DEFAULT_CAPABILITIES)

```python
# Add new capability
DEFAULT_CAPABILITIES = {
    ...
    "native_tool_calling": False,  # Default to False, enable per-provider
    ...
}
```

---

### 2. Update Perplexity Provider Docstring (15 min)

**File:** `ppxai/engine/providers/perplexity.py`

**Line 97 - Replace:**
```python
tools: Ignored - Perplexity uses native search, not tools
```

**With:**
```python
tools: Converted to prompt-based tool calling. Perplexity Sonar models
       do not support native function calling via the API (tool_calls response).
       Instead, tool definitions are injected into the system prompt and
       responses are parsed for JSON tool call format.

       Note: Perplexity's Agentic Research API supports native tools for
       third-party models (openai/gpt-*, etc.) but NOT for Sonar models.

       See: https://docs.perplexity.ai/docs/agentic-research/tools
```

---

### 3. Update Gemini Provider to New SDK (2 hours)

**File:** `ppxai/engine/providers/gemini.py`

**Current:** Uses deprecated `google.generativeai`

**Replace with:** `google.genai` (official SDK)

**Steps:**
1. Update imports:
   ```python
   # OLD
   import google.generativeai as genai
   from google.generativeai import types as genai_types

   # NEW
   from google import genai
   from google.genai import types
   ```

2. Update API calls to match new SDK interface

3. Test with:
   ```bash
   cd benchmarks/llm-eval
   uv run python test_tool_calling_apis.py
   ```

**Reference:** https://github.com/google-gemini/deprecated-generative-ai-python

---

### 4. Add Benchmark Test Filtering (1 hour)

**File:** `benchmarks/llm-eval/engine_runner.py`

**Add before test loop (line ~376):**

```python
async def run_async(self, categories: Optional[list[str]] = None):
    ...

    # Check provider capabilities
    from ppxai.config import get_provider_config
    provider_config = get_provider_config(self.provider)
    has_native_tools = provider_config.get("capabilities", {}).get("native_tool_calling", False)

    # Filter tests if needed
    if not has_native_tools and categories and "tool_calling" in categories:
        print(f"\nNOTE: {self.provider} uses prompt-based tool calling (not native API)")
        print(f"      Benchmark tests validate JSON format compliance and parsing reliability\n")

    for i, test in enumerate(tests, 1):
        ...
```

**Update test results metadata:**

```python
# Line ~446
metadata={
    "runner": "engine",
    "timeout": self.timeout,
    "retries": self.retries,
    "tool_calling_method": "native" if has_native_tools else "prompt_based",  # ← ADD
},
```

---

### 5. Create Documentation (30 min)

**File:** `docs/tool-calling.md` (NEW)

```markdown
# Tool Calling in ppxai

## Overview

ppxai supports two methods of tool calling:

1. **Native Tool Calling** - Uses provider's native function calling API
2. **Prompt-Based Tool Calling** - Injects tools into prompt, parses JSON responses

## Provider Support Matrix

| Provider | Native | Prompt-Based | Notes |
|----------|--------|--------------|-------|
| Gemini | ✅ Yes | ✅ Fallback | Uses `function_declarations` API |
| OpenAI | ✅ Yes | ✅ Fallback | Standard `tool_calls` response |
| OpenRouter | ✅ Yes | ✅ Fallback | Depends on routed model |
| **Perplexity** | ❌ No | ✅ Yes | Sonar models use prompt-based only |
| vLLM/Local | ⚠️ Varies | ✅ Yes | Depends on `--tool-call-parser` config |

## How It Works

### Native Tool Calling

Provider API returns structured `tool_calls`:

```json
{
  "choices": [{
    "message": {
      "tool_calls": [{
        "function": {"name": "read_file", "arguments": "{\"path\": \"/test.txt\"}"}
      }]
    }
  }]
}
```

### Prompt-Based Tool Calling

1. Inject tool definitions into system prompt:
   ```
   You have access to the following tools. To use a tool, output:
   {"tool": "tool_name", "arguments": {...}}

   Available tools:
   - read_file: Read contents of a file...
   ```

2. Model responds with JSON in text:
   ```
   {"tool": "read_file", "arguments": {"path": "/test.txt"}}
   ```

3. ppxai parses JSON from response text

## Configuration

### Perplexity

Sonar models do NOT support native function calling. Use prompt-based:

```json
{
  "providers": {
    "perplexity": {
      "capabilities": {
        "native_tool_calling": false
      }
    }
  }
}
```

### Gemini

Supports native function calling (enabled by default):

```json
{
  "providers": {
    "gemini": {
      "capabilities": {
        "native_tool_calling": true
      },
      "generation_params": {
        "temperature": 0.0  // Use low temp for deterministic tool calls
      }
    }
  }
}
```

## Benchmark Implications

Tool calling benchmarks test different capabilities based on provider:

- **Native providers** (Gemini, OpenAI): Tests native API reliability
- **Prompt-based providers** (Perplexity): Tests JSON format compliance and parsing

Scores are NOT directly comparable between native and prompt-based methods.

## Troubleshooting

### No tool calls detected

1. Check provider capabilities
2. Verify API key is set
3. Enable debug mode: `--debug`
4. Check debug logs for tool call attempts

### Intermittent tool calls

Common with prompt-based methods. Model may:
- Explain instead of calling tool
- Output malformed JSON
- Miss tool definitions in long prompts

**Fix:** Use lower temperature (0.0-0.2) and shorter, clearer prompts.
```

---

### 6. Update User Config Example (15 min)

**File:** `ppxai-config.example.json`

**Add to Perplexity section:**

```json
"perplexity": {
  ...
  "capabilities": {
    "native_tool_calling": false,
    "__comment_native_tool_calling": "Sonar models use prompt-based tool calling, not native API"
  },
  ...
}
```

**Add to Gemini section:**

```json
"gemini": {
  ...
  "capabilities": {
    "native_tool_calling": true,
    "__comment_native_tool_calling": "Gemini 2.5+ models support native function calling"
  },
  "generation_params": {
    "temperature": 0.0,
    "__comment_temperature": "Use 0.0 for deterministic tool calls, 0.3 for creative tasks"
  },
  ...
}
```

---

## Testing Plan

After implementing changes:

### 1. Verify Capability Flags

```bash
uv run python -c "
from ppxai.config import initialize, get_provider_config
initialize()
print('Perplexity native_tool_calling:', get_provider_config('perplexity').get('capabilities', {}).get('native_tool_calling'))
print('Gemini native_tool_calling:', get_provider_config('gemini').get('capabilities', {}).get('native_tool_calling'))
"
```

Expected output:
```
Perplexity native_tool_calling: False
Gemini native_tool_calling: True
```

---

### 2. Re-run API Tests

```bash
cd benchmarks/llm-eval
uv run python test_tool_calling_apis.py
```

Expected results:
- Perplexity: IGNORED (confirmed)
- Gemini: SUPPORTED (after SDK update)
- ppxai Engine: Works for both

---

### 3. Re-run Benchmarks

```bash
# With debug logs
python benchmark.py --provider perplexity --model sonar-pro --categories tool_calling --debug
python benchmark.py --provider gemini --model gemini-2.5-flash --categories tool_calling --debug
```

Check debug logs for:
- Perplexity: tool_calling_method = "prompt_based"
- Gemini: tool_calling_method = "native"

---

### 4. Verify Unit Tests

```bash
uv run pytest tests/ -v -k tool
```

All tests should pass.

---

## Success Criteria

✅ Capability flags correctly set for all providers
✅ Documentation clearly explains native vs prompt-based
✅ Benchmark results include tool_calling_method metadata
✅ Test suite passes without regressions
✅ Gemini uses new SDK successfully
✅ User config example updated with correct settings

---

## Rollout Notes

**User Impact:** Low
- Existing functionality unchanged
- Benchmarks become more accurate
- Better understanding of tool calling methods

**Breaking Changes:** None
- Additive changes only
- Backward compatible

**Documentation Updates Required:**
- docs/tool-calling.md (new)
- ppxai-config.example.json
- CHANGELOG.md entry

---

## Time Estimate

| Task | Time |
|------|------|
| Capability flags | 30 min |
| Docstrings | 15 min |
| Gemini SDK update | 2 hours |
| Benchmark filtering | 1 hour |
| Documentation | 30 min |
| Testing | 15 min |
| **TOTAL** | **~4 hours** |
