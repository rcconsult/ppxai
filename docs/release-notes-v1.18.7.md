# Release Notes — v1.18.7

> **Scope:** A bugfix-class follow-up to v1.18.6. Repository hygiene,
> test-coverage backfill, one targeted decomposition (the largest
> method in the web client), a model-catalog refresh to the
> 2026-05-31 generation, and forward-looking paperwork for two
> v1.20.x asks surfaced by peer ppxai-sre RFCs. The v1 API gateway
> shape (`POST /v1/oneshot`, bearer-token auth) is preserved
> byte-identical — ppxai-sre's outlook-monitor agent and any other
> v1-gateway consumer is unaffected.
>
> **Five themes ran on this branch**, opened by the post-v1.18.6
> graphify + CRG scan that surfaced concrete, narrow fixes worth
> landing before the next feature wave, then extended by
> cross-repo signal from ppxai-sre's outlook-monitor work week.

## Branch + commit ranges

`bugfix/v1.18.7` (from master @ `fc60cd6f`). 13 commits as of
release prep, all doc/test/refactor/chore/data-table — zero
runtime-path code changes.

| Theme | Commits |
|---|---|
| Repo hygiene | `2e842e6f` chore(repo): untrack `site/` |
| Test coverage | `d06c5ee2` test(server): add HTTP route tests for `/files/read` |
| Decomposition | `819b623c` refactor(web): split `PpxaiApp._previewAttachment` into per-format renderers |
| Debt tracking | `39e740f7` docs(debt): file Items 21-23 from CRG analysis |
| Release notes draft | `2411028c` docs(release): draft release notes for v1.18.7 |
| Version bump | `d11fa76c` chore(version): bump to v1.18.7 across all SoT files |
| Docs refresh | `91dfe8ce` CLAUDE/CHANGELOG/release-notes refresh; `017b347b` uv.lock sync |
| api-gateway version-compat note | `14249929` added, `01d7d013` reverted — net-zero (see "Reverted" below) |
| Model catalog refresh | `b873ec2b` feat(models): refresh provider model catalog to 2026-05-31 generation |
| Two-tier memory | `4f027b05` docs(lessons): repo-tracked engineering hazards (cherry-picked from v1.18.6 `771685e9`) |
| v1.20.x paperwork | `1b056c0c` docs(roadmap): /v1/embeddings entry + MCP plan write-tool stance |

## Theme 1 — Repository hygiene

### `site/` removed from tracking, added to `.gitignore`

The `site/` directory is `mkdocs build` output. CI already publishes
it to the `gh-pages` branch via `.github/workflows/docs.yml`. Keeping
it tracked in `master` added 134 files of pure noise and (after the
v1.18.6 Step E rename) staleness: `site/` still pointed at the
**OLD UPPERCASE** doc paths (`AGENT_MODE_GUIDE/`, `ARCHITECTURE/`,
…) and re-stored the AWS paper at its pre-Step-C location
(`site/2512.15943v1.pdf`).

CRG analysis flagged the vendored `site/assets/javascripts/lunr/wordcut.js`
(365 LoC) as the 3rd-largest function in the codebase — entirely a
build-artifact false positive that self-resolves with this change.

Also added `graphify-out.bak.*/` to ignore the timestamped backup
that `graphify` keeps during a clean rebuild.

## Theme 2 — Test coverage backfill

### HTTP route tests for `/files/read`

CRG analysis identified `ppxai/server/routes/files.py::read_file` as
a 67-degree centrality hub with no dedicated test. Existing coverage
turned out to be:

- `test_files_cwd_anchor.py` — Phase D anchor / 409 conflict only
- `test_utils.py` — `read_file_content` (a different function in
  `ppxai/common/utils.py`, not the HTTP route)

The route's response surface — status codes, MIME branches, special
path prefixes — sat untested. The new `tests/test_files_route.py`
adds 12 cases (all pass, ~4s, no production code changes), organized
into four classes:

| Class | Cases | What it pins |
|---|---|---|
| `TestReadTextFile` | 3 | absolute path 200 + filename + lines; relative path resolves against working_dir; filename falls back to basename when path resolves outside working_dir |
| `TestReadErrors` | 4 | 404 missing file; 400 not-a-file (directory); 403/404 path outside allowed roots (never 200); 400 binary-file `UnicodeDecodeError` path |
| `TestReadBinaryPreview` | 2 | 1×1 PNG returns base64 + mime_type with round-trip; PDF returns base64 with type=pdf |
| `TestSpecialPathPrefixes` | 3 | `@search-query` finds first match; no-match → 404; `~/path` tilde branch doesn't crash |

Uses the same `TestClient` + `X-Session-Id` fixture pattern as
`test_files_cwd_anchor.py`; complements (does not duplicate) the
existing cwd_anchor coverage.

## Theme 3 — `PpxaiApp._previewAttachment` decomposition

`ppxai/web/app.js::PpxaiApp._previewAttachment` was the **largest
method in the entire web client**: 347 lines, 6 distinct preview
branches (image / pdf / spreadsheet / presentation / word /
generic+text), with a nested `AttachmentView` class re-declared every
time the method ran. CRG + graphify both surfaced it as the obvious
extract-method seam inside `PpxaiApp` (3,679-LoC god class).

Refactor strategy was **strictly behavior-preserving**:

1. **`AttachmentView` hoisted to module scope.** The nested class
   declaration moved from inside the method (depth-6 indented) to
   file-level, just above `class PpxaiApp`. Same `BaseView`-subclass
   contract — `getTitle`, `getPath`, `getIcon`, `mount`, `unmount`,
   `focus`, `onKeyDown` — byte-identical.
2. **Dispatcher shrunk 8x.** `_previewAttachment` is now 40 lines: it
   builds a shared `ctx` bag (`frame`, `name`, `mediaType`, `b64`,
   `sizeKB`) once, then dispatches to one of 6 renderers. The 7
   predicate branches are kept in the same order with the same
   logic.
3. **Six per-format renderers extracted** as private methods on
   `PpxaiApp`, each individually browseable:
   - `_renderImageAttachment` (~30 lines) — `data:` URI + zoom toggle
   - `_renderPdfAttachment` (~25) — Blob URL + `<iframe>` + cleanup
   - `_renderSpreadsheetAttachment` (~75) — SheetJS + DataTableViewer
   - `_renderPresentationAttachment` (~90) — PPTX slide navigator
   - `_renderWordAttachment` (~55) — DOCX → PDF conversion via fetch
   - `_renderGenericAttachment` (~40) — other Office info panel +
     text-file decode fallback

**Net file size change: +71 LoC** (method-declaration boilerplate +
hoisted class). The dispatcher itself dropped 8x; each format is now
its own readable unit instead of being buried inside a 347-line
`else if` ladder.

**Behavior risks pinned in the commit message:**

- PDF and Word renderers preserve their `view.unmount = () => {
  URL.revokeObjectURL(blobUrl); origUnmount(); }` override exactly —
  the Blob URL cleanup pattern was the single riskiest piece.
- Renderers that use `this.state.contextAttachments` /
  `this.apiClient.getHeaders()` (PPTX, Word) are instance methods,
  so `this` resolves the same way as before.
- `node --check ppxai/web/app.js` passes; no e2e test directly
  covers `_previewAttachment` so manual browser smoke is the
  acceptance test.

This is one targeted slice of the broader `PpxaiApp` god-class
debt (now tracked as DEBT Item 22). The remaining decomposition
likely needs a build step (esbuild, mirror of the v1.18.2 vscode
work) and is not in v1.18.7's scope.

## Theme 4 — Debt inventory updates

Three new items opened in `docs/debt-inventory.md` to track work
that surfaced during the bugfix/v1.18.7 CRG + graphify scan but is
too large for a bugfix branch:

| # | Item | Status |
|---|---|---|
| **21** | `chat_with_tools` decomposition (673-LoC engine hot path, no direct unit tests) | Open — needs ADR + test scaffold first; likely v1.19.x alongside ADR 0003 Stage 2 |
| **22** | `PpxaiApp` further decomposition (3,749 LoC after the v1.18.7 split) | Open — trigger-deferred; revisit when the web client gets a build step or another client wants to share logic |
| **23** | `SessionManager` growth drift (1,648 → 2,091 LoC, +27%) | **Flag-only, no action** — verified per CLAUDE.md "verify-before-flagging" rule: every accounting commit is intentional ADR 0006 wiring. Documented so future analysis doesn't re-flag |

Item 3 (k8s session-manager security tests) unchanged. The closed
sections are unchanged.

## Theme 5 — Model catalog refresh (2026-05-31)

`ppxai/engine/model_profiles.py` + `ppxai-config.example.json`
updated for the model lineup as of release date. Current-gen entries
added, deprecated identifiers retired, deprecation table synced.
Pure data change — no engine code paths touched. Provider profiles
preserve `supports_vision`, `supports_reasoning`, `max_tokens`,
`tool_calling` shapes from their predecessors where the new model
has the same capability surface (sub-tier moves explicitly called
out in commit `b873ec2b`).

This matters most for the `/doctor` advisor's deprecated/new/
recommended model scan — outdated catalogs surface stale
recommendations and miss new tiers worth surfacing to users.

## Theme 6 — Forward-looking docs (v1.20.x paperwork)

Two upstream asks surfaced this week by peer ppxai-sre RFCs were
captured in ppxai docs so they reach the v1.20.x implementation
branch without re-derivation.

### `docs/lessons/` — two-tier memory infrastructure

Cherry-picked from `bugfix/v1.18.6` (`771685e9` → `4f027b05`).
Repo-tracked engineering hazards live in `docs/lessons/`, syncing
via `git pull` and visible to humans + AI agents on any clone.
Per-host AI memory (`~/.claude/projects/<repo>/memory/`) stays for
user preferences + session scratchpads. Promotion criteria
(cross-host + grep-verifiable), workflow, and format spec are in
`docs/lessons/README.md`. CLAUDE.md "Shared lessons" section
instructs agents to propose promotion when they discover qualifying
hazards.

Seeded with `docs/lessons/mcp-not-yet-integrated.md` documenting
the three filename-level traps that make ppxai look MCP-enabled
when it isn't:

| Trap | What it is | Why it misleads |
|---|---|---|
| `pyproject.toml [mcp]` extras | Declared `mcp>=0.1.0` since v1.9.x | Dep is documented intent, not shipped functionality. Venv install excludes it; `import mcp` raises `ModuleNotFoundError` |
| `.mcp.json` at repo root | Lists `code-review-graph` | Placeholder. Zero Python code in `ppxai/` loads it |
| `tests/test_mcp.py` | Exists | Diagnostic script, not integration test against ppxai MCP wiring (which doesn't exist) |

The full v1.20.x integration plan lives at
`docs/mcp-integration-plan.md`.

### v1.20.x `/v1/embeddings` ROADMAP entry

New sibling to MCP Day-0 under v1.20.x in `ROADMAP.md`. Surfaced
by peer outlook-monitor's RFC `DESIGN-outlook-write-tools.md`
(peer master commit `87e421d`, 2026-05-31). The peer's `Embedder`
Protocol currently uses bundled FastEmbed CPU (bge-small-en-v1.5,
384-dim), explicitly designed as a swap seam for a future
`PpxaiEmbedder` once `/v1/embeddings` exists upstream. Today's
local-first decision is correct (offline/air-gapped, mailbox
content stays local, no dim coupling to ppxai pin); the upstream
ask makes the swap **opt-in**.

Design points captured but deferred to `feat/v1-embeddings`
implementation branch: provider abstraction (parallel to
chat-model routing or independent?), pooling semantics
(mean/cls/last-token, request-level or provider-config?), dim
negotiation, auth (bearer pattern mirrors `/v1/oneshot`), billing
(embeddings tokens are a separate counter in provider pricing —
`/usage` needs a new column).

### MCP plan write-tool stance refinement

Same peer RFC also surfaced a Day-0 scope refinement for
`docs/mcp-integration-plan.md`. The plan's consent-tier mapping
had Tier 2 ("consent-once-per-session, e.g. write tools") as if
write-capable MCP tools would ship from Day-0. The RFC §3
explicitly rejects this for any MCP server reading attacker-
controlled content (email, PRs, web pages, etc.) — Surface-A
defenses (output framing, sender-trust labels) cannot enforce
consumer-LLM behavior, only frame the content; write blast radius
(move/delete/forward) makes residual injection risk unacceptable.

Plan now says: Tier 2/3 plumbing still gets built, but **every
Day-0 MCP server's config should pin `tier: 1`** unless the server
author has done a Surface-A red-team corpus proving writes are
safe. The peer's interim path for outlook-monitor writes is CLI
subcommands gated by per-invocation human approval, not MCP. Both
ppxai and ppxai-sre's planned write surfaces inherit this
constraint.

## Reverted

The branch contains one revert pair worth flagging in the release
record:

- **`docs(api-gateway): add version-compatibility note for downstream consumers`** (commits `14249929` added, `01d7d013` reverted ~2 min apart on 2026-05-31). The note added a "Version compatibility" section to `docs/api-gateway.md` documenting the v1 gateway's byte-identical compatibility window (v1.18.4 → v1.18.7) and recommending a `>=1.18.4` consumer pin against released versions. Reverted without explicit rationale in the git history; most plausible reading is that the content was correct at write-time but inherently time-sensitive — lines like "Latest released: v1.18.6" and "1.18.7 is not a release" would silently rot the moment v1.18.7 ships, becoming wrong without a manual update step.
- Net change to the repo: zero.
- Worth re-attempting in a release-evergreen form (e.g. derived from `latest` tag at render time, or a CI step that updates the version-cells on each release) if downstream pinning guidance is still wanted. Not in v1.18.7 scope.

## What did NOT change in v1.18.7

- **Version strings bumped, but not released.** `chore(version):
  bump to v1.18.7` moved `pyproject.toml`, `ppxai/version.py`,
  `vscode-extension/package.json` + lock, `README.md`, and
  `docs/index.md` to `1.18.7` so the SoT files agree. The release
  itself (tag, CI assets, `gh release`) has **not** run — this
  branch ships only when the user invokes `/release`.
- **No runtime-path code change.** Every commit is doc, test, a
  behavior-preserving JS refactor, or the version-string chore.
- **v1 API gateway shape preserved byte-identical.** `POST /v1/oneshot`
  request/response, bearer-token auth, error envelope, and event
  stream are all unchanged. ppxai-sre's `>=1.18.4` pin still
  satisfies; outlook-monitor is unaffected.
- **No database migration.** Session schema_version still 2 (per
  ADR 0006 in v1.18.6). No `v2 → v3` discussion.

## Tests

All existing tests pass. New: 12 cases in `tests/test_files_route.py`,
~4s additional runtime. Total reported test count: **3707 pass**, 2
skipped on Unix (9 skipped on Windows due to `os.getpgid` / `os.killpg`
`patch()` limitations on `TestKillPreviewBackend`). Up +12 from v1.18.6's
3695 baseline — matches the new HTTP-route suite exactly, no other
test churn.

The model-catalog refresh (`b873ec2b`) is data-only and exercises the
same existing test parametrizations under `test_model_vision.py` +
`test_doctor.py`; no new test cases were needed.

## Acknowledgements

The CRG + graphify analysis that drove this branch is captured in
the rebuild summary on master @ `fc60cd6f`. The decomposition trade-
offs documented per CLAUDE.md "verify before flagging" rule —
production-only inbound count + channel-ratio inspection — caught
Item 23 (SessionManager growth) before it became a needless refactor
candidate.
