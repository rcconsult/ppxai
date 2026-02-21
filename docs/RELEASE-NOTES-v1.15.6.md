# Release Notes: v1.15.6

**Release Date:** 2026-02-19
**Branch:** feature/benchmark-openai-models
**Focus:** Native OpenAI Provider, Model Profile System, Benchmark Infrastructure

---

## Overview

v1.15.6 adds a dedicated native OpenAI provider, a model profile system covering 37 models, and significant benchmark infrastructure improvements. This is the foundation release for v1.16.0's profile-driven tool loop.

**Key Changes:**
- Native OpenAI provider with Chat Completions + Responses API routing
- Model profile system with 37 built-in profiles (data structure only, not yet wired into chat.py)
- Brace-counting JSON parser replacing regex (handles nested braces in apply_patch diffs)
- JSON stripping from response text when native tool_calls are present
- 54+ benchmark runs across 27 model variants with detailed analysis
- 1,349 total tests passing

---

## Major Changes

### 1. Native OpenAI Provider

**What:** `OpenAINativeProvider` — a standalone provider class for the OpenAI API that correctly handles modern OpenAI models.

**Why:** The previous `OpenAICompatibleProvider` treated all OpenAI-compatible APIs the same, but newer OpenAI models (GPT-5.x, o-series, Codex) require specific API handling:
- GPT-5.x and o-series require `max_completion_tokens` instead of `max_tokens`
- o-series models reject `temperature` and `top_p` parameters
- Codex models use the Responses API (`/responses`) instead of Chat Completions (`/chat/completions`)
- GPT-5.2 outputs tool call JSON in both `tool_calls` AND response text (needs stripping)

**Key features:**
| Feature | Description |
|---------|-------------|
| Chat Completions API | Standard `/chat/completions` for GPT-4.1, GPT-5.x, o-series |
| Responses API | `/responses` endpoint for Codex and Pro models |
| 404 auto-fallback | Tries Chat Completions first, falls back to Responses on 404 |
| `max_completion_tokens` | Automatically used for GPT-5.x and o-series (replaces `max_tokens`) |
| Param stripping | Removes `temperature`/`top_p` for models that reject them |
| Reasoning tokens | Extracts reasoning token counts from o-series responses |
| Native tool calling | Streaming tool call assembly from chunked responses |
| Web search | `web_search_preview` tool via Responses API (opt-in) |

**Impact:** Only affects users with `openai` provider configured. OpenRouter, local, and custom providers are unchanged (still use `OpenAICompatibleProvider`).

**Key files:**
- `ppxai/engine/providers/openai_native.py` — Provider implementation (812 lines)
- `tests/test_openai_native.py` — 46 unit tests

### 2. Model Profile System

**What:** `model_profiles.py` — a registry of per-model behavioral profiles encoding tool calling strategy, API routing, max_tokens, and benchmark performance tier.

**Why:** The benchmark analysis (27 models, 7 categories) showed that models have fundamentally different tool calling behaviors. A one-size-fits-all approach doesn't work:
- o4-mini scores up to 80.8% with prompt-based vs 11.5% with native tool calling
- gpt-4.1-mini scores 71.9% prompt-based vs 60.9% native
- GPT-5.2 needs JSON stripping from response text
- Codex models need Responses API routing

**Architecture:**

```python
@dataclass
class ToolCallingProfile:
    mode: "native" | "prompt_based" | "auto"
    fallback_on_empty: bool      # Retry with prompt-based if native returns empty
    fallback_on_failure: bool    # Retry on native parse failure
    strip_json_from_text: bool   # Remove duplicate tool JSON from content
    parallel_tool_calls: bool    # Process all tool calls, not just first
    api_path: "chat" | "responses" | "auto"

@dataclass
class ModelProfile:
    tool_calling: ToolCallingProfile
    max_tokens: int              # 0 = use provider default
    supports_reasoning: bool     # o-series models
    restricted_params: List[str] # Params to strip (temperature, top_p)
    tier: str                    # S/A/B/C/D benchmark tier
```

**37 built-in profiles** covering:
- OpenAI: gpt-5.2, gpt-5, gpt-5-mini, gpt-5-nano, gpt-4.1, gpt-4.1-mini, gpt-4.1-nano, gpt-4o, gpt-4o-mini, o4-mini, o3, o3-mini, o3-pro, o1, o1-mini, gpt-5.1-codex, gpt-5.1-codex-mini
- Perplexity: sonar, sonar-pro, sonar-reasoning-pro, sonar-deep-research, llama-3.1-sonar
- Gemini: 2.5-pro, 2.5-flash, 3-flash-preview, 3-pro-preview, 2.0-flash-exp
- DGX/vLLM: Qwen3-Coder-30B, Qwen3-Coder-Next, Qwen3-Next-80B (Instruct + Thinking), RedHatAI Qwen3-30B
- Ollama: qwen2.5-coder:32b, qwen2.5-coder (small), qwen3:30b-a3b
- Other: openai/gpt-oss

**v1.15.6 scope:** Data structure + registry only. Profiles are NOT yet consulted by `chat.py`. The profile-driven tool loop integration happens in v1.16.0.

**Key files:**
- `ppxai/engine/model_profiles.py` — Profiles and registry (488 lines)
- `tests/test_model_profiles.py` — 41 tests

### 3. Brace-Counting JSON Parser (P2)

**What:** Replaced regex-based JSON extraction in `engine/tools/parser.py` with a brace-counting parser that correctly handles nested braces.

**Why:** The previous regex `\{[^}]+\}` broke when parsing `apply_patch` tool calls containing code diffs with `{` and `}` characters. The regex would match partial JSON, causing parse failures.

**How:** `_find_json_objects()` scans text character-by-character, tracking brace depth and string literal boundaries. It correctly handles:
- Nested braces in code diffs
- Escaped characters inside strings
- Multiple JSON objects in a single response
- Markdown code fences around JSON

Both `parse_tool_call()` and `strip_tool_json_from_text()` now use this parser.

### 4. Benchmark Infrastructure

**54+ runs across 27 model variants** with the improved benchmark runner:

| Rank | Model | Score | Tool Calling |
|------|-------|-------|-------------|
| 1 | o4-mini | 100.0% | prompt-based |
| 2 | gpt-4.1-mini | 100.0% | prompt-based |
| 3 | gemini-3-flash-preview | 100.0% | native |
| 4 | sonar-pro | 100.0% | native |
| 5 | gpt-oss-120b | 89.1% | prompt-based |
| 6 | Qwen3-Coder-30B | 81.2% | native |
| 7 | gemini-2.5-pro | 81.2% | native |
| 8 | gemini-2.5-flash | 81.2% | native |
| 9 | sonar | 75.0% | native |
| 10 | gpt-5.2 | 70.3% | native |

**Benchmark improvements:**
- `--tool-calling-method` flag to force native/prompt-based per run
- `--debug` flag saves per-request JSON with full AI responses
- Engine bypass: benchmark calls provider directly (no engine tool conflicts)
- Profile-aware routing: benchmark consults ModelProfile for tool mode
- Prompt-based scoring fix: `tool_json_in_content` penalty removed for prompt-based mode

---

## Benchmark Findings

The 27-model analysis identified 5 architectural gaps in `chat.py`:

| Gap | Issue | v1.15.6 Fix | v1.16.0 Fix |
|-----|-------|------------|------------|
| 1 | Binary native/prompt decision too coarse | Model profiles encode per-model strategy | Profile-driven tool loop |
| 2 | Synthetic tool result messages | — | Proper `tool` role messages |
| 3 | Only first tool call processed | — | Multi-tool support |
| 4 | Tool JSON leaks in response text | `strip_tool_json_from_text()` | — |
| 5 | No fallback between modes | Profile `fallback_on_empty` flag | Adaptive fallback |

---

## Files Changed

### New Files
- `ppxai/engine/providers/openai_native.py` — Native OpenAI provider
- `ppxai/engine/model_profiles.py` — Model profile system
- `tests/test_openai_native.py` — OpenAI provider tests
- `tests/test_model_profiles.py` — Model profile tests
- `docs/archive/MODEL-BEHAVIOR-ANALYSIS.md` — 27-model benchmark analysis
- `docs/archive/RELEASE-PLAN-v1.15.6-v1.16.0.md` — Phased release plan (archived)
- `scripts/package-windows-zip.ps1` — Windows offline deployment packager
- `benchmarks/llm-eval/results/*.json` — 54+ benchmark result files

### Modified Files
- `ppxai/engine/tools/parser.py` — Brace-counting parser, JSON stripping, truncated tool detection
- `ppxai/engine/providers/base.py` — Added `get_model_profile()`
- `ppxai/engine/providers/gemini.py` — Added `get_model_profile()`
- `ppxai/engine/chat.py` — JSON stripping integration, AGENTS.md hints for native providers
- `benchmarks/llm-eval/engine_runner.py` — Profile-aware routing, debug logging, engine bypass
- `benchmarks/llm-eval/response_quality.py` — Prompt-based scoring awareness
- `benchmarks/llm-eval/test_cases.py` — Profile-aware payload calibration

---

## Migration Notes

**No breaking changes.** v1.15.6 is fully backwards-compatible:

- Model profiles exist but are NOT consulted by `chat.py` (v1.16.0)
- `OpenAINativeProvider` only affects `openai` provider; other providers unchanged
- Existing `ppxai-config.json` configurations work without modification
- Existing sessions load without changes

**For OpenAI users:** The `openai` provider now uses the native provider automatically. If you experience issues, you can switch back to the compatible provider by configuring your OpenAI endpoint as a `custom` provider instead.

---

## Test Summary

| Category | Count |
|----------|-------|
| Model profile tests | 41 |
| OpenAI provider tests | 46 |
| Parser tests (existing + enhanced) | ~30 |
| All other tests | ~1,232 |
| **Total** | **1,349** |

All tests passing on Windows 11 (Python 3.12).
