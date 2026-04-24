# v1.18.0 Stabilization Pass — Summary

**Branch:** `feature/v1.18.0`
**Starting commit:** `177b25a1` (heartbeat P0 already shipped)
**Final commit:** `a330c187`
**Duration:** one working session, Apr 2026
**Tests:** 2,410 before → 2,582 after (+172), 0 failing

Before adding any v1.18.x features, we ran a deliberate cleanup pass
to pay down architectural drift accumulated across v1.16.x / v1.17.x.
Stability over velocity.

## Discipline rules we held to

1. **One commit per phase**, each with a coherent scope.
2. **Every change had a failing-before / passing-after test.** No drive-
   by edits.
3. **Violations found mid-work got written down, not fixed.** Scope
   discipline beats completeness.
4. **Kept the existing public API.** No breaking changes even inside
   `ppxai.engine`.
5. **Tests pass at every commit.**

## Phase 1 — AGENT_BEAT cross-client rendering parity

Commit: `3615dfe3`

The audit suspected the four heartbeat renderers (Rich, Textual, web,
VSCode) might have drifted. Rather than assume, we wrote a parity test:
one shared fixture table driven through every renderer, asserting the
invariants all four must satisfy.

- Python renderers called directly.
- JS renderers extracted from `main.js` / `app.js` with a brace-
  balanced regex and evaluated via `node -e` against a DOM stub.
- 20 parametrised assertions (4 clients × 5 fixtures).

Result: parity confirmed. Rich's known divergence (no warning/error
variants — uses the textual "fail" token instead of a colour class)
captured explicitly in the contract so it can't rot silently.

**Zero production code changed.** Suspicion ruled out.

## Phase 2.5 — Clear pre-existing test failures

Commit: `246c6035`

While running Phase 1 we discovered 19 failing tests on
`feature/v1.18.0` that predated any stabilisation work. Triaged into
six clusters. Two turned out to be real production bugs affecting
Windows users:

| Cluster | Kind | Fix |
|---|---|---|
| Zombie threshold tests (×5) | Test drift | Mock `_get_zombie_threshold` in each test; clear config for library-default check |
| `test_app_state` schema readers (×4) | Windows test bug | `read_text(encoding="utf-8")` |
| `/attach` text CRLF (×1) | **Prod bug** | `PendingFile.text` normalises `\r\n`→`\n` so a Windows-saved file doesn't ship CRLF bytes to the LLM |
| CSV tools (×3) | 2 test + 1 prod | Fixture uses `newline=""`; `preprocess_file` forces `.csv` to text regardless of platform mimetype (Windows resolves `.csv` to Excel) |
| `test_handle_save` path (×2) | Windows test bug | `.replace("\\", "/")` before asserting |
| `test_server_routes` path (×3) | Windows test bug | Same |

**Result: 2,525 passing, 0 failing on Windows.** Linux/macOS unchanged
— all normalisations are no-ops when the platform already uses `/`.

## Phase 2 — `GET /state` snapshot endpoint for SSE reconnect

Commit: `0c4ac1f4`

### Problem
When a web or VSCode client loses its SSE connection (network blip,
server restart, tab sleep), any `state_sync` events that fire during
the gap are lost. On reconnect the client's mirror of `AppState`
drifts until the user triggers a full reload.

### Fix
- Hoisted `_SSE_SYNC_FIELDS` (previously local to `EngineClient.__init__`)
  to a module-level `SSE_SYNC_FIELDS` frozenset in
  `ppxai/engine/client.py`. Single source of truth the server endpoint
  imports directly; no more AST parsing in tests.
- New `GET /state` endpoint (`ppxai/server/routes/state.py`) returns a
  snapshot of exactly those fields. Shape matches the accumulated
  payload of live `state_sync` events, so clients feed the response
  directly to their `updateFromPython()` facade.
- Web `apiClient.getState()` + wired into the heartbeat recovery path.
  Previously only the 4-strike full reconnect triggered a fresh state
  load via `loadInitialState()`; the 2-3 strike quick-recovery window
  now catches up via `/state` + `state.updateFromPython()`.
- VSCode `httpClient.fetchState()` exposed as a primitive. The
  extension's existing `updateStatus()` already refreshes on
  reconnect-like triggers via `/status`, so no behavioural wiring is
  needed yet.

### Scope we did not touch
- VSCode doesn't have a heartbeat loop. Adding one is a feature, not
  a fix. Deferred.
- Web `loadInitialState()` still uses `/status` (works fine;
  refactoring it would only add regression risk).

## Phase 3 — AppState scanning cleanup

Commit: `012911f1`

### What the audit flagged vs. what was real
The audit identified three sites where clients scanned
`session.messages` directly. On close inspection only one was a real
architectural violation. The other two are legitimate message
iteration (session-restore rendering, auto-save counter throttling)
that doesn't fit the AppState-mirror pattern.

**We fixed the one violation and left the other two alone.**

### The real fix — Rich interrupt handler
- New `AppState.last_message_role` schema field. Empty string for an
  empty session, otherwise mirrors `session.messages[-1].role`.
- `EngineClient._on_messages_changed` became a fan-out callback that
  calls both `_refresh_context_attachments` and
  `_refresh_last_message_role`. Future message-derived AppState
  fields add a `_refresh_<field>` method and wire it here — nobody
  touches `session.on_messages_changed` directly.
- `rich/main.py` interrupt handler reads `state.get("last_message_role")`
  instead of `session.messages[-1].role`. Same observable behaviour,
  single source of truth.
- 11 new tests (`test_last_message_role_state.py`) covering field
  default, dedup behaviour, and every mutation entry point.
- Field-count sentinels bumped `19 → 20` in two places.

## Phase 4 — Unify token and usage-badge formatting

Commit: `a330c187`

### Problem
`format_tokens` (compact "1.2K" display) had four inline copies across
Rich, web, VSCode webview, and VSCode extension host — three of them
slightly different. `format_usage_badge` (the "1.2K↓/0.5K↑ $0.0045"
string) had its own triplicate inline versions.

### Fix
- New canonical `ppxai/common/format.py` with `format_tokens(n)` and
  `format_usage_badge(prompt, completion, cost)`.
- Rich `ui_components.format_usage_string` delegates to the canonical.
- Dead `format_tokens` in `rich/main.py` removed.
- `ppxai/web/shared/formatters.js` exports mirrors on both the
  SharedFormatters global and the CommonJS module.
- `vscode-extension/src/shared/formatters.ts` exports typed mirrors.
- VSCode webview (standalone script, no module system) gets an inline
  copy with a pointer comment back to the Python source.

### Cross-language parity test
New `tests/test_usage_format.py`:
- 42 parametrised tests (token fixtures × 4 source files + usage
  fixtures × 3 source files with arrows).
- Python runs natively; JS/TS functions extracted with a brace-
  balanced regex and run via `node -e` with `encoding="utf-8"` so the
  Unicode arrow glyphs survive the round-trip on Windows.
- Any copy that drifts from Python fails the test and names the
  offending file.

### Scope we didn't touch
- `formatTokens` inline in `web/app.js::updateContextInfo` uses
  `.toFixed(0)` (zero decimals for "128K"). That's a deliberate
  formatting choice for context limits, not drift. Left alone.
- VSCode webview zero-cost suppression (hide "$0.0000" when cost=0)
  preserved — different from the shared helper by design, comment
  explains why.

## Things we deliberately did NOT do

The audit surfaced several tempting refactors. All were declined in
this pass:

- **Extract god-objects** (`tui/app.py` 1,933 LOC, `chatPanel.ts`
  3,014 LOC). Large files aren't tech debt on their own — they only
  become debt when you're trying to add features into them. No features
  are being added; leave the files alone.
- **Refactor web `loadInitialState()`** to use the new `/state`
  endpoint. It works fine via `/status`. Zero-diff principle.
- **Move all `.read_text()` calls** to explicit UTF-8 encoding
  repo-wide. Only fixed the ones that were actually failing.
- **Bump unit/integration test ratio.** Tests aren't slow or fragile
  enough to justify the churn.
- **Add type hints to TUI/Rich.** Improve opportunistically, not as a
  sweep.

## Outcomes

- 2,410 → 2,582 passing tests (+172)
- 19 pre-existing failures → 0
- 2 real production bugs fixed (CRLF in `/attach`, CSV routing on Windows)
- 1 architectural debt cleared (last_message_role now centralised)
- 4 new cross-cutting invariants locked in by tests:
  1. All four heartbeat renderers agree on the contract
  2. `GET /state` shape matches `SSE_SYNC_FIELDS` exactly
  3. `last_message_role` dedups on same-role mutations
  4. `format_tokens` / `format_usage_badge` produce byte-identical
     strings across Python, web JS, VSCode TS, and VSCode webview
- 0 behavioural changes users can see (except the two Windows bug
  fixes)

## What's ready for v1.18.0 release

The heartbeat P0 plus these five stabilisation commits. No new
features, no new commands, no new dependencies. Ship as "hardened
heartbeat release" — which means feature work lands on a foundation
that doesn't shift under it.
