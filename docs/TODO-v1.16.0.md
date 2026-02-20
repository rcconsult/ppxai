# TODO: v1.16.0 — Profile-Driven Tool Loop

**Branch:** TBD (after v1.15.6 merge to master)
**Previous:** [ARCHIVE-v1.15.6-debug-sessions.md](ARCHIVE-v1.15.6-debug-sessions.md)
**Release Plan:** [RELEASE-PLAN-v1.15.6-v1.16.0.md](RELEASE-PLAN-v1.15.6-v1.16.0.md)

---

## P1

- [ ] **B1** Session context reset on model switch — strip assistant/tool messages, keep user messages. `session.py` new `reset_for_model_switch()`, `client.py` call on switch, `http.py` add `reset_context` option. Foundation for B7. **Validated critical by Session 2:** codex-mini worked clean, broke with polluted context.

## P2

- [ ] **A3** (from v1.15.6) Emit warning on model switch when session has messages
- [ ] **A12** (from v1.15.6) Benchmark test design review — binary scoring doesn't test agent loops
- [ ] **B2** Per-model iteration limit — add `max_tool_iterations` to `ModelProfile` (sonar→20, gemini→25, codex-mini→20, qwen3-coder→20). Use `max(tool_manager.max_iterations, profile.max_tool_iterations)` in `chat.py`.
- [ ] **B3** Belt-and-suspenders prompt injection — inject `get_tools_prompt()` into system prompt for native mode when profile has fallback flags. Generalize codex A8 pattern.
- [ ] **B4** `multi_file_review` benchmark — score = files_read / files_available. Claims without tool calls = 0.0.
- [ ] **B5** `claim_without_action` benchmark — fabricated report = 0.0, honest refusal = 1.0. Builds on A1 validator.
- [ ] **B6** `consecutive_tool_loop` benchmark — 5-step dependent chain: list_dir → read config → read entry → search → read match.
- [ ] **B9** Partial credit scoring — correct tool name +50%, correct args +50%.
- [ ] **B11** SSE disconnect detection — `request.is_disconnected()` in `sse_event_generator` to cancel background task.
- [ ] **B12** GenAIScript integration — Phase 1-2 agent loop tests as `.genai.mts` scripts.

## P3

- [ ] **B7** Session pollution detection — >90% response similarity to previous model → WARNING. Depends on B1.
- [ ] **B8** `time_to_first_tool_call` metric — penalize >100 tokens before first tool call.

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
