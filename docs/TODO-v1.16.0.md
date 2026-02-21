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
Step 1: Provider Hierarchy    (no deps — simplifies everything after)
   │
Step 2: Profile-Driven Loop   (needs Step 1's clean interface)
   │
   ├─→ Step 3: Tool Messages  (needs Step 2's profile routing)
   │      │
   │      └─→ Step 4: Multi-Tool  (needs Step 3's message format)
   │             │
   │             └─→ Step 6: Grouped UI  (needs Step 4's multi-tool)
   │
   └─→ Step 5: Config Integration  (needs Step 2's profiles, independent of 3-4)

Step 7: Benchmark v2          (independent — can run in parallel with any step)
```

---

## Step 1: Provider Hierarchy Refactoring

**Dependencies:** None — do first, it removes `hasattr` guards and simplifies Steps 2-4.

`OpenAINativeProvider` and `GeminiProvider` are standalone classes with duck typing (`hasattr` guards). This works but is fragile.

- [ ] **Shared ABC or Protocol** — `OpenAINativeProvider` and `GeminiProvider` inherit from `BaseProvider` or `ProviderProtocol` (3h)
- [ ] **Eliminate duplicate methods** — move `needs_tool`, `get_model_profile`, `_format_error`, `_log_error_traceback` to base (2h)
- [ ] **Remove `hasattr` guards** — replace `hasattr(provider, 'get_capabilities_for_model')` in `chat.py` with guaranteed interface (1h)
- [ ] **`get_capabilities_for_model` → profile** — replace with `get_model_profile()` as single source of truth (2h)
- [ ] **Tests** — all providers pass shared interface compliance test (2h)

---

## Step 2: Profile-Driven Tool Loop

**Dependencies:** Step 1 (clean provider interface with guaranteed `get_model_profile()`)

Replace the binary decision point in `chat.py:210`:

```python
# BEFORE:
use_native_tools = bool(provider_caps and provider_caps.native_tool_calling)

# AFTER:
profile = ctx.provider.get_model_profile(ctx.model) or default_profile
tc_mode = profile.tool_calling.mode
```

- [ ] **Replace binary decision** — `chat.py:210` uses profile lookup instead of capability check (2h)
- [ ] **`strip_json_from_text`** — when profile says strip AND native tool calls present, clean response text (3h)
- [ ] **`fallback_on_empty`** — when native returns empty, fall back to prompt-based parsing (3h)
- [ ] **`auto` mode** — start native, switch to prompt-based on first empty/failure (2h)
- [ ] **Backwards compat** — missing profile → default profile → current behavior (1h)
- [ ] **Tests** — profile-driven routing unit tests with mock provider (4h)

**Note:** Belt-and-suspenders (B3) already done — injects tool descriptions for fallback-enabled profiles.

---

## Step 3: Proper Tool Message Format

**Dependencies:** Step 2 (profile routing determines when to use `tool` role vs synthetic pairs)

Replace synthetic message pairs with proper `tool` role messages:

```python
# BEFORE (chat.py:437-444):
ctx.session.add_message(Message("assistant", f"I'll use the {tool_name} tool..."))
ctx.session.add_message(Message("user", f"The {tool_name} tool returned..."))

# AFTER (native mode):
ctx.session.add_message(Message("assistant", "", tool_calls=[...]))
ctx.session.add_message(Message("tool", result, tool_call_id=tc_id))
```

- [ ] **Extend `Message` type** — add `tool_calls` and `tool_call_id` fields to `Message` dataclass (1h)
- [ ] **Native mode messages** — use proper `assistant` (with tool_calls) + `tool` role messages (3h)
- [ ] **Prompt-based unchanged** — keep synthetic pairs for prompt-based mode (0h)
- [ ] **Provider message conversion** — all providers handle `tool` role in `_convert_messages()` (4h)
- [ ] **Session serialization** — save/load handles new message fields (2h)
- [ ] **Migration** — v1.15.x sessions with old format still load correctly (2h)
- [ ] **Tests** — message format, session serialization, provider conversion (4h)

---

## Step 4: Multi-Tool Support

**Dependencies:** Step 3 (proper tool messages needed to send multiple tool results per iteration)

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

- [ ] **Sequential tool execution** — process all native tool calls in sequence (not parallel — safety) (3h)
- [ ] **Multi-result events** — emit multiple `TOOL_CALL`/`TOOL_RESULT` events per iteration (2h)
- [ ] **Session messages** — add all tool call/result message pairs (1h)
- [ ] **Consent handling** — each tool call still requires individual consent (2h)
- [ ] **Loop detection** — update tool loop detection for multi-tool iterations (1h)
- [ ] **Tests** — multi-tool extraction, execution, message format (3h)

---

## Step 5: Config Integration

**Dependencies:** Step 2 (profiles must exist before config can override them; independent of Steps 3-4)

- [ ] **Config overrides** — `tool_calling` section in `ppxai-config.json` per model (2h)
- [ ] **AGENTS.md influence** — model hints can set `tool_calling_mode: prompt_based` (2h)
- [ ] **`/model info` command** — show active profile for current model (2h)
- [ ] **Documentation** — config format, profile precedence, migration guide (3h)

---

## Step 6: Grouped Tool Call UI

**Dependencies:** Step 4 (multi-tool support) — without processing all tool calls, there's nothing to group.

- [ ] **Engine SSE events** — new `TOOL_GROUP_START` / `TOOL_GROUP_END` events wrapping multiple tool calls from a single iteration
- [ ] **Web app** — render grouped tool calls in a single collapsible bubble (tool name + result per row)
- [ ] **VSCode extension** — same grouped bubble in chat panel, collapsible with expand/collapse
- [ ] **ppxaide TUI** — grouped tool calls in Textual Collapsible or vertical scroll
- [ ] **ppxai Rich CLI** — compact grouped output with separator lines

---

## Step 7: Benchmark v2 — Remaining Items

**Dependencies:** None — can run in parallel with any step. Re-benchmark after Steps 2-4 to validate.

Phase 1 (scoring distortions) is mostly done. Remaining:

### Phase 1 (remaining)
- [ ] **`patch_apply_verify`** — model generates patch, actually apply with `_replace_hunk`, verify output (4h)

### Phase 2: Agentic Patterns
- [ ] **`search_then_edit`** — search_code → read_file → apply_patch without given path (4h)
- [ ] **`test_fix_verify`** — write code → test failure → fix → re-test → pass (5h)
- [ ] **`information_gathering`** — find and read 3 auth files spread across project (4h)
- [ ] **`error_recovery_chain`** — read → not found → search → read → edit → permission denied (3h)

### Phase 3: Efficiency & Hints
- [ ] **Token/cost metrics** — `prompt_tokens`, `completion_tokens`, `total_cost` per test (3h)
- [ ] **With/without AGENTS.md** — run suite twice per model, report delta (3h)
- [ ] **Tool call efficiency** — total calls vs minimum required (2h)

### Validation
- [ ] **Re-benchmark all models** — full v2 suite, validate ranking matches real-world matrix (manual)

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

- [ ] **Step 1:** Provider hierarchy — shared interface, no `hasattr` guards
- [ ] **Step 2:** Profile-driven routing replaces binary decision in `chat.py`
- [ ] **Step 3:** Proper `tool` role messages for native mode
- [ ] **Step 4:** Multi-tool support for models returning parallel calls
- [ ] **Step 5:** Config overrides for per-model `tool_calling` settings + `/model info`
- [ ] **Step 6:** Grouped tool call UI in all clients
- [ ] **Step 7:** Benchmark v2 agentic tests + efficiency metrics
- [ ] No provider regressions (full benchmark suite)
- [ ] Session migration from v1.15.x works seamlessly
- [ ] All existing tests pass + 50+ new tests
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
| Tool loop (binary decision) | `ppxai/engine/chat.py` | Line 210 (`use_native_tools`) |
| Tool loop (main while) | `ppxai/engine/chat.py` | Lines 229-586 |
| Single tool extraction | `ppxai/engine/chat.py` | Line 331 (`native_tool_calls[0]`) |
| Synthetic message pairs | `ppxai/engine/chat.py` | Lines 437-444 |
| Truncation retry | `ppxai/engine/chat.py` | Lines 504-509 |
| Belt-and-suspenders | `ppxai/engine/chat.py` | Lines 296-312 |
| Pollution check | `ppxai/engine/chat.py` | Lines 591-605 |
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
