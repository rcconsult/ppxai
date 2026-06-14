# Release Notes — v1.18.8

> **Scope:** A bugfix-class follow-up to v1.18.7. Cross-client `/files/*`
> parity (the original branch charter) plus a wave of correctness and
> security findings surfaced by parallel code reviews and live desktop
> testing. **No new features.** The v1 API gateway (`POST /v1/oneshot`,
> bearer auth) and the `/command/*` envelope shape are **byte-identical to
> v1.18.7** — ppxai-sre's outlook-monitor and any other consumer is
> unaffected.

## Branch

`bugfix/v1.18.8` (from master @ v1.18.7). All changes are
bugfix/test/doc/chore — no v1-gateway shape changes.

The work landed in three overlapping waves:

1. **`/files/*` cross-client parity** — the original charter (debt 25–28).
2. **Broader code-review findings** — completion coupling, console leak,
   session-mutation hygiene, envelope serialization (debt 29–32), plus the
   `serve_image` security fix (debt 27).
3. **Findings from parallel reviews + live testing** — session save/load
   security, cross-platform LibreOffice discovery, and the session
   auto-restore bug.

## Security

- **Session-file path traversal.** `save()` wrote `sessions_dir/<name>.json`
  from a user-supplied name with no separator check (`save("../escaped")`
  escaped the directory), and `load()` trusted the JSON's internal
  `session_name` (a safe file could set `"session_name":"../escaped"` and
  poison the next autosave). New `_safe_session_name()` rejects separators /
  `..` / NUL — HTTP 400 on save; load falls back to the validated requested
  name. (`de3b56d7`)
- **Stale attachment file-IDs after session load.** Loading a text-only
  session didn't reset the file store, so the previous session's attachment
  `file_id`s still resolved via `/files/serve/{id}` and `/files/preview/{id}`.
  The store now resets on every load. (`de3b56d7`)
- **Corrupt load corrupting the file store.** `load()` rebuilt the store
  before parsing `session.json`; a corrupt file wiped the store while keeping
  messages. JSON is parsed first now. (`de3b56d7`)
- **`/files/image/` home confinement** (debt 27). `serve_image` still used the
  `str.startswith` prefix check the v1.18.7 fix had migrated elsewhere, so
  `/home/userEVIL` bypassed home confinement through the image route. Swapped
  to the component-wise `_within_tree()`. (`7fb83d8b`)

## `/files/*` cross-client parity

- **`/files/read` type contract** (debt 25). Every consumer now branches on
  the server `type` — `CodeEditorView` refuses any non-`text` type (no more
  base64-as-text / corrupt-on-save), the RPF stack round-trips an `office`
  view, the deploy-skew guard is dropped, and VSCode `readFile` gets the real
  typed union. (`2a22807c`)
- **`/files/preview` unified** (debt 26). The path-based and id-based routes
  collapse onto one `render_office_preview()` helper: one JSON shape, always
  `200 + text_fallback` when LibreOffice is missing (never 503), legacy
  `.ppt`/`.doc` return a typed message instead of a 500. (`579a2fe8`)
- **OfficeFileView blob-revoke race + attachment text_fallback** (debt 28 +
  follow-up). `disposed` guards close the object-URL leak on fast view
  switching; chat-bubble attachments degrade to extracted text like the file
  tree; VSCode no longer writes a JSON text_fallback into a `.png`/`.pdf`.
  (`ef17f748`, `84ee33c2`)

## Office preview — cross-platform LibreOffice

The office-preview pipeline probed only `shutil.which("libreoffice")` and
invoked the literal `libreoffice` — but macOS ships `soffice` inside
`/Applications/LibreOffice.app` and adds nothing to PATH, so a plain
`brew install --cask libreoffice` left raster preview dead (users had to
hand-symlink). New leaf `ppxai/common/libreoffice.py` resolves across
platforms (PATH `libreoffice`/`soffice`, the macOS `.app` bundle, Windows
Program Files, `PPXAI_LIBREOFFICE` override). The LibreOffice-missing web
fallback now shows a formatted, platform-aware install card with a Download
button. (`9d1c7550`)

## Session restore

- **Auto-restore landed on defaults.** The web client ignored the
  `auto_restore` config and always popped a `window.confirm()`; when that
  dialog was dismissed/suppressed the restore silently never fired and the
  session came back on fresh defaults — even though the engine restore path
  was correct. `/status` now exposes `auto_restore`, and the client honors
  `always`/`prompt`/`never` (`always` restores with no dialog). (`1fe60ea5`)
- **Textual restore dropped directory-format sessions.** ppxaide checked only
  `<name>.json`, so a saved multimodal session (`<name>/session.json`) looked
  missing and the restore pointer was cleared. A shared
  `SessionManager.session_file_exists()` now accepts both formats; the server
  route routes through it too. (`de68215e`)
- **Named saves from web/VSCode were ignored.** `POST /sessions/save` bound
  `name` as a query parameter, but the clients send `{"name": ...}` in the
  JSON body → saved under the auto-name. Changed to `Body(None, embed=True)`.
  (`de68215e`)

## Other review findings

- **coding auto-route notice** (debt 30) now rides in
  `AIResponseResult.content` so web/VSCode see it (was a lost `console.print`).
  (`0f21cee1`)
- **Session-mutation hygiene** (debt 31) — alternation cleanup routes through
  new `SessionManager` helpers so the AppState callback fires. (`44bb5dea`)
- **Command envelope** (debt 32) — `ConfirmationResult.to_dict()` sanitizes
  `details` via a recursive `_jsonsafe()`; guard test over every
  `CommandResult` subclass. (`439a0325`)
- **`engine.completion` decoupled** (debt 29 seed) via the public
  `CommandFactory.iter_completion_specs()`. The first-class `CompletionService`
  + AppState roster are designed in **ADR 0007** for v1.19.x. (`6a0a0a72`)
- **AGENTS.md model-hint corrections** — wrong tool/param names (`apply_patch`
  is `file_path`/`unified_diff`; `read_file` is `filepath`; `edit_file` /
  `run_command` aren't real tools), additive-hints documentation, reworded
  Chain-of-Thought hints. (`17fabfc8`)

## New tests

`test_files_route.py` (office-type contract, serve_image confinement),
`test_files_preview_download.py` (unified preview), `test_libreoffice_resolver.py`,
`test_session_security.py` (3 findings), `test_session_restore_format.py`,
`test_server_routes.py` (named-save), `test_command_envelope_serialization.py`,
`test_coding_autoroute.py`, plus accessor/mutation-helper tests.

## What did NOT change

- The v1 gateway (`POST /v1/oneshot`, bearer auth) — byte-identical.
- The `/command/*` envelope shape (ppxai-sre reuses ppxai source).
- The AppState 4-mirror schema DTO.

## Known follow-ups (debt inventory)

- **Item 34:** the release CI is **verified** to build with `--all-extras`
  (shipped binaries bundle office deps); only the local `/build-install` skill
  (`--no-sync`) and a missing `python-docx` in `[data]` remain — neither blocks
  release.
- **ADR 0007** completion service, **Item 33** console sweep — v1.19.x.

## Verification note

Web/VSCode UI changes are `node --check` / `tsc --noEmit` clean but have **no
automated DOM harness** — a manual browser + extension pass on office preview
and session restore is the acceptance gate before tagging.

## Acknowledgements

Multiple parallel code reviews (codex) caught the session-security findings,
the LibreOffice-detection / `/files/*` contract gaps, and the test-isolation
regressions; live desktop testing surfaced the office-preview packaging and
auto-restore issues.
