# Release Plan: v1.15.6 (Foundation) → v1.16.0 (Breaking Changes)

**Created:** 2026-02-19
**Status:** v1.15.6 done (pending merge), v1.16.0 planning
**Predecessor:** v1.15.5 (released 2026-02-15)
**Active Branch:** `feature/benchmark-openai-models` (native OpenAI provider + benchmarks)
**Analysis:** [model-behavior-analysis.md](../model-behavior-analysis.md)
**Debug Sessions:** [ARCHIVE-v1.15.6-debug-sessions.md](ARCHIVE-v1.15.6-debug-sessions.md)

---

## Motivation

The `feature/benchmark-openai-models` branch introduced:
1. **`OpenAINativeProvider`** — correct OpenAI API handling (Chat Completions + Responses API)
2. **49+ benchmark runs** across 27 models revealing 5 architectural gaps in `chat.py`

The benchmark analysis ([model-behavior-analysis.md](../model-behavior-analysis.md)) identified that the current binary `native_tool_calling: bool` decision is too coarse. Models like gpt-4.1-mini (71.9% prompt-based vs 60.9% native) and o4-mini (62.5% prompt-based vs 10.9% native) perform significantly worse when forced into the wrong mode.

**Key insight:** The benchmark runner bypasses `chat.py` entirely (calls `provider.chat()` directly), so none of the identified gaps are testable without a real client. The TUI (`ppxai`/`ppxaide`) is the primary test vehicle for these changes.

---

## Benchmark Findings Backlog (P0–P4)

Prioritized issues identified during the benchmark work (49+ runs, 27 models):

| Priority | Issue | Target | Status |
|----------|-------|--------|--------|
| **P0** | **Codex native tool calling works** — Codex models via Responses API DO emit native `function_call` items when tools are sent as API params. Previous assumption was wrong (prompt-based mode failed because codex can't parse tool schemas from text). Fix: `get_capabilities_for_model()` returns `native_tool_calling=True` for codex models + belt-and-suspenders hint injection. | v1.15.6 Goal 2 | ✅ Fixed + verified (Session 3: codex 71+ calls, codex-mini 19 calls + synthesis) |
| **P1** | **AGENTS.md hints skipped for native providers** — Bootstrap/AGENTS.md hints were only injected for prompt-based mode. Native providers (OpenAI, Gemini) never saw the hints. Fix: inject hints into system prompt for ALL modes. | v1.15.6 Goal 1 | ✅ Fixed (chat.py) |
| **P2** | **Port brace-counting JSON parser to engine** — Engine's `tools/parser.py` uses regex which breaks on `apply_patch` with complex diff content containing braces. Benchmark runner already has `_find_json_objects()` with brace-counting. Port it. | v1.15.6 Goal 2 | ✅ Done (`_find_json_objects()` ported, `parse_tool_call()` + `strip_tool_json_from_text()` use brace-counting) |
| **P3** | **Re-benchmark all providers with fixed runner** — All provider scores were artificially low due to engine tool conflicts (engine tools `read_file(filepath)` vs benchmark tools `read_file(path)`). Need to re-run for GPT-5.2, Gemini, Perplexity sonar. | v1.15.6 Goal 4 | ✅ Done (sonar 70.3%, sonar-pro 68.8%, gemini-2.5-pro 75.0%, gemini-3-flash 57.8%, gemini-3-pro 62.5%) |
| **P4** | **Belt-and-suspenders in real engine** — Engine does either native OR prompt-based, never both. If native tool calling is flaky (vLLM HarmonyError), there's no fallback. **Partially done:** codex models now have belt-and-suspenders (tool hints in `instructions` field + native function tools). Generalize to other providers. | v1.16.0 Goal 1 | ⚡ Partially done (codex only) |

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
| **Codex → native** | Enable native tool calling for codex: removed `_is_responses_api_model()` from prompt-based override, added belt-and-suspenders hint injection, updated model profiles and AGENTS.md hints | P0 | ✅ Done (Session 3) |
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

#### Debug Session 1 Findings (2026-02-19, Windows) — v1.15.6 Items

From [DEBUG-SESSION-2026-02-19.md](DEBUG-SESSION-2026-02-19.md) Section 5.1:

| # | Item | Priority | Effort | Status |
|---|------|----------|--------|--------|
| A1 | **Read-claim validator** — `_check_read_claims_without_tools()` in `validator.py` to catch fabricated "I read each file" with 0 `read_file` calls | P1 | 2h | ✅ Done (Session 5) |
| A2 | **Stronger truncation retry** — `[SYSTEM: ...]` framing in `chat.py:504-509` | P2 | 30min | ✅ Done (Session 5) |
| A3 | **Model switch warning** — deferred to v1.16.0 (B1 session reset is the proper fix) | P2 | — | → v1.16.0 |
| A4 | **gpt-4o AGENTS.md hints** — multi-file reading + no-narration hints | P2 | 15min | ✅ Done (Session 2) |
| A5 | **codex profiles** — reversed: native works, changed to `mode="native"` + `api_path="responses"` | P2 | 30min | ✅ Done (Session 3) |
| A6 | **codex live validation** — codex: 71+ calls, codex-mini: 19 + synthesis | P3 | 2h | ✅ Done (Session 3) |
| A7 | **codex AGENTS.md hints** — updated to "native function calling" language | P3 | 15min | ✅ Done (Session 3) |

#### Debug Session 2 Findings (2026-02-20, macOS) — Additional v1.15.6 Items

From [DEBUG-SESSION-2026-02-19.md](DEBUG-SESSION-2026-02-19.md) Sections 9-13:

| # | Item | Priority | Effort | Status |
|---|------|----------|--------|--------|
| A0 | **Bool sentinel crash fix** — removed `openai_tools = True` in `chat.py:217` that caused `TypeError` for all Responses API models | P0 | done | ✅ Fixed |
| H1 | **"Make ONE" hint anti-pattern** — replaced 24 "Make ONE tool call" hints with "Chain multiple DIFFERENT tool calls" | P0 | done | ✅ Fixed |
| H2 | **Interrupt during tool execution** — `chat.py:372` now checks `is_interrupted` and cancels running tool task | P0 | done | ✅ Fixed |
| H3 | **Interrupt after provider.chat()** — `chat.py:327` catches interrupt before processing tools | P0 | done | ✅ Fixed |
| A8 | **Codex native tool calling** — removed prompt-based override, added belt-and-suspenders hint injection | P0 | 4h | ✅ Done (Session 3) |
| A9 | **o3-mini provider routing** — removed `openrouter` as built-in provider, o3-mini routes through `OpenAINativeProvider` | P2 | 1h | ✅ Done (Session 4) |
| A10 | **gpt-5-mini hints** — "Do NOT ask permission before using tools" | P2 | 15min | ✅ Done (Session 4) |
| A11 | **gpt-5-nano synthesis failure** — max_tokens 2048→8192, added profile with `fallback_on_empty` | P2 | 2h | ✅ Done (Session 5) |

**Key validation from Session 2:** The "Make ONE" hint fix (H1) is confirmed transformative:
- gpt-5.2: 1 tool/turn → 8 tools chained back-to-back
- gemini-2.5-flash: 19 iterations, hit max — read every file in 2 agent directories
- sonar-pro: 10 tools with efficient search_files strategy
- gpt-5-nano: 11 tools chained perfectly (synthesis failed due to model capacity)
- gpt-4.1-mini: **no improvement** — insufficient model capacity to follow hints

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

### Goal 7: Benchmark v2 — Real-World Agent Evaluation

**Motivation:** Live testing on 2026-02-19 revealed a massive gap between benchmark scores and real-world agent behavior. gemini-3-flash-preview scored **57.81%** on the benchmark but was the **best performer** in actual web app usage — reading all 8 project files consecutively and producing a quality improvement plan. Meanwhile, sonar-pro and gpt-5.2 scored higher on the benchmark but failed basic multi-file tasks in practice (sonar fabricated results, gpt-5.2 read only 1 file per turn).

**Root cause:** The current 26-test suite measures single-turn tool correctness (exact tool name, exact arg match, binary pass/fail) but misses the agentic patterns that matter: consecutive tool loops, multi-file navigation, search-then-edit workflows, and iterative refinement.

#### Phase 1: Close Scoring Distortions (Priority)

| Item | Description | Gap Addressed | Effort |
|------|-------------|---------------|--------|
| **`multi_file_review`** | "Read all files in this project and summarize" with 5-8 simulated files. Score = files_read / files_available (continuous 0.0-1.0). Must read files via tool calls, not fabricate content. | Multi-file read loops (gemini-3-flash: 8/8, gpt-5.2: 1/8 per turn, sonar: 0/8) | 4 hours |
| **`consecutive_tool_loop`** | 5-step chain: list_dir → read config → read entry point → search for pattern → read matching file. Score = steps completed / total steps. Model must chain results (each step depends on previous). | Agent loop depth (current max: 3 turns) | 4 hours |
| **`claim_without_action`** | Ask model to read and report file contents. Inject no tool results. Check if model fabricates a report. Inspired by sonar-pro claiming "ALL 8 FILES RE-READ" with zero tool calls. | Hallucination in agentic context (sonar fabricated entire reviews) | 3 hours |
| **Partial credit scoring** | Replace binary pass/fail for tool calling tests: correct tool name +50%, correct args +50%. Wrong tool = 0%, right tool wrong arg key = 50%. Reduces cliff effect. | gemini-3-flash: 0% code editing for using `read_file` instead of `apply_patch` despite excellent real behavior | 4 hours |
| **`patch_apply_verify`** | Give file content + edit instruction. Model generates patch. Actually apply the patch (using `_replace_hunk` from engine). Verify result matches expected output. | Current tests check patch structure, never apply it | 4 hours |

**Expected impact:** These 5 items would have correctly ranked tonight's models: gemini-3-flash > gpt-5.2 > sonar-pro, matching observed real-world behavior.

#### Phase 2: Agentic Patterns

| Item | Description | Gap Addressed | Effort |
|------|-------------|---------------|--------|
| **`search_then_edit`** | "Fix the bug in the divide function" without giving file path. Model must: search_code → read_file → apply_patch. Simulated tool results guide the chain. | Real agents navigate, current tests give paths directly | 4 hours |
| **`test_fix_verify`** | Write code → simulated test failure → model fixes → re-run tests → pass. Score = reached final passing state. | The core TDD loop is completely untested | 5 hours |
| **`information_gathering`** | "How is authentication implemented?" with 3 files containing auth code spread across the project. Model must find and read all 3 to give a complete answer. Score = relevant files read / total relevant files. | Codebase understanding requires exploration, not given paths | 4 hours |
| **`error_recovery_chain`** | Read file → not found → search for it → read result → edit it → permission denied → report failure clearly. Tests adaptive strategy over 4+ turns. | Current `tool_error_recovery` is single-turn | 3 hours |

#### Phase 3: Efficiency & Hints

| Item | Description | Gap Addressed | Effort |
|------|-------------|---------------|--------|
| **Token/cost metrics** | Track `prompt_tokens`, `completion_tokens`, `total_cost` per test. Report efficiency ratio: score_per_dollar. | No efficiency comparison between models | 3 hours |
| **Time-to-first-tool-call** | Measure latency from prompt to first tool invocation. Penalize models that narrate before acting. | gpt-5.2 explains before each tool call, gemini-3-flash acts immediately | 2 hours |
| **With/without AGENTS.md** | Run identical test suite twice per model: once with hints, once without. Report delta. | Perplexity dropped 75% → 48.4% without hints; currently no systematic measurement | 3 hours |
| **Tool call efficiency** | Count total tool calls vs minimum required. Penalize unnecessary reads, reward models that batch independent operations. | sonar makes 5-6 duplicate calls; gemini reads exactly what's needed | 2 hours |

#### Framework: GenAIScript Integration

**What:** [GenAIScript](https://microsoft.github.io/genaiscript/) — Microsoft's JS-based LLM orchestration framework with built-in evaluation via [promptfoo](https://promptfoo.dev/). Runs tests across multiple models in a single command.

**Reference docs:** [genaiscript-llms.txt](external-refs/genaiscript-llms.txt) (index) | [genaiscript-getting-started.txt](external-refs/genaiscript-getting-started.txt) | [genaiscript-reference-cli.txt](external-refs/genaiscript-reference-cli.txt) | [genaiscript-llms-full.txt](external-refs/genaiscript-llms-full.txt) (complete, 1.4MB)

**Why:** Complements the existing Python benchmark suite. GenAIScript excels at multi-model comparison, rubric-based grading (LLM-as-judge), and agent loop testing with `defTool()` for simulated file systems. The Python suite remains the engine regression layer.

**Key capabilities for our use:**
- `--models` flag — run the same test against 16 models in one invocation
- `defTool()` — define simulated `read_file`, `search_code`, `apply_patch` tools matching our engine's tool schemas
- Rubric-based scoring via promptfoo — LLM-as-judge replaces binary pass/fail for code editing quality
- `defFileOutput` — test code generation without actual file system changes
- Built-in support for OpenAI, Gemini, Perplexity, local models (25+ providers)

**Integration plan:**

| Item | Description | Effort |
|------|-------------|--------|
| **GenAIScript agent loop tests** | Implement Phase 1-2 agent tests (`multi_file_review`, `consecutive_tool_loop`, `claim_without_action`, `search_then_edit`) as `.genai.mts` scripts with `defTool()` simulated tools | 6 hours |
| **Multi-model comparison runner** | Single `npx genaiscript eval` invocation testing all 16 configured models, output as JSON for comparison dashboard | 2 hours |
| **Rubric-based code editing eval** | Replace binary pass/fail for `apply_patch` tests with LLM-as-judge rubrics (correctness, minimal diff, context preservation) | 4 hours |
| **CI integration** | `npm run benchmark:genaiscript` script in `benchmarks/` alongside existing Python runner | 2 hours |

**Architecture:** GenAIScript tests live in `benchmarks/genaiscript/` alongside the existing `benchmarks/llm-eval/` Python suite. Both can run independently. Results feed into the same comparison dashboard.

**Dependency:** Node.js 20+ (already required for VSCode extension build)

#### New Category: Agent Loop (proposed, 5 tests)

| Test | Weight | Tags | Source |
|------|--------|------|--------|
| `multi_file_review` | 2.0 | critical, gate | Phase 1 |
| `consecutive_tool_loop` | 2.0 | critical | Phase 1 |
| `claim_without_action` | 2.0 | critical, gate | Phase 1 |
| `search_then_edit` | 1.5 | — | Phase 2 |
| `test_fix_verify` | 1.5 | — | Phase 2 |

**Total new weight: 9.0** (matches hallucination_resistance, the other critical gate category)

#### Scoring Changes

| Change | Current | Proposed |
|--------|---------|----------|
| **Tool call tests** | Binary pass/fail | Partial credit (tool name 50% + args 50%) |
| **Agent loop tests** | N/A | Continuous 0.0-1.0 (steps completed / steps required) |
| **Code editing tests** | Structural check only | Apply patch + verify output |
| **New metric: efficiency** | Not tracked | tokens_per_point, cost_per_point, time_to_first_tool |
| **New metric: AGENTS.md delta** | Not tracked | score_with_hints - score_without_hints |

#### Real-World Validation Matrix (2026-02-19 Live Testing)

This table documents the gap that Goal 7 aims to close. Models are ranked by **observed real-world utility**, not benchmark score:

| Rank | Model | Benchmark Score | Real-World Behavior | Gap |
|------|-------|----------------|---------------------|-----|
| 1 | gemini-3-flash-preview | 57.81% | Read 8/8 files in 18s, produced quality improvement plan | Benchmark **under-scores** by ~30%: 0% code editing (wrong tool name), 16.7% hallucination (doesn't match behavior) |
| 2 | gpt-5.2 | 70.31% | Tool calling works but reads 1 file/turn, requires repeated prompting | Benchmark **over-scores** by ~10%: doesn't test multi-file laziness |
| 3 | sonar-pro | 68.75% | Fabricated "ALL 8 FILES RE-READ" with 0-1 tool calls, hallucinated results | Benchmark **over-scores** by ~30%: doesn't test agentic hallucination |
| 4 | gpt-5.1-codex | 40.63% → TBD | Session 2: Zero tool calls (broken). **Session 3: 71+ tool calls, fully functional** with native tool calling fix | Benchmark **needs re-run**: old score reflects broken prompt-based mode, not current native mode |

**Target:** After Goal 7, benchmark ranking should match columns 1-4 (real-world rank).

### Debug Session Findings (2026-02-19 + 2026-02-20) — Additional v1.16.0 Items

From [DEBUG-SESSION-2026-02-19.md](DEBUG-SESSION-2026-02-19.md) Sections 5.2 + 11:

| # | Item | Aligns With | Priority | Effort | Session |
|---|------|-------------|----------|--------|---------|
| B1 | **Session context reset on model switch** — `session.reset_for_model_switch()` strips assistant/tool messages, keeps user messages. **Definitively validated:** codex-mini worked in Session 1 (clean), completely broke in Session 2 (codex refusals polluted session) | New (Goal 4) | P1 | 4h | 1+2 |
| B10 | ~~**Codex native tool calling via Responses API**~~ — **DONE in v1.15.6 (Session 3).** Native function calling works: codex-mini 19 iterations + synthesis, codex 71+ calls. No longer needed for v1.16.0. | New | ~~P1~~ | ~~8h~~ | 2→3 |
| B2 | **Per-model iteration limit** — `max_tool_iterations` field in `ModelProfile`: gemini-2.5-flash→25 (hit 19 ceiling), gpt-5-nano→8 (prevent empty synthesis), sonar→20 | Goal 3 | P2 | 2h | 2 |
| B3 | **Belt-and-suspenders** — inject `get_tools_prompt()` into system prompt even for native when profile has fallback flags | Goal 1 / P4 | P2 | 3h | 1 |
| B11 | **SSE disconnect detection** — use `request.is_disconnected()` in `sse_event_generator` to cancel background generator when client disconnects. Currently Esc closes UI but server task continues. | New | P2 | 3h | 2 |
| B7 | **Session pollution detection** — compare response similarity against previous assistant messages from different models | New | P3 | 3h | 1 |

Benchmark v2 items (already captured in Goal 7):

| # | Item | Goal 7 Phase | Priority | Effort |
|---|------|-------------|----------|--------|
| B4 | `multi_file_review` test — score = files_read / files_available | Phase 1 | P2 | 4h |
| B5 | `claim_without_action` test — catch fabricated reports | Phase 1 | P2 | 3h |
| B6 | `consecutive_tool_loop` test — 5-step dependent chain | Phase 1 | P2 | 4h |
| B8 | `time_to_first_tool_call` metric | Phase 3 | P3 | 2h |
| B9 | Partial credit scoring (tool name 50% + args 50%) | Phase 1 | P2 | 4h |

### v1.16.0 Testing Strategy

| Test Type | What | Target |
|-----------|------|--------|
| **Unit tests** | Profile-driven routing, message format, multi-tool | 40-50 new tests |
| **Integration tests** | Full tool loop with mock providers in all modes | 10-15 new tests |
| **TUI manual tests** | Test each provider with tool-using conversations | All providers |
| **Benchmark v2 tests** | New agent_loop category (5 tests), partial credit scoring, patch verification | 8-10 new tests |
| **GenAIScript eval** | Agent loop tests via GenAIScript + rubric-based code editing scoring | 4-6 `.genai.mts` scripts |
| **Benchmark re-runs** | Full v2 suite (Python + GenAIScript) for all 16 models to validate ranking matches real-world | 16+ runs |
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
| **New benchmark tests too hard** | Phase 1 tests must have at least 1 model scoring >80%; if all fail, tests are unrealistic |
| **Partial credit inflates scores** | Compare v1 and v2 overall scores; document mapping so historical results remain comparable |

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
├── Week 2-3: Goal 7 Phase 1 (Benchmark v2 — scoring fixes + agent loop tests)
├── Week 3: Goal 4 (Config integration) + Goal 6 (Provider hierarchy)
├── Week 3-4: Goal 7 Phase 2-3 (Agentic patterns + efficiency metrics)
└── Release after full v2 re-benchmark validates ranking matches real-world
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

### v1.15.6 — All Done
- [x] o4-mini scores up to 80.8% prompt-based (from 10.9% native)
- [x] gpt-4.1-mini scores up to 100% prompt-based (from 60.9% native)
- [x] Codex native tool calling verified — Session 3: 71+ calls (codex), 19 + synthesis (codex-mini)
- [x] Brace-counting parser handles apply_patch diffs without breaking (P2)
- [x] JSON stripping cleans up tool_json_in_content responses
- [x] `ModelProfile` dataclasses with 37 built-in profiles
- [x] No regressions for existing providers (Gemini, Perplexity, local)
- [x] 1349 tests passing (87+ new tests)
- [x] Read-claim validator catches "I read each file" with 0 read_file calls (A1)
- [x] Truncation retry uses `[SYSTEM: ...]` framing (A2)
- [x] Model switch warning → deferred to v1.16.0 (A3 → B1 session reset is proper fix)
- [x] codex profiles corrected to native (A5 — reversed: native works, prompt_based was wrong)
- [x] ppxaide `/debug-log on` fix — Logger.enable_all() (A14)
- [x] codex-mini tuning — anti-hesitation, fallback_on_empty, restricted_params (A13)
- [x] gpt-5-nano synthesis fix — max_tokens 8192, profile with fallback_on_empty (A11)
- [x] Pre-release cleanup C1-C9 (profile count, prefix matching, tier fixes, doc sync)

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
- [ ] Session context reset on model switch works correctly (B1)
- [x] ~~Codex native tool calling via Responses API~~ — Done in v1.15.6 Session 3
- [ ] Per-model iteration limit consulted from ModelProfile (B2) — gemini→25, nano→8
- [ ] Belt-and-suspenders prompt injection for fallback-enabled profiles (B3)
- [ ] SSE disconnect detection cancels background tasks on client disconnect (B11)
- [ ] Session pollution detection emits WARNING on response replay (B7)
- [ ] **Benchmark v2:** `agent_loop` category with 5 tests (multi_file_review, consecutive_tool_loop, claim_without_action, search_then_edit, test_fix_verify)
- [ ] **Benchmark v2:** Partial credit scoring for tool calling tests (tool name 50% + args 50%)
- [ ] **Benchmark v2:** `patch_apply_verify` test actually applies patches and verifies output
- [ ] **Benchmark v2:** Efficiency metrics tracked (tokens, cost, time-to-first-tool-call)
- [ ] **Benchmark v2:** Ranking matches real-world validation matrix (gemini-2.5-flash > codex-mini > sonar-pro > gpt-5.2 > codex > gemini-3-pro > gpt-4.1)
