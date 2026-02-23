# Release Notes: v1.16.0

**Release Date:** 2026-02-23
**Branch:** feature/v1.16.0
**Focus:** Profile-driven tool loop, multi-tool support, agent UI, benchmark v2

---

## Overview

v1.16.0 rewrites the core tool calling loop in `chat.py` with profile-driven routing, proper `tool` role messages, multi-tool support, and grouped tool call UI across all 4 clients. This is the largest single release in ppxai history.

**Key Numbers:**
- 154 files changed, 30,400+ lines added
- 1,536 tests passing (up from 1,349 in v1.15.6)
- 36 benchmark tests across 9 categories (up from 28 in 7 categories)
- 100+ benchmark runs across 29 model variants
- 7 implementation steps over 4 days

**Breaking Changes:** Tool message format changed from synthetic assistant/user pairs to proper `tool` role messages for native mode. Session migration is automatic (v1.15.x sessions load via `None`-safe `.get()`). Prompt-based mode is unchanged.

---

## Major Changes

### 1. Provider Hierarchy (Step 1)

**What:** All providers now inherit from `BaseProvider` ABC with a shared interface.

**Why:** `chat.py` relied on `hasattr` guards and duck-typing to handle provider differences. This made adding new providers fragile and the tool loop logic hard to follow.

**Changes:**
- `BaseProvider` ABC defines the full provider interface: `stream()`, `get_capabilities_for_model()`, `get_model_profile()`, `list_models()`, `validate_config()`, `_convert_messages()`, `_get_generation_params()`, `_get_max_tokens()`, `_parse_usage()`
- `OpenAINativeProvider`, `GeminiProvider`, and `OpenAICompatibleProvider` all inherit from `BaseProvider`
- Removed all `hasattr` guards from `chat.py` — providers are called through guaranteed interface methods
- 61 new parametrized tests in `test_provider_hierarchy.py`

**Impact:** Internal refactoring only. No user-facing changes.

### 2. Profile-Driven Tool Loop (Step 2)

**What:** `ToolCallingProfile.mode` ("native", "prompt_based", "auto") replaces the binary `native_tool_calling: bool` decision.

**Why:** The v1.15.6 benchmark analysis (27 models, 54+ runs) showed that models need different tool calling strategies:
- o4-mini: 80.8% prompt-based vs 11.5% native
- gpt-4.1-mini: 71.9% prompt-based vs 60.9% native
- GPT-5.2: needs JSON stripping from response text
- Codex models: need Responses API routing

**How it works:**

```
1. Look up ModelProfile for current model
2. Merge with AGENTS.md overrides → ppxai-config.json overrides
3. Check tc_profile.mode:
   - "native" → send tools in API request, parse tool_calls from response
   - "prompt_based" → inject tool schema into system prompt, parse JSON from text
   - "auto" → try native first, fall back to prompt-based on empty/failure
4. Fallback flags:
   - fallback_on_empty → native returns empty → retry with prompt-based
   - fallback_on_failure → native tool parse fails → try prompt-based parser
5. Belt-and-suspenders → models with fallback flags get tool hints in system prompt
   even in native mode (safety net)
```

**Truncation recovery:** Detects raw JSON truncation (unbalanced braces), sends escalating recovery messages, caps retries at 3 (`MAX_TRUNCATION_RETRIES`) with `stuck_tool_loop` WARNING event.

**Key files:**
- `ppxai/engine/chat.py` — Mode routing (~line 470), fallback logic, truncation recovery
- `tests/test_chat_profile_routing.py` — 16 routing tests
- `tests/test_engine_tool_parsing.py` — 7 truncation + 4 stuck-loop tests

### 3. Proper Tool Messages (Step 3)

**What:** Native mode now uses proper `tool` role messages instead of synthetic assistant/user pairs.

**Before (v1.15.x):**
```python
# Synthetic pair — all providers
messages.append(Message(role="assistant", content="[tool call: read_file]"))
messages.append(Message(role="user", content="[tool result: file contents]"))
```

**After (v1.16.0):**
```python
# Native mode — proper tool messages
messages.append(Message(
    role="assistant",
    content="",
    tool_calls=[{"id": "tc_1", "function": {"name": "read_file", "arguments": "..."}}]
))
messages.append(Message(
    role="tool",
    content="file contents",
    tool_call_id="tc_1"
))

# Prompt-based mode — unchanged synthetic pairs
messages.append(Message(role="assistant", content="[tool call: read_file]"))
messages.append(Message(role="user", content="[tool result: file contents]"))
```

**Why:** OpenAI, Gemini, and other providers expect `tool` role messages when using native function calling. Synthetic pairs worked but caused some models to get confused about conversation structure.

**Changes:**
- `Message` dataclass extended with `tool_calls: Optional[List[Dict]]` and `tool_call_id: Optional[str]`
- All 4 providers handle `tool` role in `_convert_messages()`:
  - `base.py` — default conversion
  - `openai_native.py` — OpenAI-specific format with function wrapper
  - `openai_compat.py` — OpenAI-compatible format
  - `gemini.py` — Gemini's `functionCall`/`functionResponse` format
- Session serialization updated to save/load new fields
- v1.15.x session migration: `m.get("tool_calls")` / `m.get("tool_call_id")` returns `None`
- Message order validation allows `tool` messages after `assistant(tool_calls)`
- 28 new tests in `test_tool_messages.py`

### 4. Multi-Tool Support (Step 4)

**What:** All native tool calls in a response are processed, not just the first one.

**Before:** `native_tool_calls[0]` — only the first tool call was executed.

**After:** `for tc in tool_calls_list` — all tool calls are executed sequentially.

**Gating:** The `parallel_tool_calls` profile flag controls this behavior:
- `True` (qwen3-coder, gpt-5.2, gemini-3.1-pro-customtools): Process all tool calls
- `False` (default): Process only the first tool call (preserves v1.15.x behavior)

**Sequential execution:** Even when processing multiple calls, they're executed one at a time with individual consent prompts and loop detection per tool.

**Key files:**
- `ppxai/engine/chat.py` — Multi-tool loop (~line 639), profile gating (~line 607)

### 5. Agent UI Noise Reduction (Step 5)

**What:** Tool calls are grouped per iteration with collapsible UI across all 4 clients.

**New engine events:**
- `TOOL_GROUP_START` — emitted before each iteration's tool calls (contains iteration number)
- `TOOL_GROUP_END` — emitted after (contains tool names, success/failure counts)
- `AGENT_COMPLETE` — emitted when tool loop finishes (iteration count, commit hash)

**Client rendering:**

| Client | Rendering |
|--------|-----------|
| Web app | Collapsible `.tool-group` containers, checkpoint bubble suppression, undo badge on commits only |
| VSCode | Tool group forwarding via `stream.ts` → `chatPanel.ts`, CSS styling |
| ppxaide TUI | Non-verbose: one summary line per group. Verbose: unchanged individual bubbles |
| ppxai Rich CLI | Dim separator lines with iteration number and status |

**SSE fixes:**
- Event type dispatch: side-channel events now emit their actual `EventType` instead of all being sent as `consent_request`
- Consent deadlock: SSE generator uses racing poll pattern (`asyncio.ensure_future` + 100ms polling) instead of `async for`

### 6. Config Integration (Step 6)

**What:** Per-model tool calling overrides with 3-layer precedence.

**Precedence (highest wins):**
1. `ppxai-config.json` — user's explicit config
2. `AGENTS.md` — project-specific hints with `tool_calling:` YAML front matter
3. Built-in profile — `model_profiles.py` default

**ppxai-config.json example:**
```json
{
  "providers": {
    "local-vllm": {
      "models": {
        "*/qwen3-coder-30b*": {
          "tool_calling": {
            "mode": "native",
            "parallel_tool_calls": true
          }
        }
      }
    }
  }
}
```

**AGENTS.md example:**
```yaml
tool_calling:
  "gpt-5.2*":
    mode: native
    strip_json_from_text: true
  "o4-mini*":
    mode: prompt_based
```

**`/model info` command:** Shows effective profile with source attribution per field (e.g., "mode: native (built-in profile)" vs "mode: prompt_based (AGENTS.md override)").

**Key files:**
- `ppxai/config/__init__.py` — `get_tool_calling_config()`
- `ppxai/engine/bootstrap.py` — `_parse_tool_calling_section()`, `get_tool_calling_overrides()`
- `ppxai/engine/chat.py` — `_get_effective_profile()` (3-layer merge)
- 16 new tests across config, bootstrap, and profile merging

### 7. Benchmark v2 (Step 7)

**What:** Expanded from 28 tests/7 categories to 36 tests/9 categories with agentic multi-turn tests, efficiency metrics, and AGENTS.md delta testing.

**New categories:**
- `agentic_tool_loops` — multi-turn tool call chains requiring search → read → edit patterns
- `efficiency` — measures token usage and tool call redundancy

**New tests:**

| Test | Category | Description | Scoring |
|------|----------|-------------|---------|
| `patch_apply_verify` | code_editing | Generate patch, apply with `_replace_hunk()`, verify fix | 0.0/0.5/0.7/1.0 |
| `search_then_edit` | agentic_tool_loops | search_code → read_file → apply_patch (3 turns) | steps/3 |
| `fix_verify` | agentic_tool_loops | write → test → fail → fix → retest (4 turns) | steps/4 |
| `information_gathering` | agentic_tool_loops | Find and read 3 auth-related files | files_found/3 |
| `error_recovery_chain` | agentic_tool_loops | Handle not-found → search → read → permission denied (4 turns) | steps/4 |
| `multi_file_review` | agentic_tool_loops | Read all files before making claims | files_read/total |
| `claim_without_action` | hallucination_resistance | Refuse to fabricate without tool calls | 0.0 or 1.0 |
| `consecutive_tool_loop` | agentic_tool_loops | 5-step dependent chain | steps/5 |
| `time_to_first_tool_call` | efficiency | Penalize preamble >100 chars | 0.0/0.5/1.0 |
| `tool_call_efficiency` | efficiency | Score by redundant calls vs optimal | 0.3-1.0 |

**AGENTS.md delta testing:**
- `--agents-md both` runs suite twice per model (with/without AGENTS.md hints)
- Reports per-category score delta and overall percentage lift
- Biggest delta: gemini-3.1-pro-customtools +20.1% (81.5% → 61.4%)

**Token/tool tracking:**
- `total_tokens` and `total_tool_calls` in benchmark metadata
- Per-test `tokens_used` and `tool_calls_made` in test details

**Duplicate tool call detection:**
- `_dedup_tool_call()` helper returns `[DUPLICATE CALL]` feedback for repeated tool+args
- `exempt_tools` set for tools with intentionally varying results (run_command, search_code)

---

## Benchmark Rankings (v1.16.0, 36 tests)

| Rank | Model | Score | Mode | Tier |
|------|-------|-------|------|------|
| 1 | qwen3-coder (cloud) | 95.8% | native | S |
| 2 | gpt-5.2 | 91.4% | native | A |
| 3 | gemini-2.5-flash | 90.6% | native | S |
| 4 | gpt-5 | 89.1% | native | A |
| 5 | gemini-2.5-pro | 87.5% | native | S |
| 6 | gpt-5-mini | 86.5% | native | A |
| 7 | gemini-3-flash | 84.4% | native | S |
| 8 | sonar-pro | 84.4% | prompt-based | A |
| 9 | gpt-4.1 | 82.8% | native | A |
| 10 | gemini-3.1-pro-customtools | 81.5% | native | A |
| 11 | gemini-3.1-pro | 81.5% | native | A |
| 12 | Qwen3-Coder-30B (DGX) | 81.2% | native | S |
| 13 | o4-mini | 80.8% | prompt-based | B |
| 14 | sonar | 76.6% | prompt-based | B |
| 15 | gpt-4.1-mini | 71.9% | prompt-based | B |

### AGENTS.md Delta Testing Results

| Model | WITH | WITHOUT | Delta |
|-------|------|---------|-------|
| gemini-3.1-pro-customtools | 81.5% | 61.4% | +20.1% |
| sonar-pro | 84.4% | 68.7% | +15.7% |
| gpt-5.2 | 91.4% | 82.8% | +8.6% |
| gemini-2.5-flash | 90.6% | 84.4% | +6.2% |
| qwen3-coder | 95.8% | 93.7% | +2.1% |

---

## New Commands

### `/ls` — Directory Listing

Lists files and directories with size, modification time, and type indicators.

```
/ls                    # List current directory
/ls /path/to/dir       # List specific directory
```

Available in ppxaide TUI, Web app, and ppxai Rich CLI. HTTP endpoint: `GET /files/list?path=...`

### `/tree` — Directory Tree

Shows directory structure as an indented tree with file counts.

```
/tree                  # Tree of current directory
/tree /path/to/dir     # Tree of specific directory
/tree --depth 2        # Limit depth
```

Available in all 3 clients. HTTP endpoint: `GET /files/tree?path=...&depth=...`

### `/model info` — Model Profile Info

Shows the effective tool calling profile for the current model with source attribution.

```
/model info
# Output:
# Model: gpt-5.2
# Tool Calling Profile:
#   mode: native (built-in profile)
#   strip_json_from_text: true (built-in profile)
#   parallel_tool_calls: true (AGENTS.md override)
#   fallback_on_empty: false (default)
```

---

## Session Management

### Model Switch Context Reset

Switching models now resets session context to prevent cross-model confusion:
- `session.reset_for_model_switch()` clears conversation history
- Commands show count of cleared messages
- Session restore paths pass `reset_context=False` to preserve history on load

### Per-Model Iteration Limits

`ModelProfile.max_tool_iterations` sets the maximum tool loop iterations per model:

| Model | Max Iterations |
|-------|---------------|
| gemini-2.5-pro/flash | 25 |
| gemini-3.1-pro | 20 |
| sonar-pro, sonar | 20 |
| qwen3-coder | 20 |
| codex-mini | 20 |
| Default | 15 |

### Session Pollution Detection

After the first tool loop iteration, `check_session_pollution()` computes bigram similarity between the model's latest response and the previous one. Similarity >90% triggers a WARNING event, indicating the model is repeating itself.

### SSE Disconnect Detection

`request.is_disconnected()` is checked in the SSE event generator. When a client disconnects mid-stream, the server stops processing instead of continuing to generate events into the void.

---

## Files Changed

### New Files

| File | Description |
|------|-------------|
| `tests/test_provider_hierarchy.py` | 61 provider hierarchy tests |
| `tests/test_chat_profile_routing.py` | 16 profile routing + 11 truncation tests |
| `tests/test_tool_messages.py` | 28 tool message format tests |
| `benchmarks/llm-eval/test_cases.py` (8 new tests) | Agentic + efficiency benchmark tests |

### Modified Files (Key)

| File | Change |
|------|--------|
| `ppxai/engine/chat.py` | Profile-driven tool loop, proper tool messages, multi-tool, grouped events |
| `ppxai/engine/types.py` | `Message.tool_calls`, `Message.tool_call_id`, new EventTypes |
| `ppxai/engine/session.py` | `reset_for_model_switch()`, tool message serialization, validation |
| `ppxai/engine/client.py` | Model switch reset, config reload |
| `ppxai/engine/providers/base.py` | `BaseProvider` ABC with shared interface |
| `ppxai/engine/providers/openai_native.py` | `tool` role message conversion |
| `ppxai/engine/providers/openai_compat.py` | `tool` role message conversion |
| `ppxai/engine/providers/gemini.py` | `functionCall`/`functionResponse` conversion |
| `ppxai/engine/model_profiles.py` | Updated tiers, Gemini 3.1 profiles |
| `ppxai/engine/bootstrap.py` | `tool_calling` YAML parsing, overrides |
| `ppxai/engine/context.py` | `tool_calling_overrides` scope merging |
| `ppxai/config/__init__.py` | `get_tool_calling_config()` |
| `ppxai/server/http.py` | `/files/list`, `/files/tree`, SSE fixes, consent deadlock fix |
| `ppxai/commands/utility.py` | `/ls`, `/tree` commands |
| `ppxai/commands/provider.py` | `/model info` command |
| `ppxai/commands/session.py` | Model switch reset UI |
| `ppxai/tui/app.py` | Tool group rendering, non-verbose mode |
| `AGENTS.md` | Gemini 3.1 hints, Perplexity rewrite, tool calling YAML |
| `ppxai-config.example.json` | `tool_calling` override examples |
| `benchmarks/llm-eval/engine_runner.py` | AGENTS.md delta, token tracking, partial credit |

---

## Migration Notes

### Session Format

v1.15.x sessions load automatically. The new `tool_calls` and `tool_call_id` fields on `Message` default to `None` when loading old sessions. New sessions saved in v1.16.0 format are not backwards-compatible with v1.15.x.

### Configuration

No configuration changes required. Existing `ppxai-config.json` files work without modification.

**New optional config:** Per-model `tool_calling` overrides in provider config:

```json
{
  "providers": {
    "my-provider": {
      "models": {
        "model-name": {
          "tool_calling": {
            "mode": "prompt_based"
          }
        }
      }
    }
  }
}
```

### AGENTS.md

New optional `tool_calling:` YAML front matter section for project-specific tool calling overrides. Existing AGENTS.md files work unchanged.

### Provider API

`BaseProvider` is now the required base class. Custom providers extending `OpenAICompatibleProvider` are unaffected (it inherits from `BaseProvider`). Direct provider implementations must implement the `BaseProvider` interface.

---

## Test Summary

| Category | Count |
|----------|-------|
| Provider hierarchy tests | 61 |
| Profile routing + truncation tests | 27 |
| Tool message tests | 28 |
| Config + bootstrap + profile merging | 16 |
| Benchmark test definitions | 36 |
| All other tests | ~1,368 |
| **Total** | **1,536** |

All tests passing on macOS (Python 3.12).
