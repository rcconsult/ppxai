# v1.18.8 Plan — `/files/*` parity + post-release code-review fixes

**Branch:** `bugfix/v1.18.8` (off master @ v1.18.7).
**Class:** bugfix / post-release regression follow-up. No new features.
**Source:** post-v1.18.7 code review. Two waves:
- **Wave 1 — `/files/*` cross-client parity** (original branch charter):
  debt items [25](debt-inventory.md), 26, 27, 28.
- **Wave 2 — broader code-review findings** (scope extension, owner-directed):
  debt items [29](debt-inventory.md), 30, 31, 32. Architectural-leaning
  findings scoped to their **bugfix-grade minimum** so the branch stays
  bugfix-class; the maximal refactors are split out / deferred per item.

## Why

v1.18.7 added a workspace file-browser feature set (office preview, upload,
download, spreadsheet rendering) to the **web client + server**, but changed
the semantics of **shared** `/files/*` endpoints and propagated the changes
into only one client path. ppxai's design intent is that the **VSCode
extension delegates to VSCode-native UI while consuming the same server
endpoints with identical semantics** — so a divergent or type-unstable
contract is a latent user-facing break, not just a cosmetic gap. v1.18.7 also
left one security fix (`09eae96e`) applied inconsistently across the file
routes.

**Guiding invariant for this branch:** every `/files/*` endpoint has **one
response contract with one set of semantics**, regardless of which client
calls it. Clients may render differently (web in-page, VSCode native, TUI
local), but the bytes/shape/status they receive must be identical and stable.

## The v1 gateway is out of scope

`POST /v1/oneshot` + bearer auth stay **byte-identical** (ppxai-sre consumer).
None of the changes below touch the v1 gateway tier. The `/command/*`
envelope shape also stays stable (ppxai-sre reuses ppxai source).

## Consolidated execution order (full v1.18.8 scope)

Phases are lettered to match the debt items. Detail for the `/files/*`
phases (A, F) is under "`/files/*` work detail" below; detail for the
code-review phases (B, C, D, E) is under "Extended-scope work detail".

| Order | Phase | Item | What | Risk |
|------:|-------|------|------|------|
| 1 | **A** | 27 | `serve_image` → `_within_tree` (security) | trivial |
| 2 | **B** | 32 | drop raw `Message` from `/load`; recursive envelope-serialization guard test | low |
| 3 | **C** | 31 | `SessionManager` mutation helpers; replace direct `messages.pop()/append()` | medium (hot path) |
| 4 | **E** | 30 | route `coding.py` user-facing output through events/result | low |
| 5 | **F** | 25/26/28 | `/files/read` typing + `/files/preview` unify + OfficeFileView race | medium (bulk) |
| 6 | 🔒 gate | — | in-depth review of Item 29 — **done 2026-06-14** → ADR 0007 | — |
| 7 | **D** | 29 | **seed only** (option a): `iter_completion_specs()`, stop reading privates. Full first-class service → v1.19.x | low |

A and B land first. C, E, F are mutually independent and can land in any
order after B. **D's review gate is done** — outcome in
[ADR 0007](decisions/0007-completion-first-class-service.md): land the
accessor seed on this branch, defer the first-class `CompletionService` +
AppState roster to v1.19.x.
Item 6 / debt 22 (`PpxaiApp` decomposition) is **not triggered**: Phase F
edits a few `app.js` methods in place; no decomposition required.

## Extended-scope work detail (Phases B, C, D, E — debt 29–32)

### Phase B — Item 32: envelope can't carry raw objects ✅ landed
- **Audit correction:** the `/load` `details["messages"]` key is **not**
  consumer-free — the in-process Textual renderer
  (`rendering/textual_renderer.py::render_confirmation`) reads it as live
  `Message` objects. So it can't be dropped; sanitize at the wire boundary
  instead.
- **Done:** `ConfirmationResult.to_dict()` runs `details` through a recursive
  `_jsonsafe()` (dataclass→`to_dict()`/`asdict`, bytes→marker, unknown→`str`)
  so the envelope is always `json.dumps`-able; in-process callers still read
  raw objects from `result.details` (never call `to_dict()`).
- **Tests:** `tests/test_command_envelope_serialization.py` (the `/load`
  Message regression + `_jsonsafe` unit coverage) + a parametrized
  `test_to_dict_is_json_serializable` over **every** `CommandResult` subclass
  in `tests/test_command_result_serialization.py`.

### Phase C — Item 31: session-mutation hygiene
- Add `SessionManager` helpers (callback-firing):
  `pop_orphan_trailing_users()` (replaces the `streaming.py:175` loop) and a
  `preserve_trailing_user()` context manager (wraps the `chat.py` preflight
  round-trip).
- Replace direct `session.messages.pop()/append()` at `chat.py:273/276`,
  `596/599`, `1064`, and `streaming.py:175`.
- Tests: AppState invalidation callback fires after orphan cleanup; preflight
  nets identical history. **Note:** `chat.py:273` already nets to a no-op;
  the real mutation is `streaming.py:175`. Keep behavior identical — lean on
  existing alternation tests.

### Phase D — Item 29: decouple `completion` from `commands` internals (seed; review gate done → ADR 0007)
- **Gate outcome (2026-06-14):** completion reframed as a capability over
  `(command-space × live-context)` — see
  [ADR 0007](decisions/0007-completion-first-class-service.md). Land the
  **accessor seed (option a)** here; the first-class `CompletionService` +
  AppState roster are v1.19.x.
- **Seed (this branch):** added `CommandFactory.iter_completion_specs()` +
  `CompletionCommandInfo` (public, narrow shape — no handler/internal
  storage); `engine.completion._complete_commands` consumes that snapshot
  instead of `_registry`/`_aliases`. The `engine → commands` import stays
  (its removal is the v1.19.x service work). Behaviour byte-identical.
- Tests: 61 existing completion tests unchanged + 3 new accessor tests in
  `test_tui_command_factory.py` (registry/alias coverage, alias→canonical,
  narrow-shape contract).

### Phase E — Item 30: coding-command output lost cross-client
- Route the user-facing notices in `commands/coding.py` (auto-route message
  L73, initial-message banner L80, +3) through the event/result channel so
  web/VSCode users see them; keep Rich rendering identical for TUI.
- **Defer** the broad console-purity sweep (`agent.py` ~43, `utility.py` ~39,
  `handler.py` ~29 — interactive TUI-only `input()` flows) to v1.19.x.
- Test: a `coding.py` command run under `ServerCommandContext` surfaces the
  auto-route notice via the result/events (not only server stdout).

## `/files/*` work detail (Phases A & F — Wave 1)

Phase 0 below = **Phase A**; Phases 1–3 below = **Phase F**.

## Order of work (security first, then contract, then robustness)

### Phase 0 — Item 27: `/files/image/` confinement (quick, security)
- Swap `serve_image`'s `str(path).startswith(str(home_dir))` for
  `_within_tree(path, home_dir)`, mirroring `read_file`/`write_file`.
- Add a regression test: a sibling-prefix path (`/home/userEVIL/...`) must
  return 403 via `/files/image/`.
- One-line change + one test. Land first; it's the only security item.

### Phase 1 — Item 25: stabilize the `/files/read` contract
- **Decision point (pick one, document in an ADR-style note):**
  - **(a) Keep `/files/read` text-stable**: revert csv to `type:"text"`;
    keep spreadsheets/office out of `/files/read` entirely (they go through
    `/files/preview`). Simplest; restores pre-v1.18.7 editor behavior.
  - **(b) Make `/files/read` fully typed**: keep the `office_spreadsheet`
    type but update **every** consumer to branch on `type` — add an
    `office_spreadsheet` case to `CodeEditorView` (refuse-to-edit + redirect
    to `OfficeFileView`) and to the RPF save/restore stack; remove the
    `typeof OfficeFileView !== 'undefined'` silent-fallthrough.
  - **Recommendation:** (b) for the web client + a shared response-handler,
    because the feature (client-side SheetJS render of xlsx/csv) depends on
    the typed contract. Restoring csv-as-text (a) would regress the new
    spreadsheet view. So: keep the type, fix the consumers.
- **Web fixes:**
  - `onFileEdit`/double-click: route office types to `OfficeFileView`
    (read-only) instead of `CodeEditorView`; never load base64 into the editor.
  - RPF `_saveRpfStack`/`_restoreRpfStack`: add an `OfficeFileView` case so
    reload restores the correct view.
  - Drop the `typeof OfficeFileView !== 'undefined'` guard (the script is
    bundled; a missing-script state should error visibly, not silently
    downgrade to base64).
- **VSCode-delegation guard:** even if `httpClient.readFile` stays unused,
  update its TS return type to the real union (`{type, mime_type, content,
  size, filename}`) and add a `type`-switch comment, so the next delegation
  feature can't silently write base64 into a buffer.
- **Tests:** server `/files/read` per-type contract (text / office_spreadsheet
  / 400-hint) pinned in `test_files_route.py`; web double-click + RPF-restore
  for `.csv`/`.xlsx` asserted to render a table, not base64.

### Phase 2 — Item 26: unify `/files/preview`
- Collapse the id-based (`/files/preview/{file_id}`, `file_serve.py`) and
  path-based (`/files/preview?path=`, `files.py`) routes onto **one handler**
  accepting either `file_id` or `path`.
- **One JSON shape** for both: always include `type`, `kind`,
  `libreoffice_available`, `total`, `name`.
- **One LibreOffice-missing semantics**: always `200 + text_fallback`
  (never 503), so VSCode and web degrade identically.
- Gate `.ppt`/`.doc` (legacy binary) on actual LibreOffice availability —
  return a clear "legacy format needs LibreOffice" message instead of a 500
  from python-pptx/docx on the OOXML-only fallback path.
- **Tests:** both entry points return identical shapes for the same document;
  LibreOffice-missing returns `text_fallback` (mock the missing binary);
  legacy `.ppt`/`.doc` without LibreOffice returns the typed message, not 500.

### Phase 3 — Item 28: OfficeFileView blob-URL revoke race (opportunistic)
- Capture the revoke handle synchronously, or guard the `.then()` against an
  already-unmounted view; revoke on unmount regardless of fetch timing.
- Assert the `text_fallback` `content` key explicitly (surface an error on
  key drift instead of rendering "(empty)").
- Lowest priority; land only if Phases 0–2 are clean.

## Cross-client verification (acceptance)

For each of `.csv`, `.xlsx`, `.docx`, `.pptx`, `.ppt`, and a text file:
1. **Server contract test** — `/files/read` and `/files/preview` return the
   documented, stable shape (pinned in `tests/`).
2. **Web** — single-click, double-click, and reload all render correctly
   (no base64-in-editor, no silent downgrade).
3. **VSCode** — the endpoints it calls (`/files/list`, `/files/tree`,
   `/files/preview/{id}`, and `readFile` if/when wired) parse without error
   and degrade identically to web when LibreOffice is absent.
4. **TUI** — unaffected (reads locally via `read_file_content`); confirm no
   regression in `/tree`/`/ls`.

## Out of scope (defer / roadmap)

- Adding office-preview/upload/download **UI** to VSCode or TUI — that's
  feature parity, not contract parity, and belongs on the roadmap. This
  branch only guarantees the **endpoints** are compatible so that delegation
  *can* land cleanly later.
- Web `app.js` decomposition (debt Item 22).

## Test-count note

v1.18.7 canonical = 3907 passed / 3 skipped (`--all-extras`). New tests here
add to that; pin the final count at v1.18.8 pre-tag from a canonical
`uv sync --all-extras` run (the release script's own count is env-dependent —
see the v1.18.7 README-badge-vs-docs discrepancy).
