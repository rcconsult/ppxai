# v1.18.0 Stabilization Pass — Summary

**Branch:** `feature/v1.18.0`
**Starting commit:** `177b25a1` (heartbeat P0 already shipped)
**Final commit:** `502e4c0d`
**Duration:** two working sessions, Apr 2026
**Tests:** 2,410 before → 2,591 after (+181), 0 failing

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

## Phase 5 — audit-driven polish (second session)

The Phases 1–4 audit surfaced 17 additional items. After user review
of each, seven were approved for action:

### Phase 5a — trivial cleanup (commit `0ea64cd5`)

- Duplicate `from pathlib import Path` in `rich/ui_components.py` removed.
- Seven `.read_text()` calls in `tests/test_shared_commands.py` now
  pass `encoding="utf-8"` — defensive for future non-ASCII content.

### Phase 5b — remove deprecated `has_vision_model` alias (`6c530b80`)

The back-compat alias from v1.17.4's `has_vision_sidecar` rename was
scheduled for removal in v1.18.x. Verified safe via GitHub search on
`ppxai-sre` (zero external callers). Alias removed, test references
updated, `test_pptx_render.py` simplified (was setting both the real
method and the alias on the engine mock).

### Phase 5c — PyInstaller spec coverage (`62c661fa`)

`ppxai-server.spec` listed 17 of 18 route modules in `hiddenimports`;
`schema.py` relied on the `routes/__init__.py` import cascade. Added
explicit listing, reordered alphabetically, added a policy comment.

Scope note: the decision said "list in all three specs" but `ppxai`
(TUI) and `ppxai-desktop` don't import `ppxai.server` — they spawn
`ppxai-server` as a subprocess — so adding route listings there
would be wrong. Applied only where the imports actually live.

### Phase 5d — unified zero-cost badge suppression (`8fc0be9f`)

Before: Rich TUI and web showed `"$0.0000"` during free-tier / local-
model turns; VSCode webview hid it. Three-way inconsistency.

After: `format_usage_badge` (Python canonical) drops the cost suffix
when `estimated_cost == 0`. JS and TS mirrors updated to match. All
four clients now produce byte-identical output — verified by the
cross-language parity tests from Phase 4.

### Phase 5e — architecture rules documented (`cdcc0369`)

Two doc-only additions with no code change:

- `AppState` class docstring gained a **Listener contract** section
  spelling out the re-entrant behaviour: listeners dispatched outside
  the lock, safe to call `state.get()`, must NOT synchronously call
  `state.set()` on another field (nested-dispatch ordering becomes
  observable, infinite-loop risk).
- New **Error Routing Conventions** section in `docs/ARCHITECTURE.md`:
  three channels (event bus / logger / raise), when to use each, and
  the two narrow cases where `except Exception:` is acceptable
  (Textual `NoMatches` guards and AppState listener isolation).

### Phase 5f — auto-save failure surfacing + Textual narrows (`2d200718`)

After verifying the audit's seven error-swallow findings, five were
legitimate defensive patterns and two were real user-impact bugs.

- **New `ppxai/common/autosave_guard.py::AutosaveFailureGuard`**: 3-
  failure threshold before firing a user-visible warning, one warning
  per streak, success resets and re-arms. Rich TUI uses a yellow
  `console.print`; Textual uses `app.notify(severity="warning")`.
  Previously a run with a full disk or revoked permissions silently
  lost every turn's save for the rest of the session.
- **Textual `query_one` narrowing**: two bare `except Exception:`
  blocks in `tui/app.py` (around `action_show_help_panel` and
  `action_toggle_file_tree`) narrowed to `except NoMatches:` per
  memory pattern #6. Any other exception now propagates.
- 8 new tests in `tests/test_autosave_guard.py` pin the state machine.
- Commit message lists all five audit false-positives so they don't
  get re-flagged.

### Phase 5g — "go via interfaces" for test imports (`6719c93e`, `502e4c0d`)

**The principle.** Project architecture rule: tests go via documented
interfaces, not private internals. Seven test files were importing
eight underscore-prefixed helpers from the engine / server / TUI.

**The judgement call.** Applied Option E from the discussion — pure
functions get promoted to public (signature + docstring is the
interface); I/O helpers get extracted to dedicated utility modules
with explicit contracts. Rejected Option D (Protocol for every helper)
as ceremony over insight for stateless utilities.

**Step 1 — 6 pure functions promoted:**

| Module | Before | After |
|---|---|---|
| `server.routes.chat` | `_is_empty_or_context_only` | `is_empty_or_context_only` |
| `config.loader` | `_load_dotenv_with_bom_handling` | `load_dotenv_with_bom_handling` |
| `engine.file_preprocessing` | `_count_csv_rows_cols` | `count_csv_rows_cols` |
| `engine.chat` | `_get_effective_profile` | `get_effective_profile` |
| `tui.widgets.message_box` | `_normalize_content_to_text` | `normalize_content_to_text` |
| `server.routes.file_serve` | `_is_word_document` | `is_word_document` |

Each rename applied atomically across production + tests in a single
commit — no back-compat alias (would be the exact compat-shim anti-
pattern the guidelines forbid). Docstrings updated to note the
public-surface status.

**Step 2 — 2 I/O helpers extracted:**

- `_atomic_replace` → `ppxai.common.atomic_file.atomic_replace`.
  Contract: bounded-retry file rename for Windows lock races.
  Four internal callers in `editor.py` updated.
- `_convert_docx_to_pdf` → `ppxai.common.docx_to_pdf.convert_docx_to_pdf`.
  Contract: LibreOffice headless docx→pdf with cache. Single caller
  in `file_serve.py` updated.

**Outcome.** Zero test files in the repo now import underscore-prefixed
names from `ppxai.*`. Every former private helper tests consumed is now
either public-on-its-module (pure) or in a dedicated utility module
(I/O). Architecture rule enforced, not aspirational.

## What's ready for v1.18.0 release

The heartbeat P0 plus twelve stabilisation commits across two sessions.
No new features, no new commands, no new dependencies. Ship as
"hardened heartbeat release" — feature work lands on a foundation
that doesn't shift under it.

### Cumulative numbers

- **2,410 → 2,591 passing tests (+181)**, 2 skipped, 0 failing
- **19 pre-existing test failures cleared** (Phase 2.5)
- **4 real production bugs fixed** as side-effects of the audit:
  - CRLF in `/attach` text files (Phase 2.5)
  - CSV routing on Windows (Phase 2.5)
  - Stale badge after SSE reconnect (Phase 2)
  - Silent auto-save failures (Phase 5f)
- **1 deprecated alias removed** (`has_vision_model`)
- **8 former private helpers promoted / extracted** for testability
- **5 cross-cutting invariants now locked in by tests:**
  1. Four heartbeat renderers agree on the rendering contract
  2. `GET /state` shape matches `SSE_SYNC_FIELDS` exactly
  3. `last_message_role` dedups on same-role mutations
  4. `format_tokens` / `format_usage_badge` byte-identical across
     four languages
  5. `AutosaveFailureGuard` state machine (below / at / no-spam / reset)
