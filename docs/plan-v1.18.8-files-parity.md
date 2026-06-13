# v1.18.8 Plan — `/files/*` cross-client parity & contract stability

**Branch:** `bugfix/v1.18.8` (off master @ v1.18.7).
**Class:** bugfix / post-release regression follow-up. No new features.
**Source:** post-v1.18.7 code review (cross-client parity). Debt items
[25](debt-inventory.md), 26, 27, 28.

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
None of the changes below touch the v1 gateway tier.

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
