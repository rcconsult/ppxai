# Implementation Quick Reference: v1.16.0

**Active TODO:** [TODO-v1.16.0.md](TODO-v1.16.0.md) — single source of truth for all v1.16.0 items
**v1.15.6 archive:** [ARCHIVE-v1.15.6-debug-sessions.md](ARCHIVE-v1.15.6-debug-sessions.md) | [RELEASE-PLAN-v1.15.6-v1.16.0.md](RELEASE-PLAN-v1.15.6-v1.16.0.md)

---

## Completed (macOS session, 2026-02-20)

All P1-P3 foundation items are done:

- [x] **B1** Session context reset — `session.reset_for_model_switch()`, `client.set_model(reset_context=)`
- [x] **B2** Per-model iteration limit — `ModelProfile.max_tool_iterations`
- [x] **B3** Belt-and-suspenders — native mode injects `get_tools_prompt()` for fallback profiles
- [x] **B4** `multi_file_review` benchmark
- [x] **B5** `claim_without_action` benchmark
- [x] **B6** `consecutive_tool_loop` benchmark
- [x] **B7** Session pollution detection — `check_session_pollution()` bigram similarity
- [x] **B8** `time_to_first_tool_call` benchmark
- [x] **B9/A12** Partial credit scoring (0.0-1.0)
- [x] **B11** SSE disconnect detection — `request.is_disconnected()`
- [x] **Goal 5** `/ls` and `/tree` commands — all 3 clients + HTTP endpoints

## Open (see TODO-v1.16.0.md for full details)

| Goal | Summary | Effort |
|------|---------|--------|
| **Goal 1** | Profile-driven tool loop — replace binary decision in `chat.py:210` | ~15h |
| **Goal 2** | Proper `tool` role messages — extend `Message`, update providers | ~16h |
| **Goal 3** | Multi-tool support — process all native tool calls | ~12h |
| **Goal 4** | Config integration — per-model overrides, `/model info` | ~9h |
| **Goal 6** | Provider hierarchy — shared ABC, remove `hasattr` guards | ~10h |
| **Goal 7** | Benchmark v2 remaining — Phase 2 agentic tests, efficiency metrics | ~24h |
| **Goal 9** | Grouped Tool Call UI — `TOOL_GROUP_START/END`, all clients | ~TBD |

---

## Key Code Locations

| Area | File | Key |
|------|------|-----|
| Binary decision (to replace) | `ppxai/engine/chat.py` | Line 210 (`use_native_tools`) |
| Tool loop (main while) | `ppxai/engine/chat.py` | Lines 229-586 |
| Single tool extraction (to fix) | `ppxai/engine/chat.py` | Line 331 (`native_tool_calls[0]`) |
| Synthetic message pairs (to fix) | `ppxai/engine/chat.py` | Lines 437-444 |
| Belt-and-suspenders (done) | `ppxai/engine/chat.py` | Lines 296-312 |
| Pollution check (done) | `ppxai/engine/chat.py` | Lines 591-605 |
| Session reset (done) | `ppxai/engine/session.py` | Line 215 |
| Model profiles | `ppxai/engine/model_profiles.py` | 37 profiles |
| Message type (to extend) | `ppxai/engine/types.py` | `Message` dataclass |
| Provider caps (to replace) | `ppxai/engine/providers/openai_native.py` | `get_capabilities_for_model()` |
| Validator | `ppxai/engine/tools/validator.py` | Lines 52-462 |
| Max iterations | `ppxai/engine/tools/manager.py` | Line 25 (default: 15) |
| HTTP /chat | `ppxai/server/http.py` | Line 673 |
| HTTP /files/list (done) | `ppxai/server/http.py` | Line 1639 |
| HTTP /files/tree (done) | `ppxai/server/http.py` | Line 1707 |
| Benchmark agentic tests | `benchmarks/llm-eval/test_cases.py` | Line 1367+ |
