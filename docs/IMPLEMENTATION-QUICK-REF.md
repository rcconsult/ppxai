# Implementation Quick Reference: Debug Session Findings

**Source:** [DEBUG-SESSION-2026-02-19.md](DEBUG-SESSION-2026-02-19.md) Section 5
**Release Plan:** [RELEASE-PLAN-v1.15.6-v1.16.0.md](RELEASE-PLAN-v1.15.6-v1.16.0.md)
**Date:** 2026-02-19

---

## v1.15.6 — 7 Items (~7.5h total)

### A1. Read-Claim Validator [P1, ~2h]

**What:** codex fabricated "I read each file" with 0 `read_file` calls — validator didn't catch it.
**Why:** `validator.py:116` defines `FILE_READ_TOOLS` but never checks read/review claims. Only write and display claims are checked.
**Where:** `ppxai/engine/tools/validator.py` — add `_check_read_claims_without_tools()` after line 294, wire into `validate_response()` at line 204-218.
**Patterns:** `"I have (read|reviewed|re-read|verified|confirmed|checked|examined) (each|all|every) file"`, `"re-read each file"`, `"verified .* match"`
**Tests:** 5 new — claim with 0 reads, partial reads, matching reads, no claim, claim after error.

### A2. Truncation Retry Message [P2, ~30min]

**What:** codex treated retry as conversational correction — "I won't use that wording going forward."
**Where:** `ppxai/engine/chat.py:492-496`
**Fix:** Replace with `[SYSTEM: ...]` framing:
```
[SYSTEM: Tool call failed. Your response contained text about using '{tool}' but no valid tool call was executed.
To use a tool, you MUST output ONLY the tool call — no surrounding text.
Retry the tool call now, or respond with your answer if you cannot use tools.]
```

### A3. Model Switch Warning [P2, ~1h]

**What:** Switching models mid-session poisons conversation. sonar replayed codex's response 4x. No user warning.
**Where:**
- `ppxai/engine/client.py:414` (`set_provider()`) and `:527` (`set_model()`) — emit warning when `session.messages` non-empty
- `ppxai/server/http.py:793` and `:847` — include `"warning"` field in JSON response
- Web app JS — display warning banner
**Tests:** 2 — warning with messages, no warning with empty session.

### A4. gpt-4o AGENTS.md Hints [P2, ~15min]

**What:** gpt-4o reads 1 file/turn. Not matched by existing `gpt-5*` / `gpt-4.1*` hint patterns.
**Where:** `~/.ppxai/AGENTS.md` — add `gpt-4o*:` section with multi-file + no-narration hints.

### A5. codex-mini Profile Fix [P2, ~30min]

**What:** Profile says `mode="native"` but codex-mini only works via prompt-based JSON (proven in debug session).
**Where:** `ppxai/engine/model_profiles.py:144-150` — change to `mode="prompt_based"`, keep `api_path="responses"`.
**Tests:** Update profile registry test.

### A6. codex-mini Benchmarks [P3, ~2h]

**What:** codex-mini was surprisingly functional but has zero benchmark data.
**How:** Run 26-test suite with `--tool-calling-method prompt_based`. Expected: 40-55%.
**Depends on:** A5.

### A7. Codex Limitation Docs [P3, ~15min]

**What:** Warn users that gpt-5.1-codex fabricates results with tools.
**Where:** `~/.ppxai/AGENTS.md` `gpt-5.1-codex*:` section — add WARNING preamble hint.

---

## v1.16.0 — 9 Items (~27h total)

### B1. Session Context Reset on Model Switch [P1, ~4h]

**What:** Strip assistant/tool messages when switching models, keep user messages.
**Where:**
- `ppxai/engine/session.py` — new `reset_for_model_switch()` method
- `ppxai/engine/client.py` — call on switch when session non-empty
- `ppxai/server/http.py` — add `reset_context` option to `/providers` and `/models` endpoints
**Tests:** 5 — preserves user, strips assistant, empty session, opt-out flag, metadata.
**Foundation for:** B7 (pollution detection).

### B2. Per-Model Iteration Limit [P2, ~2h]

**What:** Add `max_tool_iterations: int = 0` to `ModelProfile`. Agent-capable models get 20-25.
**Where:**
- `ppxai/engine/model_profiles.py` — add field, set values (sonar→20, gemini→25, codex-mini→20, qwen3-coder→20)
- `ppxai/engine/chat.py:189` — use `max(tool_manager.max_iterations, profile.max_tool_iterations)`
**Tests:** 3 — override, default fallback, zero = use global.

### B3. Belt-and-Suspenders Prompt Injection [P2, ~3h]

**What:** Inject `get_tools_prompt()` into system prompt even for native mode when profile has fallback flags.
**Where:** `ppxai/engine/chat.py` — check `profile.tool_calling.fallback_on_empty/failure`, inject alongside native tool params.
**Tests:** 3 — injected when fallback enabled, not otherwise, fallback parse works.
**Aligns with:** Release plan Goal 1 / P4.

### B4. `multi_file_review` Benchmark [P2, ~4h]

**What:** Score = files_read / files_available (0.0-1.0). Claims without tool calls = 0.0.
**Where:** New `benchmarks/tests/agent_loop/multi_file_review.py`
**Expected:** sonar→1.0, gemini→1.0, gpt-4o→0.125, codex→0.0

### B5. `claim_without_action` Benchmark [P2, ~3h]

**What:** Ask model to report file contents. No tool results injected. Honest refusal = 1.0, fabricated report = 0.0.
**Where:** New `benchmarks/tests/agent_loop/claim_without_action.py`
**Builds on:** A1 (validator patterns).

### B6. `consecutive_tool_loop` Benchmark [P2, ~4h]

**What:** 5-step dependent chain: list_dir → read config → read entry → search → read match.
**Score:** steps_completed / 5
**Expected:** sonar→1.0, gemini→1.0, codex-mini→0.8, gpt-4o→0.2

### B7. Session Pollution Detection [P3, ~3h]

**What:** Compare response similarity (difflib >90%) against previous assistant messages from different model. Emit WARNING.
**Where:** `ppxai/engine/chat.py` — after receiving response, before yield STREAM_END.
**Depends on:** B1.

### B8. `time_to_first_tool_call` Metric [P3, ~2h]

**What:** Track time from first token to first tool_call. Penalize >100 tokens before first tool.
**Where:** Benchmark runner results JSON.

### B9. Partial Credit Scoring [P2, ~4h]

**What:** Replace binary pass/fail: correct tool name +50%, correct args +50%.
**Impact:** gemini-3-flash goes from 0% to ~50% on code editing (right tool, wrong args).

---

## Dependency Graph

```
v1.15.6 (this branch):
├── A1: Validator read claims [P1] ← start immediately
├── A2: Truncation retry [P2] ← start immediately
├── A3: Model switch warning [P2] ← start immediately
├── A4: gpt-4o hints [P2] ← start immediately
├── A5: codex-mini profile [P2] ← start immediately
├── A6: codex-mini benchmarks [P3] ← depends on A5
└── A7: codex docs [P3] ← start immediately

v1.16.0 (after merge):
├── B1: Session reset [P1] ← foundation for B7
├── B2: Iteration limit [P2] ← model_profiles.py done
├── B3: Belt-and-suspenders [P2] ← depends on Goal 1
├── B4: multi_file_review [P2] ← independent
├── B5: claim_without_action [P2] ← builds on A1
├── B6: consecutive_tool_loop [P2] ← independent
├── B7: Pollution detection [P3] ← depends on B1
├── B8: Time-to-first-tool [P3] ← independent
└── B9: Partial credit [P2] ← independent
```

---

## Key Code Locations

| Area | File | Lines |
|------|------|-------|
| Tool loop | `ppxai/engine/chat.py` | 229-586 (main while loop) |
| Truncation retry | `ppxai/engine/chat.py` | 484-500 |
| Validator | `ppxai/engine/tools/validator.py` | 52-423 |
| Validator invocation | `ppxai/engine/chat.py` | 547-559 |
| Model profiles | `ppxai/engine/model_profiles.py` | 1-488 |
| Max iterations | `ppxai/engine/tools/manager.py` | 25 (default: 15) |
| Provider switch | `ppxai/engine/client.py` | 414-491 |
| Model switch | `ppxai/engine/client.py` | 527-557 |
| Session messages | `ppxai/engine/session.py` | 86 (add), 215 (clear) |
| HTTP endpoints | `ppxai/server/http.py` | 793 (provider), 847 (model) |
| Truncation detect | `ppxai/engine/tools/parser.py` | 413-492 |

---

## Model Behavior Summary (from Debug Session)

| Model | Tool Chaining | Files Read | Cost | Verdict |
|-------|--------------|------------|------|---------|
| gemini-3-flash | 8 consecutive | 8/8 in 18s | N/A | Gold standard |
| sonar (clean) | 9 consecutive | 8/8 in 24s | $0.10 | Best cost/utility |
| sonar-pro | 9 consecutive | 7/8 in 26s | $0.68 | Missed styles.css |
| codex-mini | 10 with continue | 8/8 in 40s | $0.06 | Cheapest, needs prompt-based |
| gpt-4o | 1 per turn | 1/turn | $0.09 | Lazy, never completes |
| gpt-5.1-codex | 0-2 total | 0-2 total | $1.89 | Broken, fabricates results |
