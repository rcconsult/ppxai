# TODO: v1.16.0 — Profile-Driven Tool Loop

**Branch:** feature/v1.16.0
**Previous:** [ARCHIVE-v1.15.6-debug-sessions.md](ARCHIVE-v1.15.6-debug-sessions.md)
**Release Plan:** [RELEASE-PLAN-v1.15.6-v1.16.0.md](RELEASE-PLAN-v1.15.6-v1.16.0.md)

---

## P1

- [x] **B1** Session context reset on model switch — `session.reset_for_model_switch()`, `client.set_model(reset_context=)`, `http.py` request models. All session restore paths pass `reset_context=False`.

## P2

- [x] **A3** Emit warning on model switch — `client.last_model_switch_reset`, `/model` and `/provider` commands show cleared count, TUI notifies user.
- [x] **A12** Benchmark partial credit scoring — `engine_runner.py` supports `score` (0.0-1.0) in test details, backward-compatible with bool. Tool calling tests award +50% for correct tool name, +50% for correct args.
- [x] **B2** Per-model iteration limit — `ModelProfile.max_tool_iterations` field, populated for sonar(20), gemini(25), codex-mini(20), qwen3-coder(20). `chat.py` uses `max(manager.max_iterations, profile.max_tool_iterations)`.
- [x] **B3** Belt-and-suspenders prompt injection — `chat.py` native mode injects `get_tools_prompt()` when profile has `fallback_on_empty` or `fallback_on_failure`.
- [x] **B4** `multi_file_review` benchmark — score = files_read / files_available. Claims without tool calls = 0.0. Multi-turn with simulated file contents.
- [x] **B5** `claim_without_action` benchmark — fabricated report = 0.0, honest refusal = 1.0. Detects fabrication vs honest refusal patterns.
- [x] **B6** `consecutive_tool_loop` benchmark — 5-step dependent chain: list_dir → read config → read entry → search → read match. Score = steps_completed / 5.
- [x] **B9** Partial credit scoring — merged into A12 implementation.
- [x] **B11** SSE disconnect detection — `request.is_disconnected()` in `sse_event_generator`, `raw_request: Request` parameter on `/chat` endpoint.

## P3

- [x] **B7** Session pollution detection — `check_session_pollution()` in validator, bigram similarity >90% → WARNING. Wired into `chat.py` after first iteration response.
- [x] **B8** `time_to_first_tool_call` benchmark — penalize >100 chars preamble before tool call. Score: 1.0 (clean), 0.5 (verbose), 0.0 (no tool call).

## Goal 9: Grouped Tool Call UI

- [ ] **Engine SSE events** — New `TOOL_GROUP_START` / `TOOL_GROUP_END` events wrapping multiple tool calls from a single iteration
- [ ] **Web app** — Render grouped tool calls in a single collapsible bubble with scrollable content (tool name + result per row)
- [ ] **VSCode extension** — Same grouped bubble in chat panel webview, collapsible with expand/collapse toggle
- [ ] **ppxaide TUI** — Grouped tool calls in a single panel/container (Textual Collapsible or vertical scroll)
- [ ] **ppxai Rich CLI** — Compact grouped output with separator lines between tool results

**Depends on:** Goal 3 (multi-tool support) — without processing all tool calls, there's nothing to group.

## Goal 10: Interactive File Navigation (v1.16.1+)

- [ ] **Clickable file names in `/ls` results** — clicking a file opens it in preview (side panel / CodeEditor / Monaco)
- [ ] **Clickable directories in `/ls` results** — clicking a directory re-runs `/ls` on that path (drill-down navigation)
- [ ] **Clickable entries in `/tree` results** — files open in preview, directories expand or run `/ls` on click
- [ ] **ppxaide TUI** — TreeResult/TableResult entries emit click events via EventBus, handlers open preview or re-list
- [ ] **Web app** — Rendered entries are anchor/button elements, click triggers `handleLsCommand(path)` or file preview
- [ ] **VSCode extension** — Entries rendered as clickable links, file click opens in native editor, directory click drills down
- [ ] **ppxai Rich CLI** — Copy-to-clipboard button per entry (copies full absolute path), usable with `/show` command for markdown rendering with citations and clickable links

**Depends on:** Goal 5 (`/ls`, `/tree` commands) — completed in v1.16.0.

## Goal 11: GenAIScript Integration (v1.16.1+)

- [ ] **B12** Agent loop tests as `.genai.mts` scripts with `defTool()` simulated tools
- [ ] Multi-model comparison runner — `npx genaiscript eval` across all configured models
- [ ] Rubric-based code editing eval — LLM-as-judge for `apply_patch` quality
- [ ] CI integration — `npm run benchmark:genaiscript` in `benchmarks/genaiscript/`

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
