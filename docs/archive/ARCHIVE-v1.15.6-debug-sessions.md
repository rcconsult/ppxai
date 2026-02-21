# Archive: v1.15.6 Debug Session Fixes

**Branch:** `feature/benchmark-openai-models`
**Sessions:** 5 (2026-02-19 → 2026-02-20)
**Status:** All items done. 1349 tests passing.
**Context:** [DEBUG-SESSION-2026-02-19.md](DEBUG-SESSION-2026-02-19.md) | [RELEASE-PLAN-v1.15.6-v1.16.0.md](RELEASE-PLAN-v1.15.6-v1.16.0.md)

---

## All Items (A0-A14, C1-C9)

### Critical / P0

- [x] **A0** Fix `TypeError: 'bool' is not iterable` crash for Responses API models — removed `openai_tools = True` sentinel in `chat.py:217`
- [x] **H1** Fix "Make ONE tool call" anti-pattern in AGENTS.md — replaced all 24 occurrences with "Avoid duplicate calls. Chain multiple DIFFERENT tool calls without stopping to narrate"
- [x] **H2** Add interrupt check during tool execution — `chat.py:372` now checks `is_interrupted` and cancels running tool task
- [x] **H3** Add interrupt check after provider.chat() returns — `chat.py:327` catches interrupt before tool processing
- [x] **A8** Enable codex native tool calling via Responses API — removed `_is_responses_api_model()` from prompt-based override, added belt-and-suspenders tool hint injection, added `_build_tool_hint()` method
- [x] **C1** Fix profile count in docs — 43→37 (after openrouter removal). Updated CHANGELOG, RELEASE-NOTES (4 places), AGENTS.md.
- [x] **C2** Fix `PROMPT_BASED_MODELS` exact match bug — renamed to `PROMPT_BASED_MODEL_PREFIXES`, changed `in` to `.startswith()`. Added 3 tests.

### P1

- [x] **A1** Add `_check_read_claims_without_tools()` to `validator.py` — 6 regex patterns + wired into `validate_response()` + 5 tests
- [x] **C3** Fix `gemini-3-pro*` tier S→A in `model_profiles.py`, updated test
- [x] **C4** Fix wrong test filename in release notes — `test_openai_native_provider.py` → `test_openai_native.py` (2 places)
- [x] **C5** Remove OpenRouter profile references from CHANGELOG/release notes
- [x] **C6** Sync `~/.ppxai/AGENTS.md` — copied repo version

### P2

- [x] **A2** Change truncation retry message to `[SYSTEM: ...]` framing in `chat.py:504-509`
- [x] **A4** Add `gpt-4o*:` model hints to AGENTS.md
- [x] **A5** Update codex profiles in `model_profiles.py` — both `gpt-5.1-codex*` and `gpt-5.1-codex-mini*` now `mode="native"`
- [x] **A9** Fix o3-mini routing — removed `openrouter` as built-in provider
- [x] **A10** Add `gpt-5-mini*` hints — "Do NOT ask permission before using tools"
- [x] **A11** Fix gpt-5-nano synthesis failure — max_tokens 2048→8192, removed stripped params, added profile with `fallback_on_empty=True`
- [x] **A13** codex-mini tuning — profile (fallback_on_empty, strip_json, restricted_params, tier B), hints (anti-hesitation), config (max_tokens 16384)
- [x] **A14** Fix ppxaide `/debug-log on` — added `Logger.enable_all()` / `Logger.disable_all()` to `toggle_debug_logging()`
- [x] **C7** Fix test count in release notes — 1,342→1,346 (2 places)
- [x] **C8** Add `restricted_params` to `gpt-5.1-codex*` profile
- [x] **C9** Fix o4-mini score in release notes — "73.4%" → "up to 80.8%"

### P3

- [x] **A6** Run codex models in live testing — gpt-5.1-codex: 25+ iterations, gpt-5.1-codex-mini: 19 iterations + synthesis
- [x] **A7** Updated codex AGENTS.md hints — changed from "prompt-based" to "native function calling" language

### Deferred to v1.16.0

- **A3** Model switch warning — B1 (session reset) is the proper fix
- **A12** Benchmark design review — design only, current suite uses binary scoring

---

## Session Log

### Session 1 (Windows, 2026-02-19 21:30–22:00)
- Anti-fabrication hints for `sonar*` in AGENTS.md
- Strengthened `perplexity:` provider hints
- Multi-file reading hints for `gpt-5*`, `gpt-4.1*`, `gpt-5.2*`
- Prompt-based format instructions for `gpt-5.1-codex*`
- AGENTS.md version section updated to v1.15.6

### Session 2 (macOS, 2026-02-20 00:00–00:42)
- A0, H1, H2, H3, A4 implemented
- Rebuilt and installed all binaries + VSIX + DMG
- Tested 10 models across 4 providers

### Session 3 (macOS, 2026-02-20 00:42–01:20)
- A8, A5, A7 implemented
- `max_iterations` and `max_tool_iterations` doubled from 25 to 50
- Rebuilt and installed all binaries
- Live-tested codex models successfully

### Session 4 (Windows, 2026-02-20)
- A9, A10 implemented

### Session 5 (Windows, 2026-02-20)
- A1, A2, A11, A13, A14 implemented
- C1-C9 pre-release cleanup completed
- Rebuilt and installed all binaries + VSIX
- 1349 tests passing

---

## Key Discoveries

### Session 2

| Finding | Impact | Action |
|---------|--------|--------|
| "Make ONE" hint fix is transformative | gpt-5.2: 1/turn → 8/turn | H1 ✅ |
| gemini-2.5-flash is the best agent (19 iterations) | Sets the bar for tool chaining | B2 (v1.16.0) |
| gpt-5-nano chains 11 tools but empty synthesis | Nano models need output budget management | A11 ✅ |
| gpt-4.1-mini ignores hints entirely | Mini models can't follow complex instructions | Model limitation |
| Session pollution definitively proven | codex-mini: works in Session 1, broken in Session 2 | B1 (v1.16.0) |
| o3-mini needs `OpenAINativeProvider` routing | Wrong provider causes `max_tokens` error | A9 ✅ |
| Interrupt only works at coarse granularity | Esc closes UI but background task continues | H2/H3 ✅, B11 (v1.16.0) |

### Session 3

| Finding | Impact | Action |
|---------|--------|--------|
| Codex native tool calling works perfectly | Both codex models fully functional | A8 ✅ |
| codex-mini synthesizes at 19 iterations | Smarter than codex (breadth-first scan, then synthesize) | codex-mini is the better codex model |
| codex exhaustive (71+ calls, won't stop) | Reads every file without synthesizing | B2 (v1.16.0) |
| Belt-and-suspenders proven for codex | Tool hints in instructions + native API params | B3 (v1.16.0) |
| Benchmark scores don't reflect reality | codex was "broken" in benchmarks but works in live testing | A12 (v1.16.0) |

### Session 5

| Finding | Impact | Action |
|---------|--------|--------|
| codex-mini hesitates 3 times before first tool call | Permission-seeking wastes turns | A13 ✅ |
| ppxaide `/debug-log on` never wrote to log files | All log files 0 bytes since Feb 13 | A14 ✅ |
| Profile count 43 is stale (post openrouter removal) | Docs wrong | C1 ✅ |
| PROMPT_BASED_MODELS exact match misses dated IDs | o4-mini-2025-04-16 bypasses routing | C2 ✅ |
| gemini-3-pro tier S but scores 73% | Tier too generous | C3 ✅ |

---

## Model Behavior Summary (from Debug Sessions 1-5)

| Model | Tool Chaining | Files Read | Cost | Verdict |
|-------|--------------|------------|------|---------|
| gemini-3-flash | 8 consecutive | 8/8 in 18s | N/A | Gold standard |
| sonar (clean) | 9 consecutive | 8/8 in 24s | $0.10 | Best cost/utility |
| sonar-pro | 9 consecutive | 7/8 in 26s | $0.68 | Missed styles.css |
| codex-mini | 19 iterations + synthesis | 8/8 in 50s | $0.06 | Tier B — tuned: anti-hesitation, fallback_on_empty, max_tokens 16384 |
| gpt-5.1-codex | 71+ calls (25 iterations) | exhaustive | $1.89 | Works but won't stop, needs B2 iteration limit |
| gpt-4o | 1 per turn | 1/turn | $0.09 | Lazy, never completes |
