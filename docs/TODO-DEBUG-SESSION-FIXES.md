# TODO: Debug Session Fixes (2026-02-19)

**Branch:** `feature/benchmark-openai-models`
**Context:** [DEBUG-SESSION-2026-02-19.md](DEBUG-SESSION-2026-02-19.md) | [IMPLEMENTATION-QUICK-REF.md](IMPLEMENTATION-QUICK-REF.md)

---

## v1.15.6 — Do Before Merge

- [ ] **A1** [P1] Add `_check_read_claims_without_tools()` to `validator.py` — catch "I read each file" with 0 `read_file` calls + 5 tests
- [ ] **A2** [P2] Change truncation retry message to `[SYSTEM: ...]` framing in `chat.py:492-496` — codex misinterpreted retry as conversation
- [ ] **A3** [P2] Emit warning on model switch when session has messages — `client.py:set_provider()/set_model()` + server JSON response + web app banner
- [ ] **A4** [P2] Add `gpt-4o*:` model hints to AGENTS.md — multi-file reading + no-narration between tool calls
- [ ] **A5** [P2] Fix codex-mini profile in `model_profiles.py:144` — change `mode="native"` to `mode="prompt_based"`
- [ ] **A6** [P3] Run benchmark suite for gpt-5.1-codex-mini (depends on A5)
- [ ] **A7** [P3] Add WARNING hint to `gpt-5.1-codex*:` in AGENTS.md — "fabricates results, use codex-mini instead"

## v1.16.0 — After Merge

- [ ] **B1** [P1] `session.reset_for_model_switch()` — strip assistant/tool messages, keep user messages (foundation for B7)
- [ ] **B2** [P2] Add `max_tool_iterations` to `ModelProfile` — sonar→20, gemini→25, codex-mini→20
- [ ] **B3** [P2] Belt-and-suspenders — inject tool prompt into system message for profiles with fallback flags
- [ ] **B4** [P2] `multi_file_review` benchmark test — score = files_read / files_available
- [ ] **B5** [P2] `claim_without_action` benchmark test — fabricated report = 0.0, honest refusal = 1.0
- [ ] **B6** [P2] `consecutive_tool_loop` benchmark test — 5-step dependent chain
- [ ] **B7** [P3] Session pollution detection — >90% similarity to previous model's response → WARNING
- [ ] **B8** [P3] `time_to_first_tool_call` metric in benchmark runner
- [ ] **B9** [P2] Partial credit scoring — tool name 50% + args 50%

## Already Done (This Session)

- [x] Anti-fabrication hints for `sonar*` in AGENTS.md
- [x] Strengthened `perplexity:` provider hints
- [x] Multi-file reading hints for `gpt-5*`, `gpt-4.1*`, `gpt-5.2*`
- [x] Prompt-based format instructions for `gpt-5.1-codex*`
- [x] AGENTS.md version section updated to v1.15.6

## Quick Start Next Session

1. Start with **A1** (validator) and **A5** (codex-mini profile) — both are independent, highest impact
2. **A2** and **A4** are 15-30 min quick wins
3. **A3** touches 3 files (client.py, http.py, web app) — do after the quick wins
4. Run tests: `.uv/uv run pytest tests/ -v`
5. After all A items done, merge branch to master and tag v1.15.6
