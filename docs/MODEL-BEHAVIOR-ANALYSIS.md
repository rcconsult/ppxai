# Model Behavior Analysis & ppxai Architecture Recommendations

**Created:** 2026-02-19
**Last updated:** 2026-02-22
**Status:** Living document — updated with each benchmark session

---

## Part 1: Model Behavior Taxonomy

Based on 49+ benchmark runs across 27 unique models, we identify **5 distinct behavior archetypes** — not just the binary native/prompt-based split.

### Tier S: Full Native Tool Calling (80%+)

| Model | Best | Tool Calling | Code Editing | Key Trait |
|-------|------|-------------|-------------|-----------|
| Gemini 2.5 Pro | 81.3% | 100% | 100% | Clean native, no workarounds needed |
| Qwen3-Coder-30B FP8 | 81.3% | 100% | 100% | Hermes parser, stable |
| Gemini 2.5 Flash | 81.3% | — | — | Same as Pro |

These models use native tool calling correctly: structured `tool_calls`, proper argument formatting, no JSON leaking into response text. ppxai's current architecture works perfectly for them.

### Tier A: Native-Preferred with Quirks (65-75%)

| Model | Best | Best Method | Key Quirk |
|-------|------|------------|-----------|
| gpt-5.2 | 70.3% | native | 100% hallucination resistance but 0% code editing, duplicate tool calls |
| gpt-4.1 | 67.2% | native | High variance (48-67%), hallucinates nonexistent tools |
| gpt-5-mini | 67.2% | native | `tool_json_in_content` — outputs JSON in text AND via tool_calls |
| gpt-5 | 62.5% | native | Extremely slow (25 min), timeouts |

These models work better with native tool calling but exhibit hybrid behaviors. The `tool_json_in_content` anti-pattern is the critical issue: the model outputs tool JSON in its response text **simultaneously** with structured tool_calls.

### Tier B: Prompt-Based Preferred (60-72%)

| Model | Best | Best Method | Key Quirk |
|-------|------|------------|-----------|
| gpt-4.1-mini | 71.9% | prompt_based | Native only gets 60.9% |
| gpt-5.1-codex | 64.1% | prompt_based | Responses API, can't do native function calls |
| o4-mini | 62.5% | prompt_based | Native returns empty responses (10.9%) |

These models produce better results when tools are described in the prompt and tool calls are parsed from text output. Forcing native tool calling on them causes regressions or total failure.

### Tier C: Marginal / High Variance (40-60%)

| Model | Best | Issue |
|-------|------|-------|
| gpt-4.1-nano | 50.0% | Hallucinates tools (replace_block, execute_shell_command) |
| gpt-5.1-codex-mini | 40.6% | Low capability, not enough quality |
| Qwen3-Coder-Next FP8 | 60.9% | Declining across runs, high variance |

### Tier D: Broken / Unusable (<40%)

| Model | Best | Issue |
|-------|------|-------|
| o4-mini (native) | 10.9% | Returns empty responses for everything |
| gemini-2.0-flash-exp | 10.9% | Fundamentally broken |
| llama-3.1-sonar-large | 10.9% | No tool calling capability |

---

## Part 2: The Spectrum of Tool Calling Behaviors

The current binary native/prompt-based decision is too coarse. Here's the actual spectrum:

```
BEHAVIOR SPECTRUM (not binary!)

  Pure Native     Native+Leaky    Hybrid          Pure Prompt    Broken
  ──────────────────────────────────────────────────────────────────
  Gemini 2.5      gpt-5-mini      gpt-4.1-mini    gpt-5.1-codex  o4-mini
  Qwen3-Coder     gpt-5.2         o4-mini(pb)     codex-mini     (native)
                   gpt-4.1                         GPT-OSS
                   gpt-5
```

**Pure Native**: Model uses structured tool_calls correctly, no JSON in text.

**Native + Leaky**: Model uses structured tool_calls BUT also outputs JSON in response text. The current parser ignores the text JSON when native calls are present, which is correct — but the text JSON confuses the response validator and wastes tokens.

**Hybrid**: Model performs differently depending on tool type or conversation state. gpt-4.1-mini scores 71.9% prompt-based but only 60.9% native. These need per-model routing decisions.

**Pure Prompt**: Model can't or shouldn't use native function calling. Tool calls are extracted from text output. This works well for GPT-OSS (Harmony bypass) and codex models (Responses API).

**Broken**: Model fundamentally can't do what's asked regardless of mode.

---

## Part 3: Detailed Benchmark Results

### Best Score Per Unique Model (Full Suite Only)

| # | Model | Best Score | Provider | Best Tool Method | # Runs |
|---|-------|-----------|----------|-----------------|--------|
| 1 | gemini-2.5-pro | 81.25% | gemini | native | 2 |
| 2 | Qwen3-Coder-30B-A3B-FP8 | 81.25% | asusai-vllm | native | 1 |
| 3 | gemini-2.5-flash | 81.25% | gemini | n/a | 1 |
| 4 | sonar | 75.00% | perplexity | n/a | 1 |
| 5 | gpt-4.1-mini | 71.88% | openai | prompt_based | 3 |
| 6 | gpt-5.2 | 70.31% | openai | native | 5 |
| 7 | gemini-3-pro-preview | 70.31% | gemini | n/a | 1 |
| 8 | gpt-4.1 | 67.19% | openai | native | 4 |
| 9 | gpt-5-mini | 67.19% | openai | native | 5 |
| 10 | sonar-reasoning-pro | 67.19% | perplexity | n/a | 1 |
| 11 | gpt-5.1-codex | 64.06% | openai | prompt_based | 8 |
| 12 | gpt-5 | 62.50% | openai | native | 5 |
| 13 | o4-mini | 62.50% | openai | prompt_based | 4 |
| 14 | Qwen3-Coder-Next-FP8 | 60.94% | asusai-vllm | n/a | 3 |
| 15 | gpt-4.1-nano | 50.00% | openai | native | 3 |
| 16 | gpt-5.1-codex-mini | 40.63% | openai | native | 3 |

*Note: gemini-3-flash-preview (100%) and sonar-pro (100%) only ran 3-test subset, not comparable.*

### Per-Category Scores (OpenAI Models, Best Run)

| Model | Overall | Halluc. | Tools | Code | Format | Instruct | Reason | Recovery |
|-------|---------|---------|-------|------|--------|----------|--------|----------|
| **gpt-5.2** | **70.3%** | **100** | 28.6 | 0 | 100 | 100 | 66.7 | 100 |
| **gpt-4.1** | **67.2%** | 33.3 | 64.3 | **71.4** | 100 | 100 | **100** | 66.7 |
| **gpt-5-mini** | **67.2%** | 55.6 | 42.9 | 28.6 | 100 | 100 | **100** | 100 |
| **gpt-5.1-codex** | **64.1%** | 61.1 | 64.3 | 0 | 100 | 100 | 66.7 | 66.7 |
| **gpt-5** | **62.5%** | 55.6 | 50.0 | 0 | 100 | 100 | **100** | 66.7 |
| **gpt-4.1-mini** | **60.9%** | 33.3 | 57.1 | 0 | 100 | 100 | **100** | 100 |
| **gpt-4.1-nano** | **50.0%** | 16.7 | 42.9 | 42.9 | 100 | 57.1 | 66.7 | 100 |
| **o4-mini** | **10.9%** | 16.7 | 0 | 0 | 33.3 | 0 | 0 | 33.3 |

### Per-Category Scores (Non-OpenAI, Best Run)

| Model | Overall | Halluc. | Tools | Code | Format | Instruct | Reason | Recovery |
|-------|---------|---------|-------|------|--------|----------|--------|----------|
| **Gemini 2.5 Pro** | **81.3%** | 55.6 | **100** | **100** | 66.7 | **100** | 66.7 | **100** |
| **Qwen3-Coder-30B** | **81.3%** | 55.6 | **100** | **100** | **100** | 71.4 | 66.7 | **100** |
| **Sonar** | **48.4%** | 38.9 | 28.6 | 0.0 | **100** | 57.1 | 66.7 | **100** |

### Native vs Prompt-Based per Model

| Model | Native Best | Prompt Best | Winner |
|-------|------------|-------------|--------|
| gpt-5.2 | **70.3%** | 67.2% | Native |
| gpt-4.1 | **67.2%** | 62.5% | Native |
| gpt-5 | **62.5%** | 48.4% | Native |
| gpt-5-mini | **67.2%** | 65.6% | Native (marginal) |
| gpt-4.1-mini | 60.9% | **71.9%** | **Prompt** |
| gpt-5.1-codex | 57.8% | **64.1%** | **Prompt** |
| o4-mini | 10.9% | **62.5%** | **Prompt** |
| gpt-4.1-nano | **50.0%** | — | Native |
| gpt-5.1-codex-mini | **40.6%** | 10.9% | Native |

---

## Part 4: Recurring Failure Modes

### A. Tool JSON in Content (`tool_json_in_content`)

**Affected:** GPT-5, GPT-5-mini, GPT-5.1-codex (all runs), GPT-5.2 (prompt_based), GPT-4.1-mini, GPT-4.1-nano, Sonar

The model outputs tool call JSON as text in the response content instead of (or in addition to) using the `tool_calls` API field. This is the **single most damaging anti-pattern** because it causes code_editing tests to fail even when the patch content is correct.

### B. Hallucinated Tools

- GPT-4.1: `list_directory` (doesn't exist)
- GPT-5.1-codex: `execute_shell_command`, `list_directory`
- GPT-4.1-nano: `get_working_directory`, `replace_block`
- GPT-5-mini: mentioned tools in content that weren't actually called

### C. Large Payload Truncation

Failed for nearly all OpenAI models. Expected ~3500 chars but got 0-2652. Consistent weakness.

### D. Failure Acknowledgment Blindness

`respects_tool_failure` and `repeated_failure_acknowledgment` failed for 7 of 8 OpenAI models (only GPT-5.2 passed). Models either kept retrying, responded about the failure incorrectly, or output more JSON instead of text acknowledgment.

### E. Contradiction Detection

`contradiction_detection` defeats **every model** in the full test suite — the universal hallucination resistance bottleneck. Even 81.25% models (Gemini 2.5 Pro, Qwen3-Coder-30B) fail this test.

### F. Code Editing Universally Weak (OpenAI)

Only GPT-4.1 achieved >0% code editing (71.4%). All other OpenAI models score 0%. Dominant failures: empty patches, `tool_json_in_content`, using wrong tools (read_file instead of apply_patch).

---

## Part 5: Architectural Gaps in Current ppxai

### Gap 1: Binary Decision at Wrong Layer

**Current state** (`chat.py:210`):
```python
use_native_tools = bool(provider_caps and provider_caps.native_tool_calling)
```

This is a single boolean, decided once before the tool loop, applied uniformly for all iterations. Problems:

1. **No per-model profile** — gpt-4.1-mini needs prompt-based but gpt-5.2 needs native, yet both come through the same `openai` provider
2. **No adaptation** — if native tool calling fails (empty response, `tool_json_in_content`), the loop can't switch to prompt-based mid-conversation
3. **No hybrid handling** — when a model returns BOTH native tool_calls AND JSON in text, the code takes the native call and ignores the text

### Gap 2: Tool Results as Synthetic Messages

**Current state** (`chat.py:437-444`):
```python
ctx.session.add_message(Message("assistant", f"I'll use the {tool_name} tool..."))
ctx.session.add_message(Message("user", f"The {tool_name} tool returned..."))
```

Tool results are always injected as `assistant`/`user` message pairs regardless of mode. For native tool calling models, OpenAI expects `tool` role messages with `tool_call_id` matching. The current approach works but is suboptimal.

### Gap 3: Single Tool Call Per Iteration

**Current state** (`chat.py:331`):
```python
tc = native_tool_calls[0]
```

Only the first native tool call is processed. Models that return multiple parallel tool calls have all but the first silently discarded.

### Gap 4: No Response Deduplication

When `tool_json_in_content` occurs, the model outputs tool JSON in text AND via `tool_calls`. The native path takes the structured call, but the text JSON remains in the streamed response, confusing users and wasting context.

### Gap 5: Provider Capabilities Are Static

`ProviderCapabilities` is a simple dataclass with boolean flags. No way to express "fall back to prompt-based if native returns empty" or "strip JSON from response text when native tool calls are present."

---

## Part 6: Proposed Architecture — Model Behavior Profiles

Instead of a single `native_tool_calling: bool`, introduce a **Model Behavior Profile** system:

```python
@dataclass
class ToolCallingProfile:
    """Describes how a specific model handles tool calls."""

    # Primary mode
    mode: Literal["native", "prompt_based", "auto"] = "native"

    # Fallback behavior
    fallback_on_empty: bool = False          # Switch to prompt-based if native returns empty
    fallback_on_failure: bool = False        # Switch to prompt-based after N native failures

    # Response cleaning
    strip_json_from_text: bool = False       # Remove tool JSON from text when native calls present

    # Multi-tool support
    parallel_tool_calls: bool = False        # Process all native tool calls, not just first

    # API routing (OpenAI-specific)
    api_path: Literal["chat", "responses", "auto"] = "chat"


@dataclass
class ModelProfile:
    """Complete behavior profile for a model."""
    tool_calling: ToolCallingProfile
    max_tokens: int = 4096
    supports_reasoning: bool = False
    restricted_params: List[str] = field(default_factory=list)
```

### Example Profiles

```python
PROFILES = {
    # Tier S: Clean native
    "gemini-2.5-*": ModelProfile(
        tool_calling=ToolCallingProfile(mode="native")
    ),

    # Tier A: Native + cleanup
    "gpt-5.2": ModelProfile(
        tool_calling=ToolCallingProfile(
            mode="native",
            strip_json_from_text=True,
            parallel_tool_calls=True,
        ),
        restricted_params=["temperature", "top_p"]
    ),

    # Tier B: Prompt preferred
    "gpt-4.1-mini": ModelProfile(
        tool_calling=ToolCallingProfile(mode="prompt_based")
    ),

    # Tier B: Responses API
    "gpt-5.1-codex*": ModelProfile(
        tool_calling=ToolCallingProfile(
            mode="prompt_based",
            api_path="responses"
        )
    ),

    # Tier B: Auto-detect
    "o4-mini": ModelProfile(
        tool_calling=ToolCallingProfile(
            mode="auto",
            fallback_on_empty=True,
        ),
        supports_reasoning=True
    ),
}
```

### What Changes in chat.py

The binary decision point becomes profile-driven:

```python
# BEFORE (line 210):
use_native_tools = bool(provider_caps and provider_caps.native_tool_calling)

# AFTER:
profile = ctx.provider.get_model_profile(ctx.model)
tc_mode = profile.tool_calling.mode
if tc_mode == "auto":
    tc_mode = "native"  # Start with native, may fallback
```

In the tool extraction phase:

```python
# Profile-aware extraction
if native_tool_calls and tc_mode in ("native", "auto"):
    tool_calls_to_process = (native_tool_calls
                             if profile.tool_calling.parallel_tool_calls
                             else [native_tool_calls[0]])

    if profile.tool_calling.strip_json_from_text and full_response:
        full_response = strip_tool_json_from_text(full_response)

    tool_call = unwrap_tool_call(tool_calls_to_process[0])

elif not native_tool_calls and tc_mode in ("prompt_based", "auto"):
    tool_call = parse_tool_call(full_response, ctx.tool_manager.get_tool)

elif not native_tool_calls and tc_mode == "native" and profile.tool_calling.fallback_on_empty:
    # Native mode returned nothing — fallback to prompt-based parsing
    tool_call = parse_tool_call(full_response, ctx.tool_manager.get_tool)
    if tool_call:
        tc_mode = "prompt_based"  # Switch for rest of conversation
```

### Where Profiles Come From

Three sources, merged with priority:

1. **Built-in defaults** — hardcoded profiles for known models (replaces scattered prefix tuples)
2. **ppxai-config.json** — user overrides per model or model pattern:
   ```json
   {
     "models": {
       "gpt-4.1-mini": {
         "tool_calling": {
           "mode": "prompt_based"
         }
       }
     }
   }
   ```
3. **AGENTS.md hints** — existing hint system can influence tool calling behavior

---

## Part 7: Concrete Next Steps

### Immediate Wins (No Architecture Change)

1. **Override `get_capabilities_for_model()` for o4-mini** — return `native_tool_calling=False`
2. **Override for gpt-4.1-mini** — same, return `native_tool_calling=False`
3. **Add JSON stripping** — when native tool calls are present, strip `{"tool":...}` JSON blocks from the response text before yielding `STREAM_CHUNK` events
4. **Add unindexed results to index.json** — gpt-4.1-mini at 71.9% and o4-mini at 62.5% are significant findings

### Phase 1: Model Profile System (Non-Breaking, Foundational)

1. Create `ppxai/engine/model_profiles.py` with `ToolCallingProfile` and `ModelProfile` dataclasses
2. Create a profile registry with glob-pattern matching for model names
3. Populate with profiles for all 27 benchmarked models
4. Wire `get_model_profile()` into providers (providers can override/extend profiles)
5. No behavior change yet — just the data structure

### Phase 2: Profile-Driven Tool Loop (Incremental Migration)

1. Replace the binary decision in `chat.py:210` with profile lookup
2. Add `strip_json_from_text` response cleaning
3. Add `fallback_on_empty` adaptive behavior
4. Keep backwards compatibility — missing profiles default to current behavior

### Phase 3: Multi-Tool Support

1. Process all native tool calls when `parallel_tool_calls=True`
2. Use proper `tool` role messages with `tool_call_id` for native mode
3. Add per-iteration tool call tracking for better loop detection

### Phase 4: Config Integration

1. Allow `tool_calling` overrides in ppxai-config.json per model
2. Allow AGENTS.md hints to influence profile selection
3. Add `/model info <name>` command showing active profile

### What NOT to Do

- Don't try to make all models work equally well — Tier D models are broken and no architecture change fixes that
- Don't over-engineer the profile system — start with the 5 fields shown above, expand only when benchmarks prove the need
- Don't break existing provider implementations — `OpenAICompatibleProvider` and `GeminiProvider` should work unchanged with default profiles

---

## Part 8: Addressing the OpenAI Native Provider Regression

The regression isn't that `OpenAINativeProvider` is wrong — it's that models previously routed through `OpenAICompatibleProvider` with its simpler assumptions now expose their full quirky behaviors through the native path. Specifically:

1. **gpt-4.1-mini scored 71.9% prompt-based but only 60.9% native** — the old path would have used prompt-based by default, which was actually better
2. **o4-mini is completely broken on native** — but the unindexed result shows 62.5% on prompt-based, which is competitive
3. **gpt-5.1-codex** was correctly identified as needing prompt-based via `get_capabilities_for_model()`, and its improving trajectory (40.6% -> 64.1%) validates that approach

The fix is the profile system, NOT reverting to `OpenAICompatibleProvider`. The native provider correctly handles the two OpenAI API paths, restricted parameters, and reasoning tokens. It just needs better per-model tool calling decisions.

---

## Key Differentiators: What Separates 80%+ from Sub-50%

| Capability | 80%+ Models | Sub-50% Models |
|------------|-------------|----------------|
| **Native tool calling** | Use OpenAI-format `tool_calls` properly | Output JSON in content text (anti-pattern) |
| **Tool identity** | Accept their role as tool-using agents | Refuse tools ("I'm a search assistant") |
| **Multi-tool chaining** | Issue sequential tool calls across turns | Stop after first result, explain textually |
| **Large payloads** | Produce 3300+ char tool arguments | Truncate at ~2650 chars |
| **Code editing** | Clean tool-only responses, no text pollution | Tool calls "work" but polluted with JSON-in-content |
| **Error recovery** | All models handle this well (100%) | Even weak models get 100% here |

The **single biggest differentiator** is clean native tool calling vs. leaky/prompt-based. The **hardest unsolved category** is hallucination resistance — `contradiction_detection` defeats every model tested against the full suite.

---

## Part 9: Feb 22 Update — v1.16.0 Step 2 Results

**Date:** 2026-02-22
**Branch:** feature/v1.16.0
**Changes:** Profile-driven tool loop (Step 2), truncation recovery, sonar profile/hint fixes

### Updated Rankings (Best Score Per Model, Most Recent Run)

| # | Model | Best % | Tier | Provider | Date | Trend |
|---|-------|-------:|------|----------|------|-------|
| 1 | gpt-oss-120b | 89.1 | S | custom (vLLM) | Feb 5 | — |
| 2 | gemini-2.5-flash-lite | 86.2 | S | Gemini | Feb 21 | NEW |
| 3 | gemini-2.5-pro | 85.1 | S | Gemini | Feb 22 | +3.9 |
| 4 | gpt-5.1-codex | 82.8 | S | OpenAI | Feb 22 | +10.9 |
| 5 | gpt-5 | 82.7 | S | OpenAI | Feb 22 | +20.2 |
| 6 | Qwen3-Coder-30B FP8 | 81.3 | S | DGX vLLM | Feb 7 | — |
| 7 | gemini-2.5-flash | 81.3 | S | Gemini | Feb 5 | — |
| 8 | sonar-pro | 76.7 | A | Perplexity | Feb 22 | +7.9 |
| 9 | gemini-3-pro-preview | 76.2 | A | Gemini | Feb 20 | +5.9 |
| 10 | sonar | 73.8 | A | Perplexity | Feb 22 | +3.5 |
| 11 | gemini-3-flash-preview | 73.6 | A | Gemini | Feb 22 | +5.4 |
| 12 | gpt-5.2 | 70.3 | B | OpenAI | Feb 17 | — |
| 13 | sonar-reasoning-pro | 66.2 | B | Perplexity | Feb 22 | -1.0 |
| 14 | gpt-4.1 | 67.2 | B | OpenAI | Feb 17 | — |
| 15 | gpt-5-mini | 67.2 | B | OpenAI | Feb 17 | — |
| 16 | Qwen3-Coder-Next FP8 | 60.9 | B | DGX vLLM | Feb 10 | — |
| 17 | RedHat Qwen3-30B FP8 | 60.9 | B | DGX vLLM | Feb 6 | — |
| 18 | gpt-4.1-nano | 57.8 | C | OpenAI | Feb 17 | — |
| 19 | gpt-5.1-codex-mini | 40.6 | D | OpenAI | Feb 17 | — |
| 20 | llama-3.1-sonar-large | 10.9 | D | Perplexity | Feb 7 | — |
| 21 | gemini-2.0-flash-exp | 10.9 | D | Gemini | Feb 7 | — |

*o4-mini (100%) and gpt-4.1-mini (100%) omitted — volatile, achieved 100% once after hint tuning but median ~62%.*

### Notable Improvements Since Feb 19

| Model | Feb 19 Best | Feb 22 | Delta | Cause |
|-------|------------:|-------:|------:|-------|
| gpt-5 | 62.5% | 82.7% | +20.2 | Partial credit scoring (A12) + AGENTS.md hints |
| gpt-5.1-codex | 64.1% | 82.8% | +18.8 | Belt-and-suspenders hints + native Responses API |
| sonar-pro | 68.8% | 76.7% | +7.9 | AGENTS.md hint fix (removed "use native" contradiction) |
| gemini-3-flash | 57.8% | 73.6% | +15.8 | Steady improvement across 5 runs with hint tuning |

### sonar-reasoning-pro Deep Dive (Feb 22)

Re-benchmarked after v1.16.0 profile/hint fixes. Score essentially flat: 67.2% → 66.2% (-1.0%).

| Category | Score | Notes |
|----------|------:|-------|
| format_compliance | 100% | Perfect |
| instruction_following | 100% | Perfect |
| efficiency | 100% | Perfect (time_to_first_tool_call) |
| agentic_tool_loops | 80% | consecutive_tool_loop partial (40%), others pass |
| code_editing | 71.4% | Major improvement (was 0% in Feb 7 run) |
| error_recovery | 66.7% | tool_error_recovery fails |
| reasoning | 66.7% | dependency_ordering fails |
| tool_calling | 50% | 3/6 fail: simple_tool_call, multi_tool_sequence, no_explain_before_tool |
| hallucination_resistance | 38.9% | Weakest: fails respects_tool_failure, repeated_failure_acknowledgment, multi_turn_consistency |

### Benchmark vs Real-World Gap Analysis

sonar-reasoning-pro exemplifies a critical gap in the current benchmark methodology:

**In benchmarks (66.2%):**
- Single-turn tests, no iterative feedback
- 38.9% hallucination_resistance — claims success after tool failures
- 50% tool_calling — can't reliably produce clean tool calls in isolation
- But 100% format/instruction/efficiency — understands what to do, inconsistent at executing

**In real-world use (observed: high effectiveness):**
- Reasoning tokens plan multi-step approaches before acting
- AGENTS.md hints + conversation history enable course-correction
- Truncation recovery (v1.16.0) provides corrective feedback on failed tool calls
- Chains tool calls across longer sessions with iterative feedback loops

**Key insight:** The benchmark penalizes models that need a feedback loop to perform well. sonar-reasoning-pro's strength is reasoning through problems and adapting when given corrective signals — exactly what the truncation recovery and stuck-loop detection (added in this session) enables.

This validates the need for **Step 7: Benchmark v2** — agentic multi-turn tests that measure iterative recovery, tool call chaining across turns, and response to `[SYSTEM: ...]` corrective messages. The current single-turn benchmark systematically underscores models with strong reasoning but weak single-shot tool execution.

### Sonar Profile/Hint Corrections Applied

**Problem discovered:** All sonar profiles had `mode="native"` but Perplexity API has `native_tool_calling=False`. AGENTS.md hints said "use native tool calling only" — directly contradicting the prompt-based mechanism these models actually use.

**Fixes applied (this session):**
1. All 5 sonar profiles changed to `mode="prompt_based"` in `model_profiles.py`
2. Removed `strip_json_from_text=True` (parser needs the JSON in response text)
3. Perplexity provider hints rewritten: "output ONLY the JSON object" instead of "use native tool calling"
4. Sonar model hints rewritten: explicit JSON format example, small-patch guidance, truncation recovery hints

### Tier Reassignment

Based on Feb 22 results with partial credit scoring:

| Model | Old Tier | New Tier | Justification |
|-------|----------|----------|---------------|
| gpt-5 | B (62.5%) | **S** (82.7%) | Partial credit + hints pushed past 80% |
| gpt-5.1-codex | B (64.1%) | **S** (82.8%) | Steady improvement over 10 runs |
| gemini-2.5-flash-lite | — | **S** (86.2%) | New model, strong first result |
| sonar-pro | A (68.8%) | **A** (76.7%) | Improved but below S threshold |
| sonar | B (70.3%) | **A** (73.8%) | Upgraded with consistent improvement |
| gemini-3-flash-preview | B (57.8%) | **A** (73.6%) | Steady uptrend across 5 runs |
| sonar-reasoning-pro | C (67.2%) | **B** (66.2%) | Flat score, but real-world effectiveness higher |
