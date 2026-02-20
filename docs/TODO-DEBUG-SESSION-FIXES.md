# TODO: Debug Session Fixes (2026-02-19 / 2026-02-20)

**Branch:** `feature/benchmark-openai-models`
**Context:** [DEBUG-SESSION-2026-02-19.md](DEBUG-SESSION-2026-02-19.md) | [RELEASE-PLAN-v1.15.6-v1.16.0.md](RELEASE-PLAN-v1.15.6-v1.16.0.md)

---

## v1.15.6 — Do Before Merge

### Critical / P0

- [x] **A0** [P0] Fix `TypeError: 'bool' is not iterable` crash for Responses API models — removed `openai_tools = True` sentinel in `chat.py:217`
- [x] **H1** [P0] Fix "Make ONE tool call" anti-pattern in AGENTS.md — replaced all 24 occurrences with "Avoid duplicate calls. Chain multiple DIFFERENT tool calls without stopping to narrate"
- [x] **H2** [P0] Add interrupt check during tool execution — `chat.py:372` now checks `is_interrupted` and cancels running tool task
- [x] **H3** [P0] Add interrupt check after provider.chat() returns — `chat.py:327` catches interrupt before tool processing
- [x] **A8** [P0→done] Enable codex native tool calling via Responses API — removed `_is_responses_api_model()` from prompt-based override in `get_capabilities_for_model()`, added belt-and-suspenders tool hint injection in `_chat_responses_api()`, added `_build_tool_hint()` method

### P1

- [ ] **A1** [P1] Add `_check_read_claims_without_tools()` to `validator.py` — catch "I read each file" with 0 `read_file` calls + 5 tests

### P2

- [ ] **A2** [P2] Change truncation retry message to `[SYSTEM: ...]` framing in `chat.py:492-496` — codex misinterpreted retry as conversation
- [ ] **A3** [P2] Emit warning on model switch when session has messages — `client.py:set_provider()/set_model()` + server JSON response + web app banner
- [x] **A4** [P2] Add `gpt-4o*:` model hints to AGENTS.md — multi-file reading + no-narration between tool calls
- [x] **A5** [P2→done] Update codex profiles in `model_profiles.py` — both `gpt-5.1-codex*` and `gpt-5.1-codex-mini*` now `mode="native"` (native tool calling via Responses API works after A8 fix)
- [ ] **A9** [P2] Fix o3-mini routing — currently goes through `OpenAICompatibleProvider` which uses `max_tokens` instead of `max_completion_tokens`. Should route through `OpenAINativeProvider`.
- [ ] **A10** [P2] Add `gpt-5-mini*` hints — "Do NOT ask permission before using tools. Call tools immediately without explaining."
- [ ] **A11** [P2] Investigate gpt-5-nano synthesis failure — model returns empty after 11 tool calls. Consider: higher `max_output_tokens` for synthesis call, or reduce iteration limit for nano models.
- [ ] **A12** [P2] Benchmark test design review — current 26-test suite uses binary pass/fail scoring, doesn't test agent loop patterns (multi-file, consecutive chains, claim-without-action), and scoring doesn't correlate with real-world agent utility. See Session 3 analysis.

### P3

- [x] **A6** [P3→done] Run codex models in live testing — gpt-5.1-codex: 25+ iterations, gpt-5.1-codex-mini: 19 iterations + synthesis. Both fully functional with native tool calling.
- [x] **A7** [P3→done] Updated codex AGENTS.md hints — changed from "prompt-based" to "native function calling" language, removed outdated "don't output JSON in text" instructions

## v1.16.0 — After Merge

### P1

- [ ] **B1** [P1] `session.reset_for_model_switch()` — strip assistant/tool messages, keep user messages (foundation for B7). **Validated critical by Session 2:** codex-mini worked in Session 1 (clean), broke in Session 2 (polluted by codex refusals)

### P2

- [ ] **B2** [P2] Add `max_tool_iterations` to `ModelProfile` — sonar→20, gemini-2.5-flash→25, gpt-5-nano→8 (prevent empty synthesis). Note: global config already doubled to 50 in Session 3.
- [ ] **B3** [P2] Belt-and-suspenders — inject tool prompt into system message for profiles with fallback flags (partially done for codex in A8, needs generalization)
- [ ] **B4** [P2] `multi_file_review` benchmark test — score = files_read / files_available
- [ ] **B5** [P2] `claim_without_action` benchmark test — fabricated report = 0.0, honest refusal = 1.0
- [ ] **B6** [P2] `consecutive_tool_loop` benchmark test — 5-step dependent chain
- [ ] **B9** [P2] Partial credit scoring — tool name 50% + args 50%
- [ ] **B11** [P2] SSE disconnect detection — use `request.is_disconnected()` in `sse_event_generator` to cancel background task when client disconnects
- [ ] **B12** [P2] GenAIScript integration — implement Phase 1-2 agent loop tests as `.genai.mts` scripts with `defTool()` simulated tools, multi-model comparison runner, rubric-based code editing eval. Lives in `benchmarks/genaiscript/`.

### P3

- [ ] **B7** [P3] Session pollution detection — >90% similarity to previous model's response → WARNING
- [ ] **B8** [P3] `time_to_first_tool_call` metric in benchmark runner

## Already Done (Sessions 1 + 2 + 3)

### Session 1 (Windows, 2026-02-19 21:30–22:00)
- [x] Anti-fabrication hints for `sonar*` in AGENTS.md
- [x] Strengthened `perplexity:` provider hints
- [x] Multi-file reading hints for `gpt-5*`, `gpt-4.1*`, `gpt-5.2*`
- [x] Prompt-based format instructions for `gpt-5.1-codex*`
- [x] AGENTS.md version section updated to v1.15.6

### Session 2 (macOS, 2026-02-20 00:00–00:42)
- [x] **A0:** Fixed `TypeError: 'bool' is not iterable` crash — `chat.py:217` removed bool sentinel
- [x] **H1:** "Make ONE tool call" anti-pattern fixed — 24 occurrences in AGENTS.md (14 repo + 10 global)
- [x] **H2:** Interrupt check added during tool execution wait loop — `chat.py:372`
- [x] **H3:** Interrupt check added after provider.chat() returns — `chat.py:327`
- [x] **A4:** Added `gpt-4o*` and `gpt-5.1-codex-mini*` model hints to AGENTS.md
- [x] Rebuilt and installed all binaries (ppxai, ppxaide, ppxai-server, ppxai-desktop) + VSIX + DMG
- [x] Tested 10 models across 4 providers — documented in DEBUG-SESSION-2026-02-19.md Session 2

### Session 3 (macOS, 2026-02-20 00:42–01:20)
- [x] **A8:** Codex native tool calling fix — 3 changes to `openai_native.py`:
  1. `get_capabilities_for_model()`: removed `_is_responses_api_model()` from prompt-based check
  2. `_chat_responses_api()`: belt-and-suspenders tool hint injection into `instructions` field
  3. Added `_build_tool_hint()` static method for formatting tool descriptions
- [x] **A5:** Updated `model_profiles.py` — `gpt-5.1-codex*` from `mode="prompt_based"` to `mode="native"`
- [x] **A7:** Updated codex AGENTS.md hints — "native function calling" language
- [x] AGENTS.md changelog updated — "Codex models use native function calling via Responses API with belt-and-suspenders fallback"
- [x] `ppxai-config.json` — `max_iterations` and `max_tool_iterations` doubled from 25 to 50
- [x] Rebuilt and installed all binaries (ppxai, ppxaide, ppxai-server)
- [x] **Live-tested codex models successfully:**
  - gpt-5.1-codex: 25 iterations (hit old max), 71+ tool calls across 4 turns
  - gpt-5.1-codex-mini: 19 iterations, synthesized `**Repository Review Summary**` — perfect behavior

## Key Discoveries

### Session 2

| Finding | Impact | Action |
|---------|--------|--------|
| "Make ONE" hint fix is transformative | gpt-5.2: 1/turn → 8/turn | Already fixed (H1) |
| gemini-2.5-flash is the best agent (19 iterations) | Sets the bar for tool chaining | Raise iteration limit for gemini (B2) |
| gpt-5-nano chains 11 tools but empty synthesis | Nano models need output budget management | A11 (investigate) |
| gpt-4.1-mini ignores hints entirely | Mini models can't follow complex instructions | Accept as model limitation |
| Session pollution definitively proven | codex-mini: works in Session 1, broken in Session 2 | B1 (session reset) is critical |
| o3-mini needs `OpenAINativeProvider` routing | Wrong provider causes `max_tokens` error | A9 |
| Interrupt only works at coarse granularity | Esc closes UI but background task continues | H2/H3 done, B11 for SSE disconnect |

### Session 3

| Finding | Impact | Action |
|---------|--------|--------|
| Codex native tool calling works perfectly | Both codex models fully functional | A8 done — biggest fix in v1.15.6 |
| codex-mini synthesizes at 19 iterations | Smarter than codex (breadth-first scan, then synthesize) | codex-mini is the better codex model |
| codex exhaustive (71+ calls, won't stop) | Reads every file without synthesizing | Need per-model iteration limits (B2) or synthesis hints |
| B10 no longer needed | Codex native tool calling works in v1.15.6 | Removed from v1.16.0 |
| Belt-and-suspenders proven for codex | Tool hints in instructions + native API params | Generalize to other providers (B3) |
| Benchmark scores don't reflect reality | codex was "broken" in benchmarks but works in live testing | Benchmark redesign needed (A12) |

## Quick Start Next Session

1. **A1** (validator read claims) — independent, highest impact remaining P1
2. **A9** (o3-mini routing) — quick fix, prevents user-facing error
3. **A10** (gpt-5-mini hints) — 15 min quick win
4. **A11** (gpt-5-nano synthesis) — investigation, may be quick fix
5. **A12** (benchmark review) — design agent loop tests, partial credit scoring
6. Run tests: `uv run pytest tests/ -v`
7. After all P1/P2 items done, merge branch to master and tag v1.15.6
