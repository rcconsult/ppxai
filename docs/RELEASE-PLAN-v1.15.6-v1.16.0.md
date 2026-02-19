# Release Plan: v1.15.6 (Foundation) → v1.16.0 (Breaking Changes)

**Created:** 2026-02-19
**Status:** Planning
**Predecessor:** v1.15.5 (released 2026-02-15)
**Active Branch:** `feature/benchmark-openai-models` (native OpenAI provider + benchmarks)
**Analysis:** [MODEL-BEHAVIOR-ANALYSIS.md](MODEL-BEHAVIOR-ANALYSIS.md)

---

## Motivation

The `feature/benchmark-openai-models` branch introduced:
1. **`OpenAINativeProvider`** — correct OpenAI API handling (Chat Completions + Responses API)
2. **49+ benchmark runs** across 27 models revealing 5 architectural gaps in `chat.py`

The benchmark analysis ([MODEL-BEHAVIOR-ANALYSIS.md](MODEL-BEHAVIOR-ANALYSIS.md)) identified that the current binary `native_tool_calling: bool` decision is too coarse. Models like gpt-4.1-mini (71.9% prompt-based vs 60.9% native) and o4-mini (62.5% prompt-based vs 10.9% native) perform significantly worse when forced into the wrong mode.

**Key insight:** The benchmark runner bypasses `chat.py` entirely (calls `provider.chat()` directly), so none of the identified gaps are testable without a real client. The TUI (`ppxai`/`ppxaide`) is the primary test vehicle for these changes.

---

## Benchmark Findings Backlog (P0–P4)

Prioritized issues identified during the benchmark work (49+ runs, 27 models):

| Priority | Issue | Target | Status |
|----------|-------|--------|--------|
| **P0** | **Codex `native_tool_calling` must be False** — Codex models via Responses API never emit native function calls; they output tool JSON as text. With `native_tool_calling=True` the engine sends tools as API params (codex ignores them) and skips prompt injection. Fix: `get_capabilities_for_model()` returns `native_tool_calling=False` for codex models. | v1.15.6 Goal 2 | ✅ Fixed (benchmark runner); needs engine verification |
| **P1** | **AGENTS.md hints skipped for native providers** — Bootstrap/AGENTS.md hints were only injected for prompt-based mode. Native providers (OpenAI, Gemini) never saw the hints. Fix: inject hints into system prompt for ALL modes. | v1.15.6 Goal 1 | ✅ Fixed (chat.py) |
| **P2** | **Port brace-counting JSON parser to engine** — Engine's `tools/parser.py` uses regex which breaks on `apply_patch` with complex diff content containing braces. Benchmark runner already has `_find_json_objects()` with brace-counting. Port it. | v1.15.6 Goal 2 | ✅ Done (`_find_json_objects()` ported, `parse_tool_call()` + `strip_tool_json_from_text()` use brace-counting) |
| **P3** | **Re-benchmark all providers with fixed runner** — All provider scores were artificially low due to engine tool conflicts (engine tools `read_file(filepath)` vs benchmark tools `read_file(path)`). Need to re-run for GPT-5.2, Gemini, Perplexity sonar. | v1.15.6 Goal 4 | ✅ Done (sonar 70.3%, sonar-pro 68.8%, gemini-2.5-pro 75.0%, gemini-3-flash 57.8%, gemini-3-pro 62.5%) |
| **P4** | **Belt-and-suspenders in real engine** — Engine does either native OR prompt-based, never both. If native tool calling is flaky (codex, vLLM HarmonyError), there's no fallback. Consider always including tool text in system prompt even for native providers. | v1.16.0 Goal 1 | ⏳ Pending |

### Key Findings (Unnumbered)

Two critical behavioral findings that inform profile design but don't have direct code fixes:

1. **`*** Begin Patch` format** — GPT-5.2 and codex models use `*** Begin Patch` format instead of unified diff for code editing. This causes 0% code_editing scores. The Model Profile system needs to account for patch format preferences, or AGENTS.md hints must explicitly instruct unified diff.

2. **Perplexity identity leak** — Without AGENTS.md override, Perplexity sonar responds as "I'm Perplexity, a search assistant" and refuses tool use. Score dropped from 75.0% to 48.4% after the engine bypass fix removed implicit AGENTS.md injection. Confirms that AGENTS.md identity hints are critical for Perplexity models.

---

## Release Strategy

### v1.15.6 — Foundation (Non-Breaking)

**Theme:** Model Profile System + Immediate Wins
**Goal:** Ship the `OpenAINativeProvider`, benchmark results, and foundational profile infrastructure. All changes are additive — no existing behavior changes for users who don't use OpenAI models.
**Risk:** Low. Default profiles reproduce current behavior.

### v1.16.0 — Breaking Changes

**Theme:** Profile-Driven Tool Loop + Multi-Tool Support
**Goal:** Replace the binary tool calling decision with profile-driven routing. Change tool result message format. Support parallel tool calls. These are breaking changes to the engine's chat loop that affect all providers.
**Risk:** Medium. Requires thorough re-benchmarking across all providers.

---

## v1.15.6 — Foundation (Non-Breaking)

**Branch:** `feature/benchmark-openai-models` (continue current branch)
**Estimated effort:** 5-7 days

### Goal 1: Merge Native OpenAI Provider (Already Done)

Ship what's already on the branch:

| Item | Status |
|------|--------|
| `OpenAINativeProvider` (812 lines) | ✅ Done |
| Chat Completions + Responses API routing | ✅ Done |
| 404 auto-fallback (Chat → Responses) | ✅ Done |
| `max_completion_tokens` for GPT-5.x/o-series | ✅ Done |
| Restricted param stripping | ✅ Done |
| Reasoning token extraction | ✅ Done |
| 43 unit tests | ✅ Done |
| AGENTS.md hints for OpenAI models | ✅ Done |
| Benchmark results for 9 OpenAI models | ✅ Done |
| Benchmark runner: AGENTS.md + engine bypass | ✅ Done |
| Model behavior analysis document | ✅ Done |

### Goal 2: Immediate Wins (No Architecture Change)

Quick fixes that improve scores without restructuring `chat.py`:

| Item | Description | Backlog | Effort |
|------|-------------|---------|--------|
| **o4-mini → prompt-based** | Override `get_capabilities_for_model()` to return `native_tool_calling=False` for o4-mini | — | 1 hour |
| **gpt-4.1-mini → prompt-based** | Same override for gpt-4.1-mini | — | 1 hour |
| **Codex → prompt-based** | Verify engine `get_capabilities_for_model()` returns `native_tool_calling=False` for codex models (already fixed in benchmark runner) | P0 | 1 hour |
| **JSON stripping in response text** | When native `tool_calls` are present, strip `{"tool":...}` JSON from streamed text | — | 3 hours |
| **Brace-counting JSON parser** | Port `_find_json_objects()` from benchmark runner to `engine/tools/parser.py` (regex breaks on apply_patch diffs with nested braces) | P2 | 3 hours |
| **Index unindexed results** | Add gpt-4.1-mini (71.9% prompt) and o4-mini (62.5% prompt) to benchmark index | — | 30 min |

**Validation:** Re-run benchmarks for o4-mini and gpt-4.1-mini after overrides. Expected improvement:
- o4-mini: 10.9% → ~62.5%
- gpt-4.1-mini: 60.9% → ~71.9%

### Goal 3: Model Profile System (Data Structure Only)

Create the foundational data structures without wiring them into `chat.py`. This is the scaffolding for v1.16.0.

| Item | Description | Effort |
|------|-------------|--------|
| **`model_profiles.py`** | Create `ppxai/engine/model_profiles.py` with `ToolCallingProfile` and `ModelProfile` dataclasses | 2 hours |
| **Profile registry** | `ModelProfileRegistry` with glob-pattern matching for model names | 2 hours |
| **Built-in profiles** | Populate profiles for all 27 benchmarked models based on analysis | 2 hours |
| **Provider integration** | Add `get_model_profile()` to `BaseProvider` interface (default: return None) | 1 hour |
| **OpenAI profiles** | `OpenAINativeProvider.get_model_profile()` returns profiles for known models | 1 hour |
| **Unit tests** | Test profile matching, glob patterns, provider overrides, defaults | 2 hours |

**Dataclass design** (from analysis Part 6):

```python
@dataclass
class ToolCallingProfile:
    mode: Literal["native", "prompt_based", "auto"] = "native"
    fallback_on_empty: bool = False
    fallback_on_failure: bool = False
    strip_json_from_text: bool = False
    parallel_tool_calls: bool = False
    api_path: Literal["chat", "responses", "auto"] = "chat"

@dataclass
class ModelProfile:
    tool_calling: ToolCallingProfile
    max_tokens: int = 4096
    supports_reasoning: bool = False
    restricted_params: List[str] = field(default_factory=list)
```

**No behavior change** — profiles exist but aren't consulted by `chat.py` yet. The immediate wins (Goal 2) use the existing `get_capabilities_for_model()` override mechanism.

### Goal 4: Benchmark Improvements

| Item | Description | Effort |
|------|-------------|--------|
| **Engine runner uses profiles** | Update `engine_runner.py` to consult `ModelProfile` for native vs prompt routing | 2 hours |
| **Prompt-based benchmark runs** | Add `--tool-calling-method prompt_based` CLI flag to force prompt-based | 1 hour |
| **Re-benchmark with overrides** | Run o4-mini, gpt-4.1-mini, gpt-5-mini with correct modes | 2 hours |

### v1.15.6 Testing Strategy

| Test Type | What | Target |
|-----------|------|--------|
| **Unit tests** | ModelProfile dataclasses, registry, glob matching | 15-20 new tests |
| **Unit tests** | OpenAI capability overrides (o4-mini, gpt-4.1-mini, codex) | 5 new tests |
| **Unit tests** | JSON stripping from response text | 5 new tests |
| **Unit tests** | Brace-counting JSON parser (nested braces, apply_patch diffs) | 5 new tests |
| **Benchmarks** | Re-run o4-mini, gpt-4.1-mini, gpt-5.2 to validate improvements | Manual |
| **TUI manual test** | Verify o4-mini conversation with tools works in ppxaide | Manual |
| **Regression** | Full `pytest tests/ -v` passes | ~1250 tests |

### v1.15.6 Deliverables

1. Native OpenAI provider (already done)
2. Model behavior analysis document
3. Benchmark results for 16 unique models
4. Immediate capability overrides (o4-mini, gpt-4.1-mini, codex) — P0
5. Brace-counting JSON parser ported to engine — P2
6. JSON stripping for native tool calls
7. `model_profiles.py` module (data structures + registry)
8. Benchmark runner profile integration
9. Updated AGENTS.md hints

---

## v1.16.0 — Breaking Changes

**Branch:** `feature/v1.16.0` (new branch from master after v1.15.6 merge)
**Estimated effort:** 10-14 days
**Prerequisite:** v1.15.6 merged and validated

### Why v1.16.0 (Not v1.15.7)

These changes modify the core tool loop in `chat.py` which affects **every provider and every client**:

1. **Tool result message format changes** — from synthetic `assistant`/`user` pairs to proper `tool` role messages (Gap 2)
2. **Multi-tool processing** — from `native_tool_calls[0]` to processing all calls (Gap 3)
3. **Adaptive fallback** — tool mode can change mid-conversation (Gap 5)
4. **Profile-driven routing** — replaces the binary decision at `chat.py:210` (Gap 1)

Any of these could cause regressions in providers that rely on the current message format (especially local models via `OpenAICompatibleProvider`).

### Goal 1: Profile-Driven Tool Loop (Gap 1)

Replace the binary decision point in `chat.py:210`:

```python
# BEFORE:
use_native_tools = bool(provider_caps and provider_caps.native_tool_calling)

# AFTER:
profile = ctx.provider.get_model_profile(ctx.model) or default_profile
tc_mode = profile.tool_calling.mode
```

| Item | Description | Effort |
|------|-------------|--------|
| **Replace binary decision** | `chat.py:210` uses profile lookup instead of capability check | 2 hours |
| **`strip_json_from_text`** | When profile says strip AND native tool calls present, clean response text | 3 hours |
| **`fallback_on_empty`** | When native returns empty, fall back to prompt-based parsing | 3 hours |
| **`auto` mode** | Start native, switch to prompt-based on first empty/failure | 2 hours |
| **Belt-and-suspenders** | Always inject tool descriptions into system prompt even for native providers, so fallback parsing has schema context (P4) | 2 hours |
| **Backwards compat** | Missing profile → default profile → current behavior | 1 hour |
| **Tests** | Profile-driven routing unit tests with mock provider | 4 hours |

### Goal 2: Proper Tool Message Format (Gap 2)

Replace synthetic message pairs with proper `tool` role messages:

```python
# BEFORE (chat.py:437-444):
ctx.session.add_message(Message("assistant", f"I'll use the {tool_name} tool..."))
ctx.session.add_message(Message("user", f"The {tool_name} tool returned..."))

# AFTER (native mode):
ctx.session.add_message(Message("assistant", "", tool_calls=[...]))
ctx.session.add_message(Message("tool", result, tool_call_id=tc_id))
```

| Item | Description | Effort |
|------|-------------|--------|
| **Extend `Message` type** | Add `tool_calls` and `tool_call_id` fields to `Message` dataclass | 1 hour |
| **Native mode messages** | Use proper `assistant` (with tool_calls) + `tool` role messages | 3 hours |
| **Prompt-based unchanged** | Keep synthetic pairs for prompt-based mode (models don't expect tool messages) | 0 |
| **Provider message conversion** | Ensure all providers handle `tool` role messages in their `_convert_messages()` | 4 hours |
| **Session serialization** | Update session save/load to handle new message fields | 2 hours |
| **Migration** | Existing sessions with old format still load correctly | 2 hours |
| **Tests** | Message format, session serialization, provider conversion | 4 hours |

### Goal 3: Multi-Tool Support (Gap 3)

Process all native tool calls when the profile allows it:

```python
# BEFORE (chat.py:331):
tc = native_tool_calls[0]  # Only first tool call

# AFTER:
if profile.tool_calling.parallel_tool_calls:
    for tc in native_tool_calls:
        # Execute each tool, collect results
else:
    tc = native_tool_calls[0]
```

| Item | Description | Effort |
|------|-------------|--------|
| **Parallel tool execution** | Process all native tool calls in sequence (not parallel — safety) | 3 hours |
| **Multi-result messages** | Emit multiple `TOOL_CALL`/`TOOL_RESULT` events per iteration | 2 hours |
| **Session messages** | Add all tool call/result message pairs | 1 hour |
| **Consent handling** | Each tool call still requires individual consent | 2 hours |
| **Loop detection** | Update tool loop detection for multi-tool iterations | 1 hour |
| **Tests** | Multi-tool extraction, execution, message format | 3 hours |

### Goal 4: Config Integration

| Item | Description | Effort |
|------|-------------|--------|
| **Config overrides** | `tool_calling` section in `ppxai-config.json` per model | 2 hours |
| **AGENTS.md influence** | Model hints can set `tool_calling_mode: prompt_based` | 2 hours |
| **`/model info`** | New command showing active profile for current model | 2 hours |
| **Documentation** | Config format, profile precedence, migration guide | 3 hours |

### Goal 5: File Navigation (from TODO-v1.16.0.md)

The previously planned v1.16.0 content (file navigation) fits naturally alongside the engine changes:

| Item | Description | Effort |
|------|-------------|--------|
| **`/ls` command** | List files with sizes, permissions, gitignore | 1 day |
| **`/tree` command** | Render directory tree structure | 1 day |
| **CommandResult types** | `DirectoryListingResult`, `DirectoryTreeResult` | 2 hours |
| **Renderer implementations** | Rich + Textual renderers for new result types | 3 hours |

### Goal 6: Provider Hierarchy Refactoring

`OpenAINativeProvider` and `GeminiProvider` are standalone classes that duplicate the entire `BaseProvider` interface (duck typing via `hasattr` guards). This works but is fragile and prevents shared behavior.

| Item | Description | Effort |
|------|-------------|--------|
| **Shared ABC or Protocol** | Make `OpenAINativeProvider` and `GeminiProvider` inherit from `BaseProvider` (or a shared `ProviderProtocol`) | 3 hours |
| **Eliminate duplicate methods** | Move shared methods (`needs_tool`, `get_model_profile`, `_format_error`, `_log_error_traceback`) to base class | 2 hours |
| **Remove `hasattr` guards** | Replace `hasattr(provider, 'get_capabilities_for_model')` / `hasattr(provider, 'get_model_profile')` in `chat.py` with guaranteed interface methods | 1 hour |
| **`get_capabilities_for_model` → profile** | Replace `get_capabilities_for_model()` with `get_model_profile()` as the single source of truth for per-model behavior | 2 hours |
| **Tests** | Verify all providers pass a shared interface compliance test | 2 hours |

**Why v1.16.0:** Changing the provider interface is a breaking change for any custom providers. The v1.15.6 duck-typing approach is a safe intermediate step.

### v1.16.0 Testing Strategy

| Test Type | What | Target |
|-----------|------|--------|
| **Unit tests** | Profile-driven routing, message format, multi-tool | 40-50 new tests |
| **Integration tests** | Full tool loop with mock providers in all modes | 10-15 new tests |
| **TUI manual tests** | Test each provider with tool-using conversations | All providers |
| **Benchmark re-runs** | Full suite for all 16 models to validate no regressions | 16+ runs |
| **Session migration** | Load v1.15.x sessions in v1.16.0, verify no data loss | Manual |
| **Regression** | Full `pytest tests/ -v` passes | ~1300+ tests |

### v1.16.0 Risk Mitigation

| Risk | Mitigation |
|------|------------|
| **Message format breaks local models** | Keep synthetic pairs for prompt-based mode; only native mode uses `tool` messages |
| **Multi-tool breaks consent flow** | Execute tools sequentially, not in parallel; each gets individual consent |
| **Profile mismatch causes regressions** | Default profile = current behavior; explicit opt-in for new features |
| **Session format incompatible** | Migration layer reads old format, writes new format |
| **Benchmark scores drop** | Re-benchmark before and after; block release if any model regresses >5% |

---

## What NOT to Change

Carried forward from analysis Part 7:

1. **Don't try to fix Tier D models** — o4-mini (native), gemini-2.0-flash-exp are fundamentally broken
2. **Don't over-engineer profiles** — start with 6 fields, expand only when benchmarks prove the need
3. **Don't break `OpenAICompatibleProvider`** — it should work unchanged with default profiles
4. **Don't break `GeminiProvider`** — it should work unchanged with default profiles
5. **Don't merge Goals 2+3 (v1.16.0) into v1.15.6** — message format changes are breaking

---

## Timeline

```
v1.15.6 (Foundation, Non-Breaking)
├── Week 1: Goal 2 (Immediate wins) + Goal 3 (Profile data structures)
├── Week 1-2: Goal 4 (Benchmark improvements) + validation
└── Release when benchmarks validate improvements

v1.16.0 (Breaking Changes)
├── Week 1: Goal 1 (Profile-driven tool loop) + Goal 2 (Message format)
├── Week 2: Goal 3 (Multi-tool) + Goal 5 (File navigation)
├── Week 3: Goal 4 (Config integration) + comprehensive testing
└── Release after full re-benchmark validates no regressions
```

---

## ROADMAP.md Updates Required

1. **v1.15.6 section** — Add after v1.15.5 in the v1.15.x series
2. **v1.16.0 section** — Restructure: File Navigation becomes one goal alongside engine changes
3. **v1.16.1 → v1.17.0** — Renumber: ppxaide file tree and web app sidebar shift forward
4. **Model Evaluation table** — Update with latest benchmark results
5. **Future Considerations** — Add Model Profile System as a completed/in-progress item

---

## Success Criteria

### v1.15.6
- [ ] o4-mini scores >60% (up from 10.9%)
- [ ] gpt-4.1-mini scores >70% (up from 60.9%)
- [ ] Codex capability override verified in engine (P0)
- [ ] Brace-counting parser handles apply_patch diffs without breaking (P2)
- [ ] JSON stripping cleans up tool_json_in_content responses
- [ ] `ModelProfile` dataclasses exist with profiles for 27 models
- [ ] No regressions for existing providers (Gemini, Perplexity, local)
- [ ] All existing tests pass + 30+ new tests

### v1.16.0
- [ ] Profile-driven routing replaces binary decision in chat.py
- [ ] Proper `tool` role messages for native mode
- [ ] Multi-tool support works for models that return parallel calls
- [ ] Config overrides allow per-model tool_calling settings
- [ ] `/model info` shows active profile
- [ ] `/ls` and `/tree` commands work in all clients
- [ ] No provider regressions (full benchmark suite)
- [ ] Session migration from v1.15.x works seamlessly
- [ ] All existing tests pass + 50+ new tests
