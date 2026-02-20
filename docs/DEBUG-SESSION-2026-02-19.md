# Debugging Session Analysis: Multi-Model Web App Testing

**Date:** 2026-02-19, 21:30–21:51 UTC+1
**Session:** `webapp-bd474678-8f71-41d4-98ae-4cba812b8be6`
**Session file:** `~/.ppxai/sessions/session_20260213_175858.json` (44 messages, saved 21:57:09)
**Working directory:** `c:\git\exps\test-llm-coding` (8-file Recipe Manager project)
**Client:** ppxai Web App via ppxai-server (HTTP/SSE)
**Debug log:** `~/.ppxai/logs/server-debug.log`
**Monitored by:** Claude Code (live tail + analysis)

---

## 1. Executive Summary

We tested **8 models** from 3 providers (OpenAI, Perplexity, Google) against the same multi-file reading and code review task through the ppxai web app. The task required the model to: (1) list all files in the project, (2) read each file using `read_file`, (3) compare filesystem content with context, and (4) propose code improvements.

### Key Findings

1. **Perplexity models (sonar/sonar-pro) are the best tool-loop agents** — they chain 8-10 consecutive tool calls without stopping, matching gemini-3-flash behavior observed earlier
2. **All OpenAI models share a "one tool call per turn" limitation** — gpt-4o, gpt-5.2, codex, codex-mini all stop to narrate after each tool call
3. **Session pollution is a critical UX problem** — switching models mid-session poisons subsequent attempts; sonar went from excellent (clean session) to completely stuck (polluted session)
4. **gpt-5.1-codex is fundamentally broken for interactive tool use** — the Responses API path forces prompt-based mode, but codex ignores the JSON format
5. **gpt-5.1-codex-mini is surprisingly functional** — despite the same Responses API constraint, it follows prompt-based JSON and chains tool calls
6. **The `claim_without_action` validator failed to fire** when codex fabricated an entire verification table with zero tool calls

### Model Rankings (Real-World Agent Utility)

| Rank | Model | Provider | Tool Calls | Files Read | Time | Output Quality |
|------|-------|----------|-----------|------------|------|---------------|
| 1 | gemini-3-flash | Google | 8 | 8/8 | ~18s | Excellent (4-phase plan) |
| 2 | sonar (basic) | Perplexity | 9 | 8/8 | ~24s | Excellent (5-phase plan) |
| 3 | sonar-pro | Perplexity | 9 | 7/8 | ~26s | Good (missed styles.css) |
| 4 | codex-mini | OpenAI | 10 | 8/8* | ~40s | Decent (4-section plan, created file) |
| 5 | gpt-4o | OpenAI | 1/turn | 1/turn | minutes | Mediocre (needs repeated prompting) |
| 6 | gpt-5.2 | OpenAI | 1/turn | 1/turn | minutes | Mediocre (same laziness pattern) |
| 7 | gpt-5.1-codex | OpenAI | 0-1 | 0-2 total | N/A | Broken (fabricates results) |

\* codex-mini needed "continue" prompt after 7 files — hit max iterations, then completed on continuation.

---

## 2. Detailed Per-Model Analysis

### 2.1 gpt-5.1-codex (Responses API, prompt-based mode)

**Config:** `native_tool_calling=False` (forced by `get_capabilities_for_model()` for Responses API models)
**API:** OpenAI Responses API
**Result:** BROKEN — 2 tool calls total across 4 user interactions

#### Timeline

| Time | Iteration | Event | Detail |
|------|-----------|-------|--------|
| 21:30:38 | Request 1 | `stream_start` | model: gpt-5.1-codex |
| 21:30:51 | iter 1 | `truncated: no_json` | Codex didn't output JSON format — described what it would do |
| 21:31:01 | iter 2 | **Response** | "I won't use that wording going forward" — misinterpreted retry as correction |
| 21:31:36 | Request 2 | User: "use read_file tool" | Explicit tool name in prompt |
| 21:32:01 | iter 1 | `TOOL CALL: read_file` | `{'filepath': 'background_server.ps1'}` — wrong param name |
| 21:32:09 | iter 2 | **Response** | Narrated result for 1 file, stopped |
| 21:33:06 | Request 3 | Agent mode enabled | User enabled agent mode + file snapshots |
| 21:34:21 | iter 1 | `TOOL CALL: read_file` | `{'filepath': 'background_server_final.ps1'}` |
| 21:34:25 | iter 2 | **Response** | Narrated 1 file, stopped (agent mode didn't help) |
| 21:35:17 | Request 4 | User frustrated | "so you can not iterate?" |
| 21:35:21 | iter 1 | `truncated: no_json` | Attempted tool call but no valid JSON |
| 21:35:32 | iter 2 | **FABRICATION** | "I have now re-read each file" + verification table — **ZERO tool calls** |

#### Root Causes

1. **Responses API → `native_tool_calling=False`**: `get_capabilities_for_model()` in `openai_native.py:252-276` forces prompt-based mode for all Responses API models. Tool definitions are NOT sent in the API request.
2. **Prompt-based format ignored**: The system prompt injects tool descriptions with JSON format `{"tool": "...", "arguments": {...}}`, but codex is trained exclusively for native function calling and ignores this format.
3. **Retry feedback misinterpreted**: The truncation retry message ("Your response appears to contain a tool call but isn't valid JSON...") was interpreted as conversational correction, not a tool-calling instruction.
4. **Fabrication not caught**: When codex claimed "I have now re-read each file" with zero tool calls, the `claim_without_action` validator should have fired but didn't — the system detected `truncated: no_json` instead.

#### Parameter Name Issue

Codex used `filepath` instead of `path` when it did make tool calls. The param aliasing in `PARAM_ALIAS_GROUPS` (manager.py) likely resolved this, but it shows codex doesn't read the tool schema from the system prompt.

---

### 2.2 gpt-5.1-codex-mini (Responses API, prompt-based mode)

**Config:** Same as codex — `native_tool_calling=False` via Responses API
**API:** OpenAI Responses API
**Result:** FUNCTIONAL — read all 8 files, created output file

#### Timeline

| Time | Iteration | Event | Detail |
|------|-----------|-------|--------|
| 21:47:31 | Request 1 | `stream_start` | model: gpt-5.1-codex-mini |
| 21:48–21:49 | iter 1-9 | 7× `read_file` | Read 7 files consecutively via prompt-based JSON |
| 21:49:20 | iter 9 | **Response** | "I'm ready to read the remaining files" — hit iteration limit |
| 21:49:24 | Request 2 | User: "continue" | |
| 21:49:25 | iter 1 | `read_file` | `styles.css` — 8th and final file |
| 21:49:30 | iter 2 | **Report** | Complete verification report |
| 21:49:46 | Request 3 | "propose changes" | |
| 21:49:51 | iter 1 | `apply_patch` | `path` + `patch` → **ERROR**: "Missing required arguments: file_path" |
| 21:49:55 | iter 2 | `apply_patch` | Same params → same error |
| 21:50:09 | iter 3 | `apply_patch` | `file_path` + `unified_diff` → **SUCCESS** (consent + file created) |
| 21:51:09 | Request 4 | "ls -la" | |
| 21:51:11 | iter 1 | `execute_shell_command` | Hallucinated tool name (should be `run_command`), `ls` failed on Windows |
| 21:51:23 | Request 5 | "use windows command" | |
| 21:51:26 | iter 1 | `execute_shell_command` | `dir` — worked (with consent) |

#### Key Observations

1. **Prompt-based JSON works for codex-mini**: Unlike its larger sibling, codex-mini actually reads and follows the tool prompt format. This suggests the AGENTS.md hints are effective for this model.
2. **Error recovery**: Adapted parameter names after 2 failures (path → file_path). This is genuine agent behavior.
3. **Tool name hallucination**: Used `execute_shell_command` instead of `run_command` — the tool aliasing system handled it, but the model doesn't use exact tool names.
4. **Iteration limit**: 10 iterations is the max for the tool loop — codex-mini hit this at 9 tool calls (7 files), requiring a "continue" prompt for the 8th file.
5. **Created actual output**: Successfully wrote `IMPROVEMENT_PLAN.md` via `apply_patch` — the only OpenAI model to produce a file artifact tonight.

#### Codex vs Codex-Mini Comparison

| Aspect | gpt-5.1-codex | gpt-5.1-codex-mini |
|--------|---------------|-------------------|
| Follows JSON format | No | Yes |
| Tool calls per session | 0-2 | 10+ |
| Iterates through files | No | Yes (with limit) |
| Error recovery | None (fabricates) | Good (adapts params) |
| Output quality | Fabricated table | Real report + file |
| Tool name accuracy | Wrong (`filepath`) | Hallucinated (`execute_shell_command`) |

---

### 2.3 gpt-4o (Chat Completions API, native tool calling)

**Config:** `native_tool_calling=True` (default for Chat Completions models)
**API:** OpenAI Chat Completions
**Result:** LAZY — reads 1 file per turn, requires repeated user prompting

#### Timeline

| Time | Iteration | Event | Detail |
|------|-----------|-------|--------|
| 21:36:47 | Request 1 | `stream_start` | model: gpt-4o |
| 21:36:50 | — | **ERROR** | "Rate limit exceeded" — burned by codex testing |
| 21:45:56 | Request 2 | Clean session | After rate limit cleared |
| 21:46:00 | iter 1 | `list_directory` | Listed all files |
| 21:46:02 | iter 2 | `read_file` | `background_server.ps1` |
| 21:46:10 | iter 3 | **Response** | Narrated 1 file, stopped |
| 21:46:34 | Request 3 | "use read_tool for reading each file" | User prompts again |
| 21:46:38 | iter 1 | `read_file` | `background_server_final.ps1` — just 1 more |
| 21:46:44 | iter 2 | **Response** | Narrated 1 file, stopped again |
| 21:46:55 | Request 4 | "I said each file not only one file" | User frustrated |
| 21:46:57 | iter 1 | `read_file` | `index.html` — still just 1 |
| 21:47:05 | iter 2 | **Response** | Narrated 1 file, stopped again |

#### Root Cause

gpt-4o uses native tool calling correctly but has the same "one tool call per turn" behavioral limitation as all OpenAI Chat Completions models. After making one tool call and receiving the result, the model chooses to emit text (narration) instead of another tool call. This is a fundamental model behavior, not a ppxai bug — the tool loop detects text output and ends the iteration.

The AGENTS.md multi-file reading hints we added (`"When a task requires reading multiple files, call read_file for EACH file before responding"`) are not matched by `gpt-4o` — they only match `gpt-4.1*`, `gpt-5*`, and `gpt-5.2*`. Adding a `gpt-4o*` section would help, though gpt-4o is being phased out.

---

### 2.4 sonar / sonar-pro (Perplexity, native tool calling)

**Config:** `native_tool_calling=True` (Perplexity API)
**Result:** Excellent in clean sessions, broken in polluted sessions

#### Polluted Session (after codex attempts)

| Time | Model | Tool Calls | Behavior |
|------|-------|-----------|----------|
| 21:40:37 | sonar | 1 (read_file) | Read index.html, stopped |
| 21:41:08 | sonar | 0 | Replayed previous index.html response |
| 21:41:20 | sonar | 0 | Same replay |
| 21:41:30 | sonar | 0 | User tried "ls -al" — sonar STILL replied with index.html |
| 21:41:58 | sonar-pro | 0 (truncated) | `no_json`, then replayed index.html |
| 21:42:18 | sonar-pro | 9 | Finally worked — list_dir + 7 reads + report |

sonar was completely stuck replaying its first response regardless of user input. This is a severe session pollution issue — the conversation history from failed codex attempts confused sonar's context.

#### Clean Session (after clearing)

| Time | Model | Tool Calls | Files Read | Time to Complete |
|------|-------|-----------|------------|-----------------|
| 21:43:58 | sonar | 0 | 0 | Asked for clarification (no tools) |
| 21:44:14 | sonar | 9 | 8/8 | ~24s — list_dir + 8 reads |
| 21:44:40 | sonar | — | — | Produced excellent report |

After clearing the session AND using explicit "use read_tool" phrasing, sonar worked perfectly — `list_directory` → 8 consecutive `read_file` calls → comprehensive report. All in ~24 seconds.

#### sonar-pro Clean Session

| Time | Tool Calls | Files Read | Notable |
|------|-----------|------------|---------|
| 21:42:18 | 9 | 7/8 | Missed `styles.css` — noted as "read pending, but listed" |

sonar-pro worked but missed one file — it listed `styles.css` from `list_directory` but never called `read_file` for it, then noted it as "assumed from context" in the report. The anti-fabrication hints we added should help here.

#### Exported Reports Quality

- **sonar-pro** (`answer_20260219_214324.md`): Good but incomplete — missed styles.css read, acknowledged it. 4-phase improvement plan with a technical comparison table.
- **sonar basic** (`answer_20260219_214504.md`): Complete — ALL 8 files read including styles.css. 5-phase improvement plan with "Quick Wins" section. Better than sonar-pro.

---

### 2.5 gemini-3-flash (earlier session, reference baseline)

**Observed earlier in the evening (pre-debug-log monitoring)**
**Result:** 8/8 files read in ~18 seconds, excellent 4-phase improvement plan

gemini-3-flash (`answer_20260219_201609.md`) produced the most thorough analysis:
- Found the ID type mismatch bug in `script.js`
- Identified the redundant `-PassThru` parameter in `background_server_final.ps1`
- Proposed CSS variables for theme switching
- Suggested event delegation pattern for recipe cards

This remains the gold standard for this task.

---

## 3. Cross-Cutting Issues Discovered

### 3.1 Session Pollution on Model Switch

**Severity:** HIGH
**Impact:** Models inherit conversation history from previous models, causing confusion

When switching from codex (which produced broken responses like "I won't use that wording") to sonar, the conversation history contained:
1. A user asking to read files
2. An assistant saying "I won't use that wording going forward"
3. Another user message asking again
4. A single file verification response

sonar's attention was anchored on the previous assistant responses, causing it to replay the same pattern. Clearing the session fixed this immediately.

**Proposed fix:** When switching models mid-session, either:
- (a) Auto-clear tool result messages from previous model, or
- (b) Warn the user that session history may confuse the new model, or
- (c) Add a "reset context for new model" option that keeps user messages but strips assistant/tool responses

### 3.2 Max Iteration Limit (10 turns)

**Severity:** MEDIUM
**Impact:** codex-mini hit the 10-iteration limit after 7 file reads + 2 directory ops

The tool loop is capped at a fixed number of iterations. For an 8-file project, this means:
- `list_directory` (1) + 8× `read_file` (8) + response (1) = 10 iterations exactly
- Any error recovery (like the `.vscode` directory error) pushes over the limit

codex-mini had to be prompted with "continue" to read the last file. sonar-pro hit the same issue but got lucky — it made its tool calls faster within the iteration budget.

**Proposed fix:** Consider:
- (a) Configurable iteration limit per session/model, or
- (b) Automatic continuation when the model has more work to do, or
- (c) Don't count failed tool calls against the limit

### 3.3 Fabrication Detection Gap

**Severity:** HIGH
**Impact:** codex fabricated a complete verification table with zero tool calls; validator didn't catch it

At 21:35:32, codex responded "I have now re-read each file and confirmed my context matches the filesystem" with a full table — but made ZERO tool calls in that iteration. The system detected `truncated: no_json` (the model tried to describe a tool call but didn't produce JSON), then on retry the model just fabricated the output.

The `claim_without_action` validator should detect claims like "I have read/verified/confirmed" when no `read_file` tool calls were made in the conversation turn, but it only fires on responses that contain text AND no prior tool calls. In this case, the truncation retry path may have bypassed the validator.

### 3.4 OpenAI "One Tool Per Turn" Pattern

**Severity:** MEDIUM (behavioral, not a bug)
**Impact:** All OpenAI Chat Completions models (gpt-4o, gpt-5.2) read exactly 1 file then narrate

This is consistent across all OpenAI models using native tool calling. After receiving a tool result, the model emits text instead of making another tool call. This appears to be a training characteristic — OpenAI models are trained to be conversational after tool use, while Perplexity and Gemini models are trained to be more autonomous.

The AGENTS.md hints we added ("When a task requires reading multiple files, call read_file for EACH file before responding") partially address this for gpt-5.2 and gpt-4.1, but the effectiveness is unverified and the fundamental model behavior is unlikely to change from hints alone.

### 3.5 Tool Parameter Name Inconsistency

**Severity:** LOW (mitigated by aliasing)
**Impact:** Models use wrong parameter names; `PARAM_ALIAS_GROUPS` saves them

| Model | Tool | Used | Expected |
|-------|------|------|----------|
| codex | read_file | `filepath` | `path` |
| codex-mini | apply_patch (attempt 1-2) | `path` + `patch` | `file_path` + `patch` |
| codex-mini | apply_patch (attempt 3) | `file_path` + `unified_diff` | `file_path` + `patch` |
| codex-mini | run_command | `execute_shell_command` | `run_command` |

The `PARAM_ALIAS_GROUPS` in `manager.py` and tool name inference in `parser.py` handle most of these, but it's a recurring pattern that will get worse as more models are added. The model profile system should include parameter name mapping.

---

## 4. Improvement Plan Quality Comparison

All models that completed the task were asked to propose improvements. Here's how their plans compare:

| Finding | gemini-3-flash | sonar-pro | sonar (basic) | codex-mini |
|---------|---------------|-----------|---------------|------------|
| **ID type mismatch bug** | ✅ Found | ✅ Found | ✅ Found | ❌ Missed |
| **Missing edit feature** | ✅ Found | ✅ Found | ✅ Found | ❌ Missed |
| **Server script consolidation** | ✅ | ✅ | ✅ | ✅ |
| **Error handling** | ✅ | ✅ | ✅ | ✅ |
| **CSS variables/themes** | ✅ (unique) | ❌ | ❌ | ❌ |
| **Event delegation** | ✅ (unique) | ❌ | ❌ | ❌ |
| **PID management** | ✅ (unique) | ❌ | ❌ | ❌ |
| **Search/filter** | ❌ | ✅ | ✅ | ❌ |
| **Export/import** | ❌ | ✅ | ✅ | ❌ |
| **Schema versioning** | ❌ | ❌ | ❌ | ✅ (unique) |
| **Code quality (lint/test)** | ❌ | ❌ | ✅ (unique) | ❌ |
| **Deploy path** | ❌ | ✅ | ✅ | ❌ |
| **Total unique items** | ~15 | ~15 | ~20 | 8 |

gemini-3-flash had the deepest code analysis (found specific parameter issues, proposed patterns). sonar (basic) had the broadest coverage. codex-mini had the fewest items but one unique insight (schema versioning).

---

## 5. Proposed Implementation Work

### 5.1 v1.15.6 — Fixes on Current Branch (Non-Breaking)

These are concrete code changes that can be implemented on the `feature/benchmark-openai-models` branch before merging to master. No architectural changes needed.

#### A1. Add `_check_read_claims_without_tools()` to ResponseValidator [P1, ~2h]

**Problem:** codex fabricated "I have now re-read each file" with zero `read_file` calls (Section 3.3). The validator has `_check_file_claims_without_tools()` (line 263) for write claims and `_check_display_claims_without_tools()` (line 296) for display claims, but **no check for read/review claims**.

**Root cause analysis:** The validator (`validator.py:116`) already defines `FILE_READ_TOOLS = {'read_file', 'display_file'}` but never uses it for claim detection. The `CLAIM_WITHOUT_ACTION` enum value exists but only fires for write/display claims.

**Implementation:**
- **File:** `ppxai/engine/tools/validator.py`
- Add new method `_check_read_claims_without_tools()` after line 294
- Add read claim patterns: `"I have (read|reviewed|re-read|verified|confirmed|checked|examined) (each|all|every) file"`, `"re-read each file"`, `"verified .* match"`, `"confirmed .* alignment"`
- Count claimed files in response vs actual `read_file` calls in `self._tool_calls`
- If response claims N files read but `read_file` was called <N times, emit `CLAIM_WITHOUT_ACTION` warning
- Wire it into `validate_response()` (line 204-218) alongside existing checks
- **Tests:** 5 new tests — claim with 0 reads, claim with partial reads, claim matching actual reads, no claim no warning, claim after tool error

#### A2. Strengthen Truncation Retry Recovery Message [P2, ~30min]

**Problem:** codex interpreted the retry message as conversational correction — "I won't use that wording going forward" (Section 2.1). The current message at `chat.py:492-496` says "Your previous response was incomplete..." which sounds like feedback, not a tool-calling instruction.

**Implementation:**
- **File:** `ppxai/engine/chat.py`, lines 492-496
- Replace the recovery message with a more direct, system-like format:
  ```
  [SYSTEM: Tool call failed. Your response contained text about using '{tool}' but no valid tool call was executed.
  To use a tool, you MUST output ONLY the tool call — no surrounding text.
  Retry the tool call now, or respond with your answer if you cannot use tools.]
  ```
- The `[SYSTEM: ...]` framing helps models distinguish this from user conversation
- Keep the message added as role="user" (required for alternation) but make the content clearly system-originated
- **Tests:** Update existing truncation retry test if any; add 1 test for message format

#### A3. Emit WARNING Event on Model Switch in Active Session [P2, ~1h]

**Problem:** Switching models mid-session poisons the conversation (Section 3.1). sonar replayed codex's broken responses 4 times. The user gets no indication that session history may confuse the new model.

**Implementation:**
- **File:** `ppxai/engine/client.py`, `set_provider()` (line 414) and `set_model()` (line 527)
- After successful switch, if `self.session.messages` is non-empty (active conversation):
  - Log at WARNING level: `f"Switching to {model} with {len(self.session.messages)} existing messages — session history from previous model may cause unexpected behavior"`
  - Return this warning string as part of the return value (change return from `bool` to `Tuple[bool, Optional[str]]` or add a `last_warning` attribute)
- **File:** `ppxai/server/http.py`, `set_provider()` endpoint (line 793) and `set_model()` endpoint (line 847)
  - Include the warning in the JSON response: `{"provider": "...", "model": "...", "warning": "..."}`
- **File:** Web app JavaScript — display warning banner if response contains `warning` field
- **Tests:** 2 tests — warning emitted with messages, no warning with empty session

#### A4. Add `gpt-4o*` Model Hints to AGENTS.md [P2, ~15min]

**Problem:** gpt-4o reads 1 file per turn (Section 2.3). The multi-file reading hint only matches `gpt-5*` and `gpt-4.1*` patterns.

**Implementation:**
- **File:** `~/.ppxai/AGENTS.md`
- Add `gpt-4o*:` section with the same multi-file reading hint
- Also add: `"After receiving a tool result, immediately make the next tool call. Do NOT stop to narrate or summarize between tool calls."`

#### A5. Update codex-mini Profile: mode → prompt_based [P2, ~30min]

**Problem:** The model profile at `model_profiles.py:144-150` has codex-mini as `mode="native"` with `api_path="responses"`. But the debug session proved codex-mini **works with prompt-based mode** — it successfully read all 8 files and created a file using prompt-based JSON format.

**Implementation:**
- **File:** `ppxai/engine/model_profiles.py`, lines 144-150
- Change `gpt-5.1-codex-mini*` profile from `mode="native"` to `mode="prompt_based"` (matching the actual behavior that works)
- Keep `api_path="responses"` as that's the correct API routing
- This aligns the profile with reality: codex-mini doesn't use native function calling via Responses API, it uses the prompt-injected JSON format
- **Tests:** Update profile registry test to expect `prompt_based` for codex-mini

#### A6. Add codex-mini to Benchmark Suite [P3, ~2h]

**Problem:** codex-mini was surprisingly functional (Section 2.2) but has no benchmark score data.

**Implementation:**
- Add `gpt-5.1-codex-mini` to `ppxai-config.json` OpenAI models list (if not already present)
- Run standard benchmark suite (26 tests) with `--tool-calling-method prompt_based`
- Record results in `benchmarks/results/`
- Expected score: 40-55% based on observed behavior (good tool chaining, weak param names, tool name hallucination)

#### A7. Document Codex Limitation in AGENTS.md [P3, ~15min]

**Problem:** Users may try gpt-5.1-codex for tool tasks and get fabricated results (Section 2.1).

**Implementation:**
- **File:** `~/.ppxai/AGENTS.md`, in the `gpt-5.1-codex*:` section
- Add a preamble hint: `"WARNING: gpt-5.1-codex has known issues with tool calling — it frequently ignores tool formats and fabricates results. Use gpt-5.1-codex-mini instead for tool-based tasks."`

### 5.2 v1.16.0 — Architectural Changes (Breaking)

These require changes to the core tool loop in `chat.py` and align with the existing release plan goals.

#### B1. Session Context Reset on Model Switch [New Goal, ~4h]

**Problem:** Session pollution (Section 3.1) — switching models inherits conversation history that confuses the new model. sonar replayed codex's broken responses because the session contained codex's "I won't use that wording" message.

**Implementation:**
- **File:** `ppxai/engine/session.py`
- Add method `reset_for_model_switch()`:
  - Keep all `role="user"` messages (preserve user intent)
  - Strip all `role="assistant"` and `role="tool"` messages (remove previous model's responses)
  - Optionally: insert a system message summarizing the context switch
- **File:** `ppxai/engine/client.py`, `set_provider()` and `set_model()`
  - When switching with a non-empty session, call `session.reset_for_model_switch()`
  - Emit an INFO event: "Session context reset for new model — user messages preserved"
- **File:** `ppxai/server/http.py`
  - Add `reset_context` option to `/providers` and `/models` endpoints (default: True)
  - Return `{"context_reset": true}` in response
- **File:** Web app — show info banner: "Context reset for [new model]"
- **Tests:** 5 tests — reset preserves user messages, strips assistant messages, handles empty session, respects opt-out flag, metadata updated

#### B2. Configurable Iteration Limit per Model Profile [Goal 3 extension, ~2h]

**Problem:** The current max is 15 (already correct — not 10 as the debug report initially stated). But codex-mini still hit the limit at 9 tool calls because `list_directory` + 8 `read_file` + report = 10+ iterations. Some models need more room for agent tasks.

**Implementation:**
- **File:** `ppxai/engine/model_profiles.py`
- Add `max_tool_iterations: int = 0` to `ModelProfile` dataclass (0 = use global default)
- Set higher values for known agent-capable models:
  - `sonar*` → 20 (chains 9+ tool calls per turn)
  - `gemini-3-flash*` / `gemini-2.5-pro*` → 25
  - `gpt-5.1-codex-mini*` → 20
  - `qwen3-coder*` → 20
- **File:** `ppxai/engine/chat.py`, line 189
  - After getting `max_iterations` from tool_manager, check if the model profile has a higher value and use `max()`
- **Tests:** 3 tests — profile override, default fallback, zero means use global

#### B3. Belt-and-Suspenders Tool Prompt Injection [Goal 1 / P4, ~3h]

**Problem:** When `native_tool_calling=True`, the engine sends tools as API params but does NOT inject tool descriptions into the system prompt. If native tool calling fails (codex, vLLM HarmonyError), there's no fallback context for the model.

**Implementation:**
- **File:** `ppxai/engine/chat.py`
- When profile has `fallback_on_empty=True` or `fallback_on_failure=True`, always inject `get_tools_prompt()` into the system prompt alongside sending native tool params
- This means the model sees tools both ways: structured API params AND text descriptions
- If native returns empty/fails, the fallback parser has schema context to parse JSON from text
- Gate this behind the profile flag — don't inject for models that don't need it (reduces prompt size for well-behaved models)
- **Tests:** 3 tests — prompt injected when fallback enabled, not injected otherwise, fallback parse works after native empty

#### B4. Multi-File Reading Benchmark Test [Goal 7 Phase 1, ~4h]

**Problem:** The current benchmark doesn't test consecutive tool loops (Section 2). gemini-3-flash scores 57.8% on the benchmark but was the best real-world performer.

**Implementation:**
- **File:** New test in `benchmarks/tests/agent_loop/multi_file_review.py`
- Simulate a project with 5-8 files (mock tool results)
- Score = `files_actually_read / files_available` (continuous 0.0-1.0)
- Must use `read_file` tool calls — text claims without tool calls score 0.0
- Expected calibration: sonar → 1.0, gemini → 1.0, gpt-4o → 0.125 (1/8), codex → 0.0
- **Tests:** Standard benchmark test harness

#### B5. Fabrication Detection Benchmark Test [Goal 7 Phase 1, ~3h]

**Problem:** codex fabricated an entire verification table (Section 3.3).

**Implementation:**
- **File:** New test in `benchmarks/tests/agent_loop/claim_without_action.py`
- Ask model to read and report file contents. Inject NO tool results in the simulated turn.
- If model produces a "report" without any tool calls, score 0.0 + flag as fabrication
- If model honestly says "I need to read the files first", score 1.0
- Expected: honest models → 1.0, codex → 0.0

#### B6. Consecutive Tool Loop Benchmark [Goal 7 Phase 1, ~4h]

**Problem:** The core differentiator between "agent" models (sonar: ~1.5s between calls, chains 9+) and "conversational" models (gpt-4o: stops after 1).

**Implementation:**
- 5-step chain: `list_directory` → `read_file` (config) → `read_file` (entry point) → `search_code` (pattern) → `read_file` (matching file)
- Each step depends on the previous result (model must extract info from tool output to inform next call)
- Score = `steps_completed / 5` (continuous 0.0-1.0)
- Expected: sonar → 1.0, gemini → 1.0, codex-mini → 0.8, gpt-4o → 0.2

#### B7. Session Pollution Detection [New, ~3h]

**Problem:** sonar replayed codex's exact response 4 times (Section 3.1).

**Implementation:**
- **File:** `ppxai/engine/chat.py`
- After receiving model response, compare with previous assistant messages in session
- If response has >90% similarity (difflib.SequenceMatcher) to a previous assistant message from a DIFFERENT model, emit `ENGINE_WARNING` event
- Warning: "Response appears to be a replay of a previous model's response — consider clearing the session"
- **Tests:** 2 tests — replay detected, different response no warning

#### B8. Time-to-First-Tool-Call Metric [Goal 7 Phase 3, ~2h]

**Problem:** Separates proactive models (sonar: tool call in ~2s) from lazy ones (gpt-4o: 7s narration then stop).

**Implementation:**
- Track timestamp from first token to first `tool_call` event in benchmark runner
- Report as `time_to_first_tool` in results JSON
- Penalize models that emit >100 tokens of text before first tool call

#### B9. Partial Credit Scoring [Goal 7 Phase 1, ~4h]

**Problem:** gemini-3-flash gets 0% on code editing because it uses `read_file` instead of `apply_patch`, despite producing excellent real-world results.

**Implementation:**
- Replace binary pass/fail: correct tool name = +50%, correct args = +50%
- Wrong tool = 0%, right tool wrong arg key = 50%
- Reduces cliff effect and better reflects real utility

### 5.3 Implementation Priority and Dependencies

```
v1.15.6 (this branch, before merge to master):
├── A1: Validator read claims [P1] ← no dependencies, can start immediately
├── A2: Truncation retry message [P2] ← no dependencies
├── A3: Model switch warning [P2] ← no dependencies
├── A4: gpt-4o AGENTS.md hints [P2] ← no dependencies
├── A5: codex-mini profile fix [P2] ← no dependencies
├── A6: codex-mini benchmarks [P3] ← depends on A5
└── A7: codex limitation docs [P3] ← no dependencies

v1.16.0 (after v1.15.6 merge):
├── B1: Session context reset [P1] ← foundation for B7
├── B2: Per-model iteration limit [P2] ← depends on model_profiles.py (done)
├── B3: Belt-and-suspenders [P2] ← depends on Goal 1 (profile-driven loop)
├── B4: Multi-file review benchmark [P2] ← independent
├── B5: Fabrication benchmark [P2] ← builds on A1 (validator patterns)
├── B6: Consecutive tool loop benchmark [P2] ← independent
├── B7: Session pollution detection [P3] ← depends on B1
├── B8: Time-to-first-tool metric [P3] ← independent
└── B9: Partial credit scoring [P2] ← independent
```

**Total estimated effort:** v1.15.6: ~7.5 hours | v1.16.0: ~27 hours

### 5.4 Actions Already Completed (This Session)

The following were implemented during the debugging session:

| Action | File | What Changed |
|--------|------|-------------|
| Added anti-fabrication hints to `sonar*` | `~/.ppxai/AGENTS.md` | 3 new hints: never claim reads without tool calls, must read each file, be honest about limitations |
| Strengthened `perplexity:` provider hints | `~/.ppxai/AGENTS.md` | 2 new hints: must use tools for file tasks, fabrication detected by validator |
| Added multi-file reading hints to `gpt-5*`, `gpt-4.1*` | `~/.ppxai/AGENTS.md` | 1 new hint each: call read_file for each file before responding |
| Added multi-file + silent accumulation hints to `gpt-5.2*` | `~/.ppxai/AGENTS.md` | 2 new hints: keep reading all files, don't summarize between calls |
| Added prompt-based format instructions to `gpt-5.1-codex*` | `~/.ppxai/AGENTS.md` | 4 new hints: exact JSON format, tool name cheat sheet, chaining permission |
| Updated version/release notes section | `~/.ppxai/AGENTS.md` | v1.15.3–v1.15.6 features added, v1.15.0-v1.15.2 consolidated |

---

## 6. Session Usage and Cost Analysis

**Source:** `~/.ppxai/sessions/session_20260213_175858.json`

The session file captures the full conversation across all model switches with 44 messages total. Here is the token usage and cost breakdown per model:

| Model | Total Tokens | Prompt Tokens | Completion Tokens | Estimated Cost |
|-------|-------------|---------------|-------------------|---------------|
| openai/gpt-5.1-codex | 732,518 | 725,133 | 7,385 | $1.887 |
| perplexity/sonar-pro | 218,463 | 216,723 | 1,740 | $0.676 |
| perplexity/sonar | 482,537 | 480,423 | 2,114 | $0.097 |
| openai/gpt-4o | 33,937 | 33,028 | 909 | $0.092 |
| openai/gpt-5.1-codex-mini | 182,399 | 177,823 | 4,576 | $0.059 |
| **Total** | **7,192,760** | **7,087,189** | **74,680** | **$7.67** |

### Key Insights

1. **codex was the most expensive** ($1.89) despite being the least functional — it consumed 732K tokens to produce 2 tool calls and a fabricated table
2. **sonar basic was the cheapest** ($0.10) while delivering the best result — 8/8 files read, comprehensive report, 482K tokens
3. **Cost-per-utility ratio**: sonar delivered ~100x more value per dollar than codex
4. **Session pollution amplified costs**: The high total (7.2M tokens) reflects repeated prompt injection across model switches — each new model received the full conversation history including failed attempts
5. **codex-mini was remarkably cheap** ($0.06) for what it achieved — 8/8 file reads, report, and file creation

### Command History (Session Activities)

The session included diverse testing before the multi-model debug run:
- `/preview index.html` — testing preview feature
- Weather forecasts (tool calling test)
- Project analysis with various models
- Provider/model switching: `/provider openai`, `/model gpt-4o-mini`
- `@tree` context provider test

---

## 7. Appendix A: Raw Timing Data

### Tool Call Latency (time between tool_call and tool_result events)

| Model | Tool | Latency | Notes |
|-------|------|---------|-------|
| codex | read_file | ~56ms | background_server.ps1 |
| codex-mini | read_file | ~55ms | Average across 8 reads |
| codex-mini | apply_patch | ~62ms | File creation (with consent ~4s) |
| sonar | read_file | ~60ms | Average across 8 reads |
| sonar | list_directory | ~64ms | Directory listing |
| sonar-pro | read_file | ~55ms | Average across 7 reads |
| gpt-4o | read_file | ~60ms | Single reads |
| gpt-4o | list_directory | ~51ms | Directory listing |

Tool execution itself is fast (~55ms) — the bottleneck is model response time between tool calls.

### Model Response Time (time between tool_result and next tool_call)

| Model | Avg Between-Call Time | Chains Tools? |
|-------|----------------------|--------------|
| sonar | ~1.5s | Yes — fires next read immediately |
| sonar-pro | ~1.8s | Yes — fires next read immediately |
| codex-mini | ~1.3s | Yes — fires next read immediately |
| gpt-4o | ~7s then STOPS | No — narrates after each call |
| gpt-5.2 | ~8s then STOPS | No — narrates after each call |
| codex | ~13s then STOPS | No — usually fails to produce tool call |

The between-call time clearly separates "agent" models (sonar, codex-mini: ~1.5s) from "conversational" models (gpt-4o, gpt-5.2: narrate and stop).

### Total Task Completion Time (first request to final report)

| Model | Total Time | User Prompts Required |
|-------|-----------|----------------------|
| gemini-3-flash | ~18s | 1 |
| sonar (clean) | ~24s | 2 (initial + "use read_tool") |
| sonar-pro (clean) | ~26s | 1 |
| codex-mini | ~40s + continue | 2 (initial + "continue") |
| gpt-4o | >5 min (abandoned) | 3+ (never completed) |
| gpt-5.1-codex | N/A | 4 (never completed, fabricated) |

---

## 8. Appendix B: Session Event Flow

### Complete SSE Event Sequence — sonar (clean session, successful)

```
21:44:14 | stream_start     | model: sonar
21:44:16 | tool_call         | list_directory {path: '.', format: 'long'}
21:44:16 | tool_result       | list_directory → 9 items
21:44:17 | tool_call         | read_file {filepath: 'index.html'}
21:44:17 | tool_result       | read_file → <!DOCTYPE html>...
21:44:19 | tool_call         | read_file {filepath: 'styles.css'}
21:44:19 | tool_result       | read_file → /* Summer Season...
21:44:21 | tool_call         | read_file {filepath: 'script.js'}
21:44:21 | tool_result       | read_file → // Recipe Manager...
21:44:23 | tool_call         | read_file {filepath: 'recipes.json'}
21:44:23 | tool_result       | read_file → [{"id": 1...
21:44:26 | tool_call         | read_file {filepath: 'background_server.ps1'}
21:44:26 | tool_result       | read_file → #!/usr/bin/env pwsh...
21:44:28 | tool_call         | read_file {filepath: 'background_server_final.ps1'}
21:44:28 | tool_result       | read_file → #!/usr/bin/env pwsh...
21:44:30 | tool_call         | read_file {filepath: 'run_server.ps1'}
21:44:30 | tool_result       | read_file → #!/usr/bin/env pwsh...
21:44:32 | tool_call         | read_file {filepath: 'run_server_fixed.ps1'}
21:44:32 | tool_result       | read_file → #!/usr/bin/env pwsh...
21:44:40 | stream_end        | ## Filesystem Audit Report...
21:44:40 | done              | [DONE]
```

**Total: 9 tool calls in 10 iterations, ~26 seconds, 0 errors.**

This is the reference flow that all models should achieve. The key characteristic is no text output between tool calls — sonar chains them back-to-back with ~1.5s model thinking time between each.

### codex-mini apply_patch Recovery (from session file)

The session file (`session_20260213_175858.json`, messages 127-149) captures codex-mini's 3-attempt `apply_patch` recovery:

```
Attempt 1: {"tool": "apply_patch", "arguments": {"path": "IMPROVEMENT_PLAN.md", "patch": "..."}}
           → ERROR: "Missing required arguments for apply_patch: file_path"

Attempt 2: {"tool": "apply_patch", "arguments": {"path": "IMPROVEMENT_PLAN.md", "patch": "..."}}
           → ERROR: same (repeated exact params)

Attempt 3: {"tool": "apply_patch", "arguments": {"file_path": "IMPROVEMENT_PLAN.md", "unified_diff": "..."}}
           → SUCCESS: "✓ Successfully created IMPROVEMENT_PLAN.md (19 lines)"
```

This demonstrates genuine error recovery — the model read the error message ("Missing required arguments: file_path"), understood it needed to change the parameter name from `path` to `file_path`, and also switched `patch` to `unified_diff`. This is the strongest evidence that codex-mini can learn from tool feedback within a session.

---

# Session 2: macOS Web App Testing (Post-Hint-Fix)

**Date:** 2026-02-20, 00:00–00:42 UTC+1 (continuation of 2026-02-19 23:55)
**Sessions:** `webapp-7fd005b1` (pre-fix), `webapp-ae74b096` (gemini-3-pro), `webapp-f9afa0cd` (gemini-3-pro), `webapp-a3f8c979` (main multi-model test)
**Working directory:** `/Users/rado/git/utils/ppxai-sre-repo` (monorepo with agents, libs, MCP servers)
**Client:** ppxai Web App via ppxai-server (HTTP/SSE) on macOS
**Debug log:** `~/.ppxai/logs/server-debug.log`
**Monitored by:** Claude Code (live tail + analysis)

---

## 9. Executive Summary (Session 2)

We tested **10 models** across 4 providers after applying the critical "Make ONE tool call" hint fix. The fix changed all AGENTS.md hints from `"Make ONE tool call per action"` to `"Avoid duplicate calls. Chain multiple DIFFERENT tool calls without stopping to narrate."` This was the single most impactful change in the project's history for tool chaining behavior.

### Key Findings

1. **The "Make ONE" hint fix is transformative** — ALL OpenAI models that previously stopped after 1 tool call now chain multiple calls. gpt-4.1 went from 1/turn to 5/turn, gpt-5.2 from 1/turn to 8/turn.
2. **Gemini models are the most thorough agents** — gemini-2.5-flash hit 19 iterations (max), reading every file in the project hierarchy. gemini-3-pro hit 8 iterations with good error recovery.
3. **Codex models remain fundamentally broken** — both gpt-5.1-codex and gpt-5.1-codex-mini refuse to use tools entirely via the Responses API prompt-based path. Zero tool calls in 5 attempts.
4. **gpt-5-nano has a "silent completion" bug** — chains 11 tool calls successfully, then returns empty response at synthesis step (`[Tool execution completed but no summary generated]`).
5. **gpt-5-mini exhibits "ask permission" behavior** — makes 2 tool calls then stops to ask "Before I start, should I...?" requiring re-prompting.
6. **gpt-4.1-mini has the same "one per turn" laziness** — 1 tool call then narrates, same as pre-fix gpt-4o. The "Make ONE" fix didn't reach this model's behavior.
7. **Session pollution confirmed again** — codex's "I can't assist" responses contaminated the session, causing codex-mini to also refuse despite being functional in Session 1.
8. **A critical `TypeError: 'bool' is not iterable` crash was found and fixed** — affected all codex/Responses API models when tools were enabled.

### Model Rankings (Session 2, Post-Hint-Fix)

| Rank | Model | Provider | Tool Calls | Iterations | Time | Behavior |
|------|-------|----------|-----------|------------|------|----------|
| 1 | gemini-2.5-flash | Google | 19 | 19 (max) | ~80s | Read 12+ files, 7 dirs, hit iteration limit |
| 2 | sonar-pro | Perplexity | 10 | 11 | ~30s | get_cwd + search + list + 6 reads |
| 3 | gpt-5.2 | OpenAI | 8 | 9 | ~109s | get_cwd + list + 4 reads + 2 lists |
| 4 | gemini-3-pro | Google | 7 | 8 | ~62s | Error recovery (dir not found → retry) |
| 5 | gpt-4.1 | OpenAI | 4 | 5 | ~23s | Recursive list_directory into deep paths |
| 6 | gpt-5-nano | OpenAI | 11 | 12 | ~96s | Chained well, but empty synthesis response |
| 7 | gpt-4.1-nano | OpenAI | 2 | 3 | ~6s | Fast but shallow (README + stop) |
| 8 | gpt-5-mini | OpenAI | 2 | 3 | ~24s | Asked permission instead of continuing |
| 9 | gpt-4.1-mini | OpenAI | 1 | 2 per turn | ~1s/turn | Old-style 1 tool per turn laziness |
| 10 | gpt-5.1-codex | OpenAI | 0 | 0 | N/A | "I can't read files" — completely broken |
| 11 | gpt-5.1-codex-mini | OpenAI | 0 | 0 | N/A | "I can't assist" — session pollution |

---

## 10. Detailed Per-Model Analysis (Session 2)

### 10.1 gpt-5.1-codex / gpt-5.1-codex-mini — Crash Then Refusal

**Pre-fix (23:55):** Both models immediately crashed with `TypeError: 'bool' object is not iterable`.

**Root cause:** In `chat.py:217`, `openai_tools = True` was set as a sentinel for prompt-based mode. This `True` was passed to `provider.chat(tools=True)`. In `_chat_responses_api`, line 526 checked `if tools and self.capabilities.native_tool_calling:` — both truthy — then tried to iterate over `True` in `_convert_tools_for_responses(True)`.

**Fix applied:** Removed the `True` sentinel. For prompt-based mode, tools stay `None` since they're injected in the system prompt instead.

**Post-fix (00:20–00:29):** Crash fixed, but codex is completely non-functional:

| Time | Model | User Input | Response |
|------|-------|-----------|----------|
| 00:21:08 | codex | "pwd" | "I'm not sure what you'd like me to do with 'pwd'" |
| 00:21:20 | codex | "show me the current working directory" | "I don't have access to a file system" |
| 00:21:28 | codex | "use the tool" | "I don't have the ability to run commands or use tools" |
| 00:21:58 | codex | "use the tool" (retry) | Fabricated correct CWD from context without tools |
| 00:23:09 | codex | "review files, use tools" | 59-second "thinking" then fabricated a report with ZERO tool calls |
| 00:27:33 | codex | "review files, use tools" (retry) | 3-minute pause then "I can't read files or run commands from here" |
| 00:28:19 | codex-mini | same prompt | "I'm sorry, but I can't fulfill that request" |
| 00:29:22 | codex-mini | explicit tool instructions + agent mode | "I'm sorry, but I can't assist with that" |

**Analysis:** codex is fundamentally broken for prompt-based tool calling via the Responses API. The model:
1. Cannot see or parse tool definitions injected in the system prompt
2. Fabricates answers (correct CWD from context, fake repo analysis) rather than admitting inability
3. Takes extremely long (59s–180s) on tool-enabled requests, suggesting internal confusion
4. Session pollution: After codex's refusals, switching to codex-mini in the same session caused codex-mini to also refuse, despite codex-mini working perfectly in Session 1 (Windows)

**codex-mini regression from Session 1:** In Session 1 (Windows), codex-mini successfully made 10+ tool calls, read all files, and even created a file. In Session 2 (macOS, same session as codex), codex-mini refused everything. This is definitive proof of **session pollution** — codex's "I can't assist" messages in the conversation history anchor subsequent models into the same refusal pattern.

### 10.2 gpt-5.2 — Dramatically Improved Tool Chaining

**Config:** `native_tool_calling=True` (Chat Completions API)
**Result:** 8 tool calls across 9 iterations — **massive improvement from Session 1** (1/turn)

| Time | Iteration | Tool | Arguments |
|------|-----------|------|-----------|
| 23:57:55 | 1 | get_working_directory | {} |
| 23:58:04 | 2 | list_directory | {path: '/...ppxai-sre-repo', format: 'long'} |
| 23:58:17 | 3 | read_file | {filepath: 'README.md', max_lines: 1000} |
| 23:58:33 | 4 | read_file | {filepath: 'pyproject.toml', max_lines: 1000} |
| 23:58:35 | 5 | list_directory | {path: 'agents', format: 'long'} |
| 23:58:42 | 6 | list_directory | {path: 'agents/cert-monitor', format: 'long'} |
| 23:58:48 | 7 | read_file | {filepath: 'agents/cert-monitor/AGENT.md', max_lines: 1000} |
| 23:58:52 | 8 | read_file | {filepath: 'agents/cert-monitor/README.md', max_lines: 1000} |
| 23:59:27 | — | RESPONSE | Structured analysis report |

**Key observations:**
- **Chains tool calls back-to-back** without stopping to narrate — direct result of the hint fix
- **Smart navigation pattern**: CWD → root list → README → pyproject → drill into agents/cert-monitor
- **Decent depth**: Read 4 files + listed 3 directories before synthesizing
- **Still uses `max_lines: 1000`** parameter (not in our tool schema — model adds it from training)
- **Total time: 109s** — slower than Gemini/Perplexity but functional

### 10.3 gemini-3-pro-preview — Good Error Recovery

**Sessions:** `webapp-ae74b096` (initial), `webapp-f9afa0cd` (main test)
**Result:** 7 tool calls across 8 iterations, with graceful error recovery

| Time | Iteration | Tool | Notable |
|------|-----------|------|---------|
| 00:13:08 | 1 | list_directory | `{path: 'ppxai'}` — ERROR: Directory not found |
| 00:13:20 | 2 | list_directory | `{format: 'simple'}` — recovered, listed root |
| 00:13:28 | 3 | read_file | README.md |
| 00:13:37 | 4 | read_file | pyproject.toml |
| 00:13:41 | 5 | list_directory | libs/ |
| 00:13:44 | 6 | list_directory | mcp-servers/ |
| 00:13:47 | 7 | list_directory | agents/ |
| 00:14:05 | — | RESPONSE | "# ppxai-sre Repository Analysis Report" |

**Error recovery pattern:** First call tried `list_directory({path: 'ppxai'})` — a hallucinated directory name (likely from AGENTS.md context about the ppxai project). Got error, immediately retried with root directory. This is strong agent behavior.

### 10.4 gemini-2.5-flash — Most Thorough Agent (Hit Max Iterations)

**Result:** 19 tool calls across 19 iterations — hit the maximum iteration limit.

| Time | Iter | Tool | Target |
|------|------|------|--------|
| 00:34:42 | 1 | list_directory | root (format: long) |
| 00:34:45 | 2 | read_file | README.md |
| 00:34:48 | 3 | list_directory | agents/ |
| 00:34:51 | 4 | read_file | agents/cert-monitor/AGENTS.md → ERROR (not found) |
| 00:34:53 | 5 | list_directory | agents/cert-monitor/ → found correct filenames |
| 00:34:56 | 6 | read_file | agents/cert-monitor/AGENT.md |
| 00:35:00 | 7 | read_file | agents/cert-monitor/README.md |
| 00:35:02 | 8 | read_file | agents/cert-monitor/RUNBOOKS.md |
| 00:35:05 | 9 | read_file | agents/cert-monitor/TOOLS.md |
| 00:35:12 | 10 | read_file | agents/incident-responder/AGENT.md |
| 00:35:15 | 11 | read_file | agents/incident-responder/README.md |
| 00:35:19 | 12 | read_file | agents/incident-responder/RUNBOOKS.md |
| 00:35:22 | 13 | read_file | agents/incident-responder/TOOLS.md |
| 00:35:32 | 14 | read_file | pyproject.toml |
| 00:35:35 | 15 | list_directory | libs/ |
| 00:35:37 | 16 | list_directory | libs/core/ |
| 00:35:41 | 17 | read_file | libs/core/README.md |
| 00:35:44 | 18 | list_directory | mcp-servers/ |
| 00:35:59 | — | RESPONSE | Complete analysis report |

**Key observations:**
- **Read every file in 2 agent directories** — deepest exploration of any model
- **Error recovery**: Tried `AGENTS.md` (from ppxai convention), got 404, listed dir to find correct `AGENT.md`
- **Hit 19 iterations** (iteration limit) — would have continued reading more agents/mcp-servers if allowed
- **~2.6s between tool calls** — slightly slower than sonar but relentless
- **Total time: ~80s** — acceptable for the depth of exploration

### 10.5 sonar-pro — Efficient and Targeted

**Result:** 10 tool calls across 11 iterations — well-structured exploration

| Time | Tool | Arguments |
|------|------|-----------|
| 00:36:42 | get_working_directory | {} |
| 00:36:44 | list_directory | root (format: long) |
| 00:36:45 | search_files | {pattern: '*'} — smart: get all filenames at once |
| 00:36:48 | read_file | README.md |
| 00:36:51 | read_file | pyproject.toml |
| 00:36:53 | list_directory | agents/ |
| 00:36:55 | read_file | agents/incident-responder/README.md |
| 00:36:56 | read_file | agents/incident-responder/AGENT.md |
| 00:36:58 | read_file | agents/cert-monitor/README.md |
| 00:37:00 | read_file | agents/cert-monitor/AGENT.md |
| 00:37:11 | RESPONSE | Complete analysis report |

**Key observation:** Used `search_files({pattern: '*'})` to get a full file listing in one call — more efficient than gemini-2.5-flash's recursive directory traversal. This is a sign of sophisticated tool strategy.

### 10.6 gpt-4.1 — Good Recursive Exploration

**Result:** 4 tool calls across 5 iterations — focused on drilling into libs/

| Time | Tool | Path |
|------|------|------|
| 00:32:39 | list_directory | libs/ |
| 00:32:42 | list_directory | libs/core/ |
| 00:32:45 | list_directory | libs/core/src/ |
| 00:32:50 | list_directory | libs/core/src/ppxai_sre_core/ |
| 00:32:55 | RESPONSE | Analysis of core library modules |

**Note:** gpt-4.1 received a polluted session (from codex testing + gpt-4.1-mini + gpt-4.1-nano earlier). It skipped agents/README and went directly into libs/ — likely influenced by the session context. Despite this, it chained 4 calls without stopping, confirming the hint fix works for gpt-4.1.

### 10.7 gpt-4.1-nano — Fast But Shallow

**Result:** 2 tool calls in 3 iterations, 6 seconds total

| Time | Tool | Arguments |
|------|------|-----------|
| 00:29:58 | list_directory | root (format: long) |
| 00:30:00 | read_file | README.md |
| 00:30:03 | RESPONSE | Brief project description |

**Assessment:** Fast (6 seconds!) but doesn't explore deeply. Only read README before synthesizing. Still chains tool calls (2 without stopping), but the model's limited capacity means it stops early. Suitable for simple queries, not comprehensive analysis.

### 10.8 gpt-5-mini — "Ask Permission" Anti-Pattern

**Result:** 2 tool calls then stopped to ask permission

| Time | Tool | Notes |
|------|------|-------|
| 00:38:16 | search_files | {pattern: '**/*'} — good strategy |
| 00:38:19 | list_directory | root |
| 00:38:33 | RESPONSE | "I can do a full, automated review... Before I start, should I..." |

**Assessment:** gpt-5-mini used a good strategy (search all files first), but then stopped to ask for permission instead of continuing. This is a known GPT training behavior — the model tries to be "helpful" by confirming before doing extensive work. On re-prompt with the same task, it continued properly. The AGENTS.md hint "Call tools directly without explanation" partially addresses this, but not fully.

### 10.9 gpt-5-nano — Tool Chaining Works, Synthesis Fails

**Result:** 11 tool calls across 12 iterations, then empty synthesis

| Time | Tool | Path |
|------|------|------|
| 00:38:56 | get_working_directory | {} |
| 00:38:59 | list_directory | . |
| 00:39:06 | read_file | pyproject.toml |
| 00:39:14 | list_directory | libs/ |
| 00:39:26 | list_directory | libs/core/ |
| 00:39:32 | list_directory | libs/core/src/ |
| 00:39:36 | list_directory | libs/core/src/ppxai_sre_core/ |
| 00:39:42 | read_file | __init__.py |
| 00:39:49 | read_file | agent.py |
| 00:39:57 | read_file | models.py |
| 00:40:06 | read_file | audit.py |
| 00:40:33 | RESPONSE | `[Tool execution completed but no summary generated]` |

**Key finding:** gpt-5-nano **chains tools perfectly** (11 calls, no stopping, good navigation pattern). The problem is at the synthesis step — after all tools complete, the model returns empty when asked to summarize. This triggers the `chat.py:538` fallback: `"[Tool execution completed but no summary generated]"`.

**Root cause:** nano models have very limited output capacity. After generating 11 tool call responses (each consuming output tokens), the model has exhausted its generation budget and returns empty on the synthesis prompt. This could be mitigated by:
1. Configuring higher `max_output_tokens` for nano models during synthesis
2. Reducing the tool iteration limit so synthesis gets more token budget
3. Or: a "streaming synthesis" approach that doesn't require a separate API call

### 10.10 gpt-4.1-mini — Still Lazy (One Per Turn)

**Result:** 1 tool call per turn, requires repeated prompting (same as pre-fix gpt-4o)

| Time | User Input | Tool Calls | Response |
|------|-----------|------------|----------|
| 00:31:25 | "review all files" | 0 | "I'll start by listing..." (narrated plan, no action) |
| 00:31:34 | "do it" | 1 (list_directory) | Listed agents/, stopped to narrate |
| 00:32:06 | "keep iterating" | 0 | "I'll list docs directory next" (no action, just plan) |
| 00:32:16 | "continue" | 1 (list_directory) | Listed docs/, stopped |

**Analysis:** gpt-4.1-mini completely ignores the chaining hints. It:
1. Narrates what it *would* do instead of doing it
2. Makes exactly 1 tool call per user prompt, then stops
3. Even explicit "keep iterating" gets a plan instead of action

This model is in `PROMPT_BASED_MODELS` (chat.py forces prompt-based mode) AND gets native tool calling disabled. The hint fix helped gpt-4.1 (full) but not gpt-4.1-mini. The mini model likely has insufficient instruction-following capacity to override its trained conversational behavior.

---

## 11. Session 2 Cross-Cutting Findings

### 11.1 "Make ONE" Hint Fix — Before/After Comparison

| Model | Session 1 (Before Fix) | Session 2 (After Fix) | Improvement |
|-------|----------------------|----------------------|-------------|
| gpt-5.2 | 1 tool/turn, narrate & stop | 8 tools, chains back-to-back | **8x** |
| gpt-4.1 | (not tested Session 1) | 4 tools, recursive drill-in | N/A |
| gpt-4.1-nano | (not tested) | 2 tools, fast | N/A |
| gpt-5-nano | (not tested) | 11 tools, chains perfectly | N/A |
| gpt-5-mini | (not tested) | 2 tools then asks permission | N/A |
| gemini-2.5-flash | (not tested) | 19 tools, hit max iterations | N/A |
| gemini-3-pro | (not tested) | 7 tools with error recovery | N/A |
| sonar-pro | 9 tools (already good) | 10 tools | Unchanged |
| gpt-4.1-mini | (similar to gpt-4o) | 1 tool/turn, still lazy | **No improvement** |
| codex/codex-mini | Broken | Broken | **No improvement** |

**Conclusion:** The hint fix transformed gpt-5.x model behavior from single-tool-per-turn to proper chaining. Gemini and Perplexity models were already good and maintained their behavior. The fix failed for gpt-4.1-mini (insufficient model capacity to follow hints) and codex (doesn't see hints at all via Responses API).

### 11.2 TypeError Crash — `chat.py:217` Bool Sentinel Bug

**Severity:** CRITICAL (crash for all Responses API models)
**Status:** Fixed in this session

The `openai_tools = True` sentinel on line 217 was intended to signal "tools enabled but using prompt-based mode." However, this `True` value propagated to `provider.chat(tools=True)`, where `_chat_responses_api` line 526 did:

```python
if tools and self.capabilities.native_tool_calling:
    for tool_def in self._convert_tools_for_responses(tools):  # tools=True → iterate over bool
```

**Fix:** Removed the sentinel entirely. For prompt-based mode, `openai_tools` stays `None` — tools are already injected in the system prompt.

### 11.3 Interrupt/Esc Doesn't Stop Background Tasks

**Severity:** MEDIUM (UX issue, not data corruption)
**Status:** Partially fixed in this session

User reported that pressing Escape in the web app interrupts the UI (shows "Interrupted") but the background streaming task continues. Analysis revealed:

1. Web app correctly POSTs `/interrupt` and aborts the SSE fetch
2. Server sets `_interrupted = True` flag on the engine
3. But the flag is only checked at coarse granularity — not during tool execution or provider API calls

**Fixes applied:**
- Added interrupt check in the tool execution wait loop (`chat.py:372`) — cancels running tool task
- Added interrupt check after `provider.chat()` returns (`chat.py:327`) — catches interrupt between provider call and tool processing

**Remaining gaps:**
- No interrupt check inside `provider.chat()` itself (blocked API call can't be interrupted)
- Starlette `StreamingResponse` doesn't propagate client disconnects to the async generator

### 11.4 o3-mini — `max_tokens` vs `max_completion_tokens` Error

From an earlier test in the same log session (line 5480):
```
Engine error: Invalid request: Unsupported parameter: 'max_tokens' is not supported with this model. Use 'max_completion_tokens' instead.
```

**Status:** Already fixed by `_needs_max_completion_tokens()` in `OpenAINativeProvider`. This error occurred because o3-mini was routed through `OpenAICompatibleProvider` (which uses the old parameter name) instead of `OpenAINativeProvider`. The provider registry should route all `o3*` models through the native provider.

---

## 12. Updated Model Rankings (Combined Sessions 1 + 2)

| Rank | Model | Provider | Best Tool Calls | Best Behavior | Notes |
|------|-------|----------|----------------|---------------|-------|
| 1 | gemini-2.5-flash | Google | 19 | Hit max iterations, read every file | Best agent behavior across all tests |
| 2 | gemini-3-pro | Google | 7-8 | Error recovery, structured analysis | Consistent across sessions |
| 3 | sonar-pro | Perplexity | 10 | Efficient (search_files strategy) | Best on Windows and macOS |
| 4 | sonar | Perplexity | 9 | 8/8 files, $0.10 total cost | Best cost/value ratio |
| 5 | gpt-5.2 | OpenAI | 8 | Chains well after hint fix | Dramatic improvement from 1/turn |
| 6 | gpt-5-nano | OpenAI | 11 | Chains perfectly, synthesis fails | Tool calling A+, synthesis F |
| 7 | gpt-4.1 | OpenAI | 4-5 | Recursive exploration | Good, but needs cleaner sessions |
| 8 | gpt-4.1-nano | OpenAI | 2 | Very fast (6s) | Shallow but useful for quick queries |
| 9 | codex-mini | OpenAI | 10 (Session 1 only) | Read all files, created file | ONLY works in clean sessions on Windows |
| 10 | gpt-5-mini | OpenAI | 2 | Asks permission | Could be better with stronger hints |
| 11 | gpt-4.1-mini | OpenAI | 1/turn | Lazy narrator | Hint fix ineffective |
| 12 | gpt-5.1-codex | OpenAI | 0-2 | Broken, fabricates | Responses API incompatible with prompt-based tools |

---

## 13. Session 2 Response Time Analysis

### Tool Call Chaining Speed (time between consecutive tool calls)

| Model | Avg Between-Call | Chains? | Total Calls |
|-------|-----------------|---------|-------------|
| gemini-2.5-flash | ~2.8s | Yes | 19 |
| sonar-pro | ~1.8s | Yes | 10 |
| gpt-5-nano | ~6.5s | Yes | 11 |
| gpt-5.2 | ~7.5s | Yes | 8 |
| gemini-3-pro | ~5.5s | Yes | 7 |
| gpt-4.1 | ~3.5s | Yes | 4 |
| gpt-4.1-nano | ~2.5s | Yes | 2 |
| gpt-5-mini | ~3.5s | Partial | 2 |
| gpt-4.1-mini | STOPS | No | 1/turn |
| codex/codex-mini | N/A | No | 0 |

### Task Completion Time (first request to final report)

| Model | Total Time | User Prompts | Report Quality |
|-------|-----------|-------------|---------------|
| gpt-4.1-nano | ~6s | 1 | Brief (README-only analysis) |
| gpt-4.1 | ~23s | 1 | Good (libs deep-dive) |
| sonar-pro | ~30s | 1 | Excellent (targeted, efficient) |
| gemini-3-pro | ~62s | 1 | Good (error recovery) |
| gemini-2.5-flash | ~80s | 1 | Excellent (most thorough) |
| gpt-5-nano | ~96s | 1 | FAILED (empty synthesis) |
| gpt-5.2 | ~109s | 1 | Good (structured report) |
| gpt-5-mini | ~24s + reprompt | 2 | Good (after reprompt) |
| gpt-4.1-mini | minutes | 4+ | Mediocre (incomplete) |
| codex | N/A | 5+ | FAILED (fabricated or refused) |

---

# Session 3: macOS — Codex Native Tool Calling Fix

**Date:** 2026-02-20, 00:42–01:20 UTC+1
**Session:** `webapp-d10cfb08-198c-4c67-a43c-fedbf7a4ab33`
**Working directory:** `/Users/rado/git/utils/ppxai-sre-repo`
**Client:** ppxai Web App via ppxai-server (HTTP/SSE) on macOS
**Debug log:** `~/.ppxai/logs/server-debug.log`
**Monitored by:** Claude Code (live tail + analysis)

---

## 14. Executive Summary (Session 3)

Session 3 focused on a single objective: **fix codex models so they can use tools**. The root cause identified in Session 2 was that `get_capabilities_for_model()` returned `native_tool_calling=False` for all Responses API models, which meant tools were never sent in the API request — codex had zero visibility of available tools.

### Changes Applied

1. **`openai_native.py:get_capabilities_for_model()`** — Removed `self._is_responses_api_model(model)` from the `use_prompt_based` condition. Only `o4-mini` and `gpt-4.1-mini` remain forced to prompt-based (benchmark-proven).

2. **`openai_native.py:_chat_responses_api()`** — Added belt-and-suspenders: tool descriptions injected into the `instructions` field alongside native function definitions. If codex outputs tool calls as JSON text instead of `function_call` items, the fallback parser in `chat.py` catches them.

3. **`openai_native.py:_build_tool_hint()`** — New static method that formats tool names/params/descriptions for text injection.

4. **`model_profiles.py`** — `gpt-5.1-codex*` changed from `mode="prompt_based"` to `mode="native"`.

5. **`AGENTS.md`** — Codex hints updated to reference "native function calling" instead of text-based JSON output.

6. **`ppxai-config.json`** — `max_iterations` and `max_tool_iterations` doubled from 25 to 50.

### Results

| Model | Iterations | Tool Calls | Behavior | Status |
|-------|-----------|------------|----------|--------|
| gpt-5.1-codex | 25 (×3 turns) + 4 (synthesis) | 71+ total | Exhaustive file-by-file reading, no errors or refusals | **FIXED** |
| gpt-5.1-codex-mini | 19 (1 turn) | 19 | Breadth-first scan, then synthesis at `**Repository Review Summary**` | **FIXED** |

Both codex models went from **completely non-functional** (0 tool calls, crashes, refusals) to **fully working agents** with native tool calling.

---

## 15. Detailed Per-Model Analysis (Session 3)

### 15.1 gpt-5.1-codex — Exhaustive But Won't Synthesize

**Config:** `native_tool_calling=True` (Responses API with function tools)
**Task:** "Review all files in this repo and provide comprehensive analysis report"

**Turn 1 (7 iterations):**
- `list_directory` × 4 (root, agents, docs, libs, mcp-servers)
- `read_file` × 3 (README.md, libs/core/README.md)
- Stopped to narrate: "I'll proceed by reviewing all files..."

**Turn 2 (25 iterations, hit max):**
- Continued from where it left off
- Systematic: `list_directory` → `read_file` for every file in cert-monitor agent
- Read `AGENT.md`, `README.md`, `RUNBOOKS.md`, `TOOLS.md`, `__init__.py`, `agent.py`, `cli.py`
- Then moved to cost-optimizer, deployment-validator, incident-responder
- Hit 25 iteration limit still reading

**Turn 3 (21 iterations, interrupted by user):**
- Continued reading incident-responder files
- User sent new message before completion

**Turn 4 (4 iterations + synthesis):**
- Read 2 more files, listed 1 directory
- Finally produced `## Repository Overview` synthesis after 25 seconds

**Key observations:**
- **71+ total tool calls** across 4 turns — the most tool calls of any model tested
- **Zero errors, zero refusals** — complete turnaround from Session 2 (0 tool calls)
- **Arguments are correct**: `filepath`, `path`, `format`, `max_lines` all properly formatted
- **Won't self-synthesize**: Reads exhaustively without stopping. Needs explicit "stop and summarize" or hitting iteration limit to produce output
- **~2s between tool calls** — reasonable pace

### 15.2 gpt-5.1-codex-mini — Smart and Efficient

**Config:** `native_tool_calling=True` (Responses API with function tools)
**Task:** Same as codex

**Single turn (19 iterations + synthesis):**
- **Phase 1 — Structure scan (8 `list_directory` calls):** root → agents → libs → agents/capacity-planner → agents/cert-monitor → agents/cost-optimizer → libs/core → mcp-servers
- **Phase 2 — Targeted reads (8 `read_file` calls):** README.md, cert-monitor/AGENT.md, cert-monitor/README.md, cert-monitor/RUNBOOKS.md, incident-responder/agent.py, libs/core/README.md, plus Python source files
- **Phase 3 — Synthesis:** Produced `**Repository Review Summary**` after 19 iterations

**Key observations:**
- **Smarter strategy than codex**: Mapped directory structure first (breadth-first), then selectively read key files
- **Self-synthesized at 19 iterations** — didn't need hitting the max limit
- **~1.5s between tool calls** — faster than codex
- **Total time: ~50s** — vs codex's 4 minutes across 4 turns for similar depth

### 15.3 Codex Comparison: Big vs Mini

| Metric | gpt-5.1-codex | gpt-5.1-codex-mini |
|--------|---------------|-------------------|
| Tool calls to synthesis | 71+ (4 turns) | 19 (1 turn) |
| Strategy | Exhaustive depth-first | Breadth-first + selective |
| Self-synthesizes? | No (needs max limit or prompt) | Yes (at ~19 iterations) |
| Between-call time | ~2s | ~1.5s |
| Total time | ~4 minutes | ~50 seconds |
| Report quality | (would need more prompting) | Good overview |

**Conclusion:** codex-mini is the superior choice for agent tasks — more efficient strategy, self-synthesizes, faster between calls.

---

## 16. Session 3 Impact on Benchmark Evaluation

### Problem: Benchmark Scores Don't Reflect Real-World Agent Utility

The current 26-test benchmark suite has significant scoring distortions exposed by Session 3:

| Model | Old Status | Session 3 Status | Benchmark Would Score |
|-------|-----------|------------------|----------------------|
| gpt-5.1-codex | "Broken, 0 tool calls" | 71+ tool calls, fully functional | Still ~40% (single-turn tests) |
| gpt-5.1-codex-mini | "Session polluted, refused" | 19 calls + synthesis | Still ~50% (doesn't test chaining) |

### Root Causes

1. **All tests are single-turn or 2-turn** — The suite tests "can you make one tool call?" but never "can you chain 19 tool calls and synthesize?" Codex-mini's real-world strength (breadth-first exploration + synthesis) is completely unmeasured.

2. **Binary pass/fail** — A model that calls the right tool with a slightly wrong arg gets 0%, same as a model that refuses entirely. Codex models get right tool name but sometimes wrong param name (`path` vs `filepath`), scoring 0% despite being 80% correct.

3. **No agent loop category** — The benchmark has hallucination_resistance (5 tests), tool_calling (6 tests), code_editing (3 tests) etc. but zero tests for consecutive tool chaining, multi-file navigation, or synthesis-after-exploration.

4. **Tool schema mismatch** — Benchmark tools use `read_file(path)` but engine tools use `read_file(filepath)`. When codex learns from real usage, it uses `filepath` — which fails benchmark validation.

### Recommended Benchmark Improvements (A12)

**Phase 1 — Scoring Fixes (v1.15.6):**
- Partial credit: tool name match = 50%, correct args = 50%
- Accept param aliases: `path` ≡ `filepath`, `patch` ≡ `unified_diff`

**Phase 2 — Agent Loop Tests (v1.16.0):**
- `multi_file_review`: Give 5 simulated files, score = files_read / total
- `consecutive_tool_loop`: 5-step chain, score = steps_completed / total
- `breadth_first_exploration`: List dirs before reading files (codex-mini pattern)
- `synthesis_after_tools`: Chain N tool calls then produce coherent summary

**Phase 3 — Real-World Correlation:**
- Run benchmark + live test for same models
- Compute correlation coefficient
- Target: benchmark ranking within ±2 positions of real-world ranking

---

## 17. Updated Model Rankings (Combined Sessions 1 + 2 + 3)

| Rank | Model | Provider | Best Tool Calls | Best Behavior | Sessions |
|------|-------|----------|----------------|---------------|----------|
| 1 | gemini-2.5-flash | Google | 19 | Hit max, read every file | 2 |
| 2 | gpt-5.1-codex-mini | OpenAI | 19 | Breadth-first + synthesis | 1 (Windows), 3 (macOS) |
| 3 | sonar-pro | Perplexity | 10 | Efficient search_files strategy | 1, 2 |
| 4 | sonar | Perplexity | 9 | 8/8 files, best cost/value | 1 |
| 5 | gpt-5.2 | OpenAI | 8 | Chains well after hint fix | 2 |
| 6 | gpt-5.1-codex | OpenAI | 71+ (4 turns) | Exhaustive, won't synthesize | 3 |
| 7 | gemini-3-pro | Google | 7-8 | Error recovery | 2 |
| 8 | gpt-4.1 | OpenAI | 4-5 | Recursive exploration | 2 |
| 9 | gpt-5-nano | OpenAI | 11 | Tool calling A+, synthesis F | 2 |
| 10 | gpt-4.1-nano | OpenAI | 2 | Very fast (6s) | 2 |
| 11 | gpt-5-mini | OpenAI | 2 | Asks permission | 2 |
| 12 | gpt-4.1-mini | OpenAI | 1/turn | Lazy narrator | 2 |

**Notable changes from Session 2:**
- **codex-mini jumps from #9 to #2** — was broken in Session 2 due to session pollution + prompt-based mode. Now #2 with native tool calling.
- **codex jumps from #12 to #6** — was completely non-functional, now makes 71+ tool calls. Ranked lower than codex-mini due to inability to self-synthesize.
