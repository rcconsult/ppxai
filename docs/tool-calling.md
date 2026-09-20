# Tool Calling in ppxai

**Version:** v1.19.1+
**Updated:** 2026-08-04

> **Note (v1.19.x):** Web search backend selection now goes through
> `resolve_web_search_backend()` (`ppxai/engine/tools/search_backends.py`).
> `tools.web_search.preferred` (global) or `providers.<name>.web_search.preferred`
> is an **ordering** — first choice, then the rest of the usable fallback
> chain — not a hard pin. Add `strict: true` in the same scope to make it a
> hard pin (no fallback, egress narrowed to just that backend). See
> [provider-setup.md](provider-setup.md#web-search-backend-ordering-v1191).

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
| **Gemini** | Native | ✅ Yes | `generate_content` wire, `function_declarations` |
| **Perplexity** | **Per-model, per-wire** | ✅ on `/v1/responses` | **Not "no" any more.** Bare `sonar` on chat-completions is `prompt_based`; the namespaced `perplexity/sonar` on the Responses wire is `auto` and **measured calling the tool** (2026-08-31, `scripts/probe-perplexity-capabilities.py --api-path responses`). The gateway fleet (`anthropic/*`, `openai/*`, `google/*`, `xai/*`) is `auto` on Responses too. |
| **Anthropic** | Native | ✅ Yes | `messages` wire (ADR 0012 §6). **Opt-in and untested against the live API** — debt Item 71 |
| **OpenAI** | Per-model | ✅ Yes | `OpenAINativeProvider`; `chat_completions` or `responses` per `ModelFacts.wire_protocol` |
| **Custom** | Native | ✅ Yes | Standard `tools` parameter (OpenRouter, other OpenAI-compat) |
| **vLLM** | Per-model | ✅ Yes (with `--enable-auto-tool-choice`) | Standard `tools` parameter — but `openai/gpt-oss*` is pinned `prompt_based` in the facts table regardless of your vLLM version |
| **Ollama** | Native | ✅ Yes (Qwen models only) | Standard `tools` parameter |

> This table is **per provider**, which is a simplification that ADR 0012
> retired: tool mode is a property of the **model and the endpoint serving
> it**, and the same model id reached through two providers can legitimately
> differ. `/model info` is the authority for any specific model; the rows
> above say what the provider's models typically do. Row-verified against
> `SHIPPED_MODEL_FACTS` on 2026-09-20.

**Note:** `OpenAINativeProvider` routes each model to its measured tool mode. Some models (o4-mini, gpt-4.1-mini) use prompt-based mode even though the provider supports native tool calling, because benchmarks showed significantly better results. Since ADR 0012 that decision is table data (`ModelFacts.tool_mode`), not a prefix branch. See [model-behavior-analysis.md](model-behavior-analysis.md) — note that file self-flags as stale on model ids.

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
- Anthropic (opt-in; untested against the live API — Item 71)
- Perplexity, on `/v1/responses` only (`perplexity/sonar` and the gateway fleet)
- OpenRouter (varies by model)
- vLLM (requires `--enable-auto-tool-choice`; `gpt-oss` is pinned prompt-based anyway)
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

**This works reliably** for interactive chat and is transparent to users.

> ℹ️ **Resolved — Item 43, closed 2026-08-24.** A 2026-07-13 web-app trial
> (8 runs, `summarize docs/README.md`) found `sonar-pro` never produced a
> real tool call under `/task` in 6 attempts — it refused, confabulated a
> summary, or ran an intrinsic web search and summarized an unrelated repo
> while citing its URL, never reading the granted local file. **The premise
> was overturned twice, and the cause turned out to be ours, not
> Perplexity's:** a hardcoded `native_tool_calling=False` that was true when
> it was written and false by 2026-08-13, plus a `model_profiles` row
> pinning `prompt_based` that would have made the capability table
> decorative on its own. Fixed under ADR 0012 plan I3 (`0490ce87`).
> Perplexity tool-capable `/task` runs are no longer discouraged; Sonar
> tool-calls on `/v1/responses`, which is the wire `ModelFacts` now routes
> it to. Kept here because the failure shape — a *model* blamed for a
> *resolution* bug — is the reusable part.

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

> ℹ️ **Resolved — Item 45, closed 2026-07-22 (`edb74500`).** Gemini 3.x tool
> round-trips used to fail with `400 INVALID_ARGUMENT — Function call is
> missing a thought_signature in functionCall parts`: Gemini 3.x requires
> each returned `functionCall` part to carry an opaque `thought_signature`
> that the client echoes back on the tool-response turn, and ppxai's Gemini
> provider did not preserve it. It does now. Native-tool `/task` runs on
> Gemini 3.x are supported.

### Configuration

No per-provider flag turns this on any more — see the Configuration
Reference below.

---

## Configuration Reference

> ⚠️ **`capabilities.native_tool_calling` and `tool_calling.mode` are dead
> keys.** ADR 0012 replaced them with per-model facts, as a **clean break**:
> `grep -rn "native_tool_calling" ppxai/ --include="*.py"` returns only
> comments, docstrings and migration notes — **no live read**. A config that
> still sets them is parsed and ignored, which is exactly the failure mode
> that made Item 43 look like a Perplexity defect for six weeks. `/doctor`
> reports them as migration keys. `ppxai-config.example.json` carried a
> leftover `native_tool_calling` under `gemini` until 2026-09-20; if you
> copied that file before then, delete the key.

### Where the answer lives now

Tool mode is resolved **per model**, not per provider, because it is a
property of the model and the endpoint serving it — the same model id
reached through two providers legitimately answers differently.

| Question | Read from |
|---|---|
| Does this model tool-call natively? | `ModelFacts.tool_mode` (`"native"` / `"prompt_based"`) in `ppxai/engine/model_facts.py` |
| Which wire does it speak? | `ModelFacts.wire_protocol` (`chat_completions` / `responses` / `generate_content` / `messages`) |
| Can it emit several calls per turn? | `ModelFacts.parallel_tool_calls` |
| What does the *account* support? | `ProviderCapabilities` — key, base URL, prices; no tool-mode opinion |

The dispatch site is one line, `ppxai/engine/chat.py:646`:

```python
use_native_tools = facts.tool_mode != "prompt_based"
```

### Overriding a model's facts

Put a `facts` block on the model, not a capability flag on the provider:

```json
"providers": {
  "vllm-gpt-oss": {
    "models": {
      "openai/gpt-oss-120b": {
        "facts": {
          "wire_protocol": "chat_completions",
          "tool_mode": "prompt_based",
          "parallel_tool_calls": false
        }
      }
    }
  }
}
```

Run `/doctor` after editing: it validates facts blocks, names incomplete
ones (ADR 0012 Q0d), and prints the old→new mapping for any dead key it
still finds. `/model info` shows the resolved value per field and marks
which came from a measurement rather than the unmeasured floor.

---

## Benchmark Implications

### Why This Matters

Tool calling method affects benchmark scores:

- **Native calling:** Direct API → tool execution (faster, more reliable)
- **Prompt-based:** Prompt → LLM generation → parsing → tool execution (slower, may have errors)

**Example from v1.15.6 benchmarks:**

| Model | Method | Score | Notes |
|-------|--------|-------|-------|
| gemini-2.5-pro | Native | 81.3% | Clean native, no workarounds |
| Qwen3-Coder-30B FP8 | Native | 81.3% | Hermes parser, stable |
| gpt-5.2 [^retired] | Native | 70.3% | OpenAI flagship (100% halluc. resist) |
| sonar | Prompt-Based | 75.0% | Excellent with AGENTS.md hints |
| gpt-4.1-mini | Prompt-Based | 71.9% | Better prompt-based than native (60.9%) |

[^retired]: `gpt-5.2` is no longer a shipped model — superseded by `gpt-5.4`/`gpt-5.5`. Row retained as historical benchmark data only; do not use as a current model reference.

The gap is due to:
1. Parsing reliability
2. Model training (native models trained specifically for tool calling)
3. Response format consistency
4. Per-model routing — some models score higher with prompt-based mode

### Benchmark Metadata

Starting with v1.15.3, benchmark results include tool calling method
metadata. The `provider_capabilities.native_tool_calling` field below is the
shape **as emitted then** — that key is dead in config since ADR 0012 (see
the Configuration Reference above); this block records the historical
benchmark payload, not a key you should set:

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
   - `sonar` (75.0% benchmark) - Best cost/utility ratio
   - `sonar-pro` - More thorough but higher cost
   - Avoid `sonar-reasoning-pro` (poor tool calling: 67.2%)

3. **Check AGENTS.md exists** in your project for model-specific tuning

---

## Technical References

### API Test Results

Full test results available in archived documentation:
- `docs/archive/v1.15.3/TOOL_CALLING_ANALYSIS.md` - API verification tests
- `docs/archive/v1.15.3/ACTION_PLAN.md` - Implementation plan

### Related Documentation

- **Multi-Criteria Evaluation:** `docs/archive/benchmarks/MULTI-CRITERIA-EVALUATION.md`
- **Benchmark Summary:** `docs/archive/benchmarks/FINAL-BENCHMARK-SUMMARY.md`
- **Perplexity Analysis:** `docs/archive/benchmarks/PERPLEXITY-AB-TEST-RESULTS.md`
- **Gemini Results:** `docs/archive/benchmarks/GEMINI-QUALITY-VALIDATION-RESULTS.md`

### Provider Documentation

- Perplexity Tools: https://docs.perplexity.ai/docs/agentic-research/tools
- Gemini Function Calling: https://ai.google.dev/gemini-api/docs/function-calling
- OpenAI Function Calling: https://platform.openai.com/docs/guides/function-calling

---

## Tool Result Display Limits (v1.15.3)

### Overview

Tool results displayed to users are truncated for readability, but **full results are always sent to the LLM**. This ensures the AI has complete information while keeping the UI clean.

### Configuration

Display limits are configured in `ToolManager`:

```python
# Default limit for all tools
manager.default_display_limit = 2000  # characters

# Tool-specific limits
manager.tool_display_limits = {
    "get_weather": {
        "short": 500,      # One-line format
        "detailed": 1500,  # Current weather
        "forecast": 5000,  # Full 2-day forecast
        "default": 2000
    },
    "fetch_url": 5000,     # Web pages
    "web_search": 3000,    # Search results
    "read_file": 10000,    # Code files
}
```

### Format-Aware Limits

The `get_weather` tool uses **format-aware limits** - different truncation based on the selected format:

| Format | Limit | Typical Size | Reason |
|--------|-------|--------------|--------|
| `short` | 500 chars | ~50 chars | One line: "Geneva: ☁️  +5°C" |
| `detailed` | 1500 chars | ~200 chars | Current weather with wind, humidity |
| `forecast` | 5000 chars | ~4300 chars | Full 2-day forecast with hourly data |

**Example:**
```python
# Short format uses 500 char limit
get_weather("Geneva", format="short")
# → "Geneva: ☁️  +5°C"

# Forecast format uses 5000 char limit
get_weather("Geneva", format="forecast")
# → Full 2-day forecast (4300 chars displayed)
```

### Implementation

Display limits are applied where `get_tool_display_limit()` is called in
[`ppxai/engine/chat.py`](../ppxai/engine/chat.py) (line numbers drift; search
for `display_limit` rather than citing a fixed range):

```python
# Get tool-specific limit
display_limit = ctx.tool_manager.get_tool_display_limit(tool_name, tool_args)
truncated_result = result[:display_limit] + "..." if len(result) > display_limit else result

# Display to user (truncated)
yield Event(EventType.TOOL_RESULT, {"tool": tool_name, "result": truncated_result})

# Send to LLM (full result)
ctx.session.add_message(Message("user", f"Tool returned:\n\n{result}\n\n"))
```

### Key Points

- **Display truncation only** - LLM always receives full result
- **Format-aware** - Weather tool adjusts limit based on format parameter
- **Configurable** - Can be customized per tool or globally
- **Intelligent defaults** - Web pages get more space than one-line results

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

### Q: How do I know which method my model uses?

Run **`/model info`** — it prints the resolved `tool_mode` for the current
model and marks whether each field is a measurement or the unmeasured
floor. It is per *model*, not per provider: the same model id reached
through two providers can legitimately answer differently. (Do not look for
a `native_tool_calling` flag in `ppxai-config.json` — it is a dead key, see
the Configuration Reference above.)

---

## Changelog

### v1.15.3 (2026-02-08)
- ✅ Added `native_tool_calling` capability flags to all providers
- ✅ Created this documentation
- ✅ Verified Perplexity uses prompt-based method
- ✅ Verified Gemini uses native method
- ✅ Added benchmark metadata for tool calling method
- ✅ **NEW:** Configurable, format-aware tool result display limits
  - Default: 2000 characters for display (full result always sent to LLM)
  - Weather tool: 500/1500/5000 chars for short/detailed/forecast formats
  - Custom limits for web_search (3000), fetch_url (5000), read_file (10000)
  - 11 new tests in `tests/test_tool_display_limits.py`

### v1.15.6 (2026-02-20)
- ✅ **`OpenAINativeProvider`** — dedicated provider for OpenAI models with per-model routing
  - Chat Completions API for GPT-4.1, GPT-5.x, o-series
  - Responses API for Codex and Pro models
  - 404 auto-fallback between API paths
  - `PROMPT_BASED_MODEL_PREFIXES` routes o4-mini, gpt-4.1-mini to prompt-based mode
- ✅ **Per-model facts** — `ModelFacts` dataclass in `model_facts.py` with 68 shipped rows (ADR 0012; superseded the 37-profile `ModelProfile` table, deleted in Item 65)
  - Per-model `tool_calling.mode`, `fallback_on_empty`, `strip_json_from_text`
  - `max_tool_iterations` per model (gemini: 25, sonar/codex-mini: 20)
- ✅ **Codex native tool calling** — belt-and-suspenders: native API tools + tool hints in `instructions`
- ✅ **43 unit tests** in `tests/test_openai_native.py`

### v1.15.4 (2026-02-13)
- ✅ **Corporate SSL support** for web tools (`get_weather`, `fetch_url`, `web_search`)
  - `_create_ssl_context()` respects `SSL_VERIFY` and `SSL_CERT_FILE` env vars
  - `get_weather` tries HTTPS first, falls back to HTTP for corporate proxies
- ✅ **Configurable timeouts** - `tools.<name>.timeout` in ppxai-config.json (default 15s)
- ✅ **16 new SSL tests** in `tests/test_web_tools_ssl.py`
