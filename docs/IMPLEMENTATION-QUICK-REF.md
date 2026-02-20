# Implementation Quick Reference: v1.16.0

**v1.15.6 items:** All done → [ARCHIVE-v1.15.6-debug-sessions.md](ARCHIVE-v1.15.6-debug-sessions.md)
**Release Plan:** [RELEASE-PLAN-v1.15.6-v1.16.0.md](RELEASE-PLAN-v1.15.6-v1.16.0.md)

---

## B1. Session Context Reset on Model Switch [P1, ~4h]

**What:** Strip assistant/tool messages when switching models, keep user messages.
**Where:**
- `ppxai/engine/session.py` — new `reset_for_model_switch()` method
- `ppxai/engine/client.py` — call on switch when session non-empty
- `ppxai/server/http.py` — add `reset_context` option to `/providers` and `/models` endpoints
**Tests:** 5 — preserves user, strips assistant, empty session, opt-out flag, metadata.
**Foundation for:** B7 (pollution detection).

## B2. Per-Model Iteration Limit [P2, ~2h]

**What:** Add `max_tool_iterations: int = 0` to `ModelProfile`. Agent-capable models get 20-25.
**Where:**
- `ppxai/engine/model_profiles.py` — add field, set values (sonar→20, gemini→25, codex-mini→20, qwen3-coder→20)
- `ppxai/engine/chat.py:189` — use `max(tool_manager.max_iterations, profile.max_tool_iterations)`
**Tests:** 3 — override, default fallback, zero = use global.

## B3. Belt-and-Suspenders Prompt Injection [P2, ~3h]

**What:** Inject `get_tools_prompt()` into system prompt even for native mode when profile has fallback flags.
**Where:** `ppxai/engine/chat.py` — check `profile.tool_calling.fallback_on_empty/failure`, inject alongside native tool params.
**Tests:** 3 — injected when fallback enabled, not otherwise, fallback parse works.

## B4. `multi_file_review` Benchmark [P2, ~4h]

**What:** Score = files_read / files_available (0.0-1.0). Claims without tool calls = 0.0.
**Where:** New `benchmarks/tests/agent_loop/multi_file_review.py`

## B5. `claim_without_action` Benchmark [P2, ~3h]

**What:** Ask model to report file contents. No tool results injected. Honest refusal = 1.0, fabricated report = 0.0.
**Builds on:** A1 (validator patterns).

## B6. `consecutive_tool_loop` Benchmark [P2, ~4h]

**What:** 5-step dependent chain: list_dir → read config → read entry → search → read match.
**Score:** steps_completed / 5

## B7. Session Pollution Detection [P3, ~3h]

**What:** Compare response similarity (difflib >90%) against previous assistant messages from different model. Emit WARNING.
**Depends on:** B1.

## B8. `time_to_first_tool_call` Metric [P3, ~2h]

**What:** Track time from first token to first tool_call. Penalize >100 tokens before first tool.

## B9. Partial Credit Scoring [P2, ~4h]

**What:** Replace binary pass/fail: correct tool name +50%, correct args +50%.

## B11. SSE Disconnect Detection [P2, ~2h]

**What:** Use `request.is_disconnected()` in `sse_event_generator` to cancel background task when client disconnects.

## B12. GenAIScript Integration [P2, ~4h]

**What:** Phase 1-2 agent loop tests as `.genai.mts` scripts with `defTool()` simulated tools.

---

## Key Code Locations

| Area | File | Lines |
|------|------|-------|
| Tool loop | `ppxai/engine/chat.py` | 229-586 (main while loop) |
| Truncation retry | `ppxai/engine/chat.py` | 504-509 |
| Validator | `ppxai/engine/tools/validator.py` | 52-462 |
| Validator invocation | `ppxai/engine/chat.py` | 547-559 |
| Model profiles | `ppxai/engine/model_profiles.py` | 1-488 |
| PROMPT_BASED_MODEL_PREFIXES | `ppxai/engine/providers/openai_native.py` | 46, 266 |
| Max iterations | `ppxai/engine/tools/manager.py` | 25 (default: 15) |
| Provider switch | `ppxai/engine/client.py` | 414-491 |
| Model switch | `ppxai/engine/client.py` | 527-557 |
| Session messages | `ppxai/engine/session.py` | 86 (add), 215 (clear) |
| HTTP endpoints | `ppxai/server/http.py` | 793 (provider), 847 (model) |
| Truncation detect | `ppxai/engine/tools/parser.py` | 413-492 |
| ppxaide debug-log | `ppxai/tui/app.py` | 1505 (intercept), 2012 (toggle) |
