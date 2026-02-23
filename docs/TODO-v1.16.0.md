# TODO: v1.16.0 — Profile-Driven Tool Loop

**Branch:** feature/v1.16.0
**Previous:** v1.15.6 (released, tagged) — [RELEASE-PLAN-v1.15.6-v1.16.0.md](archive/RELEASE-PLAN-v1.15.6-v1.16.0.md)
**Debug Sessions:** [ARCHIVE-v1.15.6-debug-sessions.md](archive/ARCHIVE-v1.15.6-debug-sessions.md)

---

## Why v1.16.0 (Not v1.15.7)

These changes modify the core tool loop in `chat.py` affecting **every provider and every client**:

1. **Profile-driven routing** — replaces the binary `native_tool_calling: bool` decision
2. **Tool result message format** — from synthetic `assistant`/`user` pairs to proper `tool` role messages
3. **Multi-tool processing** — from `native_tool_calls[0]` to processing all calls
4. **Adaptive fallback** — tool mode can change mid-conversation

---

## Completed (macOS session, 2026-02-20)

<details>
<summary>P1-P3 foundation work — all done</summary>

- [x] **B1** Session context reset on model switch — `session.reset_for_model_switch()`, `client.set_model(reset_context=)`, HTTP endpoints. All session restore paths pass `reset_context=False`.
- [x] **B2** Per-model iteration limit — `ModelProfile.max_tool_iterations` field. sonar(20), gemini(25), codex-mini(20), qwen3-coder(20). `chat.py` uses `max(manager.max_iterations, profile.max_tool_iterations)`.
- [x] **B3** Belt-and-suspenders prompt injection — `chat.py` native mode injects `get_tools_prompt()` when profile has `fallback_on_empty` or `fallback_on_failure`.
- [x] **B7** Session pollution detection — `check_session_pollution()` bigram similarity >90% → WARNING. Wired into `chat.py` after first iteration.
- [x] **B11** SSE disconnect detection — `request.is_disconnected()` in `sse_event_generator`, `raw_request: Request` on `/chat`.
- [x] **A3** Model switch warning — `client.last_model_switch_reset`, commands show cleared count.
- [x] **A12** Partial credit scoring — `score` (0.0-1.0), tool calling +50% name +50% args.
- [x] **B4** `multi_file_review` benchmark — score = files_read / files_available.
- [x] **B5** `claim_without_action` benchmark — fabricated report = 0.0, honest refusal = 1.0.
- [x] **B6** `consecutive_tool_loop` benchmark — 5-step dependent chain, score = steps/5.
- [x] **B8** `time_to_first_tool_call` benchmark — penalize >100 chars preamble.
- [x] **B9** Partial credit scoring — merged into A12.
- [x] **Goal 5** `/ls` and `/tree` commands — `DirectoryListingResult`, `DirectoryTreeResult`, HTTP `/files/list` + `/files/tree`, all 3 clients.
- [x] 6 new session tests for `reset_for_model_switch`
- [x] 10 new benchmark result files

</details>

---

## Implementation Order

Goals are ordered by dependency chain. Implement in this sequence:

```
Step 1: Provider Hierarchy ✅  (no deps — simplifies everything after)
   │
Step 2: Profile-Driven Loop ✅ (needs Step 1's clean interface)
   │
   ├─→ Step 3: Tool Messages ✅ (needs Step 2's profile routing)
   │      │
   │      └─→ Step 4: Multi-Tool ✅ (needs Step 3's message format)
   │             │
   │             └─→ Step 5: Agent UI Noise Reduction  (needs Step 4's multi-tool)
   │
   └─→ Step 6: Config Integration ✅ (needs Step 2's profiles, independent of 3-4)

Step 7: Benchmark v2 ✅       (independent — 37 tests done, re-benchmark in progress)
```

---

## Step 1: Provider Hierarchy Refactoring ✓

**Status:** Completed (2026-02-22)

All providers now inherit from `BaseProvider`. `hasattr` guards removed from `chat.py`. 61 new compliance tests.

- [x] **Shared ABC** — `OpenAINativeProvider` and `GeminiProvider` inherit from `BaseProvider`
- [x] **Eliminate duplicate methods** — `needs_tool`, `get_model_profile`, `list_models`, `validate_config`, `_parse_usage`, `_convert_messages`, `_get_generation_params`, `_get_max_tokens` moved to base
- [x] **Remove `hasattr` guards** — `chat.py` uses `get_capabilities_for_model()` directly
- [x] **`get_capabilities_for_model()`** — added to `BaseProvider` (returns `self.capabilities`); `OpenAINativeProvider` overrides for o4-mini/gpt-4.1-mini
- [x] **Tests** — `test_provider_hierarchy.py` with 61 parametrized tests (inheritance, interface, capabilities, validate_config, base_url)

---

## Step 2: Profile-Driven Tool Loop ✓

**Status:** Completed (2026-02-22)

Profile-driven mode routing replaces the binary `native_tool_calling` decision. `ToolCallingProfile.mode` ("native", "prompt_based", "auto") drives routing with provider capability gating. Fallback on empty/failure, strip_json, and belt-and-suspenders all wired.

- [x] **Replace binary decision** — `chat.py` uses `tc_profile.mode` with provider capability gate
- [x] **`strip_json_from_text`** — profile-driven stripping for both native and prompt-based modes
- [x] **`fallback_on_empty`** — native empty → retry with `_build_prompt_based_messages()`
- [x] **`fallback_on_failure`** — native unknown tool → prompt-based parser fallback
- [x] **`auto` mode** — starts native if provider supports it, same as native with fallbacks
- [x] **Backwards compat** — default profile = `mode="native"` → current behavior preserved
- [x] **Truncation recovery** — raw JSON truncation detection, escalating recovery messages, stuck-loop detection (MAX_TRUNCATION_RETRIES=3)
- [x] **Sonar profile fix** — all sonar profiles corrected to `mode="prompt_based"` (was `mode="native"` gated by capability)
- [x] **AGENTS.md fix** — perplexity/sonar hints rewritten for prompt-based tool calling (was contradicting mechanism)
- [x] **Tests** — 16 profile routing tests + 7 raw truncation tests + 4 stuck-loop tests = 27 new tests

---

## Step 3: Proper Tool Message Format ✓

**Status:** Completed (2026-02-22)

Native mode now uses proper `tool` role messages. Prompt-based mode keeps synthetic pairs.

- [x] **`Message` type extended** — `tool_calls` and `tool_call_id` fields added to `Message` dataclass (`types.py:51-52`)
- [x] **Native mode messages** — `assistant` (with `tool_calls`) + `tool` role messages (`chat.py:677-702`)
- [x] **Prompt-based unchanged** — synthetic pairs for prompt-based mode (`chat.py:703-725`)
- [x] **Provider message conversion** — all 4 providers handle `tool` role in `_convert_messages()` (`base.py:251-254`, `openai_native.py:673-682`, `openai_compat.py:356-373`, `gemini.py:261-388`)
- [x] **Session serialization** — save/load handles `tool_calls`/`tool_call_id` (`session.py:115-128`)
- [x] **Migration** — v1.15.x sessions load via `m.get("tool_calls")` / `m.get("tool_call_id")` (None-safe)
- [x] **Session validation** — `_validate_message_order()` allows `tool` messages after `assistant(tool_calls)` (`session.py:151-202`)

---

## Step 4: Multi-Tool Support ✓

**Status:** Completed (2026-02-22)

All native tool calls processed when `parallel_tool_calls` profile flag is set. Sequential execution with per-tool consent and loop detection.

- [x] **Sequential tool execution** — `for tc in tool_calls_list` processes all calls in sequence (`chat.py:639-671`)
- [x] **Profile gating** — `parallel_tool_calls` flag limits to first call when false (`chat.py:607-609`)
- [x] **Multi-result events** — emit `TOOL_CALL`/`TOOL_RESULT` per tool (`chat.py:656-665`)
- [x] **Session messages** — one `assistant` message with ALL `tool_calls`, N `tool` result messages (`chat.py:677-702`)
- [x] **Consent handling** — each tool gets individual consent via `_execute_single_tool()` (`chat.py:661`)
- [x] **Loop detection** — per-tool loop detection with early break (`chat.py:644-652`)

---

## Step 5: Agent UI Noise Reduction

**Dependencies:** Step 4 (multi-tool support provides the engine-side batching; this step fixes the UI side)

**Status:** Completed (2026-02-23)

### Issue A: Checkpoint Bubble Spam — N/A

After code review, this is **not a real problem** in current code. `create_checkpoint()` only fires from `commit_agent_changes_if_needed()` AFTER the tool loop exits (chat.py:871). During the loop, `_register_checkpoint_file()` only registers files — no events. The STATUS event is queued but only delivered on the next tool execution's poll loop, which won't happen since the loop has ended.

### Issue B: Grouped Tool Call Display ✓

Each iteration's tool calls are now wrapped with `TOOL_GROUP_START`/`TOOL_GROUP_END` events. All 4 clients render them as collapsible groups.

- [x] **Engine SSE events** — `TOOL_GROUP_START` / `TOOL_GROUP_END` EventTypes in `types.py`, emitted wrapping tool execution loop in `chat.py`
- [x] **`AGENT_COMPLETE` emission** — engine now yields `AGENT_COMPLETE` event after tool loop (both normal completion and max-iterations), with `iterations` count and `commit` hash
- [x] **SSE event type dispatch fix** — side-channel queue events now emit using their actual EventType (STATUS, WORKING_DIR_CHANGED, etc.) instead of all being sent as `consent_request`. Fixes checkpoint events triggering false consent dialogs.
- [x] **Web app** — collapsible `.tool-group` container with header showing iteration, tool names, and success/failure status. Checkpoint bubble suppression (enriches commit message with count). Undo badge only shown when `agent_complete` includes a commit.
- [x] **VSCode extension** — `stream.ts` → `chatPanel.ts` → `main.js` forwarding + `.tool-group` CSS styling
- [x] **ppxaide TUI** — non-verbose mode suppresses individual tool bubbles, shows one summary line per group at group end; verbose mode unchanged. Tool group events logged at INFO level.
- [x] **ppxai Rich CLI** — dim separator lines wrapping tool groups with iteration number and status
- [x] **Consent deadlock fix** — SSE generator replaced `async for` with racing poll pattern (`asyncio.ensure_future` + 100ms polling). Removed consent event draining from `_execute_single_tool()` that was trapping events.

---

## Step 6: Config Integration ✓

**Status:** Completed (2026-02-22)

Per-model tool calling config overrides with 3-layer precedence: built-in profile → AGENTS.md → ppxai-config.json.

- [x] **Config overrides** — `get_tool_calling_config(provider, model)` reads `tool_calling` section from provider-level and model-level config (`config/__init__.py`)
- [x] **AGENTS.md influence** — `tool_calling` YAML front matter section with glob-pattern matching (`bootstrap.py:_parse_tool_calling_section`, `get_tool_calling_overrides`)
- [x] **Effective profile merging** — `_get_effective_profile()` in `chat.py` merges 3 layers
- [x] **Context merging** — `tool_calling_overrides` merged across scopes in `context.py`
- [x] **`/model info` command** — shows effective profile with source attribution (`provider.py:handle_model_info`)
- [x] **Config example** — `ppxai-config.example.json` updated with `tool_calling` examples for local-vllm and vllm-gpt-oss
- [x] **Tests** — 4 config tests + 6 bootstrap tests + 6 profile merging tests = 16 new tests

---

## Step 7: Benchmark v2 ✓ (Phase 1-3 tests done, re-benchmark in progress)

**Status:** All 37 tests implemented across 8 categories. Re-benchmark runs in progress (2026-02-22).

### Phase 1: Scoring Distortions ✓
- [x] **Partial credit scoring** — `score` field (0.0-1.0) in `engine_runner.py`, tool calling +50% name +50% args
- [x] **`patch_apply_verify`** — model generates patch, applies with `_replace_hunk()`, verifies output. Supports unified diff and search-replace formats. Score: 0.0/0.5/0.7/1.0. weight=2.0 (`test_cases.py:704`)

### Phase 2: Agentic Patterns ✓
- [x] **`search_then_edit`** — search_code → read_file → apply_patch/write_file. score=steps/3, up to 6 turns, dedup detection. weight=2.0 (`test_cases.py:1751`)
- [x] **`fix_verify`** — write → test failure → fix → retest → pass. score=steps/4, up to 8 turns. weight=2.0 (`test_cases.py:1849`)
- [x] **`information_gathering`** — find and read 3 auth files (auth.py, middleware.py, auth_config.yaml). score=files_found/3. weight=2.0 (`test_cases.py:1951`)
- [x] **`error_recovery_chain`** — read → not found → search → find real path → read → apply_patch with permission denied. score=steps/4. weight=2.0 (`test_cases.py:2043`)

### Phase 3: Efficiency & Hints ✓ (mostly)
- [x] **Token/tool_call tracking** — `total_tokens` and `total_tool_calls` in `EngineClientWrapper`, reported in `BenchmarkResult.metadata`
- [x] **With/without AGENTS.md** — `--agents-md both` mode in `benchmark.py`, reports per-category delta
- [x] **`tool_call_efficiency`** — 5-step chain, score by extra calls: ≤5=1.0, 6-7=0.8, 8-10=0.5, >10=0.3. weight=1.5 (`test_cases.py:2199`)
- [ ] **Per-test USD cost** — tokens counted but not priced (no `prompt_tokens`/`completion_tokens` split or provider pricing)

### Validation
- [ ] **Re-benchmark all models** — in progress (2026-02-22 runs for gemini-2.5-flash, gpt-5.1-codex, gpt-5.2, sonar, gemini-3.1-pro-preview)

---

## Deferred (v1.16.1+)

### Goal 10: Interactive File Navigation
- [ ] Clickable file names in `/ls` → open in preview
- [ ] Clickable directories in `/ls` → drill-down re-list
- [ ] Clickable entries in `/tree` → files preview, dirs expand
- [ ] All 4 clients (ppxaide TUI, Web, VSCode, ppxai Rich CLI)

### Goal 11: GenAIScript Integration
- [ ] Agent loop tests as `.genai.mts` scripts with `defTool()` simulated tools
- [ ] Multi-model comparison runner — `npx genaiscript eval` across all configured models
- [ ] Rubric-based code editing eval — LLM-as-judge for `apply_patch` quality
- [ ] CI integration — `npm run benchmark:genaiscript` in `benchmarks/genaiscript/`

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Message format breaks local models | Keep synthetic pairs for prompt-based; only native mode uses `tool` messages |
| Multi-tool breaks consent flow | Execute sequentially; each tool gets individual consent |
| Profile mismatch causes regressions | Default profile = current behavior; explicit opt-in |
| Session format incompatible | Migration layer reads old format, writes new |
| Benchmark scores drop | Re-benchmark before/after; block release if >5% regression |

## What NOT to Change

1. Don't try to fix Tier D models — o4-mini (native), gemini-2.0-flash-exp are fundamentally broken
2. Don't over-engineer profiles — start with existing fields, expand only when benchmarks prove need
3. Don't break `OpenAICompatibleProvider` — must work unchanged with default profiles
4. Don't break `GeminiProvider` — must work unchanged with default profiles

---

## Success Criteria

- [x] **Step 1:** Provider hierarchy — shared interface, no `hasattr` guards (1451 tests pass)
- [x] **Step 2:** Profile-driven routing replaces binary decision in `chat.py` + truncation recovery + sonar profile/hint fixes
- [x] **Step 3:** Proper `tool` role messages for native mode — `Message(tool_calls=, tool_call_id=)`, all providers, session serialization
- [x] **Step 4:** Multi-tool support — `parallel_tool_calls` gating, sequential execution, per-tool consent/loop detection
- [x] **Step 5:** Agent UI noise reduction — Issue A N/A (no real problem) + Issue B grouped tool call display ✓
- [x] **Step 6:** Config overrides for per-model `tool_calling` settings + `/model info` + AGENTS.md `tool_calling` YAML
- [x] **Step 7:** Benchmark v2 — 37 tests across 8 categories (Phase 1-3 done, per-test USD cost remaining)
- [ ] No provider regressions (full benchmark suite)
- [x] Session migration from v1.15.x works seamlessly (None-safe `.get()` for new fields)
- [ ] All existing tests pass + 50+ new tests (currently 1505 tests, all passing)
- [x] `/ls` and `/tree` commands work in all clients
- [x] Session context reset on model switch (B1)
- [x] Per-model iteration limit from ModelProfile (B2)
- [x] Belt-and-suspenders prompt injection (B3)
- [x] SSE disconnect detection (B11)
- [x] Session pollution detection (B7)
- [x] Partial credit scoring (A12/B9)
- [x] Agent loop benchmarks: multi_file_review, claim_without_action, consecutive_tool_loop (B4-B6)
- [x] time_to_first_tool_call benchmark (B8)

---

## Key Code Locations

| Area | File | Key |
|------|------|-----|
| Effective profile merging | `ppxai/engine/chat.py` | `_get_effective_profile()` (3-layer merge) |
| Tool mode resolution | `ppxai/engine/chat.py` | `tc_profile.mode` routing (~line 470) |
| Multi-tool gating | `ppxai/engine/chat.py` | `parallel_tool_calls` flag (~line 607) |
| Native tool messages | `ppxai/engine/chat.py` | `assistant(tool_calls)` + `tool` role (~line 677) |
| Prompt-based messages | `ppxai/engine/chat.py` | Synthetic pairs (~line 703) |
| Truncation retry | `ppxai/engine/chat.py` | Escalating recovery + stuck-loop cap |
| Belt-and-suspenders | `ppxai/engine/chat.py` | Tool hints injected when fallback flags set |
| Pollution check | `ppxai/engine/chat.py` | `check_session_pollution()` after iteration 1 |
| Config overrides | `ppxai/config/__init__.py` | `get_tool_calling_config()` |
| AGENTS.md overrides | `ppxai/engine/bootstrap.py` | `tool_calling_overrides`, `get_tool_calling_overrides()` |
| Validator | `ppxai/engine/tools/validator.py` | Lines 52-462 |
| Session reset | `ppxai/engine/session.py` | Line 215 (`reset_for_model_switch`) |
| Model profiles | `ppxai/engine/model_profiles.py` | 1-488 (37 profiles) |
| Provider caps | `ppxai/engine/providers/openai_native.py` | `get_capabilities_for_model()` |
| Max iterations | `ppxai/engine/tools/manager.py` | Line 25 (default: 15) |
| Provider switch | `ppxai/engine/client.py` | Lines 414-491 |
| Model switch | `ppxai/engine/client.py` | Lines 527-557 |
| Message type | `ppxai/engine/types.py` | `Message` dataclass |
| HTTP /chat | `ppxai/server/http.py` | Line 673 |
| HTTP /provider | `ppxai/server/http.py` | Line 793 |
| HTTP /model | `ppxai/server/http.py` | Line 847 |
| HTTP /files/list | `ppxai/server/http.py` | Line 1639 |
| HTTP /files/tree | `ppxai/server/http.py` | Line 1707 |
| /ls command | `ppxai/commands/utility.py` | Line 622 |
| /tree command | `ppxai/commands/utility.py` | Line 701 |
| Benchmark tests | `benchmarks/llm-eval/test_cases.py` | Line 1367+ (agentic) |
| Benchmark runner | `benchmarks/llm-eval/engine_runner.py` | Partial credit scoring |
