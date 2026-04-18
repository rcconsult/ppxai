# Release Notes — v1.17.5

## Summary

**Correctness + polish batch.** v1.17.5 closes 8 items from the post-v1.17.4 retrospective: two correctness edges in session management, a context-only chat guard that blocked Perplexity 400s, an exhaustiveness contract for the ppxaide event dispatcher, a regression guard for the Gemini null-parts crash, a UX win for `/attach` errors, a micro-perf cache on session save, streaming for the CSV counter, and an event that surfaces model narrative between tool iterations.

No new user-visible features. All fixes preserve existing behavior unless the old behavior was a bug. **+30 tests net (1973 → 2003), zero regressions.**

## Fixes

### Session correctness

- **R9 — `validate_and_fix_alternation` silently dropped `tool_calls`.** When two consecutive assistant messages appeared, the "longer text wins" tiebreak could discard a message carrying native `tool_calls[]` (which typically has empty `content`) in favour of a shorter plain-text sibling. Sessions would load cleanly but the pending tool invocations were gone. The tiebreak now prefers messages with non-empty `tool_calls` regardless of text length; when both or neither carry tool_calls, the longer message still wins. Also upgrades the trailing-user-drop log line to `DROPPED UNSENT USER PROMPT` with a 120-char preview so `/save` immediately after pressing Enter stops being silent data loss. [`ppxai/engine/session.py`](https://github.com/rcconsult/ppxai/blob/v1.17.5/ppxai/engine/session.py)

- **R10 — `_has_multimodal_attachments()` cached to fix per-save O(N) scan.** Every `save()`/`save_dirty()` call was walking all messages to decide flat vs. directory session format. Cached on `SessionManager._multimodal_cache` — `add_message` flips to `True` eagerly when a multimodal part arrives; `remove_last_message` invalidates only if the popped message carried multimodal content; `clear` sets directly to `False`; `load` / `reset_for_model_switch` / `validate_and_fix_alternation` invalidate when they reassign messages. **500-message session × 20 saves: 0 rescans after warm-up** (was 20). [`ppxai/engine/session.py`](https://github.com/rcconsult/ppxai/blob/v1.17.5/ppxai/engine/session.py)

### Client / server defense

- **R15 — VSCode context-only chat requests returned 400 from Perplexity.** When the webview sent a chat with empty user content, `chatPanel.ts` still prepended the workspace `[Context: Working in VSCode workspace "..." at ...]` block and dispatched it; the provider saw only that synthetic context and rejected with a strict-alternation 400. Two-layer defense: (1) `chatPanel.ts::handleChat` now rejects empty user content with an inline error bubble before any context injection; (2) server-side `POST /chat` detects empty-or-context-only bodies via `_is_empty_or_context_only()` and returns an SSE error event without acquiring the chat lock or reaching the provider. [`ppxai/server/routes/chat.py`](https://github.com/rcconsult/ppxai/blob/v1.17.5/ppxai/server/routes/chat.py), [`vscode-extension/src/chatPanel.ts`](https://github.com/rcconsult/ppxai/blob/v1.17.5/vscode-extension/src/chatPanel.ts)

### ppxaide (Textual TUI)

- **R16 — ppxaide silently dropped engine events.** The stream-event dispatcher covered 15 of 21 `EventType` members; the remaining six (including `CONTEXT_INJECTED`) fell through to a debug no-op. Refactored into two explicit sets — `EVENT_MAP` (routed to UI bus signals) and `NOOP_EVENTS` (intentionally ignored, with inline rationale per entry: `STATE_SYNC` via AppState observers, `AGENT_*` Rich-only, `STATUS` via INFO). Unknown types now log an actionable WARNING naming the file to edit. A drift test fails if a new `EventType` is added without updating either set — deliberate friction so ppxaide doesn't silently miss new engine signals again. [`ppxai/tui/stream_handler.py`](https://github.com/rcconsult/ppxai/blob/v1.17.5/ppxai/tui/stream_handler.py)

### Provider robustness

- **R17 — Gemini `'NoneType' object is not iterable` regression guard.** An audit of `gemini.py` confirmed all 12 access sites to `.candidates` / `.content.parts` are guarded. The original fix (commit `6feb406b`) shipped in v1.17.4; the reported log came from a pre-tag binary. Added 4 regression tests covering null `parts`, empty `candidates`, null `content`, and the `chat_sync_simple` helper so the triple guard can't silently regress.

### UX

- **R18 — `/attach <path>` error UX now surfaces close matches.** Typing the wrong directory (e.g. `/attach resources/foo.png` when the file lives in `docs/`) used to force blind retries. The error now enumerates the parent directory and lists the 5 closest matches via `difflib.get_close_matches(cutoff=0.3)`. If the parent itself is missing, walks up to the first existing ancestor and suggests similarly-named sibling directories. [`ppxai/commands/attach.py`](https://github.com/rcconsult/ppxai/blob/v1.17.5/ppxai/commands/attach.py)

- **R8 — `_count_csv_rows_cols()` no longer materializes the full file.** v1.17.4 made the row count streaming but left `_decode_text(data)` in place, producing a multi-MB Python string for a 10 MB CSV just to sniff the delimiter. Now decodes only the first 8 KB head for the sniff, then streams the raw bytes through `TextIOWrapper(BytesIO(data))` so `csv.reader` pulls one row at a time. **10 MB CSV: tracemalloc peak drops from ~20 MB to under 2 MB.** [`ppxai/engine/file_preprocessing.py`](https://github.com/rcconsult/ppxai/blob/v1.17.5/ppxai/engine/file_preprocessing.py)

## Added

- **R12 Option 1 — `EventType.AGENT_INTERMEDIATE_PROSE` surfaces model narrative between tool iterations.** During multi-step tool-calling loops the engine was stripping tool-call JSON out of each iteration's response and discarding the rest, leaving the UI silent for 5–15 seconds between tool bubbles even when the model was narrating ("I'll check the config next…"). `chat_with_tools` now emits `AGENT_INTERMEDIATE_PROSE` with the stripped prose right before `TOOL_GROUP_START` for every iteration that produced narrative. Empty responses skip the event so tool-only models (GPT-OSS native, some Qwen builds) don't trigger empty bubbles. Rich TUI renders as a `[dim italic]` preamble; ppxaide routes through a new `Events.ENGINE_AGENT_INTERMEDIATE_PROSE` bus signal to `add_system_message` in the chat view. Web/VSCode inherit via SSE pass-through and render as plain text until per-client styling ships. Option 3 (full streaming tool loop) remains deferred to v1.18.x as a provider-adapter sweep. [`ppxai/engine/chat.py`](https://github.com/rcconsult/ppxai/blob/v1.17.5/ppxai/engine/chat.py)

## Tests

- 2003 passing (was 1973 at v1.17.4)
- +46 new tests; +30 net after test consolidation
- New test files: `tests/test_chat_route_r15.py` (13), `tests/test_stream_handler_dispatch.py` (2 — drift detector), `tests/test_gemini_null_parts.py` (4), `tests/test_multimodal_cache.py` (10), `tests/test_count_csv_streaming.py` (9 — includes memory-bound regression guard)
- Existing files extended: `tests/test_tool_messages.py` (+5: 3 R9 + 2 R12), `tests/test_attach_command.py` (+3 R18)

## Deferred

- **R5** — first-class `uploaded_file` content type. Touches Python engine + JS + TS clients; the TODO's author explicitly deferred it to v1.18.x as a structural change. Current `<uploaded_file>` marker helper (v1.17.4's R6) is already centralized at [`ppxai/engine/uploaded_file.py`](https://github.com/rcconsult/ppxai/blob/v1.17.5/ppxai/engine/uploaded_file.py) so the v1.18.x lift is a wire-format swap, not a helper creation.
- **R19** — ppxaide multimodal fragility batch. Open-ended investigation rather than a point fix; deserves its own focused session.

## Upgrade notes

Drop-in release. Session format, provider adapters, API shape, and config schema are unchanged. Existing sessions (flat `.json` and directory-format) load without migration.

## Commits

```
7f611102 feat(engine): R12 Opt 1 — surface agent intermediate prose between tool iterations
a2b960a3 fix(file-preprocessing): R8 — stream CSV row count instead of materializing
98f59b61 fix(attach,session): R18 + R10 — attach error hints and multimodal cache
93a9737c fix(tui,gemini): R16 + R17 — dispatcher exhaustiveness and Gemini null-parts guard
162d63c5 chore: bump version to v1.17.5
dd78ce4b fix(session,server): R9 + R15 — tool_calls preservation and context-only chat guard
```
