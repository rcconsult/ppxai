# Tool Calling in ppxai

**Version:** v1.15.3
**Updated:** 2026-02-08

---

## Overview

ppxai supports **two different tool calling methods** depending on the AI provider:

1. **Native Tool Calling** - Provider's API returns `tool_calls` in responses
2. **Prompt-Based Tool Calling** - Tools injected into prompts, ppxai parses JSON from text

This document explains which providers use which method and the implications for users.

---

## Provider Comparison

| Provider | Method | Native API Support | ppxai Implementation |
|----------|--------|-------------------|---------------------|
| **Gemini** | Native | ✅ Yes | Uses `function_declarations` API |
| **Perplexity** | Prompt-Based | ❌ No | Injects tools in prompt, parses JSON |
| **OpenAI** | Native | ✅ Yes | Uses standard `tools` parameter |
| **OpenRouter** | Native | ✅ Yes | Uses standard `tools` parameter |
| **vLLM** | Native | ✅ Yes (with --enable-auto-tool-choice) | Uses standard `tools` parameter |
| **Ollama** | Native | ✅ Yes (Qwen models only) | Uses standard `tools` parameter |

---

## Method Details

### Native Tool Calling

**How it works:**
1. ppxai sends `tools` parameter with function schemas in API request
2. Provider's LLM decides which tools to call
3. API response includes structured `tool_calls` array
4. ppxai executes tools and sends results back to API

**Advantages:**
- ✅ More reliable (provider-optimized)
- ✅ Structured responses
- ✅ Better tool selection
- ✅ Faster (no parsing needed)

**Providers:**
- Gemini (2.5+)
- OpenAI (all models with function calling)
- OpenRouter (varies by model)
- vLLM (requires `--enable-auto-tool-choice`)
- Ollama (Qwen2.5 models only)

---

### Prompt-Based Tool Calling

**How it works:**
1. ppxai injects tool descriptions into system prompt
2. LLM outputs tool calls as JSON text in response
3. ppxai parses JSON from response text
4. ppxai executes tools and continues conversation

**Advantages:**
- ✅ Works with any text-generation API
- ✅ No special API support required
- ✅ Fallback for providers without native support

**Disadvantages:**
- ⚠️ Less reliable (JSON parsing can fail)
- ⚠️ Slower (needs text generation + parsing)
- ⚠️ May include extra explanation text
- ⚠️ Prone to formatting errors

**Providers:**
- Perplexity (all Sonar models)
- Any provider without native tool calling

---

## Perplexity Sonar Models (Prompt-Based)

### Test Results (2026-02-08)

Direct API tests confirmed that **Perplexity Sonar models do NOT support native function calling**:

**Test:** Sent `tools` parameter to Perplexity API with `sonar-pro` and `sonar-reasoning-pro`

**Result:**
- ✅ API accepts `tools` parameter without error
- ❌ Response contains NO `tool_calls`
- ❌ Model explains it "cannot access files" or "cannot read files"
- ❌ Treats request as regular chat

**Conclusion:** Perplexity API **ignores** the `tools` parameter. Models are not trained for native function calling.

### ppxai's Workaround

ppxai uses **prompt-based tool calling** for Perplexity:

1. Tools are injected into system prompt with schemas
2. Model is instructed to output JSON when calling tools
3. ppxai's parser extracts tool calls from response text
4. Tools execute and results are added to conversation

**This works reliably** and is transparent to users.

---

## Gemini (Native)

### API Support

Gemini models (2.5+) support native function calling via:
- **Standard API:** `function_declarations` parameter
- **OpenAI-Compatible API:** `tools` parameter (ppxai uses this)

**Test Results (2026-02-08):**
- ✅ API returns `tool_calls` in responses
- ✅ Structured function arguments
- ✅ Reliable tool selection
- ✅ Works with ppxai without modification

### Configuration

```json
"gemini": {
  "capabilities": {
    "native_tool_calling": true
  },
  "options": {
    "native_tool_calling": true  // Enable in provider
  }
}
```

---

## Configuration Reference

### Capability Flags

The `native_tool_calling` capability flag indicates whether a provider supports native tool calling:

```json
"capabilities": {
  "native_tool_calling": true   // Provider has native API support
}
```

### Provider-Specific Settings

**Perplexity:**
```json
"perplexity": {
  "capabilities": {
    "native_tool_calling": false  // Uses prompt-based fallback
  }
}
```

**Gemini:**
```json
"gemini": {
  "capabilities": {
    "native_tool_calling": true   // Uses native function calling
  }
}
```

**vLLM:**
```json
"vllm-gpt-oss": {
  "capabilities": {
    "native_tool_calling": true   // Requires --enable-auto-tool-choice
  }
}
```

**Ollama:**
```json
"ollama": {
  "capabilities": {
    "native_tool_calling": true   // Qwen2.5 models only
  }
}
```

---

## Benchmark Implications

### Why This Matters

Tool calling method affects benchmark scores:

- **Native calling:** Direct API → tool execution (faster, more reliable)
- **Prompt-based:** Prompt → LLM generation → parsing → tool execution (slower, may have errors)

**Example from v1.15.3 benchmarks:**

| Model | Method | Score | Notes |
|-------|--------|-------|-------|
| gemini-3-flash-preview | Native | 100% | Perfect tool execution |
| sonar-pro | Prompt-Based | 28.6% | Works but requires hints |

The gap is due to:
1. Parsing reliability
2. Model training (native models trained specifically for tool calling)
3. Response format consistency

### Benchmark Metadata

Starting with v1.15.3, benchmark results include tool calling method metadata:

```json
{
  "metadata": {
    "tool_calling_method": "native",  // or "prompt_based"
    "provider_capabilities": {
      "native_tool_calling": true
    }
  }
}
```

This allows fair comparison between providers.

---

## User Guidance

### When to Use Which Provider

**For Best Tool Calling Reliability:**
- ✅ Use Gemini (native support, 100% quality)
- ✅ Use OpenAI (native support, highly reliable)
- ✅ Use vLLM with proper flags (native support)

**For Web Search + Tools:**
- ✅ Use Perplexity (prompt-based works reliably with AGENTS.md hints)
- ⚠️ Expect slightly lower tool calling scores vs native providers

### Improving Prompt-Based Tool Calling

If using Perplexity or other prompt-based providers:

1. **Add model-specific hints** in `AGENTS.md`:
   ```yaml
   sonar*:
     - "CRITICAL: For code editing, call apply_patch ONCE - detected issue: you make 5-6 duplicate calls."
     - "Do NOT output tool call JSON in your response text - use tool calling directly."
   ```

2. **Use specific models:**
   - `sonar-pro` (73.4% benchmark) - Best for coding
   - Avoid `sonar-reasoning-pro` (poor tool calling: 50%)

3. **Check AGENTS.md exists** in your project for model-specific tuning

---

## Technical References

### API Test Results

Full test results available in archived documentation:
- `docs/archive/v1.15.3/TOOL_CALLING_ANALYSIS.md` - API verification tests
- `docs/archive/v1.15.3/ACTION_PLAN.md` - Implementation plan

### Related Documentation

- **Multi-Criteria Evaluation:** `docs/MULTI-CRITERIA-EVALUATION.md`
- **Benchmark Summary:** `docs/FINAL-BENCHMARK-SUMMARY.md`
- **Perplexity Analysis:** `docs/PERPLEXITY-AB-TEST-RESULTS.md`
- **Gemini Results:** `docs/GEMINI-QUALITY-VALIDATION-RESULTS.md`

### Provider Documentation

- Perplexity Tools: https://docs.perplexity.ai/docs/agentic-research/tools
- Gemini Function Calling: https://ai.google.dev/gemini-api/docs/function-calling
- OpenAI Function Calling: https://platform.openai.com/docs/guides/function-calling

---

## Frequently Asked Questions

### Q: Why does Perplexity not support native tool calling?

Perplexity Sonar models are optimized for search and reasoning, not function calling. Their API accepts the `tools` parameter for compatibility but doesn't use it.

### Q: Does this affect ppxai's functionality?

No. ppxai's prompt-based fallback works transparently. Users won't notice a difference in basic usage, only in benchmark scores and reliability.

### Q: Can I force native tool calling for Perplexity?

No. The Perplexity API does not return `tool_calls`, so native calling is not possible.

### Q: Which method is better?

Native tool calling is more reliable and faster, but prompt-based works well with proper hints in `AGENTS.md`.

### Q: How do I know which method my provider uses?

Check the `native_tool_calling` capability flag in `ppxai-config.json` or see the table at the top of this document.

---

## Changelog

### v1.15.3 (2026-02-08)
- ✅ Added `native_tool_calling` capability flags to all providers
- ✅ Created this documentation
- ✅ Verified Perplexity uses prompt-based method
- ✅ Verified Gemini uses native method
- ✅ Added benchmark metadata for tool calling method
