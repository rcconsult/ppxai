# Changelog

All notable changes to ppxai will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Branch: `bugfix/v1.18.7`. Theme: **bugfix-class follow-up to v1.18.6** — repository hygiene, test-coverage backfill, one targeted web-client decomposition, model-catalog refresh to the 2026-05-31 generation, plus paperwork for two v1.20.x upstream asks surfaced by peer ppxai-sre RFCs. The v1 API gateway shape (`POST /v1/oneshot`, bearer auth) is **byte-identical to v1.18.6** — ppxai-sre's outlook-monitor and any other v1-gateway consumer is unaffected.

### Added

- **`docs/lessons/` repo-tracked engineering hazards.** Two-tier memory: cross-host grep-verifiable facts live in `docs/lessons/` (syncs via `git pull`, visible to humans + AI agents on any clone), while per-host AI memory (`~/.claude/projects/<repo>/memory/`) stays for preferences + session scratchpads. Seeded with `docs/lessons/mcp-not-yet-integrated.md` documenting the three filename-level traps that make ppxai look MCP-enabled when it isn't (`[mcp]` optional extras, `.mcp.json` placeholder, `tests/test_mcp.py` diagnostic). CLAUDE.md "Shared lessons" section instructs future agents to propose promotion when they discover qualifying hazards. Commit `4f027b05` (cherry-picked from `bugfix/v1.18.6` `771685e9`).

- **HTTP route tests for `/files/read`.** First sentinel suite for this endpoint — covers cwd-relative + absolute-path resolution, the `cwd_anchor` 409 mismatch case (v1.18.1 state-sync-determinism contract), the `Path("/a/b") / "../c"` path-traversal rejection, and the binary-content rejection branch. Commit `d06c5ee2`.

### Changed

- **`PpxaiApp._previewAttachment` decomposed into per-format renderers** (`ppxai/web/app.js`). The 347-LoC monolithic dispatcher (fan-out 51 — the largest method in the web client) split into 6 per-format renderers (`_renderImageAttachment`, `_renderPdfAttachment`, `_renderOfficeAttachment`, `_renderTextAttachment`, `_renderJsonAttachment`, `_renderUnknownAttachment`) + a 40-LoC dispatcher. Per-branch behavior preserved byte-for-byte; each format now individually browseable + testable. File net +71 LoC of method boilerplate; dispatcher shrank 8x. Commit `819b623c`. (Tracks toward Item 22 — see `docs/debt-inventory.md`.)

- **Model catalog refresh to current generation (2026-05-31).** `ppxai/engine/model_profiles.py` + `ppxai-config.example.json` updated for the model lineup as of release date — adds current-gen entries, retires deprecated identifiers, syncs the deprecation table. Commit `b873ec2b`.

- **`mkdocs` `site/` directory untracked.** CI publishes the rendered site to `gh-pages` via `.github/workflows/docs.yml`; keeping `site/` in `master` added 134 files of pure noise. The v1.18.6 doc rename to lowercase-kebab-case also left `site/` pointing at stale uppercase paths. CRG analysis flagged the vendored `site/assets/javascripts/lunr/wordcut.js` (365 LoC) as the 3rd-largest function in the codebase — a pure build-artifact false positive that self-resolves with this change. Added `graphify-out.bak.*/` to `.gitignore` for the same noise-reduction reason. Commit `2e842e6f`.

### Documentation

- **v1.20.x `/v1/embeddings` ROADMAP entry.** New sibling to MCP Day-0 under v1.20.x. Surfaced by peer ppxai-sre's outlook-monitor write-tool RFC (peer `87e421d`, 2026-05-31) — the peer's `Embedder` Protocol explicitly leaves room for a `PpxaiEmbedder` impl once `/v1/embeddings` exists upstream. Today's local-first decision (bundled FastEmbed CPU, bge-small-en-v1.5, 384-dim) is correct for offline/air-gapped + mailbox-content-stays-local reasons; this entry makes the swap **optional**. Design points captured but deferred to `feat/v1-embeddings` branch: provider abstraction, pooling semantics, dim negotiation, auth (bearer mirror of `/v1/oneshot`), billing. ~2-3 days for single-provider POC. Commit `1b056c0c`.

- **MCP integration plan write-tool stance.** Same RFC surfaced a Day-0 scope refinement for `docs/mcp-integration-plan.md`: write-capable MCP tools (Tier 2/3) are deferred to Day-1+ for any server reading attacker-controlled content (email, PRs, web pages). Surface-A defenses (output framing, sender-trust labels) cannot enforce consumer-LLM behavior, only frame the content; write blast radius (move/delete/forward) makes residual injection risk unacceptable. Day-0 MCP servers should pin `tier: 1` (read-only auto-approve) unless the server author has a Surface-A red-team corpus proving safety. Tier 2/3 plumbing stays built. Commit `1b056c0c`.

- **Debt inventory: Items 21-23 from `bugfix/v1.18.7` CRG scan.** Item 21 `chat_with_tools` decomposition (673 LoC, fan-out 169 — largest function in codebase; deferred to v1.19.x ADR-backed work with test scaffold first). Item 22 `PpxaiApp` further decomposition (3,749 LoC after the v1.18.7 split — trigger-deferred until a JS build step or cross-client reuse motivates it). Item 23 `SessionManager` growth drift (+443 LoC since v1.18.2, fully explained by ADR 0006 work — flag-only, no action). Commit `39e740f7`.

- **Release notes draft for v1.18.7.** `docs/release-notes-v1.18.7.md`. Commit `2411028c`.

### Chore

- **Version bump to 1.18.7 across all SoT files** per `tests/test_version_consistency.py` registry. Commit `d11fa76c`.
- **uv.lock sync to 1.18.7.** Commit `017b347b`.
- **CLAUDE.md / CHANGELOG / release-notes refresh** to current v1.18.6+v1.18.7 state during today's pre-release sweep. Commit `91dfe8ce`.

### Reverted

- **`docs(api-gateway): add version-compatibility note for downstream consumers`** (commits `14249929` added, `01d7d013` reverted ~2 min apart on 2026-05-31). The note documented the v1 gateway's byte-identical compatibility window and recommended a `>=1.18.4` pin for downstream consumers. Reverted without explicit rationale recorded in the git history; most plausible reading is that the content was correct at write-time but inherently time-sensitive (the "Latest released: v1.18.6" + "1.18.7 is not a release" lines would silently rot the moment v1.18.7 ships, becoming wrong without a manual update). Net change to the repo: zero. Worth re-attempting in a release-evergreen form if pinning guidance for consumers is still wanted.

### Tests

3707 pass, 2 skipped on Unix (9 skipped on Windows due to `os.getpgid` / `os.killpg` `patch()` limitations on `TestKillPreviewBackend`). Test count delta from v1.18.6 = +12 (test count for v1.18.6 was 3695; +12 = the new HTTP route tests + a small handful of post-release additions on this branch).

## [1.18.6] - 2026-05-23

Branch: `bugfix/v1.18.6`. Theme: **foundation release** — ADR 0006 content-block schema separation establishes the artifact framework that v1.19.x agent platform work will consume; v1 → v2 session migration with documented breaking change; context-indicator honesty; coder-image hardening.

### Added

- **ADR 0006: ArtifactRegistry + ArtifactProjector plug-n-play framework.** Two architectural primitives mirror the existing `rendering/base.py::Renderer` per-subclass `_registry` model. `ArtifactRegistry.register("image")` decorates the dataclass for kind-discriminated serialize / deserialize. `<Projector>.register("image")` decorates a per-consumer projection handler. Three concrete consumers ship: `ContextAttachmentProjector` (badge DTO), `TextMarkerProjector` (token-counted text placeholder), `MessageBoxProjector` (TUI chip label). Adding a v1.19.x sub-agent artifact kind = decorate one new dataclass + one handler per consumer; zero reader edits. New files `ppxai/engine/artifact_registry.py`, `artifact_projector.py`, `artifact_projections.py`. Foundation work folded through Phases 1-7 across commits `b07bd0fa`, `fb46ee32`, `e91c71aa`, `676e0bec`, `a432f923`, `af63e482`, `02ef33ab`, `02d4e07a`, `4e93bf0b`, `21dd226d`.

- **`MarshallableArtifact` Protocol + 4 typed dataclasses** in `ppxai/engine/types.py`: `ImageAttachmentRef`, `PdfAttachmentRef`, `OfficeAttachmentRef`, `TextAttachmentRef`. `Message.attachments` is a sibling field next to `content` carrying engine-internal metadata that used to live inside `image_url` blocks. `engine.chat()` accepts an `attachment_refs` kwarg plumbed through from the server / TUI. Commit `57923452`.

- **Wire-format validator** (`ppxai/engine/uploaded_file.py::assert_wire_blocks_clean`) hooked into `BaseProvider._convert_messages`. Asserts that outbound `image_url` blocks carry ONLY spec keys (`{type, image_url}`) — engine-internal metadata is rejected at the wire boundary as a defensive sentinel. 20-case test suite in `tests/test_wire_block_validator.py`. Closes the class of bug where strict OpenAI-compat endpoints (corporate gateways, NIM, strict-validator vLLM) reject requests with *"Invalid chat format. Unexpected keys in a message content image dict."* Commit `1346e8c4`.

- **Cross-client warning when image attached to non-vision model.** Attach-time site (`commands/attach.py`) and send-time site (`server/routes/chat.py`) emit `Event(EventType.WARNING, ...)` with a unified render path so Rich, Textual, web, and VSCode all surface the same message. Closes the silent text-placeholder fallback that previously hid the routing bug. Commits `2887194a`, `b187fb5c`.

- **`/doctor probe` subcommand.** Opt-in network probe that hits each configured provider's `<base_url>/models` in parallel (2s timeout, max 8 concurrent), reads each model's `max_model_len`, and warns when `context_limit` exceeds the backend's actual cap (over-claim) or under-uses available headroom (under-claim). Default `/doctor` stays offline-fast. Commit `a4002844`.

- **Multi-resolution ICO favicon** (`ppxai/web/favicon.ico`, 110 KB, 6 sizes up to 256×256). `/favicon.ico` serves the .ico directly instead of redirecting to PNG; `index.html` keeps both `<link rel="icon">` entries for fallback. Commit `1507e5ca`.

- **`dgx-cluster` provider in coder cluster ConfigMap.** New PP=2 Qwen3.5-122B-A10B-NVFP4 at `dgx-cluster.trad.int/vllm/v1`. Native tool calling (qwen3_coder parser), prefix-caching, 128K max-model-len. Benchmark 2026-05-12 (native, no AGENTS.md): 76.2% (26/36) — +9pp over the prompt_based baseline (67.2%), with +34pp on `agentic_tool_loops` specifically. Side-by-side results in `benchmarks/llm-eval/results/dgx-cluster_*`. Commits `68624251`, `c7a35b01`.

- **Coder image rebuild + utility-tools expansion** (shipped 2026-05-13; see [docs/TODO-v1.18.6-coder-image-tools.md](docs/TODO-v1.18.6-coder-image-tools.md)). Stage-2 of `deploy/images/server/Dockerfile` now bundles `git jq yq curl wget ripgrep fd-find tree less unzip zip vim-tiny nano rtk` (~83 MB). Registry digest `sha256:80bed068...ab0cec`. `rtk hook check git status` returns the expected rewrite; wrapper-registry probe reports `is_available=True, is_active=True`. `gh`, `pwsh`, `kubectl`, `node`/`npm` deferred — install-on-demand snippets in the doc. Commits `e2737da4`, `9a9343ef`, `fe190b41`.

### Changed

- **Session JSON `schema_version: 2`** (`ppxai/engine/session.py`). Per-message `attachments` array serializes via `ArtifactRegistry`. v1 sessions auto-migrate on first load by a 1.18.6 build: text content + tool_calls + metadata preserved verbatim; image / uploaded_file blocks dropped with text placeholders pointing at a preserved `<name>.v1.backup/` sibling folder. Migration is idempotent and safe — `list_sessions()` filters out `*.v1.backup` entries so they don't pollute the session list. Pure-text v1 sessions migrate transparently on next save with no backup needed. **See `### Breaking` below for the multimodal-session consequence.** Permanent regression fixture at `tests/fixtures/sessions/v1_with_image/`. Commits `af63e482`, `02ef33ab`.

- **`image_url` content blocks now carry ONLY OpenAI-spec keys.** Before v1.18.6: `{"type": "image_url", "name": "shot.png", "file_id": "abc123", "image_url": {"url": "..."}}`. After: `{"type": "image_url", "image_url": {"url": "..."}}`. Engine-internal `name` / `file_id` live on `Message.attachments` as typed `ImageAttachmentRef` instead. Producers (`file_preprocessing.py`) and readers (`multimodal_ops.py`, `uploaded_file.py`) migrated through 7 ADR 0006 steps; legacy in-block keys produce no wire emission. Commit `21dd226d`.

- **Gemini 3.1 Flash Lite preview → GA.** Google announced retirement of `gemini-3.1-flash-lite-preview` on 2026-05-25. v1.18.6 renames to the GA identifier `gemini-3.1-flash-lite` across `model_deprecations.py`, `ppxai-config.json`, `ppxai-config.example.json`, `multimodal-api-models-reference.md`, and test assertions in `test_doctor.py` + `test_model_vision.py`. The wildcard `gemini-3.1-flash-lite*` glob in `model_profiles.py` already covered both names. Commit `6d319213`.

### Breaking

- **Multimodal v1 sessions lose in-conversation image rendering on migration to v2.** Original bytes are preserved at `<session>.v1.backup/<name>.<ext>` for forensic recovery, but in-app image display only works for v2 sessions saved by 1.18.6+. Pure-text v1 sessions are unaffected. Driven by ADR 0006's schema separation: legacy `{type: image_url, name, file_id, image_url}` blocks can't be losslessly reconstructed without an ArtifactRegistry kind for the missing dataclass shape, so the migration substitutes a text placeholder pointing at the backup folder.

### Fixed

- **`gpt-5.4-mini` registry gap routed images to text-placeholder fallback.** The default model since v1.17.4 had no entry in `BUILTIN_PROFILES`. `supports_vision()` returned False via the conservative default ⇒ screenshot attachments silently fell through to the text-placeholder branch in `file_preprocessing.py:309-325`. Fix: added `gpt-5.4-mini*` + `gpt-5.4*` glob entries to `BUILTIN_PROFILES`, cloned from the gpt-5.5/gpt-5.2 shape (supports_vision=True, tier A). Test parametrize extended to cover gpt-5.4 family. This bug is what motivated the ADR 0006 overhaul. Commit `e10e4847`.

- **Context indicator stale on provider/model switch.** Engine `provider_ops._apply_model_switch` now refreshes `context_percentage` against the new model immediately. Web `app.js:handleStateSync` and VSCode `chatPanel.ts:state:sync` handler both re-fetch `/context/info` when `provider` or `model` arrives via state_sync. Web `handleProviderChange` / `handleModelChange` also call `updateContextInfo()` + `updateUsage()` directly so the badge refreshes before any message is sent. Commits `a4002844`, `f5c84b7e`.

- **Web AppState re-anchors on provider/model dropdown change.** Selecting a different model via the dropdown previously left AppState's `cwd_anchor` pointing at the old session anchor until the next user message. Fix: `_reanchorFromServer()` fires from the dropdown-change handlers (cwd-anchor stays in sync the moment the model switches, not on the next turn). Commit `5f292725`.

- **Context-window over-claim (the 376% bug).** `_sync_usage_to_state` was treating cumulative session totals as per-turn token counts. After 16 turns on a 131K-cap model it reported 493K / 131K (376%). `session.update_usage` now passes the per-turn delta as a second positional arg; `client._sync_usage_to_state` uses delta for `_last_known_message_tokens` (the BPE token count of `session.messages` immediately after the turn). One-arg-listener back-compat preserved via `try/except TypeError`. Commit `70a0457f`.

- **Hard-coded `MIN_RESPONSE_TOKENS=2048`** in `openai_compat.py` ignored configured per-model `max_tokens`. New `_get_response_reservation()` returns `max(2048, configured_max_tokens)`, closing the spillover where ppxai admitted prompts vLLM rejected with HTTP 400. Commit `a4002844`.

- **chars/4 estimator under-counted code by 20-30%.** `get_context_info` now uses provider-reported `prompt_tokens + completion_tokens` as the authoritative baseline; chars/4 only fires for the suffix appended since the last usage event (typically the user's pending next message). Commit `a4002844`.

- **VSCode extension shipped without a gallery icon.** Pre-v1.18.6 extension had no top-level `"icon"` field in `package.json`, so VS Code rendered a generic Lego-brick placeholder in the installed-extensions list. Fix: wires `"icon": "resources/icon.png"` to the existing 128×128 RGBA chat-bubble asset (brand-consistent with the web favicon). Reload Window to see the icon. Commit `cfb1d4ae`.

- **`/tools enable` falsely reported "Tool support not available"** even when the active provider/model supported tools. Surfaced when the autodetected provider state lagged a `/use` switch. Commit `6fff861d`.

- **build-install skill: Windows `code.cmd` resolution.** The skill assumed `code` on PATH resolves to the CLI shim; on machines where it points to `Code.exe` (the GUI), `--install-extension` fails. Fixed to resolve `$env:LOCALAPPDATA\Programs\Microsoft VS Code\bin\code.cmd` directly. Skill commit `114d16f3`. Companion `adc3ce7f` version-pins the VSIX install to avoid multi-VSIX glob hazards.

- **Coder image TLS + rtk install.** Corporate `trad.int` TLS handshakes failed because the runtime stage had no CA bundle; `certifi`'s store also needed extending so the Python TLS stack could verify. Fix: install corporate CAs into `/usr/local/share/ca-certificates/`, run `update-ca-certificates`, append to `certifi`, set `SSL_CERT_FILE`. rtk install switched from `.deb` (glibc 2.36 incompatible with the base image's 2.39) to the musl static tarball. Commits `2206e212`, `117e2d56`, `9a9343ef`.

### Tests

3695 pass, 2 skipped on macOS. New ADR 0006 sentinel suites: 39 cases in `test_artifact_registry.py`, 30 in `test_artifact_projector.py`, 9 in `test_session_schema_v2.py`, 9 in `test_v1_session_migration.py`, 20 in `test_wire_block_validator.py`. Zero regressions across the 17 reader/producer-affected suites under the ADR 0006 migration. The 2 macOS skips are `tests/test_gemini_extras.py` (conditional on `google-genai` install). Windows runs additionally skip the 11 `@_unix_only`-marked tests in `test_server_state.py` (TestKillPreviewBackend + TestKillPreviewBackendDrainTask) because they mock Unix-specific `os.getpgid` / `os.killpg`.

## [1.18.5] - 2026-05-10

Branch: `feature/v1.18.5`. Theme: shell wrapper framework — a generic
JSON-driven extension surface for transparent CLI proxies on the shell
tool, with rtk (Rust Token Killer) shipping as the first concrete wrapper.

### Added

- **Shell wrapper framework** in `ppxai/engine/tools/wrappers/`. Generic factory + registry + base classes for transparent shell-command wrappers. Two integration layers: (a) engine-side rewrite at `engine/tools/builtin/shell.py:319` calls `WrapperRegistry.find_first_rewrite()` before spawning the subprocess and uses the rewritten form on first match; (b) system-prompt hint via `manager.py::get_tools_prompt` calls `WrapperRegistry.compose_prompt_blocks()` to inject per-wrapper markdown sections under a single `## Shell wrapper context` header. Two generic concrete classes cover every realistic wrapper without per-wrapper Python: `ProbeWrapper` (calls a dry-run command like `rtk hook check <cmd>` and parses exit code + stdout) and `AlwaysWrapper` (no dry-run; prefixes every command with a fixed string — for `time`, `nice`, perf profilers). Bespoke wrappers can subclass `Wrapper` directly and register a new `type` value in `factory._TYPE_REGISTRY`. Thread-safe lazy init: `threading.Lock` around the registry singleton + each wrapper's PATH-resolution cache, so future sub-agent worker threads (planned for v1.19.x ADR 0003 Stage 2) won't race the check-then-create pattern.

- **rtk as the first concrete wrapper.** Ships in `DEFAULT_SHELL_WRAPPERS` (`ppxai/config/defaults.py`) as a `type: "probe"` config entry — identical schema to anything a user adds. No privileged Python class for rtk; future rtk-specific tuning becomes config fields the framework consumes generically. Default `enabled: "auto"` — wrap silently when rtk is on PATH; users who installed rtk likely want the savings. Real-world reference numbers from prior rtk integrations: 47% savings on Windows manual mode (1355 commands), 66% on Unix bash hook (4338 commands). The integration degrades gracefully — without rtk on PATH, behavior is byte-identical to v1.18.4.

- **Read-only git and gh verbs in `DEFAULT_ALLOWED_COMMANDS`.** Surfaced from v1.18.5 dogfooding: `git status` was triggering `Risk Level: DANGEROUS` consent prompts because no git/gh patterns existed in the allowed list — every git command (read-only or write) fell through to the unknown-command-is-dangerous default. Added conservative regex patterns for read-only git verbs (`status`, `log`, `diff`, `show`, `branch`, `blame`, `describe`, `rev-parse`, `rev-list`, `ls-files`, `ls-tree`, `reflog`, `shortlog`, `cat-file`, `grep`, `whatchanged`, `stash list`, `remote -v`, `config --get|--list`, `tag -l`) and read-only gh verbs (`auth status`, `<noun> view|list|status` for the standard nouns). Mutating verbs (`commit`, `push`, `reset`, `rebase`, `checkout`, `merge`, `fetch`, `pull`, `stash` without `list`, `tag <name>`) stay DANGEROUS so the user reviews before they fire.

- **Transparent-prefix safety stripping.** The consent classifier's `classify_shell_command` now strips leading wrapper tokens via `WrapperRegistry.strip_transparent_prefixes()` before pattern matching, so safety verdicts are invariant under wrapping. A user (or model) typing `rtk git status` directly classifies the same as `git status`. Only **active** wrappers with `transparent_for_safety: true` license stripping; inactive wrappers and non-transparent wrappers (a hypothetical sandbox where you DO want consent on the wrapped form) are left alone. Stacked wrappers strip in order: `time rtk git status` → strip `time` → strip `rtk` → classify `git status`.

- **Sentinel test suite for the wrapper framework** (`tests/test_wrapper_framework.py`, 49 cases). Base class detection caching + thread-safety (8-thread race test on `is_available()`); `is_active` gating across `auto` / `always` / `never`; failure-marker heuristic. ProbeWrapper happy / sad / spawn-error / timeout / quoted-args paths. AlwaysWrapper happy / unavailable / empty-prefix-rejected. Factory dispatch on `type` field, required-field validation, prompt-block path resolution from package data and absolute path. Registry first-match-wins, exception swallowing, prompt-block composition (active wrappers only), transparent-prefix stripping (single + stacked + inactive-skipped), thread-safe singleton lazy init. Config integration: `_resolve_wrappers` merges defaults + user entries by name, legacy `use_rtk` / `use_rtk_prompt_hint` shim, malformed entries skipped.

- **Sentinel test suite for shell-command safety classification** (`tests/test_consent_classification.py`, 70 cases). Read-only git verbs (28 commands) are SAFE; mutating git verbs (13 commands) stay DANGEROUS; read-only gh verbs are SAFE. Transparent-prefix stripping integration: `rtk git status` classifies SAFE; inactive wrappers don't license stripping; stacked transparent wrappers strip in order; safety invariant under wrapping (read-only stays SAFE, dangerous stays DANGEROUS, never stays NEVER). Pre-v1.18.5 patterns (`ls`, `cat`, `pwd`, `rm`, `sudo`, `rm -rf /`) keep their verdicts.

- **User-facing docs** at [docs/shell-wrappers.md](docs/shell-wrappers.md): framework overview, "how to add a wrapper" recipe, schema reference, decision rules, safety-classification interaction, rtk install + config, troubleshooting. Plan / acceptance / settled-decisions doc at [docs/TODO-v1.18.5-shell-wrappers.md](docs/TODO-v1.18.5-shell-wrappers.md).

### Changed

- **Back-compat shim for rtk-specific config fields.** `tools.shell.use_rtk` (string) and `tools.shell.use_rtk_prompt_hint` (bool) — fields that briefly existed in earlier `feature/v1.18.5` iterations — are translated internally into the rtk wrappers entry's `enabled` and `prompt_block_path` fields. Plan to retire the shim in v1.20.x. New configs should use `tools.shell.wrappers: [...]` directly.

### Tests

3219 pass, 2 skipped. New: 49 framework tests + 70 consent classification tests. Pre-v1.18.5 sentinel suites green: `test_cwd_grounding` 13/13, `test_command_result_serialization` 87/87, `test_shell_tool` 32/32, `test_common_consent` 9/9.

### Phase 4 deferred

Graceful fallback (retry raw command on detected wrapper-side breakage) is wired-but-dormant: the framework has the hooks (`failure_markers`, `retry_raw_on_failure`, `Wrapper.is_wrapper_side_failure()`, `WrapperRegistry.find_active_wrapper_by_prefix()`), but the post-spawn detect-and-retry logic in `shell.py` is deferred until there's evidence of wrapper-side failures in real use. Adding it later is a localized edit (~15 LoC + 6 tests) plus populating `failure_markers` on the rtk default config entry.

## [1.18.4] - 2026-05-10

Branch: `bugfix/v1.18.4`. Scope: post-v1.18.3 fixes only — no new
features. The v1 API gateway shape (`POST /v1/oneshot`, bearer-token
auth) is load-bearing for ppxai-sre's outlook-monitor agent, so
preserve it byte-identical.

### Fixed

- **`scripts/release.py::wait_for_ci` no longer trusts stale completed runs.** Surfaced by the v1.18.3 release tag-cycle: after `--redo` deleted the broken tag and re-pushed, `wait_for_ci` polled `gh run list` during the brief window when GitHub had not yet registered the new run. Only the OLD failed run from the previous tag-cycle was visible; the previous logic accepted its `conclusion="failure"` as authoritative — returning False before the new run started. The script then jumped to `publish_release_notes` which exhausted its 12 retries against a release object that didn't yet exist (CI's release job hadn't run because `wait_for_ci` wrongly declared CI failed). Real CI for the v1.18.3 redo finished successfully and created the release with all 20 assets — the script's exit-status was a false-negative. Fix: NEVER trust a "completed" status until we have observed the run go through "queued" or "in_progress". Treat both stale success and stale failure as untrustworthy and keep polling. The notes-publishing race is fixed transitively. +7 tests in `tests/test_release_wait_for_ci.py`. (commit `dc21c87f`)

- **Web/VSCode renderers now show full `/ls` listings (and any `DirectoryListingResult`/`DirectoryTreeResult` payload).** Surfaced from a v1.18.3 user report: typing `/ls` in the web UI returned only "44 items in /Users/rado/git/exps" — the `result.message` — instead of the actual rows. Two related root causes: (1) Web/VSCode renderers dispatch on the wire `result.type` STRING, not Python class hierarchy. `DirectoryListingResult` is a Python `TableResult` subclass, so its serialized type is `"DirectoryListingResult"` — without an explicit handler, dispatch fell through to the unknown-type fallback that shows only `result.message`. The Python docstring's claim "Renderers that handle TableResult automatically handle this" was true for Rich/Textual (class-based dispatch) but false for the HTTP renderers. (2) `TreeResult` had NO `to_dict()` override at all — it inherited `CommandResult`'s base which only emits `type/status/message/metadata`. The `root` tree was silently dropped on the wire. Same class of bug as `CompositeResult.to_dict()` fixed in v1.18.3 (commit `848b4d99`). Fix: explicit handlers in both renderers + `TreeResult.to_dict()` override. +12 tests in `tests/test_directory_result_renderers.py`. (commit `462e6739`)

- **Systemic `to_dict()` and renderer-dispatch audit closed.** The `/ls` symptom was the canary for a deeper bug. A scan of `ppxai/commands/results.py` confirmed 10 more `CommandResult` subclasses with the same `to_dict()` gap and 6 with the same renderer-dispatch gap (some overlapping). Mode A (dropped fields) added `to_dict()` overrides on: `NotificationResult` (`auto_dismiss`), `AIResponseResult` (`content`, `code_blocks`), `ListResult` (`items`), `FileViewResult` (6 fields), `MarkdownResult` (`filepath`, `content`), `ImageResult` (3 fields), `PreviewResult` (`filepath`, `url`), `ProgressResult` (`current`, `total`, `description`), `DiffResult` (`files`, `summary`), `ConsentResult` (4 fields), `PromptResult` (4 fields), `ToolExecutionResult` (6 fields incl. nested `to_dict()` for `artifacts` like `CompositeResult.results`), `TextResult` (`error_details`). Mode B (renderer falls through) added explicit handlers on web (`ppxai/web/shared/result-renderer.js`) and VSCode (`vscode-extension/src/commandRenderer.ts`) for: `AIResponseResult`, `ProgressResult`, `DiffResult`, `ConsentResult`, `PromptResult`, `ToolExecutionResult`. (commit `1a81cb09`)

- **Linux-only SIGTERM bug in shell tool interrupt path.** Caught by CI on the v1.18.3 release tag — pre-tag local macOS run passed, post-tag Linux CI failed (`test_interrupt_terminates_running_subprocess` took the full 30s sleep instead of the expected <5s). The v1.18.3 async-shell-tool work spawns commands via `asyncio.create_subprocess_shell(..., start_new_session=True)`. The OS process tree is `/bin/sh -c "<command>"` → `<actual command>`. Calling `proc.terminate()` only sends SIGTERM to the shell wrapper; the child inherits the wrapper's stdout/stderr file descriptors, so even after the wrapper exits the FDs remain open in the child. `proc.communicate()` keeps waiting on EOF — i.e. for the child's natural timeout — instead of returning when the wrapper dies. macOS happens to behave differently for orphan-with-inherited-FDs so the test passed locally. Fix: send SIGTERM to the whole process group via `os.killpg(pgid, ...)` so both wrapper and child receive the signal. New helpers `terminate_subprocess_tree(proc)` and `kill_subprocess_tree(proc)`; `interrupt_stream` and the timeout/cancel paths in shell.py use them. (commit `0500d56f`)

- **`list_directory` tool now echoes the resolved path in its header.** Reported 2026-05-04 from the web UI: after `/cd ppxai_demo`, asking the model "ls" produced `"/Users/rado/git/exps contains the files and folders listed above"` — the PARENT of the actual working dir. Root cause: the tool returned bare item names (e.g. `DIR foo\nFILE bar`) with no path header. The model called the tool with `path="."` (default) and had no way to know which directory it just listed, so it confabulated a path in its response. Fix: prefix the resolved absolute path in the tool's output (`Listing of /path:` / `Long-format listing of /path:`). Empty directories still emit the header followed by `(empty)`. +8 tests in `tests/test_list_directory_tool.py`. (commit `ee90bff4`)

- **Cwd-grounding pass across cwd-relevant tools.** The `list_directory` symptom was the canary for a deeper class of bug. Audit of every cwd-relevant tool found 7 more sites where output didn't ground the model in observable facts. The v1.18.x AppState→client→UI sync invariant DID hold (the system prompt at `tools/manager.py:357` correctly includes `**Current Working Directory:** /path`), but the LLM doesn't always obey the system prompt. Defense-in-depth: tool outputs are what the model summarizes from, so put the truth there too. Mode A (output lacks cwd grounding) — `ShellExecuteTool` foreground commands now prefix `[cwd: /path]\n` (or `[cwd: /path, exit: N]\n` on non-zero); stderr-only commands like `gh auth status` get explicit `--- stderr ---` separator even when stdout is empty so the model can tell the source. `SearchFilesTool` zero-match and match paths now prefix `Searched for '<pattern>' in <dir>:`. `DisplayFileTool` success message uses resolved absolute path instead of basename. Mode C (success message uses input arg, not resolved path) — editor tools `ApplyPatchTool`, `ReplaceBlockTool`, `InsertTextTool`, `DeleteLinesTool` now quote the resolved absolute `path` instead of the input `file_path` (often a relpath like `foo.py`); without the fix, after several edits across `/cd` boundaries the model could lose track of which on-disk file it actually wrote. System prompt strengthened from "do NOT rely on previous tool results" to "**This cwd is the ONLY source of truth for your current location.** ... When summarizing tool output that references a path or directory, verify against the cwd above before quoting any other path. If a tool's output starts with a header like `Listing of /path/to/dir:` or `[cwd: /path/to/dir]`, quote that path verbatim — do not substitute a path from memory." (commit `1a301d4e`)

### Added

- **Sentinel test suite for CommandResult serialization** (`tests/test_command_result_serialization.py`, 87 parametrized cases). Walks `CommandResult.__subclasses__()` recursively and asserts: (1) every dataclass field appears in the result of `to_dict()`, with a copy-pasteable override stub in the failure message; (2) the wire-format `type` field is the concrete subclass name (renderer dispatch key); (3) every subclass has an explicit handler in `result-renderer.js` (or appears in `_SIDE_EFFECT_DRIVEN` opt-out for types that ride a side-effect kind); (4) every subclass has a case branch in VSCode's `commandRenderer.ts` switch. Plus tests that nested-result containers (`CompositeResult.results`, `ToolExecutionResult.artifacts`) recurse via the children's own `to_dict()`. The class of bug that hit us 13 times historically (CompositeResult v1.18.3, TreeResult + DirectoryListingResult/DirectoryTreeResult v1.18.4 first pass, then 10 more this branch) is now structurally caught at PR-time, not in production.

- **Cwd-grounding sentinel test suite** (`tests/test_cwd_grounding.py`, 13 cases). Pins every cwd-relevant tool's output shape: `list_directory` header, `search_files` searched-dir grounding, `execute_shell_command` `[cwd: /path]` header (with non-zero exit code variant + stderr-only separator), `display_file` resolved-path message, all four editor tools' success messages quoting the resolved absolute path. Plus a programmatic verification of the v1.18.x AppState→prompt sync invariant: `test_tools_prompt_includes_current_working_directory` asserts `Current Working Directory: /path/after/cd` appears in the system prompt verbatim AND the strengthened "ONLY source of truth" instruction is present. Next time anyone reports "the LLM doesn't know my cwd," running these tests instantly distinguishes "the prompt is wrong" (test fails → bug in our sync layer) from "the LLM didn't obey" (test passes → model issue, not infra).

## [1.18.3] - 2026-05-03

### Added

- **NVIDIA NIM provider goes first-class.** `ppxai-config.json` and `ppxai-config.example.json` ship a `nvidia` provider entry pointing at `https://integrate.api.nvidia.com/v1` with 12 curated models (NVIDIA-portal-recommended per-model `generation_params` — temp varies 0.2–0.7, top_p 0.8–0.95). Native tool calling default; `qwen2.5-coder-32b-instruct` overrides to `prompt_based`. Tier A 36-test benchmark sweep (2026-05-01) on the four healthy models: `qwen/qwen3.5-122b-a10b` 77.4% (best overall), `qwen3-next-80b-thinking` 76.6%, `qwen3-next-80b-instruct` 68.3%. The `qwen/qwen3-coder-480b` 19% result was rate-limit-contaminated on free tier — see Item 17 in [DEBT-INVENTORY-v1.18.3.md](docs/archive/DEBT-INVENTORY-v1.18.3.md).
- **`EventType.PROVIDER_THROTTLED` typed event.** New event distinguishes provider-side rate-limit / quota errors (HTTP 403 / 429) from generic model failures. `BaseProvider._classify_throttle()` produces a structured `{status_code, provider, model, message, retry_after}` payload. `openai_compat.py` emits `PROVIDER_THROTTLED` instead of `ERROR` when classification matches; `chat.py` treats both events identically on the abort path but tags `reason="provider_throttled"` in `AGENT_RUN_ERROR` so post-mortems can distinguish quota blocks from genuine failures. `_format_error()` 403 branch refined: NIM's "Operation not allowed" body produces "Provider quota / permission error... wait, switch model, or use paid tier" instead of a generic API-error wrapper. ppxaide TUI's `stream_handler.py` maps the new event onto `ENGINE_ERROR` with a dict-aware unwrap so the user sees the recovery hint, not the raw payload dict. (Tier 1 #2)
- **`extra_body` config pass-through.** New `ppxai/config/providers.py::get_extra_body()` resolves a per-provider / per-model `extra_body` dict (provider defaults, model overrides win on conflict; `__comment_*` keys stripped). `BaseProvider._get_extra_body()` is a thin instance wrapper. `openai_compat.py` forwards via `client.chat.completions.create(extra_body=...)` only when non-empty (empty dict skipped to avoid breaking strict endpoints). Unblocks Qwen3.5 / GLM `chat_template_kwargs.enable_thinking` toggle without forking the engine; future-proofs for vLLM-only parameters and other vendor-specific runtime knobs. (Tier 1 #1)
- **Seven `ModelProfile` entries for namespaced NIM IDs.** `*/qwen3-coder-480b*` (Tier S, parallel_tool_calls), `*/qwen3.5-122b*` (Tier A — NIM benchmark 77.4%), `*/qwen3.5-397b*` (Tier B provisional), `*/llama-3.3-nemotron*` (Tier B, supports_reasoning), `*/mistral-large-3*` (Tier B), `*/devstral-2*` (Tier B). Pre-fix, the existing `qwen3-coder*` (no leading `*/`) only matched non-namespaced IDs, so `qwen/qwen3-coder-480b-a35b-instruct` fell back to default. Sentinel test class `TestNvidiaNimProfiles` in `tests/test_model_profiles.py`. (Tier 1 #3)
- **`reasoning_trigger` per-model in-prompt marker.** NVIDIA's `nvidia/llama-3.3-nemotron-super-49b-v1.5` toggles reasoning via `/think` (enable) or `/no_think` (disable) appended to the system message — distinct from `chat_template_kwargs.enable_thinking` (Qwen3.5 / GLM go via `extra_body`). New `get_reasoning_trigger()` config helper + `BaseProvider._apply_reasoning_trigger()` appends the marker to the FIRST system message, idempotent (skipped when already present); when no system message exists, one is prepended carrying just the trigger. nemotron config has `"reasoning_trigger": "/think"` so reasoning fires by default. (Tier 2 #4)
- **Provider-error telemetry in `usage_stats`.** `UsageStorage.record_provider_error(provider, status_code, model)` persists a counter to `~/.ppxai/usage/usage.json` under a new `provider_errors` key (`{count, last_seen, models[]}` per `provider:status_code`). `openai_compat.py` fires it from the `_classify_throttle` path. Best-effort persistence — failures logged at DEBUG and ignored, never breaks chat. Backward-compatible with pre-v1.18.3 usage files. Surfaces "NIM returned 12 quota errors today" without re-running benchmarks; `/usage` rendering is debt Item 16 (data accumulates from v1.18.3 onward, no rendering surface yet). (Tier 2 #5)
- **`nvidia:` provider_hint block in `AGENTS.md`** (repo + home) — runtime guidance for models served via NIM: native tool calling, no-loop on "Operation not allowed" 403, free-tier quota awareness, batched chains for long agentic work.
- **41 new tests across 5 files (NIM Tier 1 + Tier 2).** `tests/test_model_profiles.py::TestNvidiaNimProfiles` (8 sentinels), `tests/test_provider_throttle.py` (9 classification + message-format tests), `tests/test_extra_body.py` (7 config-layer + provider-wiring tests), `tests/test_reasoning_trigger.py` (9 config + helper tests), `tests/test_usage_provider_errors.py` (8 persistence + backward-compat tests).
- **Cross-provider gap-fill — extends throttle telemetry + `extra_body` to Perplexity, OpenAI-native, Gemini-native.** The NIM Tier 1/2 helpers were designed provider-agnostic but only wired into `openai_compat.py`, so a 429 from any other provider used to emit generic `ERROR` and never increment the persistent `provider_errors` counter. v1.18.3 wires them all through the same contract — Perplexity (both stream paths + `chat_sync_simple`), OpenAI-native (Chat Completions API + Responses API), Gemini-native (custom `_classify_throttle` for `google.genai.errors.APIError` since the base only knows about `openai.APIStatusError`). Reasoning trigger remains NIM/openai-compat-only (no fit elsewhere). +29 tests across `test_perplexity_extras.py` (7), `test_openai_native_extras.py` (11), `test_gemini_extras.py` (11).
- **Version-string drift collapse — 13 patch points → 3 SoTs + sentinel test.** Pre-2026-05 the release script mechanically patched 13 places per release. Reliable inside `/release`, but leaves 13 drift points open *between* releases. v1.18.3 collapses to 3 SoTs (`pyproject.toml`, `ppxai/version.py`, `vscode-extension/package.json`) plus 1 derived (`package-lock.json`) and 2 shields.io badges. Retired locations now read from `ppxai.__version__` at runtime (`event_handler.py`, `logger.py`), link to `releases/latest` in markdown (CLAUDE.md, ROADMAP.md, AGENTS.md, docs/README.md), or use a `<version>` placeholder (READMEs). New `tests/test_version_consistency.py` (14 tests) enforces parity on every commit — drift becomes a CI failure on the contributing PR. `scripts/release.py` slimmed accordingly: `VERSION_FILES` 6 → 3, `VSIX_FILES` + `update_vsix_references` removed, `update_claude_md` / `update_agents_md` / `update_docs_readme` removed. `scripts/validate-release.py` 14 checks → 6 + accepts `unreleased` CHANGELOG placeholder during dev.
- **Engine resilience for live preview workflow.** Three independent fixes from a real demo-app debugging session: (a) **async + cancellable shell tool** (`a746a7c6`) — `subprocess.run` (sync) → `asyncio.create_subprocess_*` so the event loop keeps servicing `POST /interrupt` while a tool runs; trailing `&` / `nohup` detected → `stdin/stdout/stderr=DEVNULL` + `start_new_session=True` so backgrounded uvicorn can't deadlock the captured pipes for 300s. New `_active_subprocesses` registry on `EngineClient` (with `register_subprocess` / `unregister_subprocess` on `ToolEngineProtocol`); `interrupt_stream()` SIGTERMs them. +7 tests. (b) **`CompositeResult.to_dict()` override** (`848b4d99`) — the inherited path emitted only `type/status/message/metadata` and silently dropped the `results` list, so any `/usage` after a NIM throttle was recorded delivered an empty container to web/VSCode. Override recursively serializes each sub-result via its own `to_dict()`. (c) **`/preview` flag wiring** (`61240f0d`) — `--serve [cmd]`, `--proxy port`, `--port N` advertised in `web/shared/commands.js` since v1.17.1 but never reached `handle_preview`; the literal flag string was being resolved as a filepath. New shlex-based `_parse_preview_args`. Web's `open_html_preview` dispatches on `mode` → `openServedPreview` / `openProxiedPreview` / static iframe path; backwards-compatible with the legacy `{served, proxied}` boolean shape. +18 tests.
- **`prompt_text` SideEffectKind** (`74afd5a2`) — companion to v1.18.1's `prompt_quick_pick` for free-text follow-ups when the answer isn't from a finite set. Wire shape `{kind, title, question, command_to_resume, original_args, placeholder}`. Resume protocol mirrors quick-pick (no server continuation state): client re-issues `POST /command/<command_to_resume>` with `args = "<original_args> — <reply>"` (em-dash separator). Web → inline form rendered as a system message. VSCode → `vscode.window.showInputBox({prompt, placeHolder})`. TUI ignores the kind (open-enum invariant); the accompanying `NotificationResult` text serves as the user-visible nudge. First user: `validate_agent_task` rejection — `/agent fix` now auto-resumes the elaboration from web/VSCode without retyping the slash command. +8 tests across `tests/test_prompt_text_side_effect.py`. Closes [docs/archive/TODO-v1.18.2-prompt-text-kind.md](docs/archive/TODO-v1.18.2-prompt-text-kind.md).
- **`POST /v1/oneshot` — first endpoint of a new v1 API gateway tier** (`38c2743d`). Stateless single-turn LLM call — no session, no streaming, no history. Designed for external agents (classifiers, routers, structured-extraction pipelines) that want ppxai-server as a thin LLM gateway without managing sessions per call. `OpenAICompatibleProvider.oneshot()` builds messages, applies `_apply_reasoning_trigger`, forwards `extra_body` from config (so vendor knobs like NIM `chat_template_kwargs.enable_thinking` carry through). Request-level `response_format` / `max_tokens` / `temperature` win over per-model config. Returns `{content, finish_reason, model, provider, usage}`. v1 supports `OpenAICompatibleProvider` (covers `local`, `custom`, NIM, vLLM, Ollama, OpenRouter); native OpenAI / Perplexity / Gemini providers grow `oneshot()` in subsequent releases. +14 tests.
- **v1 API gateway tier with semver-style stability commitments.** Two-tier separation: `/v1/<endpoint>` is the stable external-facing surface; `/<endpoint>` (no prefix) is internal and evolves with ppxai's own clients. Required fields don't disappear, new optional fields can be added, documented status codes are stable. Breaking changes ship as `/v2/<endpoint>` with a deprecation window. New [docs/api-gateway.md](docs/api-gateway.md) documents the policy, threat model for auth, deployment-shape table, and the future direction (multi-token `/v1/tokens` registry, OIDC/JWT validation under `/v1/auth/...`).
- **Bearer-token auth middleware** (`9953b1df`) — opt-in via `PPXAI_API_TOKEN` env var; default off so localhost desktop UX is unchanged. When set, every non-OPTIONS request needs `Authorization: Bearer <token>` matching the value or gets `401` with `WWW-Authenticate: Bearer realm="ppxai"`. Token read on every request (rotation friendly). Empty / whitespace values treated as auth disabled (prevents lockout from a stray empty config). CORS preflight exempted (browsers don't send Authorization on OPTIONS by spec). Authorization scheme parsed case-insensitively per RFC 7235. Single shared token in v1; multi-token registry under `/v1/tokens` and OIDC/JWT direction documented as future work. +19 tests across `tests/test_auth_middleware.py`.
- **Release tooling closure** (`f82c9878`) — three confirmed defects from `docs/archive/TODO-release-tooling.md`: (a) `wait_for_ci` filters `gh run list --workflow="Build Executables"` so faster concurrent workflows on the same tag (Deploy Documentation, etc.) can't satisfy the gate prematurely (defect #1). (b) `.nvmrc` pins Node 20 to match CI — local test runs that shell out to node match the CI version by default, preventing the next "passes locally, fails in CI" cross-language drift (defect #3 generalisation). (c) `tests/test_release_dry_run.py` (3 tests) pins `merge_to_master_if_needed(..., dry_run=True)` invokes zero subprocess calls + sanity test that `dry_run=False` still calls git (defect #2 acceptance). Closes [docs/archive/TODO-release-tooling.md](docs/archive/TODO-release-tooling.md).

### Changed

- **Release pre-flight green during dev.** `validate-release.py` now accepts either `## [X.Y.Z] - YYYY-MM-DD` or `## [X.Y.Z] - unreleased` as a valid CHANGELOG entry. `release.py` substitutes `unreleased` → today's date as a release-time step (`update_changelog_date`), so the released artifact still carries the actual ship date. Idempotent re-runs are safe.
- **Agent-loop unification TODO re-scoped** (`6f1201ef`) based on 2026-05-03 code investigation. Original premise was partly outdated: `AGENT_BEAT` / `AGENT_RUN_*` events already fire from `engine/chat.py`; web doesn't run a client-side loop (sends `/agent <task>` to `/chat` which gates with `validate_agent_task`); only VSCode's `chatPanel.ts::handleAgentCommand` is the real divergence (~150 LoC). The outer multi-iteration continuation loop in `handle_agent` is meta-orchestration on top of `chat_with_tools`'s inner tool loop. Two design questions named: (A) does the outer loop earn its keep on modern frontier models? (needs instrumentation data, not opinion) (B) where should it run? Now superseded by [ADR 0003](docs/decisions/0003-agent-platform-architecture.md).
- **CLAUDE.md slim 59 KB → 17 KB** (`8a899051`) — Claude Code emits a "large CLAUDE.md will impact performance" warning at 40 KB. Long-form pattern docs extracted to `docs/patterns/*.md` (transactional-state, protocol-dependency-inversion, appstate, command-envelope, state-sync-determinism), `docs/dev-setup.md` (uv resolution, Windows Store Python recovery, PyInstaller flow, corporate-proxy TLS notes), `docs/ppxaide-impl.md` (Textual TUI internals + terminal images), `docs/vllm-notes.md` (Hermes vs Harmony cheat sheet; defers depth to existing `vllm-tool-calling-guide.md`). CLAUDE.md retains project overview, pattern bullet-list with links, codebase stats, install-location table, file tree, common commands, release process summary, key design decisions, "Verify, Don't Assume" rule, commit guidelines, graphify section.

### Internal

- **Sentinel test caught a missing dispatcher entry.** `tests/test_stream_handler_dispatch.py::test_every_event_type_is_covered` flagged the new `EventType.PROVIDER_THROTTLED` as missing from `stream_handler.py::EVENT_MAP`. Fixed by mapping it to `ENGINE_ERROR` (chat.py treats them identically) + dict-aware unwrap in `on_engine_error` so users see the recovery hint instead of the raw payload dict. The drift test did its job — added without it, ppxaide would silently log "Unhandled event type" warnings on every NIM 403.
- **Version-consistency sentinel verified end-to-end.** Synthetic drift test (mutate `ppxai/version.py` to "9.9.9" and re-run the sentinel) confirms CI catches the regression.
- **DEBT-INVENTORY-v1.18.3.md filed with 4 new items** (16: `/usage` throttle display, 17: 480b paid-tier rerun, 18: kimi/deepseek/397b probes, 19: example `extra_body` wiring) plus 5 carried over from v1.18.2 (Items 3, 12, 13, 14, 15). All v1.18.3-introduced debt items closed in-branch (Tier 1 #1-3, Tier 2 #4-5, Items 12, 13, 15, 16, 17, 18, 19).
- **Test count: 2866 collected, 9 skipped** (was 2785 at branch start → +81 across the full v1.18.3 scope). Distribution: 41 NIM Tier 1+2 + 29 cross-provider + 14 version-consistency + 25 engine resilience + 8 prompt_text + 14 oneshot + 19 auth + 3 release dry-run.

### Docs

- New [docs/release-notes-v1.18.3.md](docs/release-notes-v1.18.3.md) covers all ten themes.
- New [docs/DEBT-INVENTORY-v1.18.3.md](docs/archive/DEBT-INVENTORY-v1.18.3.md) (now archived; current debt lives in [docs/debt-inventory.md](docs/debt-inventory.md)).
- New [docs/api-gateway.md](docs/api-gateway.md) — v1 gateway policy, threat model for auth, deployment-shape table, future-direction sketch for multi-token registry / OIDC.
- New `docs/patterns/*.md` — five extracted architecture pattern docs (linked from CLAUDE.md): transactional-state, protocol-dependency-inversion, appstate, command-envelope, state-sync-determinism.
- New `docs/dev-setup.md`, `docs/ppxaide-impl.md`, `docs/vllm-notes.md` — extracted from CLAUDE.md.
- New [ADR 0003 — Agent platform architecture](docs/decisions/0003-agent-platform-architecture.md) (Status: Proposed). Captures the design space for sub-agents and autonomous (long-running) agents. Three-stage path: Stage 1 instruments outer-loop firing rate; Stage 2 builds `AgentRunRegistry` filesystem layout + background-task agent runs (closes the agent-loop unification TODO as a side effect); Stage 3 ships `spawn_subagent` built-in tool.
- New [ADR 0004 — LLM gateway features](docs/decisions/0004-llm-gateway-features.md) (Status: Accepted). Retroactive rationale for the v1 gateway shipped this release. Three sub-decisions accepted (path-versioned `/v1/...`, stateless `oneshot` bypassing `EngineClient`, opt-in single-token auth) with six "why this not that" alternatives explicitly considered and rejected.
- [CLAUDE.md](CLAUDE.md) "Files Updated by Release Script" table slimmed from 12 rows → 6 to reflect the new SoT layout. "Current Version" header replaced with link to `releases/latest`. ROADMAP.md / AGENTS.md / docs/README.md similarly slimmed.

## [1.18.2] - 2026-04-29

### Added

- **Tier 1 observability pass.** Three production silent paths gained log lines so the next investigation isn't blind:
  - `POST /command/{name}` now emits `HTTP POST /command/{name} from session={id} args={preview}` (INFO) plus `ok` + side-effect count (DEBUG) and a WARNING for unknown commands. Args truncated to 120 chars so noisy `/agent` prompts don't dominate the log. Pre-v1.18.2, the canonical v1.18.1 dispatch path was invisible — the exact regression the unification was built to detect would have slipped through silently. (Item 7)
  - `GET /state` now emits `HTTP GET /state from session={id}`. Pre-fix, the route was silent — a 21-min webapp session showed zero observable `/state` hits despite 5 provider switches and likely focus changes; we couldn't tell whether visibilitychange / focus re-anchor was broken or just silent. Wiring verified byte-identical between deployed `~/.ppxai/web/app.js` and repo source. (Item 9)
  - Version banner build-info injection. `version.py::_build_info()` checks for an optional `ppxai/_build_info.py` (gitignored, written by new `scripts/write_build_info.py` from current git state) before falling back to runtime probes. PyInstaller binaries can now report real commit + build-time UTC instead of "n/a, n/a". Wiring into release tooling deferred — mechanism is ready, integration is one line. (Item 8)
- **`EngineClientProtocol` in `ppxai/engine/types.py`.** Enumerates ~30 properties/methods commands actually call on the engine, grouped functionally (AppState access, provider/model switching, working dir, tools/agent management, bootstrap/context, checkpoints, chat). `commands/protocol.py` and `commands/context.py` now type against the protocol; both files dropped `from ..engine.client import EngineClient`. Sentinel tests in `tests/test_engine_client_protocol.py` pin: real `EngineClient` satisfies the protocol structurally (`isinstance` runtime check), no inheritance, neither file imports the concrete class. **Verified via graphify rebuild:** `protocol.py` → `EngineClient` edges 21 → 4 (~80% reduction); total `EngineClient` inbound 56 → 39. (Item 10)
- **VSCode extension bundled via esbuild.** New `vscode-extension/esbuild.js` (cross-platform, pure Node). `npm run typecheck` (tsc --noEmit) + `npm run package` (esbuild --production) replace the prior `npx tsc -p ./` flow. `vscode:prepublish` runs the production bundle so `vsce package` always ships minified. `.vscodeignore` rewritten to ship `dist/` + `media/` + `resources/` only. CI gains a 500 KB VSIX size-budget gate to catch accidental bloat. **Results: 1.1 MB → 128 KB VSIX (−88%); 804 → 15 files (−98%); `vsce package` warning gone.** (Item 5)
- **Contract-based `resolveWebviewView` refactor.** The 98-line monolith in `vscode-extension/src/chatPanel.ts` (criticality 0.723 in the gpt-5.5 review-graph; singleton community in the graphify VSCode subtree) becomes a 21-line orchestrator composing four typed contracts at module level: `WebviewMessage` discriminated union (16 variants), `WebviewMessageHandlers = Required<...>` exhaustive dispatch table, `configureWebview()`, `installMessageRouter()` returning Disposable, `installFocusReanchor()` returning Disposable. Adding a message type requires extending the union and adding a map entry — the type system enforces both. (Item 2)
- **`tui/session_restore_ops.py` extracted from `tui/app.py`** (272 LoC ops module). Mirrors the engine's `session_ops.py` decomposition pattern. `app.py` shrinks 1947 → 1744 LoC. `_check_session_restoration` and `_restore_session` become thin wrappers calling into the ops module. Same shape applied to TUI as v1.17.x applied to engine and v1.17.4 applied to server. (Item 1, narrowed)
- **`ADR 0002` — CommandContext three-pattern split.** Documents why Rich uses Pattern A (`__getattr__` proxy via `RichCommandContext(handler)`), Textual passes `self` directly (no adapter), and Server uses Pattern B (explicit `ServerCommandContext` delegating against `EngineClientProtocol`). Pins the rationale so reviewers don't re-litigate. Triggers to revisit: 4th context type, 5+ new CommandContext members in one release, or external SDK consumer needing `commands/`.
- **GPT-5.5 family models registered.** `gpt-5.5`, `gpt-5.5-pro`, `gpt-5.3-codex`, `gpt-5-pro` added to model profiles + benchmark sweep against the gpt-5.4 baseline.
- **`docs/model-selection-guide.md`** — planner/executor selection guide with surgical hint strip validation.
- **Runtime version banner** in Rich/Textual/server logger headers — `ppxai vX.Y.Z (commit X, source Y, python Z, platform W)`. Critical for editable-install setups where a stale Python process can outlive its source.
- **9 new tests in `tests/test_engine_client_protocol.py`** (protocol surface + structural satisfaction + import hygiene).
- **4 new tests in `tests/test_agent_logger_attribute.py`** pinning the Item 11 fix with REAL `EngineClient` (no mocks — the bug existed precisely because mocks substituted the missing attribute).

### Changed

- **`commands/agent.py:680` uses `get_logger("tui")` directly** instead of `context.engine_client.logger` (which raised `AttributeError` because `EngineClient` has no `logger` attribute). Pre-fix, the Rich-TUI `/agent <task>` path crashed mid-construction; existing tests substituted `Mock()` for the logger arg, masking the missing attribute. (Item 11)
- **CHANGELOG/CLAUDE.md trim.** CLAUDE.md's accumulated v1.17.x / v1.18.0-in-progress version highlights (~67 lines of marketing copy that duplicated CHANGELOG content) replaced with a short pointer block referencing the durable architectural pattern sections + ADRs. Net change: +14 lines (added discipline rules — verify-both-directions, graphify noise hygiene, subtree-build pattern).
- **`commands/context.py` documentation rewritten** to describe the actual three-pattern architecture (Pattern A proxy for Rich, no adapter for Textual, Pattern B explicit for Server). Old docstring claimed `TextualCommandContext` was the Textual adapter — but it was dead code never wired into `app.py`.
- **`docs/architecture.md`** updated to drop stale `TextualCommandContext` reference + document the three-pattern split with pointer to ADR 0002.
- **`gpt-5.5-mini` becomes the default OpenAI `default_model` and `coding_model`** (was `gpt-4.1-mini` and `gpt-5.1-codex-mini` respectively).
- **Engine `chat_with_tools` per-turn usage flush.** Rich + Textual TUIs now call `save_usage_to_persistent_storage()` per turn, matching server-side behaviour. Pre-fix, TUI usage tracking only flushed on `/save` or session exit — losing data on Ctrl+C interrupt or crash.

### Fixed

- **Orphan tool_calls cleanup.** Ctrl+C mid-tool-iteration left assistant messages with `tool_calls` but no following `tool` role messages — the next API call rejected the malformed conversation history. `validate_and_fix_alternation` now drops orphans, and the test suite gained a regression for it.
- **`session.load()` rejects path-traversal names** (`..`, absolute paths, embedded separators). 21 persistence tests added covering write-failure propagation, symlinks, state-pointer staleness, and concurrent IO.
- **`usage_by_model` round-trip on session load.** Pre-fix, `session.load()` was wiping `usage_by_model` and `tool_calls` because deserialization rebuilt them as empty containers. Fix hydrates both from the persisted JSON.
- **Latent `agent.py:680` `AttributeError`** on Rich TUI `/agent <task>` — see Item 11 above.
- **7 `TestKillPreviewBackend` failures on Windows** — the tests `patch("ppxai.server.state.os.getpgid")` etc., but those attributes don't exist on Windows so `unittest.mock.patch()` raised `AttributeError` before the test body ran. Added `@_unix_only` skipif decorator with documentation. The `kill_preview_backend` Windows branch (`process.terminate()`) IS cross-platform and tested separately; only the Linux signal-handling branch tests can't mock on Windows.
- **`gemini` provider None-iter defensive guards** in `_convert_tools_to_gemini` and adjacent methods.
- **`container.py:104` audited** as by-design abstract base + regression test added.

### Internal

- **`.graphifyignore` exclusions added** (`tests/`, `benchmarks/`, `scripts/`, `examples/`, `docs/archive/`). Pre-fix, a single `tests/test_tui.py` (4,788 LoC) drove 71-79% of the "god class" edges on `PPXAIDEApp` / `MessageBox` / `ChatView`, biasing whole-repo god-node ranking with test-coverage volume. Whole-repo graph 11,628 → 4,481 nodes (−61%); 46,971 → 16,602 edges (−65%). Post-exclusion top hubs reflect actual architecture (`EventType`, `CommandResult`, `SessionManager`, `BaseTool`, `BaseProvider`, `ToolManagerProtocol`).
- **Subtree-build script** used multiple times this branch (`engine`, `server`, `commands`, `vscode`, `tui`) to surface subsystem-internal structure that the whole-repo graph hides. Pattern documented in CLAUDE.md graphify section.
- **Verify-don't-assume both directions.** When a signal flags X as a problem AND when someone pushes back saying the signal is wrong, both readings need the same Tier-2-style verification (production-code-only inbound counts, channel-ratio inspection, source-code grep). Pattern-matched three times before discipline pinned: `EngineClient` (Tier 2 — turned out to be design working as intended), `ChatViewProvider` (Item 2 — turned out to be a real refactor), `PPXAIDEApp` (Item 1 — turned out to be test inflation).
- **476 tests added across the gpt-5.5 critique sweep.** Test count: 2591 → 3067 passing, 9 skipped (the 7 Unix-only `TestKillPreviewBackend` + 2 pre-existing). Coverage now spans server/state.py (28 tests across 4 classes), `_execute_ai_task` (20 tests across 7 sub-cases), tool security + `docs/consent-contract.md` (18 tests), server route edges (17 tests), session persistence (44 tests across multiple files), benchmark CI gate (9 tests).
- **Dead `TextualCommandContext` class deleted** from `commands/context.py`. Created v1.15.0, never wired into `app.py` (which passes `self` directly), survived 13 releases as dead code. Detection during Item 10's protocol enumeration.
- **CommandContext methods on `PPXAIDEApp` retained** (16 inline methods, ~100 LoC). They're the actual Pattern A implementation, NOT boilerplate to remove. ADR 0002 documents this.
- **DEBT-INVENTORY-v1.18.2.md** is the canonical home for deferred items. 9 items closed in this branch (Items 1, 2, 4, 5, 6, 7, 8, 9, 10, 11). Item 3 (k8s session-manager security tests) remains trigger-deferred — to be addressed when in k8s context environment so tests can be exercised end-to-end.

### Docs

- New [docs/release-notes-v1.18.2.md](docs/release-notes-v1.18.2.md).
- New [docs/decisions/0002-command-context-three-pattern-split.md](docs/decisions/0002-command-context-three-pattern-split.md) (second ADR).
- New [docs/model-selection-guide.md](docs/model-selection-guide.md).
- New [docs/consent-contract.md](docs/consent-contract.md) (security boundary for tool execution).
- [CLAUDE.md](CLAUDE.md) trimmed obsolete version-marketing; gained verify-both-directions discipline + graphify noise-hygiene + subtree-build pattern guidance + pointer to ADR 0002.
- [docs/architecture.md](docs/architecture.md) updated for the three-pattern CommandContext split.

## [1.18.1] - 2026-04-25

### Added

- **Command-dispatch unification (Option A).** Every slash command now flows through `POST /command/<name>` via the Python `CommandFactory`. Web's `command-dispatcher.js` and VSCode's `chatPanel.ts:handleSlashCommand` are thin shells over the v1 wire envelope `{ok, result, side_effects, events, version}`. The pre-v1.18.1 35-case switches in both clients (~775 LoC web, ~557 LoC VSCode) are gone. Where command logic previously lived twice — once in Python, once in JS/TS — there is now one source of truth. See [docs/archive/TODO-v1.18.1-command-unification.md](docs/archive/TODO-v1.18.1-command-unification.md).
- **`SideEffectKind` taxonomy (15 kinds).** Side-effects name the user's intent, not the rendering: `open_editor`, `open_viewer`, `show_image`, `show_pdf`, `reveal_in_explorer`, `open_terminal`, `run_shell`, `open_html_preview`, `refresh_file_tree`, `set_theme`, `copy_to_clipboard`, `attach_file`, `prompt_quick_pick`, `notify`, `vscode_delegate`. Web builds panels (xterm.js, CodeMirror, iframe); VSCode delegates to first-party APIs (`createTerminal`, `showTextDocument`, `executeCommand('vscode.open')`). Open-enum invariant — clients ignore unknown kinds. Taxonomy sentinel test (`tests/test_command_envelope.py`) pins the v1.18.1 set.
- **`prompt_quick_pick` resume protocol.** Per ADR `docs/decisions/0001-keys-command-cross-client.md` Q3 (b): the chosen `value` IS the literal next args. Client re-issues `POST /command/<command_to_resume>` with `args=<chosen value>`; no server-side continuation state. Used by `/show @query`, `/edit <missing>`, future free-text follow-ups.
- **State-sync determinism — Phase A (visibility re-anchor).** Web `document.visibilitychange → visible` and VSCode `vscode.window.onDidChangeWindowState → focused` fetch `GET /state` and feed the snapshot through `AppState`. Brings sleep-recovered tabs / focus-restored windows back in sync without waiting for the next chat. Shared `_reanchorFromServer` helper across both clients; parity test in `tests/test_vscode_visibility_reanchor.py`.
- **State-sync determinism — Phase B (REST piggyback).** State-mutating REST routes wrap their response in `with_drained_events(payload, engine)` so any `state_sync` events queued by the handler ride along on the same response. Clients drain `envelope.events[]` through the same dispatcher that handles live SSE events. `engine.set_working_dir`, `/cd` factory route, `/sessions/load`, etc. now reach the AppState mirror within one round-trip — no longer waiting for the next `/chat` to open an SSE generator.
- **State-sync determinism — Phase C (file tree subscribes to AppState).** Web's file tree consumes `state.workingDir` via `AppState.on()` instead of caching `_fileTreeCurrentPath`. Eliminates the 300ms debounce that masked drift; the tree refreshes in lockstep with cwd changes from any source.
- **State-sync determinism — Phase D (`cwd_anchor` 409 conflict).** `/files/read|write|image` accept an optional `cwd_anchor` argument (the `working_dir` the client thinks the relpath was captured against). Server returns `409 Conflict` with `{expected, actual, events}` on drift. Web file-view widgets and VSCode's `chatPanel.handleCwdAnchorMismatch` recover by draining the events and surfacing a notice — drift becomes named, surfaced, and recoverable instead of a silent "404 file not found".
- **Server-side `validate_agent_task` shared safety gate.** Pre-v1.18.1, the `min_task_words` check existed only in the TUI factory path; web users running `/agent fix` via `streamChat` hit `/chat` directly and the LLM-with-tools just went — a real safety gap. v1.18.1 centralises validation in `ppxai/commands/agent.py::validate_agent_task` and applies it from both `/chat` (when the message starts with `/agent `) and the factory's `handle_agent`. Friendlier rejection: `NotificationResult(WARNING)` framed as a question with concrete examples instead of a red error.
- **Rich `/spec` templates ported to factory.** Pre-v1.18.1, `/spec` returned a 5-line stub from the factory while VSCode had ~50-line rich templates inline. The full templates (api / cli / lib / algo / ui) + guidelines now live in `ppxai/commands/system.py::handle_spec`; all four clients see identical content. VSCode's client-side `handleSpecCommand` is gone.
- **VSCode `sideEffectsHandler.ts` + `commandRenderer.ts`.** Two new helper modules (~485 LoC total) translate envelope `result` → systemMessage and `side_effects` → vscode.* APIs (createTerminal, showTextDocument, executeCommand). Lazy-init from `ChatViewProvider`; webview stays a thin display surface.
- **`ADR 0001` — `/keys` command cross-client convention.** First architectural decision record under `docs/decisions/`. Establishes the convention for future ADRs and pins the cross-client routing for `/keys` (TUI in-process, web/VSCode via `vscode_delegate`).
- **`pypdfium2` replaces `pdf2image+poppler`.** Page rasterization (`GetPdfPageImageTool`) and PPTX slide rendering (`render_pptx_slides`) now use pure-wheel bindings to Google's PDFium — no system binary required, PyInstaller binaries are self-contained on every platform. License: BSD-3 OR Apache-2.0. Two tests previously skipped on dev machines without poppler now run unconditionally.

### Changed

- **VSCode `chatPanel.ts` slimmed by 557 LoC** (243 added, 800 removed). The 35-case `handleSlashCommand` switch + ~12 bespoke handlers (`handleSpecCommand`, `handleShowCommand`, `handleEditCommand`, `handleCdCommand`, `handlePwdCommand`, `handleUsageCommand`, `renderCommandResult`, duplicate min-words validation in `handleAgentCommand`) deleted. Six chat-shaped commands (`/generate /explain /test /docs /debug /implement`) keep using `_backend.codingTask` via a `CHAT_SHAPED_TASKS` Map so the active editor's language + filename ride along.
- **Web `command-dispatcher.js` slimmed by 775 LoC**. The `STREAMING_COMMANDS` set keeps the chat-shaped commands streaming; everything else is `apiClient.executeCommand(name, args)` + envelope unwrap.
- **Engine `working_dir` mutation pipeline consolidated.** `_onWorkingDirChanged` is the single subscriber for `state.workingDir` changes — coordinates badge update, file-tree refresh, and SSE-piggyback drain. The four prior write paths (REST, /chat SSE, optimistic `/cd`, `/sessions/load`) write through `AppState`; the subscriber fires once.
- **`@query` fuzzy search** in `/show` emits `PROMPT_QUICK_PICK` on multiple matches instead of the prior "type the full path" text fallback. Cross-client UX: same picker shape on TUI/web/VSCode.
- **Test count: 2926 passing, 0 skipped** (was 2924 + 2 skipped at v1.18.0). The poppler-skipped PDF tests now run unconditionally after the pypdfium2 swap.

### Fixed

- **CI build jobs now install `--all-extras`** instead of `--extra build --extra server` (or `--tui`). Pre-existing bug surfaced during v1.18.1 release pre-flight: spec hiddenimports for `[data]` (pypdf, pypdfium2, openpyxl, python-pptx), `[gemini]` (google.genai), and `[search]` (ddgs) were silently dropped at PyInstaller time because the modules weren't in the build venv. Server binaries have shipped since v1.17.4 with broken PDF rasterization, since v1.16.0 with broken native Gemini, and similar silent gaps for web search. Runtime impact was graceful (users got "pdf2image is not installed" errors instead of crashes), so the bug went undetected for six releases. v1.18.1 is the first release where shipped binaries fulfil the published feature set.
- **`uv.lock` regenerated** after the pypdfium2 swap. The lock pinned `pdf2image 1.17.0`; CI's `uv sync --frozen` would have installed the stale package list and ignored the new `pypdfium2` entry in `pyproject.toml`.

### Deferred to v1.18.2

- **Agent loop unification across HTTP clients.** Validation unified in v1.18.1; loop body still runs client-side in VSCode and via the streaming `/chat` path on web because factory's `handle_agent` is TUI-shaped (`asyncio.run`, `console.print`). See [docs/archive/TODO-v1.18.2-agent-loop-unification.md](docs/archive/TODO-v1.18.2-agent-loop-unification.md).
- **`prompt_text` side-effect kind** for free-text follow-ups when `prompt_quick_pick`'s finite-choice shape doesn't fit. See [docs/archive/TODO-v1.18.2-prompt-text-kind.md](docs/archive/TODO-v1.18.2-prompt-text-kind.md).

### Docs

- New [docs/release-notes-v1.18.1.md](docs/release-notes-v1.18.1.md).
- New [docs/decisions/0001-keys-command-cross-client.md](docs/decisions/0001-keys-command-cross-client.md) (first ADR).
- [CLAUDE.md](CLAUDE.md) gains the §"Critical Architecture Pattern: Command Dispatch via Envelope (v1.18.1)" and §"Critical Architecture Pattern: State-Sync Determinism (v1.18.1)" sections (added during the work, not at release).

## [1.18.0] - 2026-04-25

### Added

- **P0 — Agent heartbeat primitives.** New observable primitive for the agent tool loop. `EventType.AGENT_BEAT` fires once per tool iteration with an `AgentBeatState.as_event_data()` payload (`{iteration, beat, tool, ok, failures, elapsed_s}`); `AGENT_RUN_START` / `AGENT_RUN_COMPLETE` / `AGENT_RUN_ERROR` bracket the run; `AGENT_ZOMBIE` fires when the circuit-breaker trips. `ppxai/engine/chat.py` emits these across all agent-mode paths, including both exit branches (completion and max-iterations) so observers see a clean lifecycle. `AgentBeatState` (`ppxai/engine/types.py`) is a dataclass with a JSON-serializable payload contract — tests pin the wire format.
- **P0 — `AppState.agent_beat` field.** Schema-driven (added to `app_state_schema.json`) and mirrored across Python / JS / TS — the engine writes the latest beat to AppState and clears it (empty dict) on run end, so every client sees the same canonical value. Included in `_SSE_SYNC_FIELDS` whitelist so the server pushes it automatically via `state_sync` events. No server code changes — the SSE generator is event-agnostic.
- **P0 — Zombie circuit-breaker.** New config key `tools.agent.zombie_threshold` (default 3; 0 disables) stops the tool loop after N consecutive failed iterations, emits `AGENT_ZOMBIE` + `AGENT_RUN_ERROR`, and returns cleanly instead of burning `max_iterations` on hallucinated retries. Reachable via `ppxai-config.json → tools.agent.zombie_threshold`.
- **P0 — Client renderers for `agent_beat`:**
  - **Rich TUI** — dim `⚙ iter N · tool · status · Xs` line after each tool group; red `⚠ Agent stopped — …` warning on zombie trip.
  - **Textual (ppxaide)** — persistent `⚙ iN · tool · Xs` status-bar badge with variant selection: `success` (ok), `error` (single fail), `warning` (2+ consecutive failures). Cleared when engine empties the field.
  - **Web** — header badge (`#agentBeatBadge`) between streaming-badge and usage-badge with matching `.warn` / `.error` CSS variants; auto-hide when idle.
  - **VSCode extension** — identical badge in the webview header; webview receives the payload over the existing `stateSync` channel.
- **P0 — Test coverage.** ~120 new tests across `test_agent_beat_primitives.py` (dataclass + EventType), `test_agent_beat_emission.py` (chat.py emission contract), `test_agent_beat_zombie.py` (circuit-breaker), `test_agent_beat_sse.py` (end-to-end through real EngineClient + server streaming), `test_agent_beat_textual_renderer.py` (ppxaide badge variant logic), plus additions to `test_common_event_handler.py` for the Rich TUI renderer. Stream-handler drift test (`test_stream_handler_dispatch.py`) and AppState sentinel tests (`test_app_state.py`) bumped accordingly. **Suite: 2458 passed, 0 regressions.**

### Changed

- **`tests/test_app_state.py` field-count sentinel** bumped from 18 → 19 to cover the new `agent_beat` field. Intentional friction per the "cross-client state through AppState" architecture pattern.
- **VSCode `AppState` TypeScript** — `SchemaField.type` widened to include `'object'` so the new `agentBeat` field validates cleanly against the schema at module init. `AgentBeatSnapshot` interface added alongside `ContextAttachment`.
- **`ppxai/tui/stream_handler.py` `NOOP_EVENTS` comment** updated to explain that ppxaide renders heartbeat through `AppState.agent_beat`, not the event bus — event-level silence here avoids double-rendering.

### Docs

- New [docs/release-notes-v1.18.0.md](docs/release-notes-v1.18.0.md).
- New §"Agent Heartbeat Primitives (v1.18.0)" in [docs/architecture.md](docs/architecture.md) documenting the emission contract, zombie-breaker semantics, and the AppState lifecycle.
- [ROADMAP.md](ROADMAP.md) v1.18.0 section split into "P0 heartbeat (landed)" and "AppState codegen + routing (planned)" blocks.

## [1.17.7] - 2026-04-19

### Fixed

- **`ppxai-desktop --version` reported a stale hardcoded version.** The desktop launcher had been misreporting its version at least since v1.17.4 — the frozen binary's `from ppxai.version import __version__` raised `ImportError` because `ppxai/__init__.py` transitively imports `pydantic`, `openai`, `rich`, `prompt_toolkit`, `fastapi`, and `uvicorn`, all of which are intentionally **excluded** from the desktop PyInstaller spec. The silent `except ImportError` fallback returned a hardcoded string that drifted on every release. `ppxai-desktop.py` now loads `ppxai/version.py` directly by file path via `importlib.util.spec_from_file_location`, bypassing the package `__init__` entirely. The spec ships `ppxai/version.py` as a data file so `sys._MEIPASS` resolves correctly in the frozen binary. No more hardcoded version string anywhere in the desktop launcher; the binary always matches the source of truth. Discovered during the post-v1.17.6 install-on-dev-machine rebuild when the fresh desktop binary was still reporting 1.17.4.

## [1.17.6] - 2026-04-19

### Fixed

- **R19 — MessageBox rendering gap for `uploaded_file` blocks.** The ppxaide Textual widget's `_normalize_content_to_text` was missing the R5 Stage 6 branch; assistant messages with PDF/Office attachments rendered as `[uploaded_file]` instead of `[File: name (media_type)]` — inconsistent with Rich TUI, web, and VSCode clients. Now uniform across all four clients.
- **R19 — `AppState` listener dispatch wasn't isolated.** One listener raising during `set()` / `update()` silently broke the chain for every subsequent listener on the same field. Now wraps each callback in a try/except with a warning log — matches the `SessionManager.on_messages_changed` policy that already existed for session mutations. Prevents a buggy widget listener from wedging other observers mid-stream.

### Changed

- **R5 — promoted uploaded-file attachments to a first-class content type** (`{"type": "uploaded_file", "name", "media_type", "file_id", "summary", "extra"}`). PDFs, Office documents, and large CSVs previously lived as `<uploaded_file>` XML markers embedded inside `{"type": "text"}` content blocks; every consumer had to regex-parse text to find attachments, and clients rendered the raw XML. The new block type eliminates the string parsing — `refresh_context_attachments`, `remove_context_attachment`, and the R10 multimodal-cache predicate now dispatch on `block["type"]`; web and VSCode clients render a compact `[Attached: name (media_type)]` badge.
  - **Byte-identical LLM-facing strings.** Provider adapters (OpenAI, OpenAI-compat, OpenAI-native chat + Responses, Gemini, Perplexity) flatten every `uploaded_file` block back to the legacy `<uploaded_file>...</uploaded_file>` text marker via `flatten_uploaded_file_blocks()` before the API call. The flatten uses the same `format_uploaded_file_reference()` helper the producers used pre-R5, so model behavior and token counts don't drift. An explicit test asserts this equality.
  - **Backward compatible.** Sessions saved by v1.17.5 and earlier continue to load correctly — consumers recognize both the structured block and the legacy text marker, so a mid-rollout session with both shapes interleaved works too. Session round-trip preserves every field.
  - **Staged rollout.** Six commits on `bugfix/v1.17.6`: schema helpers, provider flatten, dual-read consumers, producer flip, R10 cache predicate + session round-trip, client renderers. Each stage independently reversible.
  - Producers flipped: `_preprocess_csv` (large-CSV lazy-load path), `_preprocess_pdf`, `_preprocess_office` (Excel/PPTX/DOCX) in `ppxai/engine/file_preprocessing.py`.
  - 37 new tests across `tests/test_uploaded_file_block.py`, `tests/test_r5_provider_flatten.py`, `tests/test_r5_dual_read.py`, `tests/test_r5_end_to_end.py`, `tests/test_r5_session_round_trip.py`.

### Added

- **R19 — targeted regression coverage for ppxaide multimodal flow.** 21 tests in `tests/test_r19_ppxaide_multimodal.py` covering the four failure modes the original R19 report flagged: mixed text+image+uploaded_file rendering, full multimodal agent-turn event ordering (STREAM_START → AGENT_INTERMEDIATE_PROSE → TOOL_GROUP_* → STREAM_END all routed via the blinker bus), `pending_files` lifecycle (clear on success, no cross-send contamination, clear even when engine raises), and `context_attachments` mid-stream listener resilience. The act of writing the tests surfaced the two bugs fixed above.

## [1.17.5] - 2026-04-19

### Fixed

- **R9 — `validate_and_fix_alternation` silently dropped `tool_calls`.** When collapsing two consecutive assistant messages, the "longer text wins" heuristic would discard a message carrying native `tool_calls[]` (which typically has empty `content`) in favour of a shorter plain-text sibling. `ppxai/engine/session.py` now prefers messages with non-empty `tool_calls` regardless of text length; when both or neither carry tool_calls, the longer message still wins. Also upgrades the trailing-user-drop log line to `DROPPED UNSENT USER PROMPT` with a 120-char preview so `/save` immediately after pressing Enter is diagnosable instead of silent. 3 new tests in `tests/test_tool_messages.py::TestAlternationValidationWithToolMessages`.
- **R15 — VSCode context-only chat requests returned 400 from Perplexity.** When the VSCode webview sent a chat with empty user content, `chatPanel.ts` still prepended the workspace `[Context: ...]` block and dispatched it; Perplexity's strict alternation check then rejected the resulting request. Two-layer fix: (1) `chatPanel.ts::handleChat` now rejects empty user content with an inline error bubble before any context injection; (2) server-side `POST /chat` detects empty-or-context-only bodies via `_is_empty_or_context_only()` and returns an SSE error event without acquiring the chat lock or reaching the provider. 13 new tests in `tests/test_chat_route_r15.py`.
- **R16 — ppxaide silently dropped engine events.** The Textual TUI's stream-event dispatcher only covered 15 of 21 `EventType` members; the remaining six (including `CONTEXT_INJECTED`) fell through to a debug-level no-op. Refactored `ppxai/tui/stream_handler.py` into two explicit sets — `EVENT_MAP` for events routed to UI bus signals, `NOOP_EVENTS` for events ppxaide intentionally ignores (`STATE_SYNC`, agent loop events, `STATUS`). Unknown types now log an actionable WARNING that names the file to edit. Added drift test `tests/test_stream_handler_dispatch.py` that fails if a new `EventType` is added without updating either set.
- **R17 — Gemini `'NoneType' object is not iterable` regression guard.** Audit of `ppxai/engine/providers/gemini.py` confirmed all `.candidates` / `.content.parts` access sites are properly guarded (original fix commit `6feb406b` is in the v1.17.4 tag; the reported log came from a pre-tag binary). Added 4 regression tests in `tests/test_gemini_null_parts.py` covering null `parts`, empty `candidates`, null `content`, and the `chat_sync_simple` helper so the triple guard can't silently regress.
- **R18 — `/attach <path>` error UX now surfaces close matches.** When a user typed the wrong directory (e.g. `/attach resources/foo.png` when the file lives in `docs/`), the bare "no such file" message forced blind retries. `_not_found_error()` in `ppxai/commands/attach.py` now enumerates the parent directory and lists the 5 closest file names via `difflib.get_close_matches`. If the parent doesn't exist, it walks up to the first existing ancestor and suggests similarly-named sibling directories.
- **R10 — `_has_multimodal_attachments()` cached to fix per-save O(N) scan.** Long tool-heavy conversations were walking every message on every auto-save to decide flat vs. directory session format. Result is now cached on `SessionManager._multimodal_cache` — `add_message` eagerly flips it to `True` when a multimodal part arrives; mutation sites that could remove multimodal content (`remove_last_message`, `clear`, `load`, `reset_for_model_switch`, `validate_and_fix_alternation`) invalidate appropriately. 500-msg session × 20 saves: 0 rescans after warm-up.
- **R8 — `_count_csv_rows_cols()` no longer materializes the full file.** R3 made the row-count streaming (O(1) rows) but left `_decode_text(data)` in place, producing a multi-MB Python string for a 10 MB CSV just to sniff the delimiter. Now decodes only the first 8 KB head for the sniff, then streams the raw bytes through `TextIOWrapper(BytesIO(data))` so `csv.reader` pulls one row at a time. 10 MB CSV: tracemalloc peak drops from ~20 MB to under 2 MB. 9 tests in `tests/test_count_csv_streaming.py` with an explicit memory-bound regression guard.

### Added

- **R12 Option 1 — `EventType.AGENT_INTERMEDIATE_PROSE` surfaces model narrative between tool iterations.** During multi-step tool-calling loops the engine was stripping tool-call JSON out of each iteration's response and discarding the rest, leaving the UI silent for 5–15 seconds between tool bubbles even when the model was narrating ("I'll check the config next…"). `chat_with_tools` now emits `AGENT_INTERMEDIATE_PROSE` with the stripped prose right before `TOOL_GROUP_START` for every iteration that produced narrative (empty responses skip the event so tool-only models don't trigger empty bubbles). Rich TUI renders as a `[dim italic]` preamble; ppxaide routes through a new `Events.ENGINE_AGENT_INTERMEDIATE_PROSE` bus signal to `add_system_message` in the chat view. Web/VSCode inherit automatically via SSE pass-through — they'll render as text until per-client styling ships. Full streaming tool loop (Option 3) remains deferred to v1.18.x as a provider-adapter sweep. 2 new tests in `tests/test_tool_messages.py::TestMultiToolExecution`.

## [1.17.4] - 2026-04-12

### Added

- **File Upload Phase 2 — Engine Foundation**
  - **SessionFileStore** (`ppxai/engine/session_store.py`) — content-addressed file IDs, staging-to-session directory lifecycle, save/get/cleanup/move_to_session/restore_from_session
  - **Engine wiring** — EngineClient owns SessionFileStore; session serialize/deserialize rewrites inline base64 to/from file_id references; dual-format sessions (flat .json for text-only, directory with uploads/ for multimodal); `context_attachments` schema extended with `file_id` field
  - **`/attach remove`** — `/attach remove <name>` and `/attach remove all` evict committed attachments from session history; `EngineClient.remove_context_attachment()` method
  - **File preprocessing** (`ppxai/engine/file_preprocessing.py`) — central dispatcher `preprocess_file()`, routes images/text/PDF/Office per model vision capability
  - **Image validation** (`ppxai/engine/image_validation.py`) — magic-byte sniffing (PNG/JPEG/WEBP/GIF), provider-aware size limits, dimension extraction from headers, token cost estimation
  - **`supports_vision`** flag on `ModelProfile` — set for GPT-5.x, GPT-4.x, Gemini 2.5/3/3.1, Gemma 4, Sonar/Sonar Pro, local VL models; convenience function `supports_vision(model_id)`
  - **VL sidecar config** — `tools.vision_model` section in config (endpoint, model, auto_caption, prompt); `EngineClient.has_vision_model()` + `caption_image()` methods
  - **PDF tools** (`ppxai/engine/tools/builtin/pdf_tools.py`) — `ReadPdfTool` (text extraction by pages) and `GetPdfPageImageTool` (rasterization to PNG data URI); guarded by pypdf import
  - **`[data]` deps** extended with `pypdf>=4.0` and `pdf2image>=1.17`
- **`/doctor` command** (`ppxai/commands/doctor.py`) — read-only config advisor with deprecation table (`ppxai/engine/model_deprecations.py`); scans user config, reports dead/deprecated/new/recommended models
- **Gemini 3.1 Flash Lite** + **Gemma 4 family** (31B, 26B MoE, E4B, E2B) added to ppxai-config.example.json and model_profiles.py
- **Gemini deprecation flags** — 2.0/2.5 models flagged with shutdown dates; `gemini-3-pro-preview` removed (shut down March 2026)
- **File Upload Phase 3 — Server API**
  - `ChatRequest.files[]` Pydantic model (`FileAttachment`) in `ppxai/server/models.py`
  - Chat route preprocessing integration — `preprocess_file()` per attachment in `ppxai/server/routes/chat.py`
  - `context_attachments` added to `state_sync` SSE whitelist for cross-client push
  - `POST /complete` server endpoint (`ppxai/server/routes/completion.py`) for cross-client autocomplete
  - `GET /files/serve/{file_id}` endpoint for raw binary serving of session files
  - `GET /files/preview/{file_id}?slide=N` endpoint for PPTX slide rendering via LibreOffice headless
- **File Upload Phase 4 — Excel + PPTX Tools**
  - `ReadExcelSheetTool`, `ListExcelSheetsTool`, `ListExcelChartsTool`, `RenderExcelChartTool` in `ppxai/engine/tools/builtin/excel_tools.py`
  - `ListPptxSlidesTool`, `ReadPptxSlideTextTool`, `RenderPptxSlideTool`, `SummarizePptxVisualTool` in `ppxai/engine/tools/builtin/pptx_tools.py`
  - **`summarize_pptx_visual`** — renders all slides via LibreOffice headless, captions each via VL sidecar (Qwen3-VL-8B), returns visual descriptions in a single tool call (replaces N×`read_pptx_slide_text` iterations)
  - **`ReadDocxTool`** (`read_docx`) in `ppxai/engine/tools/builtin/docx_tools.py` — extracts text from .docx via stdlib zipfile + xml.etree (no python-docx dependency)
  - **`ReadCsvTool`** (`read_csv`) + **`ListCsvColumnsTool`** (`list_csv_columns`) in `ppxai/engine/tools/builtin/csv_tools.py` — lazy-loading for large CSVs (>50KB) stored in SessionFileStore; row ranges, column filtering, markdown/CSV output
  - **CSV preprocessing threshold** — CSVs >50KB stored with `<uploaded_file>` reference instead of inlining; model uses tools on demand
  - **Type-specific tool hints** — `<uploaded_file>` references now suggest the correct tool per file type (read_docx for Word, list_excel_sheets for Excel, summarize_pptx_visual for PPTX)
- **File Upload Phase 5 — Web Client UI**
  - Paperclip attach button + hidden file input in `ppxai/web/index.html`
  - Drag-drop zone on input container + body-level drop handler
  - Attachment badge strip with image thumbnails below input
  - Inline clickable thumbnails in user message bubbles — images open split panel lightbox, PDFs open split panel embed, other files show text preview
  - `pendingFiles[]` staging array, cleared on send; `stream-handler.js` accepts `files` parameter
  - **SheetJS** (`xlsx.full.min.js`) for client-side Excel preview with `DataTableViewer` (sort, filter, pagination, sheet tabs)
  - **PPTX slide viewer** — prev/next navigation with LibreOffice-rendered slide images via `/files/preview` endpoint
  - **PDF preview** — Blob URL + `<iframe>` (replaces `data:` URI `<embed>` which fails for large PDFs)
  - **Resizable split panel** — drag handle between chat and preview, sets `flex-basis`
  - **Attachment badge** — clickable context indicator at status strip, fetches file via `file_id` for preview
- **File Upload Phase 6 — VSCode Client**
  - Webview file picker (`attachBtn` + `fileInput` + drag-drop with overlay)
  - `pendingFiles` staging with image thumbnail previews, `renderPendingBadges()`, `removePendingFile()`
  - `sendMessage` includes `files` in `postMessage` to extension host
  - `chatPanel.ts` handles `files` field, forwards to `httpClient.ts` `chat()` method
  - Inline attachment thumbnails in user message bubbles (images render, files show badge)
  - Context attachments badge from SSE `state_sync` — shows file count in status area
  - Dynamic autocomplete via `POST /complete` — replaces hardcoded 27-entry command list with live CommandFactory (56+ entries), path arguments, @file refs
  - `httpClient.complete()` method for server-side completion
- **File Upload Phase 7 — Textual TUI**
  - FileTree `a` key binding emits `FileAttach` message, handled by `on_file_tree_file_attach`
  - `Ctrl+U` shortcut (`action_attach_shortcut`) toggles file tree for attach
  - Send integration: `pending_files` consumed via `build_multimodal_content()` before `engine.chat()`
  - Public `pending_files` attribute on `PPXAIDEApp` for `CommandContext` proxy
- **CompletionProvider** (`ppxai/engine/completion.py`) — engine-layer `complete()` function is the **single source of truth** for autocomplete across all 4 clients. Rich + Textual call in-process; Web + VSCode call via `POST /complete`. Three-phase delivery:
  - **Task #11 (initial):** extracted `complete()` from Rich TUI, added `POST /complete` route, refactored Rich `PPXAICompleter` to delegate
  - **Cross-client unification:** extended `complete()` to own **all** completion sources: slash commands + aliases + `/quit`/`/exit` builtins, path args, @file refs, `@git`/`@tree`/`@clipboard`/`@url` context providers, `/tools`/`/usage`/`/checkpoint`/`/status`/`/theme` subcommands (both first- and second-level args like `/usage show <mode>`, `/theme emoji on/off`, `/checkpoint backend <backend>`, `/tools help <tool>`), dynamic `/model <name>` (pulled from active provider config), dynamic `/provider <name>` (pulled from `PROVIDERS`)
  - **Parity rollout:** Web + VSCode now receive subcommand, model, provider, tool-help, and context-provider suggestions that previously only existed in Rich and Textual. Server route passes `current_provider` and live `tool_names` from `s.engine.tool_manager.list_tools()`
  - **Client simplification:** Rich `PPXAICompleter` reduced from ~594 lines to ~85 (pure glue). Textual `TextualCompleter` reduced from ~238 lines to ~100. VSCode webview `@` flow unified with `/` flow — both trigger `POST /complete` through one code path. Legacy `handleSearchFilesForAutocomplete` + `fileSuggestions` message type retired in VSCode extension. All client-side subcommand tables (`TOOLS_SUBCOMMANDS`, `THEME_NAMES`, `USAGE_SUBCOMMANDS`, `CHECKPOINT_SUBCOMMANDS`, `STATUS_SUBCOMMANDS`, etc.) deleted — the engine owns them
  - **Stable schema:** every completion item carries `{text, display, description, kind, replace_start}`. New `kind` values: `subcommand`, `tool`, `model`, `provider`, `theme`, `context_ref`
  - **Tests:** `tests/test_completion_provider.py` grew from 21 to 39 tests (new classes `TestContextProviderCompletion`, `TestSubcommandCompletion`, `TestDynamicCompletion`). Deleted stale `TestDynamicCommandList`/`TestCacheInvalidation` in `test_completer_dynamic.py` that pinned the old Rich-internal cache. Suite: 2262 passing, zero regressions
- **Schema-driven cross-language AppState** — golden source of truth for Python/Web/VSCode state field definitions
  - **`ppxai/engine/app_state_schema.json`** — single canonical JSON file declaring all 18 AppState fields (Python snake_case name, JS/TS camelCase name, type, default value, group, doc). Every client derives its field map from this file at startup
  - **Python** (`ppxai/engine/app_state.py`) loads via `importlib.resources.files("ppxai.engine") / "app_state_schema.json"`. `AppState.FIELDS` is now derived from `AppState.SCHEMA`; mutable defaults are cloned per instance to prevent inter-instance leakage
  - **Web** (`ppxai/web/shared/app-state.js`) reads from `window.APP_STATE_SCHEMA`, injected into `index.html` by `ppxai/server/routes/static.py::serve_index` before the `shared/app-state.js` tag. Synchronous at module load, no fetch round-trip, no async bootstrap. `AppState` derives `_pythonToJs` and defaults dynamically from the injected schema
  - **VSCode** (`vscode-extension/src/appState.ts`) loads the bundled schema via `fs.readFileSync()` from `vscode-extension/resources/app-state-schema.json`. The bundled copy is kept in sync with the Python source by `vscode-extension/scripts/sync-schema.js`, wired into `package.json` as a `precompile`/`prewatch` hook so every `npm run compile` validates and refreshes the copy. `AppState.SCHEMA`, `PYTHON_TO_TS`, and defaults are all derived from the loaded JSON
  - **`GET /schema/app-state`** server endpoint (`ppxai/server/routes/schema.py`) relays `ppxai.engine.app_state.SCHEMA` verbatim as JSON — used for HTML injection and available for any future diagnostic tooling that needs to know "what fields does AppState declare?"
  - **Drift detection is architectural, not runtime**: `TestSchemaDTO::test_vscode_bundled_copy_matches_canonical` does byte-for-byte equality between `ppxai/engine/app_state_schema.json` and `vscode-extension/resources/app-state-schema.json`; CI fails if someone edits one without running `npm run sync-schema`. `updateFromPython()` on both clients also logs a runtime drift warning if the server pushes an unknown field, covering the server-and-client-on-different-versions case
  - **`updateFromPython(payload)`** method on both Web and VSCode `AppState` classes is the single cross-language boundary. Callers hand in snake_case Python payloads and get back a mapped camelCase object. `handleStateSync` in `app.js` and the `state:sync` handler in `chatPanel.ts` both shrink to one translation call plus side-effect dispatch
  - **Tests:** added `TestSchemaDTO` class (11 tests) pinning schema format, byte-equality of the bundled VSCode copy, field name case conventions, type/default matching, and a TUI source-scan test that catches Rich/Textual drift from the schema; added `tests/test_schema_endpoint.py` (10 tests) covering the `GET /schema/app-state` endpoint and the HTML injection pipeline; added `TestAppStateFieldCoverage::test_mutable_defaults_not_shared_between_instances` to pin the per-instance default cloning. Suite: 2288 passing, zero regressions
  - **Adding a new AppState field** is now a one-line edit to `app_state_schema.json` + a sentinel-count bump in the Python test + (until v1.18.x codegen lands) adding the field to the hand-maintained `AppStateFields` TypeScript interface. Everything else propagates automatically: Python FIELDS, server endpoint, HTML injection, web AppState, VSCode bundled copy via precompile hook, and the drift tests all pick up the change without further edits
  - **Rule fix:** hoisted the two lazy imports (`CommandFactory`, `engine_complete`) in `ppxai/rich/main.py` — no more `TYPE_CHECKING`-style dodges, all imports at module top per the project's DAG rule
- **EngineClient second decomposition pass** — `ppxai/engine/client.py` shrunk from 1396 → **977 lines** (−419) to undo the growth that accumulated during v1.17.4 Phase 2-7 file upload work
  - **`ppxai/engine/multimodal_ops.py`** (new, 415 lines) — owns `_refresh_context_attachments`, `get_context_attachments`, `remove_context_attachment`, `has_vision_model`, `caption_image`. All multimodal context-tracking + VL sidecar logic in one focused module.
  - **`ppxai/engine/provider_ops.py`** (new, 274 lines) — owns `set_provider`, `list_providers`, `get_current_provider`, `set_model`, `list_models`, `get_current_model`, plus the module-private helpers `_apply_model_switch` and `_log_model_hints_transition`. All provider/model switching logic in one place.
  - **`ppxai/engine/client.py`** — now a thin facade: every extracted method became a one-line delegation to the corresponding ops module. Public API unchanged; all 2288 tests still pass. The original v1.17.1 target was 955 lines after the first decomposition (checkpoint_ops + consent_ops + bootstrap_ops); this pass adds session_ops + multimodal_ops + provider_ops and lands at 977 — within 22 lines of the target, and well below the pre-v1.17.4 baseline of 1588.
  - **Engine layer totals:** client.py (977) + 6 ops modules (1408) = 2385 lines, vs. pre-v1.17.1 1588-line monolith. The total code is larger because the ops modules have focused docstrings and clear separation, but each file is now small enough to audit independently.
- **Textual TUI Ctrl+U fix** — `action_attach_shortcut` used to just call `action_toggle_file_tree()`, which meant pressing Ctrl+U twice closed the tree instead of focusing it. Now: if the tree is hidden, show it; then focus the tree widget regardless, so the user can immediately press `a` to attach. Ctrl+B remains the show/hide toggle. ([ppxai/tui/app.py:1799-1820](ppxai/tui/app.py#L1799-L1820))
- **CLAUDE.md route module count** — updated from "13 route modules" to "17 route modules" reflecting v1.17.4 additions (`completion.py`, `file_serve.py`, `preview.py`, `schema.py`)

### Fixed

- **`/save <name>`** now honors the name argument (was silently ignored)
- **`/ls <file>`** shows single-file entry (shell ls semantics, was error before)
- **`/save` warning** when pending attachments haven't been sent yet
- **Session autorestore** for directory-format sessions (line 130 check in `sessions.py`)
- **Context attachment badge visibility** — `classList` toggle instead of inline style
- **Inline attachment thumbnails** — clickable via global data map + `onclick`; `_openImagePreview` lightbox uses Blob URL instead of blocked `data:` URI navigation
- **Split panel preview** for images (zoom toggle) and PDFs (iframe embed)
- **Terminal PTY on Windows** — guarded Unix-only imports (`fcntl`, `pty`, `termios`) so server starts on Windows; WebSocket returns clear error instead of crash
- **ppxai-desktop version** — added `ppxai.version` hidden import to PyInstaller spec; updated fallback version

### Fixed (late-breaking, 2026-04-12 release day)

Landed after the initial v1.17.4 changelog draft during live release
testing. Pre-merge review by gpt-5.4 and gemini-3-flash surfaced
seven issues (R1–R7); R11 and R13 were discovered during testing;
supporting infrastructure fixes (event bus, session state, debug-log
persistence, disk-scan fallback) all landed this day.

- **R1 — `/attach remove` PDF/Office parity.** The remover only
  handled structured `image_url`/`input_file`/`file` blocks; PDFs
  and Office docs surface as `<uploaded_file>` markers inside text
  blocks and silently slipped through. Remover now walks text
  blocks too, stripping matching markers while preserving
  surrounding user text. ([ppxai/engine/multimodal_ops.py](ppxai/engine/multimodal_ops.py))
- **R2 — `ChatRequest.files` mutable default** → `Field(default_factory=list)`
  in `ppxai/server/models.py`.
- **R3 — `_count_csv_rows_cols` streaming.** Stream-count rows via
  `sum(1 for _ in reader)` instead of `list(reader)`; O(1) memory
  for the count step. (R8 for the full streaming decode lives in
  v1.17.5 TODO.)
- **R4 — `has_vision_model` → `has_vision_sidecar` rename.** The
  name was ambiguous (sidecar config vs. active-model capability).
  Renamed with a back-compat alias on `EngineClient`.
- **R6 — shared `<uploaded_file>` marker helpers** in
  `ppxai/engine/uploaded_file.py`. Single source of truth for
  format + parse + targeted strip; replaces inline regex and
  inline f-strings at 4 sites.
- **R7 — file_id-aware `/attach remove` + ambiguity detection.**
  Accepts name, file_id, short_id (8+ char suffix), or "all".
  Same-name collisions return an AMBIGUOUS warning listing each
  match's short_id instead of silently wiping all matches.
  `refresh_context_attachments` dedup no longer falls back to name
  when `file_id` is empty — two legacy same-name blocks now
  surface as two badges, not silently collapsed into one.
- **R11 — atomic flat↔directory session transition.** Two-layer
  fix: (1) duplicate-format detector in `_resolve_session_load_path`
  logs a WARNING and picks the newer format by mtime when both
  coexist, (2) atomic rename in `_write_session_json` stages the
  directory as `<name>.tmp/` and `os.rename`s into place before
  unlinking the old flat file. A crash between steps is recoverable
  without producing duplicate sessions.
- **R13 — post-write syntax validation to block silent file
  corruption.** All four file-editing tools (`apply_patch`,
  `replace_block`, `insert_text`, `delete_lines`) now run a cheap
  language-specific parser on the candidate content BEFORE
  committing the write. On parse failure the file is left untouched
  and the tool returns a clear error telling the model to re-read
  with more context and retry. Supported: `.py` (`ast.parse`),
  `.json` (`json.loads`), `.yaml`/`.yml` (`yaml.safe_load`),
  `.toml` (`tomllib.loads`), `.js`/`.mjs`/`.cjs` (`node --check`
  best-effort). Others pass-through. Discovered live on 2026-04-12
  with gemini-3.1-pro-preview: `apply_patch` corrupted two files
  and reported "✓ Successfully applied patch" anyway. R14 follow-up
  (Go, Zig, Terraform, TS/Ruby/Shell) tracked for v1.18.x.
- **Textual TUI event bus — coroutine-drop fix.** Handlers registered
  as `lambda s, **kw: _sh.on_stream_end(self, s, **kw)` were sync
  lambdas that forwarded to async functions. The event bus took
  the sync path, the lambda returned a coroutine, Python discarded
  it. `on_stream_end` body never ran → STREAM_END fired but the
  chat view never received `add_assistant_message()`. Symptom: "I
  see status change to Ready but no response text appeared."
  Event bus now detects returned coroutines via
  `asyncio.iscoroutine()` and schedules them with
  `asyncio.create_task`. Regression test pins the exact lambda
  wiring. ([ppxai/tui/event_bus.py](ppxai/tui/event_bus.py))
- **Textual TUI event bus — kwarg mismatch.** Separate pre-existing
  issue exposed during testing: emit passed `sender=self` as a
  kwarg but lambdas expected it positionally, spamming TypeError.
  Fixed to pass positionally.
- **Textual TUI `_check_session_restoration` — undefined
  `status_bar`.** NameError in the restore-branch of
  `tui/app.py::_check_session_restoration`; swapped to
  `self._status_bar`.
- **Session recovery prompt ordering** — moved
  `check_session_recovery()` to run BEFORE provider/model selection
  in `ppxai/rich/main.py`, so a Ctrl+C during selection no longer
  silently skips the prompt. Debug logging added inside the
  recovery function so future regressions leave evidence in
  `tui-debug.log`.
- **Session state — disk-scan fallback.** When
  `~/.ppxai/session-state.json` is missing but saved sessions
  still exist, engine scans `~/.ppxai/sessions/` for the newest
  session (flat or directory format), returns a synthesized state
  with `"recovered_from_disk": true`. Every client picks this up
  for free: Rich, Textual, web (`/sessions/last` + `/sessions/restore`),
  VSCode. Prompt wording in each client distinguishes "state pointer
  missing" from normal auto-restore.
- **Debug-log state persistence.** `/debug-log on` / `/debug-log off`
  now writes `tui.debug_log` to `ppxai-config.json` and is restored
  in `config.initialize()` BEFORE any client code runs. Sets
  `PPXAI_DEBUG=1` environment variable so Loggers created later
  (engine, chat, server) pick it up too. Every client gets
  persistence for free: Rich `/debug-log`, Textual `toggle_debug_logging`,
  Web/VSCode `POST /config/debug-log`. New `docs/debug-logging.md`
  explains the flow.
- **AppState `debug_log` synced from config on startup.**
  `EngineClient.__init__` now calls `get_debug_log_enabled()` and
  `state.set("debug_log", ...)` to match — previously the server's
  file logger was enabled but AppState stayed at default False, so
  the web UI's debug toggle incorrectly showed OFF.
- **read_file** — added `offset` parameter and metadata header
  (`[File: path | N lines total | showing lines X-Y]`) so models
  handle large files without re-reading from the top.

### Deploy (K8s / coder)

- **Dockerfile** — added `[data]` pip extras (pypdf, openpyxl, python-pptx, pdf2image) + `poppler-utils` + `libreoffice-nogui` system packages
- **Data persistence** — `PPXAI_DATA_DIR` moved from ephemeral `/tmp/session` to persistent `/workspace/.ppxai` (workspace PVC with Retain policy)
- **PV affinity** — `SessionMeta.workspace_pv` persists PV name so PVC recreation binds to the correct volume (prevents data loss during namespace churn)
- **deploy.sh resilience** — pre-creates namespace with Helm labels, auto-recovers Reflector-synced secrets (LDAP, TLS) via annotation toggle, auto-creates API key secret from vllm namespace
- **Ingress** — `proxy-body-size: 50m` for file uploads through nginx
- **Login wait** — polling increased from 10s to 60s with progress messages for cold pod starts
- **VL sidecar** — `tools.vision_model` configured for Qwen3-VL-8B-Instruct (auto-caption images on text-only models)

## [1.17.3] - 2026-04-03

### Added

- **CodeMirror modular architecture** — replaced 5 monolithic bundles (6.3MB, each bundling full CM core) with shared `core.min.js` (411KB, loaded once) + 30 per-language addons; lazy-loaded on first use
- **30 editor languages** — native: Python, JavaScript, JSON, YAML, Markdown, HTML, CSS, SQL, Rust, Go, Java, C/C++, XML, PHP; legacy modes: Shell, TOML, Dockerfile, Ruby, Perl, Lua, Swift, R, Kotlin, Scala, PowerShell, Diff, Protobuf, Nginx, CMake, Properties
- **Verbose Tools toggle** — menu indicator in web app `⋮` menu with green-dot active state; SSE `state_sync` push for `tools_verbose` and `debug_log` fields
- **Benchmark K8s jobs** — `--agents-md` toggle, delta test results, in-cluster benchmark runs
- **New models benchmarked** — Qwen3.5-122B-A10B-NVFP4, Qwen3.5-27B-FP8, Qwen3-Coder-Next-NVFP4-GB10

### Fixed

- **DataFileView and MarkdownFileView** — updated to new modular `cm6.newEditor()` API with language parameter; edit mode now gets proper syntax highlighting for JSON, YAML, TOML, Markdown
- **CodeMirror per-language cache** — each language addon self-registers into `cm6.langs`; switching between files in different languages preserves correct syntax highlighting
- **Filename-based language detection** — `Makefile` → shell, `Dockerfile` → dockerfile, `CMakeLists.txt` → cmake
- **Heartbeat stream abort** — skip health failure counting while `isStreaming` is true (single-worker uvicorn can't serve `/health` during LLM streaming)
- **Helm ingress** — skip ingress on upgrade, re-add rule on existing session login, field manager conflict fix, raw REST API for server-side apply
- **Preview relative URLs** — poll and asset paths use relative URLs for K8s ingress compatibility

### Changed

- **TODO consolidation** — 11 files → 2 active (`TODO-appstate-codegen.md`, `TODO-routing.md`) + 4 archived; all open items retargeted to v1.18.x
- **ROADMAP** — added v1.17.0/v1.17.1/v1.17.2 completed sections, v1.18.x planned section
- **Tool failure hints** — improved AGENTS.md hints for tool calling reliability

## [1.17.2] - 2026-03-27

**Focus:** AppState alignment across all 5 clients, thread-safety, SSE state sync, iTerm2 image rendering

### Added

- **SSE state_sync push** — engine pushes `STATE_SYNC` events via SSE side-channel when key AppState fields change (provider, model, tools, agent_mode, working_dir, session_name); web app and VSCode extension update local state automatically
- **Event router pattern** — `EventHandler` and `TUIEventHandler` use strategy dispatch dicts for O(1) event lookup instead of if/elif chains

### Fixed

- **AppState thread-safety** — listeners dispatch outside the lock (was inside RLock); event queue protected by threading.Lock with `enqueue_event()`/`drain_events()` API; fixes race between SSE drain loop and AppState observers
- **Rich TUI AppState alignment** — `get_status_line()` reads all state through AppState; `restore_session_to_handler()` relies on atomic AppState update; `agent_mode` reads from state consistently across Rich and Textual TUI
- **HTTP server AppState alignment** — `GET /status` returns `state.snapshot()`; all provider/model/tools reads in routes use `state.get()`; `ServerCommandContext` reads from `engine.state`
- **ppxaide iTerm2 image rendering** — was incorrectly assigned Kitty Graphics Protocol (TGP); now uses native iTerm2 inline image protocol (OSC 1337) via `ITerm2ImageWidget`
- **ppxaide image display without PIL** — `ITerm2ImageWidget` reads PNG/JPEG/GIF dimensions from file headers via `struct` when Pillow isn't installed; `ImageHandlerFactory` accepts native widget without `textual-image` dependency
- **ppxaide file tree sync** — AppState `working_dir` observer now updates file tree widget; `/cd`, session restore, and engine tool changes all propagate to the file browser
- **Preview `--serve` venv detection** — auto-detect checks `venv/bin/python` and `.venv/bin/python` before falling back to bare `python3`
- **Preview single-quoted commands** — `/preview --serve 'python main.py'` now works alongside double-quoted syntax

### Changed

- **All 17 AppState fields wired** — session usage (tokens, cost, context%) synced via `session.on_usage_updated` callback; session_name via `on_name_changed`; debug_log via Textual toggle
- **Event queue renamed** — `_consent_event_queue` → `_event_queue` with thread-safe `enqueue_event()`/`drain_events()` API
- Removed 16 unused imports across engine, Rich TUI, and Textual TUI modules

## [1.17.1] - 2026-03-23

**Focus:** AppState convergence, web terminal, preview hardening, server dependency injection, client.py decomposition

### Added

- **AppState** (`ppxai/engine/app_state.py`) — canonical observable application state with `subscribe()`/`notify()` pattern; wired into EngineClient, CommandHandler, Textual TUI, Web app, and VSCode extension; 243 unit tests
- **Web terminal** — interactive xterm.js terminal with PTY WebSocket backend; `/terminal`, `/term`, `/sh` commands in web and VSCode clients
- **Preview `--serve` flag** — full-stack preview launches backend process alongside frontend; `ppxai-desktop` serves previews with live backend
- **Preview `--proxy` flag** — K8s full-stack preview via reverse proxy through ingress path prefix
- **Preview K8s ingress detection** — automatic reverse proxy path prefix for K8s ingress compatibility
- **80 new tests** — ops modules (`session_ops`, `provider_ops`, `tool_ops`, `context_ops`) and server routes; graph-analysis-driven coverage

### Fixed

- **Preview route collision** — previewing files in `static/` directories no longer collides with the static file mount
- **Preview absolute URLs** — poll and asset paths in subdirectories now use absolute URLs instead of broken relative ones
- **Preview helpful 404** — previewed HTML making API calls to the preview server now gets an actionable error instead of silent failure
- **Preview python→python3** — macOS compatibility fix; backend stderr surfaced on failure
- **SSE keepalive** — reduced from 15s to 5s to prevent false disconnect detection in browsers
- **Consent route crash** — undefined `x_session_id` variable in consent route handler
- **Sessions route** — variable collision in `get_sessions` route
- **Web preview iframe** — URL encoding and sandbox warning fixes
- **Terminal WebSocket 403** — event loop fd reader for PTY output; HTTP middleware now skips WebSocket upgrades
- **Lazy imports** — 3 + 2 remaining lazy imports moved to module level (DAG compliance)
- **Swallowed exceptions** — logging added to 8 previously silent exception handlers

### Changed

- **`client.py` decomposition** — monolith split into ops modules: `session_ops.py`, `provider_ops.py`, `tool_ops.py`, `context_ops.py`; client.py reduced to facade
- **FastAPI dependency injection** — session resolution extracted from route handlers into FastAPI `Depends()` dependencies
- **`reload_config` consolidation** — scattered reload calls consolidated into `get_or_create_session`
- **`stream_handler.py` extraction** — stream handling logic extracted from Textual `app.py`
- **`constants.Default` centralization** — magic numbers (keepalive interval, debounce delay, max retries, etc.) moved to `constants.Default` enum
- **`CommandContext.__getattr__` proxy** — adapter boilerplate in command handlers replaced with attribute proxy
- **Web command help** — updated for `/terminal`, `/preview --serve`/`--proxy`, `/config` commands

## [1.17.0] - 2026-03-19

**Focus:** Server/config modularization, K8s deployment POC, key bindings registry, Textual 8.1.1, import DAG cleanup

### Added

- **Server modularization** — `http.py` (2,936 lines) split into 13 route modules under `server/routes/` + shared `state.py`, `models.py`, `streaming.py`; facade reduced to 372 lines
- **Config modularization** — `config/__init__.py` (943 lines) split into `providers.py`, `tools.py`, `features.py`, `paths.py`, `prompts.py`, `context.py`; hub reduced to 262 lines
- **K8s deployment POC** (phases 1-5) — namespace, StorageClasses, in-cluster registry, Kaniko builds, session manager (FastAPI + k8s SDK), login service, LDAP auth, Helm chart
- **Key bindings registry** (`ppxai/tui/keys.py`) — single source of truth for all 32 keyboard shortcuts; widget BINDINGS generated via `get_widget_bindings()`; `/keys` and `/keys conflicts` commands
- **Protocol-based dependency inversion** — `ToolEngineProtocol` and `ToolManagerProtocol` in `engine/types.py`; all 9 tool modules use direct protocol imports instead of TYPE_CHECKING
- **Client log forwarding** — server-side log forwarding from web/VSCode clients
- **Web heartbeat watchdog** — stale connection detection
- **Benchmark: qwen2.5-coder-7b** — LM Studio eval (69.4% / 72.2% with AGENTS.md); multi-model routing plan
- **Shared deploy configs** — `deploy/shared/` with AGENTS.md and ppxai-config for k8s deployments
- **AppState architecture docs** — 6-part TODO series for cross-client state management

### Fixed

- **Web streaming layout thrashing** — RAF-based rendering prevents layout recalculation storms
- **Preview panel freeze on display_file** — concurrent file display requests handled properly
- **Preview URLs for reverse proxy** — all URLs now relative (works behind ingress path prefix)
- **Stale session detection** — verifies pod exists before returning "existing"
- **Tool fixes** — container.py and display.py error handling improvements

### Changed

- **Textual 8.1.1** — upgraded from 7.4.0 (DirectoryTree threading fixes, weak-ref DOM, GC improvements)
- **Lazy import cleanup** — ~70 imports moved to top-level across 30+ files; all 14 TYPE_CHECKING blocks eliminated
- **install.ps1** — Windows installer rewritten
- **VSCode extension** — chatPanel and httpClient improvements
- **display-only ctrl+enter** — replaced empty action string hack with explicit `action_noop()`

## [1.16.2] - 2026-03-07

**Focus:** Web app RightPanelFrame, file tree sidebar, inline images, web refactor, server fixes

### Added

- **Web app: RightPanelFrame** — view stack navigator with LRU eviction, dedup, back/forward navigation, pin, and position indicator; full Playwright coverage (34 tests)
- **Web app: view types** — `CodeEditorView` (unified view/edit with CodeMirror 6), `MarkdownFileView` (rendered/source/edit), `DataFileView` (table/tree for CSV/JSON/YAML/TOML/HCL), `ImageFileView` (click-to-zoom), `PdfFileView` (embedded iframe)
- **Web app: collapsible file tree sidebar** — VSCode-style browser; lazy-load via `/files/list`, drag-to-resize, left-click preview, right-click `@file` inject, `localStorage` state persistence; `..` parent entry at top, double-click dir to cd into it, right-click dir to cd here; `/files/list` response includes `at_fs_root` flag
- **Web app: inline image preview** — images in chat bubbles render inline; click to open lightbox zoom overlay
- **Web app refactor** — `ApiClient` for all fetch calls, `CommandDispatcher` (slash command routing), `StreamHandler` (proper buffer/RAF rendering), `AppState` (centralised state), virtual scroll (60-message window)

### Fixed

- **Web app: side panel saves to wrong path** — `/files/read` returned `path.name` (basename); now returns relative path from working dir; `app.js` prefers original `filepath` over `data.filename` in editor
- **Validator false positive on apology** — `_claims_success()` now returns `False` immediately when response contains apology phrases ("apologies", "you are right", "I missed", etc.)
- **Inline `<think>` block parsing** — Qwen3 via vLLM: inline thinking blocks now routed to `REASONING_CHUNK` events instead of leaking into response text
- **Three post-release bugs** — `Key.ctrl` binding removed (Textual deprecation), `initResizeHandle` null crash when sidebar element missing, stale file tree paths after working dir change
- **Stale session pointer** — last-session pointer now cleared if session file has been deleted
- **Absolute/home paths in file API** — `/files/list` and `/files/tree` accept absolute paths and `~`-prefixed paths
- **Default working dir** — engine working dir now initialised to `Path.home()` on session creation (fixes binary CWD being `/`)
- **Redundant `set_model` calls** — `/provider` switch no longer triggers 3–4 redundant `set_model` calls
- **File tree refresh storm** — `working_dir_changed` events debounced (300ms); session restore no longer triggers multiple `/files/list` calls
- **Validator false positive: success-after-retries** — `_check_success_after_failure` now only flags when the *most recent* tool call failed; earlier failures in a retry sequence no longer cause false `claim_contradicts_result` errors
- **Shell: configurable shell binary and login mode** — new `tools.shell.shell_bin` (e.g. `"/bin/zsh"`) and `tools.shell.login_shell` (bool) config keys; setting `login_shell: true` invokes the shell with `-l` so the full user environment (PATH, nvm, pyenv, etc.) is sourced, matching the user's interactive terminal
- **Inline image disappears after stream_end** — `stream_end` now appends inline image markdown to the server's text response rather than overwriting `fullContent`
- **Redundant display_file tool result bubble** — `showToolResult` now skips the bubble when `data.tool === 'display_file'`; image is already visible inline and non-image files open in RightPanelFrame
- **Stale expandedDirs after cd** — `FileTreeComponent.refresh(clearExpanded=true)` collapses old subpaths on working dir change, eliminating 404 storms and doubled path segments
- **File tree flickers on every chat send** — `working_dir_changed` debounce now skips refresh when path hasn't changed; session restore replays the same cwd causing needless `refresh(true)` calls
- **AI text inserted above inline image** — `stream_end` now renders inline images before the AI text response, matching the order shown during streaming

### Changed

- **Default models updated** — `ppxai-config.json`: sonar-pro (Perplexity), gemini-3-flash-preview (Gemini), gpt-4.1-mini (OpenAI default), gpt-5.1-codex-mini (OpenAI coding)
- **AGENTS.md** — Qwen3-4B model hints added; provider hints expanded for `local`, `asusai-vllm`, `openai`, `gemini`; global preferences reorganized

## [1.16.1] - 2026-03-01

**Focus:** FileTree browser, CommandFactory server pattern, unified session restore, pre-release tech debt

### Added

- **FileTree widget** (`ppxai/tui/widgets/file_tree.py`) — Norton Commander-style file browser in ppxaide; `Ctrl+B` toggle, `Enter` preview, `Ctrl+Enter` edit, `Space` injects `@file:path` into chat input; 28 unit tests
- **CommandFactory server pattern** — `POST /command` HTTP endpoint routes to same `CommandFactory` used by TUI/CLI; `/usage` unified across TUI, VSCode, and Web clients
- **`EngineClient.restore_session()`** — single authoritative session restore covering provider, model, tools, and working_dir; fixes JSON-RPC client never restoring provider/model

### Fixed

- `TypeError: 'bool' object is not iterable` in Codex Responses API (`_non_stream_responses` iterated `item.content` which can be `True`)
- SSE exception handlers now log full traceback unconditionally; `sse_coding_task_generator` had no exception logging at all
- Pre-flight `validate_and_fix_alternation()` before provider call — prevents recurring 400 errors from Perplexity and other strict providers on malformed session history
- `ppxai-server` binary crash on startup (`prompt_toolkit` was incorrectly excluded from PyInstaller spec)
- Side panel silently discarded unsaved edits on close — now prompts to save
- `Ctrl+Enter` in FileTree blocked by app-level priority submit binding
- Duplicate provider/model switch log entries
- `STREAM_START` event missing in some `chat_simple` code paths
- `GeminiProvider` deprecated `thinking_budget` → `thinking_level`

### Changed

- Lazy imports eliminated from `engine/context.py`, `engine/session.py`, `server/http.py`, `server/jsonrpc.py`, and Rich TUI client modules (DAG-style imports throughout)
- 6 regex patterns replaced with more robust alternatives: filename detection handles dotfiles + multi-dot names; markdown link parser uses bracket/paren depth counting; success-claim detection uses keyword set + proximity window; tool JSON detection uses `_find_json_objects()`; Rich markup stripping preserves citation markers `[1]`/`[2]`; inline formatter uses linear pass (code > bold > italic priority)
- `RichRenderer` gains `ConsentResult` and `PromptResult` renderers (were silently missing)

## [1.16.0] - 2026-02-26

**Focus:** Profile-driven tool loop, multi-tool support, agent UI improvements, benchmark v2

This release rewrites the core tool calling loop in `chat.py` with profile-driven routing,
proper `tool` role messages, multi-tool support, and grouped tool call UI across all 4 clients.
154 files changed, 30,400+ lines added. 1,536 tests passing.

### Added - Provider Hierarchy (Step 1)

- **`BaseProvider` ABC** — all providers inherit shared interface; `hasattr` guards eliminated
- **`get_capabilities_for_model()`** — guaranteed method on all providers
- **61 provider hierarchy tests** (`test_provider_hierarchy.py`)

### Added - Profile-Driven Tool Loop (Step 2)

- **Profile-driven mode routing** — `ToolCallingProfile.mode` ("native", "prompt_based", "auto") replaces binary `native_tool_calling` decision; provider capabilities gate native mode
- **Fallback on empty/failure** — configurable retry with prompt-based messages when native returns empty or unknown tool
- **Belt-and-suspenders** — models with fallback flags get tool descriptions injected into system prompt even in native mode
- **Truncation recovery** — raw JSON truncation detection, escalating recovery messages, `MAX_TRUNCATION_RETRIES=3` cap with `stuck_tool_loop` WARNING event
- **27 profile routing + truncation tests** (`test_chat_profile_routing.py`, `test_engine_tool_parsing.py`)

### Added - Proper Tool Messages (Step 3)

- **Native `tool` role messages** — `assistant` (with `tool_calls` field) + `tool` role result messages replace synthetic assistant/user pairs
- **`Message` type extended** — `tool_calls` and `tool_call_id` fields on `Message` dataclass
- **All 4 providers updated** — `_convert_messages()` handles `tool` role in base, openai_native, openai_compat, gemini
- **Session serialization** — save/load handles new fields; v1.15.x sessions load via `None`-safe `.get()`
- **28 tool message tests** (`test_tool_messages.py`)

### Added - Multi-Tool Support (Step 4)

- **All native tool calls processed** — `for tc in tool_calls_list` replaces `native_tool_calls[0]`
- **`parallel_tool_calls` gating** — profile flag controls whether all or only first tool call is processed
- **Sequential execution** — per-tool consent and loop detection for each call in a batch

### Added - Agent UI Noise Reduction (Step 5)

- **`TOOL_GROUP_START`/`TOOL_GROUP_END` events** — engine wraps each iteration's tool calls for client-side grouping
- **`AGENT_COMPLETE` event** — emitted after tool loop with iteration count and commit hash
- **Web app** — collapsible `.tool-group` containers, checkpoint bubble suppression, undo badge only on commits
- **VSCode extension** — tool group forwarding and CSS styling
- **ppxaide TUI** — non-verbose summary mode (one line per group); verbose mode unchanged
- **ppxai Rich CLI** — dim separator lines with iteration number and status
- **SSE event type dispatch fix** — side-channel events emit correct EventType (was all `consent_request`)
- **Consent deadlock fix** — SSE generator uses racing poll pattern instead of `async for`

### Added - Config Integration (Step 6)

- **Per-model `tool_calling` overrides** — 3-layer precedence: built-in profile → AGENTS.md → ppxai-config.json
- **AGENTS.md `tool_calling` YAML section** — glob-pattern matching for model-specific tool calling config
- **`/model info` command** — shows effective profile with source attribution per field
- **16 config + bootstrap + profile merging tests**

### Added - Benchmark v2 (Step 7)

- **36 tests across 9 categories** — hallucination_resistance, tool_calling, code_editing, format_compliance, instruction_following, reasoning, error_recovery, agentic_tool_loops, efficiency
- **8 new agentic tests** — `patch_apply_verify`, `search_then_edit`, `fix_verify`, `information_gathering`, `error_recovery_chain`, `multi_file_review`, `claim_without_action`, `consecutive_tool_loop`
- **Efficiency metrics** — `time_to_first_tool_call`, `tool_call_efficiency` scoring by redundant calls
- **Partial credit scoring** — `score` field (0.0-1.0) with per-test weighting
- **`_dedup_tool_call()` helper** — returns feedback for duplicate tool+args in multi-turn tests
- **AGENTS.md delta testing** — `--agents-md both` mode runs suite twice and reports per-category delta
- **Token/tool call tracking** — `total_tokens`, `total_tool_calls` in `BenchmarkResult.metadata`
- **29 models ranked** across 100+ benchmark runs

### Added - Commands

- **`/ls` command** — directory listing in all 3 clients (ppxaide TUI, Web, Rich CLI)
- **`/tree` command** — directory tree in all 3 clients
- **`GET /files/list`** and **`GET /files/tree`** HTTP endpoints for IDE integration

### Added - Session Management

- **Session context reset on model switch** — `session.reset_for_model_switch()`
- **Per-model iteration limits** — `ModelProfile.max_tool_iterations` field consulted by `chat.py`
- **Session pollution detection** — bigram similarity >90% triggers WARNING after iteration 1
- **SSE disconnect detection** — `request.is_disconnected()` in `sse_event_generator`

### Changed

- **Sonar model profiles** — all sonar profiles changed to `mode="prompt_based"` (matching Perplexity API capabilities)
- **Sonar/Perplexity AGENTS.md hints** — rewritten for prompt-based tool calling
- **Gemini 3.1 model profiles** — tier S→A, `max_tool_iterations` 25→20, `strip_json_from_text=True`
- **Default models** — optimized for cost and new-user experience
- **`contradiction_detection` test** — check acknowledgment patterns before contradictions (fixes negation false positives)

### Fixed

- **Tool usage tracking** — accumulated usage now includes tool call costs in final STREAM_END metadata
- **Provider pricing** — corrected pricing across all provider configs
- **ppxaide binary** — fixed missing tree-sitter syntax highlighting in PyInstaller build
- **Usage report** — fixed missing prompt/completion token breakdown

---

## [1.15.6] - 2026-02-19

### Added - Native OpenAI Provider

- **`OpenAINativeProvider`** (`ppxai/engine/providers/openai_native.py`) — Standalone provider for OpenAI API
  - Chat Completions API for GPT-4.1, GPT-5.x, o-series models
  - Responses API for Codex and Pro models (gpt-5.1-codex, gpt-5.2-pro)
  - Automatic `max_completion_tokens` handling for GPT-5.x and o-series
  - Restricted generation param stripping (temperature, top_p rejected by newer models)
  - Reasoning token extraction for o-series models
  - Native function calling with streaming tool call assembly
  - 404 auto-fallback: Chat Completions → Responses API when model isn't a chat model
  - Web search via `web_search_preview` tool (Responses API, opt-in)
- **46 unit tests** for native OpenAI provider (model classification, message conversion, streaming, error handling, prompt-based routing)
- **AGENTS.md hints** for OpenAI provider and model-specific hints (gpt-5.2, gpt-5, gpt-4.1, o4-mini, codex)

### Added - Model Profile System (Foundation for v1.16.0)

- **`model_profiles.py`** (`ppxai/engine/model_profiles.py`) — `ToolCallingProfile` and `ModelProfile` dataclasses encoding per-model tool calling strategy, API routing, max_tokens, and benchmark tier
- **`ModelProfileRegistry`** — Glob-pattern matching registry (case-insensitive, first match wins)
- **37 built-in profiles** covering all benchmarked models: OpenAI (14), Perplexity (5), Gemini (5), DGX/vLLM Qwen3 (5), Ollama Qwen (3), GPT-OSS (1), legacy GPT-4o (2), reasoning o-series (5)
- **`get_model_profile()`** method added to `BaseProvider`, `OpenAINativeProvider`, and `GeminiProvider` (scaffolding for v1.16.0 profile-driven tool loop)
- **41 model profile tests** — profile matching, glob patterns, shadowing prevention, tier validation, data integrity

### Added - Tool Call Parser Improvements

- **Brace-counting JSON parser** (`_find_json_objects()`) — Replaces regex-based extraction; correctly handles nested braces in `apply_patch` diffs containing code with `{` and `}` characters
- **`strip_tool_json_from_text()`** — Strips duplicate tool call JSON from response text when native `tool_calls` are present (Gap 4: tool_json_in_content anti-pattern), also strips surrounding markdown code fences
- **`detect_truncated_tool_call()`** — Detects "I'll use X tool" + incomplete JSON patterns for targeted retry feedback

### Added - Benchmark System Improvements

- **Benchmark results** for 27 model variants (54+ runs across 7 categories, 26 tests each)
- **Model behavior analysis** (`docs/model-behavior-analysis.md`) — 5 behavior tiers (S/A/B/C/D), per-category scores, 5 architectural gap findings
- **`--tool-calling-method`** CLI flag — Force `native`, `prompt_based`, or `auto` mode per benchmark run
- **`--debug`** flag — Saves per-request JSON to `debug/` with full AI response content, tool_calls, and errors
- **Profile-aware benchmark runner** — Consults `ModelProfile` for native vs prompt-based routing
- **Engine bypass** — Benchmark runner calls provider directly, avoiding engine tool conflicts
- **Prompt-based scoring fix** — `tool_json_in_content` penalty removed for prompt-based mode (expected behavior)

### Added - Packaging

- **Windows ZIP packager** (`scripts/package-windows-zip.ps1`) — Creates offline deployment ZIP with binaries + web UI for air-gapped environments

### Added - Response Validation & Debug Improvements

- **Read-claim validator** (`_check_read_claims_without_tools()` in `validator.py`) — Detects "I read each file" / "reviewed all files" claims when 0 `read_file` tool calls were made; 6 regex patterns + 5 tests
- **Truncation retry `[SYSTEM: ...]` framing** — Retry messages now use system framing instead of conversational text to prevent models from misinterpreting retries as conversation

### Changed

- **OpenAI provider registration** — `openai` provider now uses `OpenAINativeProvider` instead of `OpenAICompatibleProvider`; openrouter, local, custom providers unchanged
- **`PROMPT_BASED_MODEL_PREFIXES`** — Renamed from `PROMPT_BASED_MODELS`, changed from exact match (`in`) to prefix match (`.startswith()`) so dated model IDs like `o4-mini-2025-04-16` get correct prompt-based routing
- **Benchmark engine runner** — Loads AGENTS.md hints from all scopes (global, project, subdir) matching real client behavior
- **Retired Gemini 2.0 Flash models** — Removed from default config (expired preview models)
- **gpt-5-nano max_tokens** — Increased from 2048 to 8192 to prevent empty synthesis after tool iterations
- **codex-mini tuning** — Profile: added `strip_json_from_text`, `fallback_on_empty`, `restricted_params`, tier C→B; AGENTS.md: anti-hesitation hint; config: `max_tokens: 16384`
- **gemini-3-pro tier** — Changed S→A (best benchmark 73.1%, below S threshold of 80%)

### Fixed

- **AGENTS.md hints for native providers** — Bootstrap/AGENTS.md hints were only injected for prompt-based mode; now injected for ALL providers (P1)
- **`bootstrap_prompt` NameError** in benchmark debug logging — Variable was never defined in scope; replaced with `system_content`
- **ppxaide `/debug-log on`** — Was toggling in-memory flags only; now calls `Logger.enable_all()` / `Logger.disable_all()` to actually enable file logging
- **Codex native tool calling** — Removed `_is_responses_api_model()` from prompt-based override; added belt-and-suspenders tool hint injection for Responses API models

### Documentation

- **v1.15.6/v1.16.0 release plan** (`docs/archive/RELEASE-PLAN-v1.15.6-v1.16.0.md`) — Phased release strategy, P0-P4 backlog, v1.16.0 breaking changes roadmap
- **Debug session archive** (`docs/archive/ARCHIVE-v1.15.6-debug-sessions.md`) — 5 debug sessions, 23 items (A0-A14, C1-C9), key discoveries
- **DGX Spark setup guide** — Sanitized, removed sensitive info and Ollama references

---

## [1.15.5] - 2026-02-15

### Changed - Multi-Line Chat Input (Breaking UX Change)

- **Multi-line input in ppxaide** - Input box now uses TextArea widget instead of single-line Input
  - **Enter** inserts a newline (allows multi-line messages, code blocks, etc.)
  - **Ctrl+Enter** submits the message (shown in footer for discoverability)
  - Auto-expands from 1 line up to 18 lines as content grows, then shows scrollbar
  - All existing functionality preserved: command history (Up/Down), tab completion, focus management
  - Design rationale: Shift+Enter was tried first but many terminals cannot distinguish it from Enter

### Fixed - Escape Key Handling

- **Escape key properly dismisses UI elements** - Priority-based dismissal: help panel > modal screens > side panel
  - `action_cancel()` rewritten with clean priority chain
  - `on_key()` used instead of `_on_key()` in ChatTextArea — allows Escape to bubble up to app-level handlers
  - `q` key binding added to close help panel (common convention)
  - Command palette re-enabled (was temporarily disabled during debugging)

### Fixed - Build

- **PyInstaller `blinker` hiddenimport** - Added `blinker` to `ppxaide.spec` to fix `ModuleNotFoundError` when running ppxaide binary (required by EventBus)

### Changed - Benchmarks

- **`tool_calling_method` metadata** - Benchmark results now record whether native or prompt-based tool calling was used
- **Comprehensive BENCHMARKS.md guide** - 700+ line guide covering all 7 test categories (28 tests), scoring, analysis tools
- **Legacy benchmark files archived** - 15 old JSON files moved to `benchmarks/llm-eval/docs/archive/legacy/`

### Housekeeping

- **Removed 7 debug notifications** from `action_cancel()` that were added during Escape key development
- **15 new multi-line input tests** - ChatTextArea, Ctrl+Enter binding, submit handler, history preservation
- **`native_tool_calling: true`** added to OpenAI/OpenRouter in example config
- **`RELATED-PROJECTS.md`** added documenting ppxai ↔ ppxai-sre relationship
- **TODO-v1.15.3.md** marked as complete

---

## [1.15.4] - 2026-02-13

### Added - Live HTML Preview (`/preview` command)

- **`/preview` command** - Live-reloading HTML preview across all 3 clients
  - **TUI**: Stdlib `PreviewServer` (http.server + threading), auto-opens browser
  - **Web App**: Iframe with `/preview/{filepath}` endpoint, split panel UI
  - **VSCode**: `WebviewPanel` with `FileSystemWatcher` for live reload
- **`PreviewServer`** (`ppxai/preview_server.py`) - Standalone HTTP server with mtime polling at `/poll`
- **`rewrite_asset_paths()`** - Cache-buster support appending `?_t=<mtime>` for reliable CSS/JS/JSON live-reload
- **`inject_reload_script()`** - Auto-injects polling JavaScript into preview HTML
- **`resolve_preview_path()`** - Resolves preview file paths with security validation
- **FastAPI endpoints** - `/preview/poll/{path}`, `/preview/static/{path}`, `/preview/{path}` with session-scoped working directory
- **Non-HTML asset serving** - Preview iframe `fetch()` for JSON/CSS/JS files now served correctly via `FileResponse`
- **Session resolution from Referer** - JS `fetch()` calls from preview iframe resolve session from Referer header

### Added - VSCode Extension Improvements

- **Consent EventBus migration** - Consent dialog handling moved to EventBus pattern
- **Preview auto-refresh** - `FileSystemWatcher` monitors CSS/JS/JSON/SVG/PNG/JPG siblings for live reload
- **Autocomplete fixes** - Improved slash command autocomplete reliability
- **highlight.js rebuild** - Added PowerShell, Dockerfile, DOS, AppleScript language support

### Fixed - Web Tools & SSL

- **Corporate SSL support** - New `_create_ssl_context()` respects `SSL_VERIFY` and `SSL_CERT_FILE` env vars
- **`get_weather` HTTP fallback** - Tries HTTPS first, falls back to HTTP when corporate proxy stalls HTTPS
- **Configurable web tool timeouts** - `tools.<name>.timeout` in ppxai-config.json (default 15s)

### Fixed - Debug Logging

- **`/debug-log on` enables ALL logger instances** - Previously only enabled "tui" logger
- **`Logger.enable_all()` / `Logger.disable_all()`** - Class methods for centralized log control across all components

### Fixed - Session & Provider

- **Session restore** - Correctly restores provider/model from session metadata
- **Gemini provider** - Fixed content handling for tool responses with None content

### Added - Benchmarks & Testing

- **Qwen3-Coder-Next FP8 benchmarks** - 3 benchmark runs with per-category analysis
- **Model evaluation summary** - Comparative table across 7 tested models
- **34 new preview tests** - Covering utilities, server, cache-busting, and data file serving
- **16 new SSL tests** - Corporate proxy, timeout, and fallback scenarios
- **Total tests: 1,227 passing**

### Documentation

- **RELEASE-NOTES-v1.15.4.md** - Complete release documentation
- **archive/v1.15.4/PLAN-live-html-preview.md** - Implementation plan for preview feature
- **archive/v1.15.4/BUGFIX-WEB-TOOLS-CORPORATE-SSL.md** - Updated from planned to fixed status

---

## [1.15.3] - 2026-02-07

### Fixed - Config Hot-Reload & DAG-Based Initialization

- **Config hot-reload** - `/model` and `/provider` commands now auto-reload config from disk
  - All 3 clients (TUI, Rich, HTTP server) reload config before restoring sessions
  - HTTP + JSON-RPC endpoints reload before listing/switching providers/models
  - Fixes stale config cache when config file is edited externally
  - Root cause: ConfigStore singleton + EngineClient snapshot pattern caused stale references
- **DAG-based config initialization** - Replaced `__getattr__` lazy loading with explicit `initialize()`
  - Module-level PROVIDERS/MODELS dicts populated at startup
  - In-place mutation (`.clear()` + `.update()`) ensures all references stay fresh
  - EngineClient uses `@property providers_config` instead of snapshot
  - Removed 4 workarounds (deferred imports, manual re-fetches)
  - Added `reset_config_after_test` fixture for test isolation
  - All 1157 tests pass (100% pass rate)
- **New `EngineClient.reload_config()` method** - Single entry point to refresh all cached config data
  - Refreshes ConfigStore + shell/agent configs
  - Automatically called by `/config reload` command

### Fixed - Platform Alignment (Windows/macOS/Linux)

- **Signal handling** - SIGINT (Ctrl+C) and SIGTERM now work on all platforms including Windows
  - Removed Windows exclusion for signal handlers
  - TUI gracefully shuts down on both signals across all platforms
  - Uses `call_from_thread()` for thread-safe quit action
- **Binary search path filtering** - Platform-aware filtering for efficiency
  - Windows skips `/usr/*` paths (Unix-only)
  - Unix/macOS/Linux skip `AppData` paths (Windows-only)
  - Desktop app uses filtered paths from config
- **Path expansion standardization** - Standardized to `Path.home()` for internal paths
  - Intentional `os.path.expanduser()` kept only in tool handlers (supports `~username` syntax)
  - Consistent path handling across all platforms

### Fixed - TUI EventBus Stability

- **WARNING event handler** - Added ENGINE_WARNING event handler for hallucination detection alerts
  - Displays validation warnings in chat with yellow ⚠ indicator
  - Completes v1.15.2 response validation system integration with TUI
  - Fixes "Unhandled event type: EventType.WARNING" debug messages
- **EventBus handler resilience** - Added NoMatches guards to all event handlers
  - Prevents crashes when handlers fire before chat_view is mounted
  - Fixes "No nodes match '#chat-view'" errors during startup/shutdown
  - Protected handlers: `_on_tool_call`, `_on_tool_result`, `_on_tool_error`, `_on_engine_error`, `_on_engine_warning`, `_on_engine_info`
- **Shell consent dialog threading** - Verified correct implementation using `call_from_thread()` + callback pattern
  - No `wait_for_dismiss` usage (follows Textual best practices)

### Fixed - Engine & Performance

- **Model hints debug noise** - Removed verbose "no model hints matched" messages
  - Only logs when hints ARE matched, not when they aren't
  - Reduces duplicate log messages during session restoration and model switching
  - Available patterns still visible via `/context show` command
- **Working directory change deduplication** - Only emit WORKING_DIR_CHANGED event when directory actually changes
  - Compares resolved paths to prevent duplicate events
  - Fixes double events from temporary cwd switches during tool execution

### Added - Benchmarks & Testing

- **DGX Spark benchmarks** - Added benchmark results for local models
  - GPT-OSS-120B, Qwen3-30B-A3B, Qwen2.5-Coder-32B tested
  - Results tracked in `benchmarks/llm-eval/results/`
  - Hallucination resistance gate tests added

### Documentation

- **installation.md** - Added platform-specific notes section
  - Clipboard support requirements per platform
  - Signal handling (Ctrl+C, SIGTERM) on all platforms (v1.15.3+)
  - Linux headless requirements (`xclip`/`xsel`)
- **MEMORY.md** - Added v1.15.3 critical patterns:
  - Pattern #8: TUI EventBus Handler Resilience
  - Pattern #9: WARNING Event Handling
  - Pattern #10: Working Directory Change Deduplication
- **RELEASE-NOTES-v1.15.3.md** - Complete release documentation with implementation details

---

## [1.15.2] - 2026-02-06

### Added - Gemini Native Tool Calling

- **Native function calling** - Gemini provider now uses `function_declarations` instead of prompt-based tool calling
  - Converts OpenAI tool format to Gemini format with `_convert_tools_to_gemini()`
  - Handles tool calls in streaming and non-streaming modes
  - Default capabilities include `native_tool_calling=True`
  - Backward compatible - prompt-based mode works with `native_tool_calling: false`
- **Gemini generation params** - Loads `temperature`, `top_p`, etc. from `ppxai-config.json`
- **Perplexity generation params** - Also loads generation params from config
- **Workaround for web search** - `web_search` tool now available for Gemini in agent mode
  - Uses premium search (Perplexity → Gemini grounding API → DuckDuckGo fallback)
  - Separate grounding-only API call when agent needs web data
- **Limitation:** Multi-tool use (GoogleSearch + function_declarations) requires Live API
  - Standard `generate_content` API cannot mix grounding with tools

### Added - LLM Benchmark Suite

- **Comprehensive benchmark suite** (`benchmarks/llm-eval/`) - 6 test categories, 21+ test cases
  - `hallucination_resistance` - Gate tests for basic reliability (must pass 100%)
  - `tool_calling` - Native tool execution accuracy
  - `file_editing` - apply_patch, replace_block, insert_text
  - `code_generation` - Generate working code from descriptions
  - `multi_step_tasks` - Complex multi-step agent workflows
  - `error_recovery` - Handle failures and retry
- **Generation params from config** - Benchmarks load `temperature`, `top_p` from `ppxai-config.json`
- **Engine runner** - Benchmark evaluation using ppxai Engine (not subprocess)
- **Test ordering** - `hallucination_resistance` runs first as gate tests

### Added - ppxaide TUI Improvements

- **Streaming cancellation** - Ctrl+C during streaming gracefully cancels the response
- **SIGINT handler** - Graceful shutdown on Ctrl+C for Linux/macOS
- **Trace logging mode** - `--trace` flag for verbose per-event logging (separate from `--debug`)
- **Performance optimization** - Network file crash fix (WinError 4350 on DFS paths)
- **StatusBar refactoring** - Extracted helpers (`_format_cwd_display`, `_update_checkpoint_badge`)

### Added - Response Validation & Hallucination Detection

- **ResponseValidator class** (`engine/tools/validator.py`) - Detects when LLM models:
  - Claim success after tool failures (e.g., "I've created the file" when write_file returned error)
  - Claim file operations without calling appropriate tools
  - Output tool call JSON as text instead of making actual calls
  - Fabricate output that looks like tool results (fake shell listings)
- **WARNING event type** - New SSE event for real-time validation warnings to clients
- **Web app warning display** - Styled warnings with severity, message, details, and suggested actions
- **Enhanced tool system prompt** - 5 new critical instructions for tool result validation:
  1. Always check tool results before claiming success
  2. Never claim file creation without tool confirmation
  3. Must call display_file when asked to display files
  4. Must use execute_shell_command for shell commands
  5. Call tools directly, never output JSON in response text

### Added - Terminal Features

- **`/terminal` command** - Shows terminal detection and image protocol config help
- **`PPXAI_TERMINAL` and `PPXAI_IMAGE_PROTOCOL`** - Environment variables for multi-terminal setups
- **Double Ctrl+C to quit** - Pattern in ppxaide prevents accidental exits

### Fixed - VSCode display_file Integration

- **EventBus architecture completion** - Fixed display_file tool in VSCode extension
  - Files now open in editor tab (ViewColumn.Beside) instead of chat window
  - Added missing `display_file` case in `httpClient.mapServerEvent()`
  - Completed incomplete EventBus refactoring - `handleStreamEvent()` now calls `processStreamEvent()`
  - Added `processDisplayFile()` in `stream.ts` and `stream:display_file` event type
  - Root cause: EventBus infrastructure existed but wasn't connected
- **Lesson learned:** Incomplete refactoring can leave both old and new code paths active

### Fixed - Unicode Whitespace & Tool Calling

- **Unicode whitespace normalization** in `apply_patch` - NBSP (`\xa0`), NNBSP (`\u202f`), Thin Space now match regular spaces
- **5-level fuzzy matching** in `_replace_hunk()`: exact → CRLF → Unicode normalize → strip+normalize → collapse
- **Truncated tool call detection** - Detects "I'll use X tool" with incomplete JSON and provides recovery feedback
- **GPT-OSS intermittent tool calling** - Auto-retry with targeted guidance when vLLM Harmony parser fails

### Fixed - Configuration & UI

- **Autocomplete** preserves command prefix for subcommands (`/provider ` + TAB works)
- **`/status`** shows terminal override indicators when env vars are set
- **Config loader** now includes all config sections (`server`, `session`, `tui`, `paths`, etc.)
- **`server.idle_timeout`** config now properly read (was always using 300s default)
- **Web app `/context reload`** shows correct message instead of false "not found"
- **Web app clipboard button** now uses correct global reference (`window.ppxai`)
- **Web app `display_file` event** now handled properly (opens split preview)

### Documentation

- Comprehensive terminal image display guide in installation.md
- GPT-OSS "explain before calling" tool issue and `max_tokens` mitigation

### Technical

- **Gemini provider:** `_convert_tools_to_gemini()`, `_parse_function_call()`, generation params support
- **Benchmark suite:** 20+ test cases across 6 categories, engine runner integration
- **StatusBar helpers:** `_format_cwd_display()`, `_update_checkpoint_badge()` extracted
- **EventBus logging:** Now tied to `--trace` mode instead of `--debug`
- **Network file handling:** OSError exception handling for DFS/network paths (WinError 4350)
- **Validation system:** `ValidationResult` enum, `ValidationWarning` dataclass, 27 new tests
- **Test coverage:** 20 new tests for Unicode normalization, 20 for truncation detection
- **Total tests:** 1,105 passing tests

---

## [1.15.1] - 2026-01-29

### Added - AI Tool Integration

- **`display_file` tool** - AI can now proactively show files after generating/modifying them
  - Works across all clients: ppxaide (Textual TUI), ppxai (Rich TUI), VSCode, Web
  - Reuses existing `/show` command infrastructure - no parallel event systems
  - INFO event with `execute_command` metadata triggers client-side `/show` command
  - Graceful degradation: clients without interception just show the INFO message

### Fixed - ppxaide TUI Performance

- **UI responsiveness during streaming** - Worker threads with `call_from_thread()` prevent event loop blocking
  - UI stays responsive during 30+ second HTTP waits
  - Scrolling, history navigation work during streaming
  - Footer status widget shows live elapsed timer
- **CPU usage fix** - Timer cleanup safeguard prevents runaway processes
- **VSCode extension cleanup** - Removed 10 unused imports from chatPanel.ts
- **Copy button layout** - Moved to bottom of message bubble (matches VSCode)

### Technical

- Textual's `call_from_thread()` for thread-safe UI updates from worker threads
- Worker threads with isolated asyncio event loops
- Footer status widget with 100ms timer updates
- Input box disabled during streaming to prevent concurrent requests
- INFO events with metadata for client-agnostic command execution

---

## [1.15.0] - 2026-01-26

### Added - New TUI Engine Integration

- **Complete TUI rewrite with engine integration** - Full async streaming, event-driven architecture
- **Real-time token/cost tracking** - Display usage stats with smart formatting (K/M suffixes)
- **Tool execution display** - Show AI tool calls, results, and errors in chat with proper formatting
- **Bootstrap context loading** - Auto-load AGENTS.md/CLAUDE.md on TUI startup
- **Context badge** - Status bar shows context scope (global/project/subdir)
- **Command factory pattern** - All 30 commands using centralized factory with type-based dispatch
- **7 validation scripts** - Comprehensive validation for all Phase 6 features
- **Performance optimization** - 3.5M command lookups/sec, 6.1M event processing/sec

### Added - TUI Commands

- **`/context` command** - Show context usage info (KeyValueResult)
- **`/context show`** - Display bootstrap hierarchy (TreeResult)
- **`/context hints`** - Show active provider/model hints (KeyValueResult)
- **`/context reload`** - Reload bootstrap from disk (ConfirmationResult)
- **`/usage` command** - Show usage statistics with multiple display modes
- **`/usage show|session|provider|off`** - Control usage display format

### Changed

- **Removed alias conflict** - `/test` command no longer uses "t" alias (reserved for `/tools`)
- **Event-driven messaging** - STREAM_START, STREAM_CHUNK, STREAM_END, TOOL_CALL, TOOL_RESULT, TOOL_ERROR
- **Smart truncation** - Tool arguments capped at 100 chars, results at 500 chars
- **Usage auto-update** - Token/cost stats refresh after each STREAM_END event

### Fixed

- **ErrorResult status parameter** - Fixed 4 missing `status=ResultStatus.ERROR` parameters in session commands
- **Mock fixtures** - Enhanced test mocks with proper return values for all engine methods
- **Test assertions** - Updated to accept all valid result types (ListResult, ConfirmationResult, etc.)

### Testing

- **28/28 unit tests passing** - Complete command factory test suite
- **7/7 integration tests passing** - End-to-end TUI validation
- **5 validation scripts** - Bootstrap, token/cost, tool display, commands, integration
- **Performance benchmarks** - Established baseline metrics for command/event processing

### Architecture

- **Phase 6.1** - Engine connection with async streaming
- **Phase 6.1.1** - Command factory integration (removed 434 lines of legacy code)
- **Phase 6.2** - Command handler validation (30 commands, 9 categories)
- **Phase 6.3** - Bootstrap context loading
- **Phase 6.4** - Token/cost tracking with smart formatting
- **Phase 6.5** - Tool execution display with TOOL_* events
- **Phase 6.6** - Integration testing & validation

### Documentation

- **PHASE-6-PROGRESS.md** - Comprehensive progress tracking
- **PHASE-7-POLISH-RELEASE.md** - Release preparation guide
- **Validation scripts** - scripts/validate_tui_*.py (5 scripts)

## [1.14.2] - 2026-01-23

### Added - Hierarchical Context Scopes

- **Global context** - Load defaults from `~/.ppxai/AGENTS.md` across all projects
- **Project context** - Load from `{git_root}/AGENTS.md` for project-specific instructions
- **Subdirectory context** - Load from `{cwd}/AGENTS.md` for directory-specific overrides
- **Scope merge strategy** - Files from all scopes merge additively (global → project → subdir)
- **`/context show` command** - Display bootstrap context hierarchy with scope labels
- **`GET /context/bootstrap` endpoint** - HTTP API for scoped bootstrap status

### Added - Enhanced Context Providers (merged from v1.14.3)

- **`@clipboard` provider** - Inject clipboard text content with `@clipboard` in messages
- **`@url` provider** - Fetch and inject web content with `@https://example.com/file.md`
- **Include directive** - Compose AGENTS.md from multiple files: `<!-- include: ./docs/style.md -->`
- **Hint templates** - Define reusable hint sets in `~/.ppxai/hint-templates.yaml`, reference with `- template: name`

### Changed

- **Gemini default model** - Changed from `gemini-2.0-flash` to `gemini-2.5-flash` (2.0 deprecated March 2026)
- **Provider/model hints merging** - Hints from all scopes are combined (not replaced)
- **`/context reload`** - Now reloads from all scope levels with improved feedback
- **Bootstrap status API** - Returns `sources` array with path, scope, and size for each file

### Architecture

- **`find_git_root()`** - New helper to detect git repository root for project scope
- **`ContextScope` enum** - Scope labels (global, project, subdir)
- **`find_bootstrap_files_by_scope()`** - Hierarchical scope discovery
- **`ScopedBootstrapSource` dataclass** - Bootstrap file metadata with scope info
- **`load_bootstrap_context_merged()`** - Scope-aware context loading with merge
- **`inject_clipboard_context()`** - Clipboard content injection
- **`inject_url_context()`** - URL content fetching with HTML-to-text conversion
- **`_process_includes()`** - Recursive include directive processing with cycle detection
- **`load_hint_templates()`** - Template loading from ~/.ppxai/hint-templates.yaml

### Dependencies

- **pyperclip>=1.8.0** - Cross-platform clipboard access for `@clipboard` provider

## [1.14.1] - 2026-01-21

### Added - Editor Command Support

- **`/edit` command for VSCode** - Opens file in native VSCode editor with proper language mode, supports `file:line:col` syntax
- **`/edit` command for Web App** - Monaco-style editor with syntax highlighting, line numbers, Ctrl+S save
- **`/context reload` command** - Refresh AGENTS.md/CLAUDE.md from disk without restarting session (TUI, VSCode, Web)
- **`POST /files/write` endpoint** - Server-side file write support for VSCode/Web editors
- **Auto-reload on save** - Editing AGENTS.md or CLAUDE.md automatically offers to reload bootstrap context

### Fixed

- **Gemini provider error formatting** - Added missing `_format_error` and `_log_error_traceback` methods to GeminiProvider class

### Cancelled

- **TUI `/edit` command** - Cancelled for Rich TUI; ppxaide (Textual TUI) provides full file editing via CodeEditor widget with syntax highlighting

## [1.14.0] - 2026-01-19

### Added - Bootstrap Context System

- **AGENTS.md/CLAUDE.md support** - Load project-specific instructions from bootstrap files on startup
- **YAML front matter** - Provider and model-specific hints in structured header
- **Dynamic prompt assembly** - System prompt rebuilds automatically when switching provider/model
- **`local` provider inheritance** - ollama, vllm, lmstudio providers inherit from `local` hints
- **Model pattern matching** - Glob-style patterns match model IDs (e.g., `deepseek-r1*`)
- **Configurable file aliases** - User-defined fallback list via `bootstrap.files` config
- **Bootstrap enable/disable** - Toggle via `bootstrap.enabled` config option

### Added - Context Hints Debugging

- **`/context hints` command** - Shows active provider/model hints for current session
- **`/status` hints display** - Shows count of active hints with inheritance indicator (e.g., `3+ provider hints`)
- **Debug logging on switch** - Logs hint transitions when provider/model changes (with `/debug-log on`)
- **`/context/hints` HTTP endpoint** - VSCode extension can query active hints

### Fixed

- **VSCode/Web table rendering** - Markdown tables now use word-wrap instead of horizontal scrollbars
- **CSS table-layout** - Changed from `display: block` with `overflow-x` to `table-layout: fixed` with `word-wrap`
- **Perplexity "messages must alternate" error** - Fixed session corruption when restoring tool-use sessions that start with assistant messages
- **HTTP server session autosave** - Server now calls `save_dirty()` after each chat response (was only saving usage stats)
- **Session alternation validation** - New `validate_and_fix_alternation()` method sanitizes sessions on load/save, removing leading assistant messages
- **Error rollback in chat_with_tools** - User message rollback now only happens on first iteration, preventing session corruption during multi-turn tool calls
- **Session logger routing** - Changed session.py logger from "tui" to "session" for proper server-debug.log output

### Architecture

- **`ppxai/engine/bootstrap.py`** - New module with `BootstrapContext` class for parsing and prompt assembly
- **`EngineClient._bootstrap_context`** - Stores parsed bootstrap context for session
- **`get_active_hints()` method** - Returns detailed breakdown of active hints
- **`get_active_hints_for()` method** - `BootstrapContext` method for provider/model-specific hint retrieval

## [1.13.10] - 2026-01-16

### Added - Web App Enhancements

- **Image preview in /show command** - Web app now displays PNG, JPG, GIF, WebP, SVG, BMP, ICO files directly in the preview panel
- **PDF preview in /show command** - Web app now displays PDF files using the browser's native PDF viewer
- **YAML/TOML/HCL parsing for /show** - Web app now supports structure-aware previews for YAML, TOML, and HCL/Terraform files
- **Loop detection for tool calls** - Configurable `max_same_tool_calls` (default: 3) prevents models from calling the same tool repeatedly. Forces synthesis after threshold is reached.

### Added - Architecture Improvements

- **Command Factory pattern** - Migrated all slash commands to factory pattern in `ppxai/commands/` package with self-registration
- **SessionManager singleton** - Thread-safe session management for HTTP server with proper async locks
- **ConfigStore pattern** - Thread-safe configuration with explicit `initialize()` at entry points
- **Config seeding on first run** - Bundled `ppxai-config.example.json` is copied to `~/.ppxai/` on first run
- **Constants module** - New `ppxai/constants.py` centralizes magic strings and default values
- **Improved provider error formatting** - User-friendly error messages for connection, auth, and rate limit errors

### Fixed

- **Tool parameter aliasing with duplicates** - Fixed issue where models send both canonical and alias names in same call (e.g., both `file_path` AND `filepath`). Now removes duplicate aliases instead of passing them to tool execution.
- **Session restore working directory** - Fixed issue where status bar showed wrong working directory after session restore. Now `set_working_dir()` updates both `context_injector.working_dir` and `session.working_dir`.
- **Session restore tools state** - Session now saves and restores `tools_enabled` state. Tools are automatically re-enabled when restoring a session that had tools enabled.
- **Message alternation on errors** - User message is now rolled back when provider returns error or user interrupts, preventing "messages must alternate" errors on retry.
- **Relative /cd path resolution** - `/cd` command now correctly resolves relative paths.
- **apply_patch tool** - Now handles delete+recreate pattern and detects no-change errors.
- **Loop detection argument checking** - Loop detection now checks tool arguments, not just tool names.

### Changed

- **Removed BUILTIN_PROVIDERS** - JSON config is now the single source of truth for provider definitions
- **Explicit config initialization** - Entry points must call `initialize()` before using config (no import-time side effects)
- **HTTP error handling** - Standardized on `HTTPException` exclusively, removed unused `JSONResponse`

### Technical Debt Addressed

- Extracted `SessionManager` from `http.py` (467 lines)
- Extracted `BaseConsentManager` reducing consent.py by 14%
- Refactored container tools to `CLITool` hierarchy reducing boilerplate by 40%
- Replaced dangerous `eval()` with AST-based safe evaluation in calculator
- Added selective logging to 22 silent error handling instances
- Documented DAG import structure in `architecture.md`
- Replaced `os._exit()` with graceful shutdown via `asyncio.Event` for proper cleanup
- Refactored `client.py` via 5-phase extraction (2,037→1,311 lines, 36% reduction)
- Refactored `chatPanel.ts` with EventBus + State Machine architecture (5,123→2,773 lines, 46% reduction)
- Created `handlers/` module with 1,658 lines of extracted handler code

## [1.13.9] - 2026-01-12

### Added - Session Persistence & Auto-Recovery

- **Session state file** - New `~/.ppxai/session-state.json` tracks session dirty/clean state for crash recovery
- **Command history persistence** - User input history is saved per session and restored on reload
- **Working directory persistence** - Session remembers the working directory set via `cd` command
- **Auto-save after each roundtrip** - Sessions are automatically saved after each chat exchange (configurable interval)
- **Auto-restore on startup** - Configurable behavior: `"always"`, `"prompt"` (default), or `"never"`
- **Crash recovery** - Dirty sessions (from crashes/force-quit) are automatically detected and recovered
- **Graceful exit handling** - Sessions marked clean on `/quit`, Ctrl-C (double), or EOF

### Added - Configuration

- **Session config section** - New `"session"` key in `ppxai-config.json`:
  ```json
  {
    "session": {
      "auto_restore": "prompt",
      "auto_save_interval": 1
    }
  }
  ```

- **Context limits config section** - New `"context"` key for configurable truncation and model limits:
  ```json
  {
    "context": {
      "max_injection_size": 100000,
      "default_context_limit": 128000,
      "warn_at_percent": 80
    }
  }
  ```

- **Per-model context_limit** - Models can specify their context window size:
  ```json
  {
    "providers": {
      "vllm-gpt-oss": {
        "models": {
          "openai/gpt-oss-120b": {
            "context_limit": 131072
          }
        }
      }
    }
  }
  ```

- **Context usage warning** - Shows warning when approaching context limit (configurable threshold)
- **Tools enable notification** - Shows context limit and truncation info when enabling tools
- **`/context` command** - Show context usage, injected files, and visual progress bar (TUI, Web, VSCode)
- **`/context clear` command** - Remove injected @file/@git/@tree content from history to free context space
- **Context badge in TUI** - Status line shows `Ctx: X%` with color coding (green <80%, yellow 80-99%, red ≥100%)
- **Context badge in VSCode** - Header shows context usage percentage with click-to-clear functionality

### Fixed

- **Shell `cd` command updates engine working directory** - When AI calls `execute_shell_command` with `cd`, it now updates `engine.set_working_dir()` instead of running a subprocess (which only changed the subprocess directory). Fixes `list_directory` showing wrong directory after AI-issued `cd` command.
- **@tree context truncation** - `@tree` injection now truncates at 100KB limit (same as `@file` and `@git`) to prevent "too many tokens" errors with large codebases
- **TUI @file autocomplete after cd** - File completion now uses engine's working directory instead of process cwd, so @filename autocomplete correctly shows files from the current directory after using cd command
- **TUI /show command after cd** - `/show @filename` and `/show filename` now search in the engine's working directory (set by cd) instead of the process cwd
- **Desktop app missing data viewers** - Added `components/` and `styles/` directories to `ppxai-desktop.spec` so data viewer CSS/JS files are bundled and deployed to `~/.ppxai/web/`
- **Tool parameter aliasing** - Added dynamic parameter normalization in ToolManager to handle model variations. Different tools use different naming conventions (`read_file` expects `filepath`, `apply_patch` expects `file_path`), and models may use either. The new `_normalize_params()` method maps model-provided names to what each tool expects. Comprehensive alias groups cover: file paths, directories, commands, queries, diffs, URLs, locations, containers, pods, text content, and search/replace operations.
- **Context overflow prevention** - Added token estimation in OpenAI-compatible provider to prevent "max_tokens must be at least 1" errors from vLLM when injected `@file` context exceeds model's 128K context window. Now shows a friendly error message suggesting to remove file references or start a new conversation instead of cryptic API error.
- **Empty responses after tool calls** - Fixed issue where some models (e.g., GPT-OSS 120B via vLLM) would execute tools correctly but return empty text responses instead of summarizing the results. Now detects empty responses after tool iterations and prompts the model for a summary.
- **Reasoning model support** - Handle models that return content in `reasoning_content` instead of `content` field
- **Hash-based context deduplication** - Injecting same content twice (e.g., `@git` with unchanged diff) no longer duplicates. Uses MD5 hash to detect identical content and skip re-injection.
- **Gemini model context limits** - Added `context_limit: 1000000` for all Gemini models in example and project configs (was falling back to 128K default)

## [1.13.8] - 2026-01-11

### Added - Data Visualization

- **CSV/TSV Table Viewer** - Interactive table display with sorting, pagination, and filtering
  - TUI: Rich tables with pagination controls (`n`/`p` for next/prev, `s` for source view)
  - Web: Interactive DataTableViewer component with column sorting and search
- **JSON/YAML Tree Viewer** - Collapsible tree view for structured data
  - TUI: Rich tree with expand/collapse controls
  - Web: Interactive DataTreeViewer with expand all/collapse all
- **Format Detection** - Auto-detect CSV, TSV, JSON, YAML, TOML, HCL from extension and content
- **View Toggle** - Switch between rendered (table/tree) and source (syntax-highlighted) views
  - TUI: `/show file.csv --source` flag or `s` key during viewing
  - Web: "Rendered | Source" toggle button in preview panel
- **TOML/HCL Support** - Parse and display TOML and HCL/Terraform files as trees

### Added - Container Management Tools

- **Docker/Podman Tools** - Container lifecycle management with consent for destructive operations
  - `container_list` - List containers (running or all)
  - `container_logs` - Get container logs with tail/since options
  - `container_inspect` - Detailed container information
  - `container_start/stop/restart` - State management (requires consent)
  - `container_exec` - Execute commands in containers (requires consent)
  - `image_list` - List container images
- **Kubernetes Tools** - Pod and deployment management
  - `pod_list` - List pods across namespaces
  - `pod_logs` - Get pod logs with container selection
  - `pod_describe` - Detailed pod information
  - `deployment_list` - List deployments
  - `service_list` - List services
  - `kubectl_apply` - Apply manifests (requires consent)
  - `pod_exec` - Execute in pods (requires consent)
  - `namespace_list` - List namespaces
- **Runtime Detection** - Auto-detect Docker, Podman, and kubectl availability
- **Note**: Container tools are new and may require additional testing - please report issues

### Added - Configuration Options

- **Visualization Config** - New `visualization` section in ppxai-config.json
  - `max_rows` - Limit rows loaded for large CSV files (default: 10000)
  - `page_size` - Rows per page in TUI view (default: 50)
  - `tree_depth` - Initial tree expansion depth (default: 3)
  - `auto_detect` - Enable content-based format detection
  - `csv_delimiter` - Force delimiter or use 'auto'
- **Container Config** - New `tools.container` section
  - `enabled` - Enable/disable container tools
  - `require_consent` - Require consent for destructive operations
  - `timeout` - Command execution timeout

### Added - Dependencies

- **Optional `data` extras** - `pip install ppxai[data]` for YAML/HCL parsing
  - `pyyaml>=6.0` - YAML file parsing
  - `python-hcl2>=4.3` - HCL/Terraform file parsing

### Added - Testing

- **E2E Playwright tests** - 55 browser tests for DataTableViewer and DataTreeViewer components
- **CI Playwright integration** - GitHub Actions runs E2E tests with Chromium

### Fixed

- **`@filename` autocomplete in Web App** - Now uses `/files/search` server endpoint for real file suggestions
- **`@filename` autocomplete in VSCode** - `@git` and `@tree` now appear in autocomplete suggestions
- **Autocomplete popup persistence** - Popup now hides when sending a message (fixed async race condition)
- **`@git` truncation** - Git diff content now properly truncates at 100KB limit (was only setting flag, not truncating)

---

## [1.13.7] - 2026-01-09

### Added - Hot Reload Configuration

- **`/config reload` command** - Reload config without restarting TUI
- **`POST /config/reload` endpoint** - Server-side config reload for web clients
- **VSCode `ppxai.reloadConfig` command** - Reload config from VSCode command palette
- **Web app "Reload Config" menu** - Reload config from web app settings menu

### Added - TUI Improvements

- **`/status` toggles that save** - `/status datetime|version|cwd` now toggles and persists to config
- **TUI icon** - New bold `>_` symbol for better taskbar visibility

### Fixed

- **`provider_id` error** - Fixed `'EngineClient' object has no attribute 'provider_id'`
- **`get_total_usage()` error** - Fixed `'SessionManager' object has no attribute 'get_total_usage'`
- **Private function** - Renamed `_find_config_file()` to public `find_config_file()`

---

## [1.13.6] - 2026-01-08

### Added - Server Lifecycle & Configuration

- **Server idle auto-shutdown** - Server automatically shuts down after configurable inactivity period (default 5 minutes)
- **`/shutdown` endpoint** - Graceful server shutdown via HTTP POST request
- **Activity tracking middleware** - Resets idle timer on every client request
- **Server config section** - New `server.idle_timeout` and `server.port` in JSON config

### Added - System Prompt Configuration

- **Global system prompt** - Configure `system_prompt` at config root level
- **Per-provider system prompts** - Override system prompt per provider (e.g., reduce GPT-OSS chattiness)
- **Prompt modes** - `system_prompt_mode`: "prepend" (default), "append", or "replace"

### Added - TUI Enhancements

- **Status bar badges** - Version, current working directory, and date/time in TUI status bar
- **`/status` command** - Show provider, model, tools status, and working directory
- **`/tools on|off` aliases** - Shorter aliases for `/tools enable|disable`

### Added - Shell Tool Configuration

- **Configurable interactive commands** - `tools.shell.interactive_commands` list in JSON config
- **Non-interactive with args** - `tools.shell.non_interactive_with_args` for commands like `ssh host command`
- **SSH fix** - `ssh r1lx uptime` now works (previously blocked as "interactive")

### Added - Web App Server Control

- **Server badge click** - Click server badge to stop server (with confirmation)
- **Circuit breaker reconnection** - Exponential backoff retry pattern for server connection

### Fixed

- **TUI crash** - Fixed `'EngineClient' object has no attribute 'working_dir'` error

---

## [1.13.5] - 2026-01-08

### Fixed - Critical: Session Isolation

- **Multi-client session isolation** - VSCode extension and Desktop Web App now have isolated sessions when connected to the same server
- **Session ID via HTTP header** - All clients send `X-Session-Id` header; server routes requests to isolated EngineClient instances
- **Per-session state** - Each session maintains its own: conversation history, working directory, provider/model, tool consent state
- **Session lifecycle** - Sessions auto-expire after 1 hour of inactivity; usage saved on cleanup
- **Backward compatibility** - Clients without session ID use shared `default_engine` (existing behavior)

### Added - Session Management

- **`/sessions/list` endpoint** - Monitor active sessions for debugging (GET /sessions/list)
- **Session ID in responses** - `/status`, `/chat`, `/context/working_dir` return session ID
- **VSCode extension** - Generates unique `vscode-{uuid}` session ID per extension instance
- **Desktop Web App** - Generates unique `webapp-{uuid}` session ID per browser tab (via sessionStorage)

### Technical Details

- **Server**: New `get_or_create_session()` function routes requests to per-session EngineClient
- **Consent handling**: Consent requests keyed by `(session_id, file_path)` for proper isolation
- **Request serialization**: Each session has its own asyncio.Lock for chat request ordering

---

## [1.13.4] - 2026-01-08

### Fixed - Error Handling & LLM Guidance

- **SSL certificate support** - Added `SSL_CERT_FILE` environment variable support for corporate proxy certificates in all providers
- **Standardized error logging** - All providers now include full traceback in error events for better debugging
- **Windows shell guidance** - Added explicit warning in `execute_shell_command` that bash heredocs (`<<EOF`), `$()`, and bash builtins don't work on Windows
- **Tool parameter emphasis** - `apply_patch` description now emphasizes REQUIRED parameters to prevent missing argument errors
- **Actionable error tips** - File-not-found errors now suggest appropriate tools (`insert_text`, `list_directory`, `read_file`)
- **Line number validation tips** - `delete_lines` invalid range errors now suggest using `read_file` to check file length first

### Removed - Cleanup

- **docs/archive/** - Removed 39 obsolete documentation files (13KB) - preserved at v1.13.3 tag

---

## [1.13.3] - 2026-01-07

### Fixed - Session Management

- **TUI `/sessions` command** - Fixed KeyError 'saved_at' crash when listing sessions
- **Session data alignment** - All UIs (TUI, Web App, VSCode) now show consistent session info with Created and Last Saved timestamps
- **Robust session display** - `display_sessions()` now uses `.get()` for graceful handling of missing fields

### Changed - UI Consistency

- **Sessions table format** - All three UIs now display sessions in a markdown table with: Session, Messages, Provider/Model, Created, Last Saved columns
- **SessionInfo dataclass** - Added `saved_at` field to `SessionInfo` in engine types
- **HTTP endpoint** - `/sessions` endpoint now includes `saved_at` in response

### Fixed - File Editing Tools

- **Working directory resolution** - `apply_patch`, `replace_block`, `insert_text`, `delete_lines` now resolve relative paths against the engine's working directory instead of the process working directory
- **Critical fix** - Previously, when using file editing tools with a relative path like `task_analysis.ipynb`, the file would be created in `~/.ppxai/bin/` (where ppxai-server runs) instead of the project directory shown in the UI

### Fixed - Build/Release

- **validate-release.py** - Fixed UTF-8 encoding for Windows compatibility

## [1.13.2] - 2026-01-05

### Fixed - Desktop Web App & VSCode Extension

#### Markdown Rendering
- **Fixed bullet lists** - Changed from Unicode bullet (â€¢) to markdown dash (-) for proper rendering
- **Fixed `/usage` tables** - Both VSCode extension and Web App now show usage breakdown in table format
- **Updated marked.js** - Upgraded Web App from v9.1.6 to v11.1.1 (matching VSCode extension)

#### Desktop Web App
- **Auto-detect server URL** - Web UI now uses `window.location.origin` instead of hardcoded port
- **Favicon** - Added proper favicon (same icon as VSCode extension)
- **Markdown preview** - File preview panel now renders `.md` files with full markdown support
- **Preview link clicks** - Clicking relative links in markdown preview opens files instead of 404

#### Shared Modules
- **Command parity** - New shared JS/TS modules ensure identical commands across TUI, VSCode, and Web App
- **Formatter parity** - Consistent markdown formatting for all command responses

### Fixed - Cross-Platform Compatibility (Windows)

#### Tests
- **Path handling** - Tests now use `tempfile.gettempdir()` instead of hardcoded `/tmp`
- **Filename references** - Tests use filename only, not full paths with platform-specific separators
- **Rich console** - Added `legacy_windows=False` for OSC 8 hyperlink tests

#### Configuration
- **PEP 735** - Migrated from `[tool.uv].dev-dependencies` to `[dependency-groups].dev`

### Added - Enhanced Install Script

#### New Flags
- **`--with-config`** - Generate `ppxai-config.json` and `.env` template with all providers
- **`--with-macos-app`** - Download and install DMG to `/Applications/ppxai.app`
- **`--with-launchagent`** - Install LaunchAgent for server auto-start (macOS)
- **`--uninstall`** - Remove ppxai installation (preserves config files)

#### macOS Improvements
- **Quarantine removal** - Automatically runs `xattr -cr` on downloaded binaries
- **DMG installation** - Downloads, mounts, copies app, removes quarantine attribute

#### Documentation
- **installation.md** - Comprehensive guide with all new options and platform-specific instructions

---

## [1.13.1] - 2026-01-04

### Added - Desktop Web App

#### ppxai-desktop Launcher
- **Standalone launcher** - Start server and open browser with one click
- **macOS app bundle** - Native `.app` with DMG installer for drag-and-drop install
- **Cross-platform binaries** - Linux, Windows, macOS (ARM + Intel)
- **Auto-install** - Web UI files auto-copied to `~/.ppxai/web/` on first run

#### Web UI
- **Full-featured chat** - Browser-based chat interface with SSE streaming
- **Feature parity** - All slash commands, autocomplete, tools, agent mode, themes
- **Project selector** - Quick switch between recent project directories
- **Provider/model switching** - Dropdown selectors in header
- **Usage tracking** - Token counts and cost display

#### UI Improvements
- **Tool call ordering** - Tool calls now appear before the answer (matching VSCode)
- **Visual badge states** - Tools and Agent badges turn green when enabled
- **Usage tables** - Formatted markdown tables for `/usage` reports

### Documentation
- Updated installation.md with desktop app instructions for all platforms
- Added Linux and Windows platform-specific behavior notes
- Added troubleshooting guide for desktop app

---

## [1.13.0] - 2026-01-03

### Added - Custom Provider Parity

#### Premium Web Search Tool
- **Custom provider support** - vLLM, Ollama, and other custom providers can now use premium web search
- **Priority fallback chain** - Perplexity Sonar > Gemini Grounding > DuckDuckGo (free)
- **Automatic detection** - Tool checks available API keys and uses best available option
- **Citation integration** - Web search results formatted consistently across all providers

#### SSL Proxy Support
- **`SSL_VERIFY` environment variable** - Disable SSL verification for corporate proxies
- **Corporate network compatible** - Works behind SSL-inspecting firewalls

#### Tool Usage Tracking
- **`ToolUsage` dataclass** - New type for tracking per-tool usage (calls, tokens, cost)
- **`/usage` enhancement** - Shows tool usage breakdown with provider info
- **Cost attribution** - Separate tracking for model costs vs tool costs

#### Native Tool Calling for Custom Providers
- **`native_tool_calling` capability** - Enable OpenAI-style function calling for vLLM endpoints
- **vLLM integration** - Works with `--enable-auto-tool-choice` flag
- **Streaming tool calls** - Full support for streaming responses with tool calls

#### Enhanced Tool Parsing
- **vLLM inference** - Infer tool names from argument patterns
- **Dispatcher pattern** - Match JSON arguments against registered tool schemas
- **Robust error handling** - Better recovery from malformed tool responses

### Testing
- 525 tests passing (119 new tests)
- Custom provider tool calling tests
- Tool parsing test coverage (440+ lines)
- Premium web search integration tests

---

## [1.12.5] - 2026-01-03

### Added - Native Gemini Provider

#### Google Search Grounding
- **Native Gemini SDK** - Direct integration with `google-genai` package
- **Google Search Grounding** - Real-time web search with citations (like Perplexity)
- **Streaming support** - Full async streaming with usage tracking
- **Graceful fallback** - Uses OpenAI-compatible API if `google-genai` not installed

#### Installation
```bash
pip install ppxai[gemini]   # For enhanced Gemini support
```

### Technical
- New provider: `ppxai/engine/providers/gemini.py`
- Auto-detection in provider factory
- No performance regression (benchmarked)

## [1.12.4] - 2026-01-03

### Added - Checkpoint Management & Web Search Improvements

#### `/checkpoint` Command
- **`/checkpoint status`** - View current checkpoint configuration
- **`/checkpoint list`** - List recent checkpoints (up to 10)
- **`/checkpoint backend <git|file|auto|none>`** - Switch checkpoint backend (session-only)
- **`/checkpoint clear`** - Clear old file-based checkpoint snapshots
- **`/checkpoint info <id>`** - Show details about a specific checkpoint
- **`/checkpoint undo`** - Alias for `/undo` command
- **Tab autocomplete** - Subcommands and backend options autocomplete in TUI

#### Web Search Tool Upgrade
- **`ddgs` package** - Upgraded to use `ddgs>=9.0.0` for more reliable DuckDuckGo search
- **Fallback chain** - Uses ddgs â†’ duckduckgo-search â†’ HTML scraping
- **No API key needed** - Works out of the box for all providers

### New Endpoints
- `GET /checkpoint/list` - List recent checkpoints
- `POST /checkpoint/backend` - Set checkpoint backend
- `POST /checkpoint/clear` - Clear file-based checkpoints

### VSCode Extension
- Full `/checkpoint` command support with all subcommands
- HTTP client methods for checkpoint management

### Testing
- 400 tests passing

---

## [1.12.3] - 2026-01-03

### Added - Time-Based Usage Analytics

#### Persistent Usage Storage
- **`~/.ppxai/usage/usage.json`** - Usage data now persists across sessions
- **Auto-save** - Usage saved after each chat (VSCode) or on exit (TUI)
- **Shared storage** - Both TUI and VSCode contribute to the same usage history
- **No duplicates** - Same session updates existing entry instead of appending

#### Time-Based Usage Commands
- **`/usage 24h`** - Usage for last 24 hours
- **`/usage week`** - Usage for last 7 days
- **`/usage month`** - Usage for last 30 days
- **`/usage year`** - Usage for last 365 days
- **`/usage all`** - All-time usage history

#### HTTP Endpoints
- **`GET /usage/report?period=week`** - Aggregated usage report by time period
- **`GET /usage/sessions?limit=20`** - List recorded sessions with usage data

### New Files
- `ppxai/usage.py` - Persistent usage storage module
- `tests/test_usage_persistence.py` - 14 new tests

### Testing
- 414 tests passing (14 new usage persistence tests)

---

## [1.12.2] - 2026-01-02

### Added - TUI Polish & Bug Fixes

#### Emoji Toggle
- **`/theme emoji on|off`** - Toggle emoji display in panel badges
- Switch between emoji badges and text-only badges for better alignment

### Fixed

#### Tool Call Parsing
- **Single-quote JSON** - Fixed parsing of tool calls using single quotes instead of double quotes

#### Logging & Initialization
- **Unified logging** - TUI and engine now share common logger module
- **Logger initialization** - Fixed missing `self.logger` in CommandHandler
- **Removed obsolete** `tui_logger.py` (replaced by `ppxai/common/logger.py`)

#### TUI Display
- **Checkpoint status** - Shows `â†¶` symbol instead of full git hash for cleaner display
- **Panel alignment** - Text symbols instead of emojis for consistent column alignment

### Testing
- All 377 tests passing

---

## [1.12.1] - 2026-01-02

### Added - Enhanced TUI Experience

#### Themed TUI Panels
- **4 Distinctive Themes** - Standard, Tron Legacy, Matrix, and Nord color schemes
- **Rounded Panel Corners** - User, assistant, and system messages have rounded borders
- **`/theme` Command** - List themes or switch with `/theme <name>`
- **Theme Autocomplete** - Tab completion for theme names

#### Framed Status Panel
- **Badge Display** - Provider, model, tools status as colored badges
- **Visual Hierarchy** - Clear separation between header and chat
- **Theme-Aware Styling** - Badges adapt to current theme colors

#### Clickable File Links
- **OSC 8 Hyperlinks** - Markdown links clickable in supported terminals
- **File URI Support** - Local paths convert to `file://` URIs
- **VSCode Integration** - Click file links to open in editor
- **`/show` Command** - File references in rendered markdown are clickable

### Fixed
- File link resolution for relative paths in markdown
- Link detection regex to match all markdown links (not just http/https)
- Working directory passed correctly for relative link resolution

### New Files
- `ppxai/themes.py` - Theme dataclass and 4 built-in themes
- `ppxai/ui_components.py` - Reusable Rich UI components

---

## [1.12.0] - 2025-12-29

### Added - Checkpoint System & Usage Tracking ðŸ”’ðŸ“Š

This release introduces a checkpoint system for atomic multi-file rollback and real-time token usage tracking with cost estimation.

#### Checkpoint System
- **Git-based checkpoints** - Auto-commits changes before agent tasks for atomic rollback
- **`/undo` command** - Revert last agent task with single command (`git revert HEAD`)
- **File-based fallback** - Snapshots to `~/.ppxai/checkpoints/` when git unavailable
- **Auto-detection** - Automatically selects best backend (git â†’ file â†’ none)
- **Stale detection** - Checkpoints invalidated when new commits are made after them
- **VSCode Undo button** - One-click rollback with confirmation dialog

#### Token Usage & Cost Tracking
- **Real-time streaming usage** - Extract tokens from streaming responses
- **Cost estimation** - Automatic USD cost calculation based on per-model pricing
- **TUI status line** - Shows `1.2Kâ†“/0.5Kâ†‘ $0.0045` in status bar
- **VSCode usage badge** - Live-updating badge with tooltip breakdown
- **All providers supported** - OpenAI, Perplexity, Gemini streaming

#### New Configuration Options
- `tools.agent.checkpoint_backend` - `"auto"` | `"git"` | `"file"` | `"none"`
- `tools.agent.checkpoint_message` - Custom commit message format
- `tools.agent.max_tool_iterations` - Max inner tool loop iterations

#### Bug Fixes
- Fixed `@tree` and `@git` context injection in VSCode (was treated as file search)
- Fixed usage badge not updating after responses
- Fixed table horizontal overflow in VSCode webview
- Fixed concurrent request causing 400 message alternation errors
- Session cleanup on interrupted requests

#### Documentation
- [checkpoint-guide.md](docs/checkpoint-guide.md) - Comprehensive checkpoint system guide
- [RELEASE-NOTES-v1.12.0.md](docs/archive/release-notes/RELEASE-NOTES-v1.12.0.md) - Full release notes

#### Testing
- 377+ tests passing (40 new checkpoint tests)

---

## [1.11.9] - 2025-12-27

### Fixed - Critical Agent Mode Safety ðŸ”’

This release fixes a critical safety issue where `/agent on|off` commands were being interpreted as tasks instead of toggle commands.

#### Critical Fix
- **`/agent on|off` now correctly toggles agent mode** instead of being interpreted as tasks
  - Previously, typing `/agent off` would cause AI to search for things to turn "off" (including killing server processes!)
  - Now properly recognized as toggle commands in both TUI and VSCode extension

#### Security Improvements
- **Minimum word count validation** (default: 3 words) rejects vague single-word tasks
- **`kill`, `pkill`, `killall` added to built-in dangerous shell patterns**
- Built-in defaults ensure safety even without config file

#### New Features
- **Configurable agent settings** via `ppxai-config.json`:
  - `tools.agent.max_iterations` (default: 10) - Maximum agent loop iterations
  - `tools.agent.context_char_limit` (default: 2000) - Character limit for context display
  - `tools.agent.min_task_words` (default: 3) - Minimum words required for agent tasks
- **`/agent/config` API endpoint** for retrieving agent configuration
- **Full `/tools` command parity** between TUI and VSCode extension
  - Added `/tools agent`, `/tools set verbose on|off`, `/tools help <tool>` to extension

#### Documentation
- Updated [Agent Mode Guide](docs/agent-mode-guide.md) with configuration section

#### Testing
- 337 tests passing

---

## [1.11.8] - 2025-12-27

### Added - Agent Mode + Release Fixes ðŸ¤–

This release introduces Agent Mode for autonomous task execution in the VSCode extension.

#### Agent Mode
- **Agent Toggle Button** - New button in VSCode extension header to enable/disable agent mode
- **Agent Mode API** - New endpoints for agent control:
  - `GET /agent/status` - Check agent mode status
  - `POST /agent/enable` - Enable agent mode (auto-enables tools)
  - `POST /agent/disable` - Disable agent mode
- **EngineClient Support** - `agent_mode` property, `enable_agent_mode()`, `disable_agent_mode()` methods
- **Agent Mode Guide** - Comprehensive documentation at [docs/agent-mode-guide.md](docs/agent-mode-guide.md)

#### Release Process Fixes
- **GitHub "Latest" Release Tag** - Releases now correctly marked as latest
  - Added `make_latest: true` to GitHub Actions workflow
  - Release script now uses `--latest` flag when publishing notes
- **Documentation Links** - Fixed 12 broken internal links
  - `custom-tools-guide.md` â†’ `custom-tool-development-guide.md`
  - Archived docs now properly reference `docs/archive/` paths

### Fixed
- GitHub releases not being marked as "Latest" on repository page
- Broken documentation links pointing to moved/renamed files

## [1.11.6] - 2025-12-26

### Fixed - /tools Commands After Provider Switch ðŸ”§

- **`/tools list` After Provider Switch** - Now correctly lists tools after `/provider gemini`
  - Root cause: `_list_tools()` checked `isinstance(self.client, PerplexityClientPromptTools)` which is False for non-Perplexity providers
  - Fix: Check `engine_client.tools_enabled` first, show engine tools for all providers

- **`/tools status` After Provider Switch** - Now correctly shows "Tools enabled" after switching providers
  - Same fix pattern applied

- **`/tools config` After Provider Switch** - Now works correctly after switching providers

### Testing
- 377 tests passing
- Manual TUI verification confirmed fix

---

## [1.11.5] - 2025-12-26

### Fixed - Ctrl-C and Tools Status Display ðŸ”§

- **Ctrl-C Message Alternation Error** - Fixed 400 error after interrupting streaming with Ctrl-C
  - Root cause: Ctrl-C cleanup only removed user message from legacy `client.conversation_history`, not from `engine_client.session.messages`
  - Fix: Added `SessionManager.remove_last_message()` method and cleanup logic for both legacy and engine session

- **Tools Status Display** - `/tools enable` now correctly shows "ON" in status line
  - Root cause: `get_status_line()` checked legacy `client.enable_tools` instead of `engine_client.tools_enabled`
  - Fix: Check `handler.engine_client.tools_enabled` first, fallback to legacy client check

### Testing
- 377 tests passing (2 new session cleanup tests)

---

## [1.11.4] - 2025-12-24

### Added - @git and @tree Context Injection ðŸ“‚

Automatic context injection for git changes and directory structure in AI messages.

#### New Features
- **@git injection**: Automatically includes `git diff` (staged + unstaged changes) when you type `@git` in messages
- **@tree injection**: Automatically includes directory tree structure when you type `@tree` in messages
- **Combined contexts**: Use `@file`, `@git`, and `@tree` together in the same message
- **Provider-agnostic**: Works with all providers (Perplexity, Gemini, OpenAI, custom)
- **TUI feedback**: Shows what was injected with size (e.g., "â†’ Injected context: @git (31 B)")

#### Architecture Changes
- **Unified TUI and VSCode**: Both now always use shared EngineClient (unified architecture)
- EngineClient now created at TUI startup (not just when tools enabled)
- Context injection works regardless of tools ON/OFF state

#### Testing
- 31 context injection tests passing (9 new @git/@tree tests)
- 70 command tests passing

---

## [1.11.7] - 2025-12-26

### Major - Legacy Code Removal + Clickable Citations ðŸŽ‰ðŸ”—

This release completes the migration to EngineClient and adds clickable citations/links across all interfaces.

#### Legacy Code Removed
- **Deleted ~2,100 lines of legacy code**
  - `ppxai/client.py` (447 lines - AIClient)
  - `perplexity_tools_prompt_based.py` (1,342 lines - legacy tools client)
  - `tool_manager.py` (299 lines - legacy MCP loader)
- **EngineClient is now the only client interface**
- **337 tests passing** (migrated from legacy tests)

#### New Features
- **`/tools help <tool-name>`** - Detailed documentation for any tool
- **Autocomplete for `/tools`** - Tab completion for subcommands and tool names
- **Custom Tool Development Guide** - [docs/custom-tool-development-guide.md](docs/custom-tool-development-guide.md)

### Fixed - Clickable Citations ðŸ”—

- **Perplexity Citations Clickable** - `inject_citation_urls()` converts `[1]` to `[1](url)` format
  - Perplexity API returns citations as separate metadata array
  - New function injects URLs into response text for clickable links
- **TUI Links Clickable** - OSC 8 hyperlinks via `convert_markdown_links_to_rich()`
  - Works in Ghostty, iTerm2, Kitty, Windows Terminal, GNOME Terminal 3.26+
  - Cross-platform support (macOS, Linux, Windows)
- **VSCode Tool Responses** - Added `fullResponse` message type for tool-using responses
- **`/tools list` After Provider Switch** - Now correctly lists tools after `/provider gemini`
- **Tool JSON Leak** - No longer leaks to VSCode during streaming

### Documentation
- Archived legacy documentation to `docs/archive/legacy-tools-docs/`
- Updated all guides for EngineClient architecture
- Autocomplete documentation across all relevant guides

## [1.11.3] - 2025-12-24

### Added - Foundation Refactoring + Critical Bugfixes âš™ï¸ðŸ”§

**Note:** This release consolidates v1.11.2.1 and v1.11.2.2 into v1.11.3 due to VSCode extension versioning constraints (only supports 3-part semantic versioning: major.minor.patch).

This release combines two critical patches: provider abstraction improvements and autorouter fixes, providing a solid foundation for adding new AI providers.

#### Autorouter Fix (from v1.11.2.1)

- **Fixed Provider Mismatch in Autorouter** - Coding commands now work with all providers
  - **Problem**: Using `/convert`, `/generate`, etc. with Gemini/OpenAI caused 404 errors
  - **Root Cause**: 7 coding command handlers didn't pass `self.provider` to `send_coding_task()`
  - **Fix**: All 7 handlers now pass current provider parameter
  - **Impact**: Autorouting now respects provider (Perplexityâ†’sonar-pro, Geminiâ†’gemini-2.5-pro, OpenAIâ†’gpt-4o, etc.)

#### Provider Abstraction Improvements (from v1.11.2.2)

- **Configurable Default Provider** - No more hardcoded "perplexity"
  - New `get_default_provider()` function with smart fallback chain
  - `DEFAULT_PROVIDER` environment variable support (`.env`)
  - Fallback order: env var â†’ first available provider â†’ perplexity
  - Documented in `.env.example`

- **Provider-Specific Pricing** - Each provider can have its own pricing model
  - New `get_model_pricing(provider)` function for any provider
  - Backward compatible: Legacy `MODEL_PRICING` global still exists

- **AIClientWithTools Alias** - Better naming for provider-agnostic tool client
  - `AIClientWithTools` = `PerplexityClientPromptTools` (same class, clearer name)
  - Updated docstring: "works with ALL providers (not just Perplexity)"
  - Both names supported for backward compatibility

### Fixed - Critical TUI Bugs ðŸ”§

**From branch `bugfix/gemini-tool-calling`**

- **Bug #1: Tools Status Not Persisting** - Tools now stay ON when switching providers
  - **Before**: Enable tools on Perplexity â†’ switch to Gemini â†’ Tools show OFF âŒ
  - **After**: Tools remain ON across provider switches âœ…
  - **Root Cause**: `handle_provider()` didn't check if tools were enabled before switching
  - **Fix**: Added tools persistence logic in `ppxai/commands.py` (lines 388-420)
  - **Testing**: Manual TUI testing confirms fix works

- **Bug #2: Gemini Tool Call Parsing Failure** - Fixed nested JSON parsing
  - **Before**: Gemini showed raw JSON instead of executing tools âŒ
  - **After**: Gemini tool calls execute correctly âœ…
  - **Root Cause**: Regex pattern `r'\{\s*"tool"\s*:\s*"[^"]+"\s*[^}]*\}'` broke on nested `arguments` object
  - **Fix**: Extract JSON using first/last brace positions instead of regex (`perplexity_tools_prompt_based.py` lines 1054-1083)
  - **Testing**: 4/4 new regression tests passing

### Documentation

- **docs/BUGFIX-gemini-tool-calling.md** - NEW: Comprehensive analysis of both bugs with root causes and fixes
- **docs/PROVIDER-TOOLS-COMPATIBILITY.md** - NEW: Guide explaining how tools work across different providers
- **docs/PROVIDER-ABSTRACTION-REFACTORING.md** - NEW: Detailed refactoring analysis and v1.12.0 recommendations
- **docs/RELEASE-NOTES-v1.11.2.2.md** - NEW: Complete release notes with migration guide

### Testing

- **4 new regression tests** in `tests/test_provider_tools_bugfixes.py`
  - `test_provider_switching_fix_documented()` - Documents Bug #1 fix
  - `test_parse_gemini_nested_json_tool_call()` - Tests Gemini nested JSON parsing
  - `test_parse_tool_call_in_code_block()` - Tests code block tool calls
  - `test_parse_tool_call_simple_no_nested_args()` - Tests simple tool calls
- All 4 tests passing (100%)
- Manual TUI testing confirms both bugs fixed

### Changed

- `ppxai/config.py` - Added `get_default_provider()` and `get_model_pricing(provider)` functions
- `ppxai/commands.py` - Use configurable default provider, tools persistence fix
- `perplexity_tools_prompt_based.py` - Gemini JSON parsing fix, added AIClientWithTools alias
- `.env.example` - Document `DEFAULT_PROVIDER` option

### Impact

- âœ… **Adding new providers now requires ZERO code changes** (config-only)
- âœ… Tools work correctly with all providers (Perplexity, Gemini, OpenAI, OpenRouter, Ollama)
- âœ… Solid foundation for v1.12.0+ features (deprecation warnings, code cleanup)

### Migration Guide

**For Users**: No breaking changes! Everything works as before.
- Optional: Set custom default provider via `DEFAULT_PROVIDER=gemini` in `.env`

**For Developers**: Recommended but not required:
- Use `get_default_provider()` instead of hardcoded "perplexity"
- Use `get_model_pricing(provider)` instead of global `MODEL_PRICING`
- Use `AIClientWithTools` alias for new code (clearer name)

### VSCode Extension Versioning Note

âš ï¸ **Important**: VSCode extensions only support 3-part semantic versioning (`major.minor.patch`). This is why v1.11.2.1 and v1.11.2.2 were consolidated into v1.11.3. Future releases will use 3-part versions only (e.g., 1.11.3 â†’ 1.11.4 â†’ 1.12.0).

## [1.11.2] - 2025-12-22

### Added - Shell Command Consent Security + Shared Modules Refactoring ðŸ”’

This release introduces two major improvements: a comprehensive shell command consent system for secure AI command execution, and complete shared modules architecture refactoring.

#### Shell Command Consent System

- **Regex-Based Command Classification** - Three-tier security model:
  - **Safe Commands** - Auto-approved read-only operations (ls, cat, grep, pwd, which, whoami, date, uname)
  - **Dangerous Commands** - Require user consent (rm, mv, chmod, sudo, curl | bash, kill, pkill)
  - **Never-Allow Commands** - Always blocked (rm -rf /, dd of=/dev/, fork bombs, mkfs)

- **Session-Scoped Consent** - Flexible approval options:
  - **y (yes, once)** - Approve this command execution
  - **n (no, once)** - Deny this command execution
  - **always** - Auto-approve all matching commands (this session)
  - **never** - Block all matching commands (this session)
  - Consent decisions persist for entire session
  - No persistence to disk (security feature)

- **TUI Consent Interface** - Terminal prompt with command details:
  - Shows command, working directory, risk level
  - Keyboard-friendly y/n/always/never input
  - Clear classification feedback

- **VSCode QuickPick Consent** - Native VSCode consent UI:
  - Keyboard navigation (no mouse required)
  - Four clear options: "Yes, Once", "Yes, Always", "No, Once", "No, Never"
  - Command context and risk level display
  - Dismissible (ESC to cancel)

- **Configuration System** - Customizable patterns in ppxai-config.json:
  - `tools.shell.allowed_commands` - Safe command patterns
  - `tools.shell.dangerous_commands` - Require consent patterns
  - `tools.shell.never_allow` - Forbidden command patterns
  - Uses Python regex with negative lookaheads for security

- **Critical Security Fix** - Commands with redirections now require consent:
  - `cat > file.txt` classified as dangerous (not safe)
  - `echo data > file.txt` classified as dangerous (not safe)
  - Uses `(?!.*[><])` negative lookahead in patterns

#### Shared Modules Architecture Refactoring

- **ppxai/common/ Directory** - Centralized shared code (55KB total):
  - `consent.py` (21KB) - Unified consent system for file editing and shell commands
  - `logger.py` (8KB) - Shared logging system replacing TUI-specific logger
  - `event_handler.py` (9KB) - Common event processing for both TUI and VSCode
  - `commands.py` (14KB) - Shared command handlers

- **TUI Adapter** - TUI now uses shared modules:
  - Migrated from `tui_logger.py` to `ppxai.common.logger`
  - Uses shared consent manager
  - Event handler integration
  - Eliminates duplicate code

- **HTTP Server Adapter** - VSCode backend uses shared modules:
  - Shared logger for consistent logging
  - Shared consent manager
  - Event processing via shared handler
  - Unified architecture with TUI

- **Backward Compatibility** - No breaking changes:
  - Existing ppxai-config.json files work unchanged
  - API remains compatible
  - All existing tests pass

#### Files Changed

**Shell Consent:**
- `ppxai/engine/client.py` - Added request_shell_consent() and command classification
- `ppxai/engine/session.py` - Shell consent state tracking (shell_consent_mode, allowed_shell_patterns, denied_shell_patterns)
- `ppxai/engine/tools/builtin/shell.py` - Integrated consent system into execute_shell_command
- `ppxai/server/http.py` - Added POST /shell-consent endpoint for VSCode
- `ppxai/commands.py` - TUI shell consent handler
- `vscode-extension/src/chatPanel.ts` - QuickPick consent UI implementation
- `ppxai-config.json` - Added tools.shell configuration section
- `docs/shell-consent-guide.md` - NEW: Comprehensive 642-line security guide
- `docs/RELEASE-NOTES-v1.11.2.md` - NEW: Detailed release notes

**Shared Modules:**
- `ppxai/common/__init__.py` - NEW: Public exports for shared modules
- `ppxai/common/consent.py` - NEW: Unified consent system
- `ppxai/common/logger.py` - NEW: Shared logging (replaces tui_logger.py)
- `ppxai/common/event_handler.py` - NEW: Common event processing
- `ppxai/common/commands.py` - NEW: Shared command handlers
- `ppxai/main.py` - Integrated shared modules into TUI
- `ppxai/server/http.py` - Integrated shared logger into HTTP server
- `tests/test_consent.py` - Updated for file_mode/shell_mode keys
- `tests/test_common_*.py` - NEW: Comprehensive tests for shared modules

#### Testing
- **308/308 tests passing (100%)** - All tests green
- Shell consent integration tests with edge cases
- Shared modules comprehensive test coverage
- Pattern matching validation (safe/dangerous/never)
- TUI and VSCode consent flow end-to-end tested

#### Documentation
- [docs/shell-consent-guide.md](docs/shell-consent-guide.md) - Complete security guide
- [docs/RELEASE-NOTES-v1.11.2.md](docs/archive/release-notes/RELEASE-NOTES-v1.11.2.md) - Full release notes
- Updated README.md with shell consent features
- Updated CLAUDE.md with v1.11.2 summary

### Changed
- Version bumped to 1.11.2 in all package files (pyproject.toml, vscode-extension/package.json)
- TUI and HTTP server now share common modules (no duplicate code)
- Architecture unified between all clients (TUI, VSCode, future web UI)

## [1.11.1] - 2025-12-22

### Fixed - Critical TUI Regression âš ï¸

This release fixes a critical regression in v1.11.0 where the TUI failed to display AI responses when tools were enabled.

#### Root Cause
- v1.11.0 switched TUI to use `EngineClient.chat_sync()` to enable file editing tools
- However, `chat_sync()` returns a plain string without rendering (pure function)
- Legacy `AIClient.chat()` had built-in console printing (side effect)
- Result: Response was set but never displayed to user

#### Solution
- **Unified Architecture:** Refactored TUI to use async event stream (like VSCode extension)
- **Event Handling:** TUI now properly handles all event types:
  - `STREAM_CHUNK` - Streaming response chunks
  - `TOOL_CALL` - Tool execution notifications
  - `TOOL_RESULT` - Tool results
  - `CONSENT_REQUEST` - File edit consent prompts
  - `ERROR` - Error messages
- **Real-time UX:** TUI now shows streaming chunks, tool calls, and consent prompts in real-time
- **Code Quality:** Eliminates architectural divergence between TUI and VSCode extension

#### Performance
- **No regression:** EngineClient is actually **16.5% faster** than legacy (2446ms vs 2929ms total time)
- TTFT: 1453ms, Total: 2446ms, Throughput: 64.0 tok/s
- Benchmarked against v1.10.5 baseline

#### Files Changed
- `ppxai/main.py` - Added event-based streaming loop (lines 268-325)
- `pyproject.toml` - Version 1.11.0 â†’ 1.11.1
- `vscode-extension/package.json` - Version 1.11.0 â†’ 1.11.1
- `README.md` - Updated version references and installation instructions
- `vscode-extension/README.md` - Updated version references
- `docs/README.md` - Updated version references
- `CLAUDE.md` - Documented v1.11.1 changes

#### Additional Fixes
- **Conversation History Sync:** Fixed 400 error when using tools with conversation history
  - Engine client and legacy client now properly sync conversation history
  - Fixes message alternation errors ("user or tool message(s) should alternate with assistant message(s)")
  - Syncs history when enabling tools and after each response
- **Inline Markdown in Tables:** File names and inline code now render properly in markdown tables
  - Added `parse_inline_markdown()` to handle backticks, bold, italic in table cells
  - Inline code (`` `text` ``) renders with cyan monospace on grey background (GitHub-like)
  - Bold (`**text**`) and italic (`*text*`) also supported
  - Files: `ppxai/markdown_tables.py` (lines 16-64, 135)

#### New Features
- **Verbose Tool Logging:** Added `/tools set verbose` command to inspect tool inputs/outputs
  - `/tools set verbose on` - Show tool arguments and results during execution
  - `/tools set verbose off` - Hide detailed tool information (default)
  - Useful for debugging and understanding AI tool calls
  - Files: `ppxai/commands.py` (lines 134, 495, 665-698), `ppxai/main.py` (lines 295-302)

#### Testing
- **296/301 tests passing** (same as v1.11.0)
- 5 failures are pre-existing custom endpoint config issues (unrelated)
- Syntax validated, imports verified
- Manually tested: verbose mode, conversation history sync, inline code rendering

### Changed
- Version bumped to 1.11.1 in all package files
- Updated all installation instructions to reference v1.11.1
- Updated documentation to reflect unified event-based architecture
- Enhanced markdown table rendering with inline formatting support

## [1.11.0] - 2025-12-21

### Added - File Editing Tools with User Consent ðŸŽ¯

This release introduces **autonomous file editing** capabilities with a comprehensive consent system, transforming ppxai into the first phase of an agentic developer assistant.

#### Core Features
- **4 File Editing Tools** - AI can now modify files with user permission:
  - `apply_patch` - Apply unified diff patches (git-style)
  - `replace_block` - Search and replace exact text blocks
  - `insert_text` - Insert text at specific line numbers
  - `delete_lines` - Delete line ranges from files

- **Per-File Session Consent System** - Safety-first approach:
  - **y (yes)** - Allow editing this file (this session)
  - **n (no)** - Deny this edit
  - **always** - Auto-approve all files (this session)
  - **never** - Block all edits (this session)
  - Consent persists only for current session
  - Separate consent tracking per file path

- **TUI Consent Prompts** - Interactive validation using prompt_toolkit:
  - Clear file path display
  - Validated input (only y/n/always/never accepted)
  - Persistent consent state tracking

- **VSCode Consent Dialogs** - Event-driven SSE integration:
  - Modal dialogs with 4 consent options
  - Server-Sent Events for real-time communication
  - Non-blocking async consent flow

- **Atomic File Operations** - Robust and safe:
  - Write-to-temp + rename pattern
  - Automatic rollback on failure
  - File existence validation
  - Permission checks before edit

- **In-App Help System** - `/tools help editing` command:
  - Comprehensive markdown guide
  - Practical examples with chat flows
  - Consent system explanation
  - Troubleshooting tips
  - Available in both TUI and VSCode extension

#### Documentation
- **NEW:** [docs/file-editing-guide.md](docs/file-editing-guide.md) - 400+ lines comprehensive user guide
- **NEW:** [vscode-extension/TESTING.md](vscode-extension/TESTING.md) - Testing documentation for VSCode extension
- **Updated:** README.md with File Editing Tools section
- **Updated:** CLAUDE.md with v1.11.0 feature summary and version alignment

#### Testing
- **NEW:** 36 comprehensive tests for file editing features:
  - 25 tests for file editing tools ([tests/test_file_editing_tools.py](tests/test_file_editing_tools.py))
  - 11 tests for help commands and UI ([tests/test_ui.py](tests/test_ui.py), [tests/test_commands.py](tests/test_commands.py))
- **Total:** 273/278 tests passing (98.2%)
- 5 pre-existing custom endpoint integration test failures (unrelated)

#### Technical Implementation
- `ppxai/engine/tools/builtin/editor.py` - NEW, implements all 4 file editing tools
- `ppxai/engine/client.py` - Added `request_file_edit_consent()` async method
- `ppxai/engine/session.py` - Added consent state (`allowed_files`, `edit_consent_mode`)
- `ppxai/commands.py` - TUI consent handler with prompt_toolkit validation + `/tools help editing`
- `ppxai/ui.py` - Added `display_file_editing_help()` function and updated welcome message
- `vscode-extension/src/chatPanel.ts` - Added `getFileEditingHelp()` + help command handler

### Changed
- Version bumped to 1.11.0 in `pyproject.toml` and `vscode-extension/package.json`
- Updated ROADMAP.md to reflect Phase 1 completion
- Updated all version references throughout documentation

### Fixed
- VSCode extension `/tools help editing` command now displays formatted help content

---

## [1.10.8] - 2025-12-21

### Added
- Unified `/save` and `/export` commands across TUI and VSCode extension
- New `/export [filename]` command exports last answer to markdown (`~/.ppxai/exports/`)
- Clear separation between session persistence (JSON) and answer export (markdown)

### Changed
- `/save` now saves session to JSON (`~/.ppxai/sessions/`) for persistence
- VSCode extension "Save Answer" button now saves to exports folder with auto-generated filenames

### Improved
- VSCode extension interrupt UX - orange pulsing "â¹ Streaming..." badge in header
- Streaming interrupt no longer shows red error message on user-initiated stop

---

## [1.10.7] - 2025-12-20

### Fixed
- Perplexity API compatibility - removed deprecated `sonar-reasoning` model
- Model documentation updated to reflect current Perplexity API

### Changed
- Supported Perplexity models: sonar, sonar-pro, sonar-reasoning-pro, sonar-deep-research

---

## [1.10.6] - 2025-12-20

### Added
- Gemini 3 Flash Preview - Speed-optimized with frontier intelligence and 1M context
- Gemini 3 Pro Preview - Most powerful agentic model with code execution and search grounding
- Enhanced model descriptions with detailed capabilities
- Preview pricing estimates for Gemini 3 models

---

## [1.10.5] - 2025-12-20

### Added
- Status bar showing provider, model, and tools status
- VSCode extension interrupt support via Esc key and Command Palette
- TUI Ctrl-C double-press pattern (2s timeout) - first press warns, second exits
- 7 new interrupt handling tests

### Fixed
- Ctrl-C during streaming no longer causes message alternation errors
- Conversation history cleanup on interrupt maintains LLM message alternation
- Gemini tools None content handling
- FastAPI deprecation warnings (migrated to lifespan pattern)

### Testing
- 235/241 tests passing

---

## [1.10.4] - 2025-12-19

### Fixed
- Markdown tables now render properly in TUI (no more raw `|:---|:---|` syntax)
- Tables support left/center/right alignment (`:---`, `:---:`, `---:`)
- `/show` command renders markdown files with formatted tables
- All AI responses render tables correctly

### Added
- 27 new regression tests for table rendering

---

## [1.10.3] - 2025-12-18

### Added
- Standalone `ppxai-server` executables for all platforms (no Python required)
- Automated GitHub Actions CI/CD for multi-platform builds:
  - macOS ARM64 & Intel
  - Linux AMD64
  - Windows

---

## Earlier Versions

See [ROADMAP.md](ROADMAP.md) for historical release information.

---

## Versioning

ppxai follows [Semantic Versioning](https://semver.org/):
- **MAJOR** version for incompatible API changes
- **MINOR** version for new functionality in a backwards compatible manner
- **PATCH** version for backwards compatible bug fixes

## Release Process

1. Update version in `pyproject.toml` and `vscode-extension/package.json`
2. Update CHANGELOG.md with release notes
3. Update ROADMAP.md to move release from "Next" to "Current"
4. Create git tag: `git tag -a v1.x.x -m "Release v1.x.x"`
5. Push tag: `git push origin v1.x.x`
6. GitHub Actions automatically builds and creates release

[1.15.5]: https://github.com/rcconsult/ppxai/releases/tag/v1.15.5
[1.15.4]: https://github.com/rcconsult/ppxai/releases/tag/v1.15.4
[1.15.3]: https://github.com/rcconsult/ppxai/releases/tag/v1.15.3
[1.15.2]: https://github.com/rcconsult/ppxai/releases/tag/v1.15.2
[1.15.1]: https://github.com/rcconsult/ppxai/releases/tag/v1.15.1
[1.15.0]: https://github.com/rcconsult/ppxai/releases/tag/v1.15.0
[1.14.2]: https://github.com/rcconsult/ppxai/releases/tag/v1.14.2
[1.14.1]: https://github.com/rcconsult/ppxai/releases/tag/v1.14.1
[1.14.0]: https://github.com/rcconsult/ppxai/releases/tag/v1.14.0
[1.13.10]: https://github.com/rcconsult/ppxai/releases/tag/v1.13.10
[1.13.9]: https://github.com/rcconsult/ppxai/releases/tag/v1.13.9
[1.13.8]: https://github.com/rcconsult/ppxai/releases/tag/v1.13.8
[1.13.7]: https://github.com/rcconsult/ppxai/releases/tag/v1.13.7
[1.13.6]: https://github.com/rcconsult/ppxai/releases/tag/v1.13.6
[1.13.5]: https://github.com/rcconsult/ppxai/releases/tag/v1.13.5
[1.13.4]: https://github.com/rcconsult/ppxai/releases/tag/v1.13.4
[1.13.3]: https://github.com/rcconsult/ppxai/releases/tag/v1.13.3
[1.13.2]: https://github.com/rcconsult/ppxai/releases/tag/v1.13.2
[1.13.1]: https://github.com/rcconsult/ppxai/releases/tag/v1.13.1
[1.13.0]: https://github.com/rcconsult/ppxai/releases/tag/v1.13.0
[1.12.5]: https://github.com/rcconsult/ppxai/releases/tag/v1.12.5
[1.12.4]: https://github.com/rcconsult/ppxai/releases/tag/v1.12.4
[1.12.3]: https://github.com/rcconsult/ppxai/releases/tag/v1.12.3
[1.12.2]: https://github.com/rcconsult/ppxai/releases/tag/v1.12.2
[1.12.1]: https://github.com/rcconsult/ppxai/releases/tag/v1.12.1
[1.12.0]: https://github.com/rcconsult/ppxai/releases/tag/v1.12.0
[1.11.9]: https://github.com/rcconsult/ppxai/releases/tag/v1.11.9
[1.11.8]: https://github.com/rcconsult/ppxai/releases/tag/v1.11.8
[1.11.7]: https://github.com/rcconsult/ppxai/releases/tag/v1.11.7
[1.11.6]: https://github.com/rcconsult/ppxai/releases/tag/v1.11.6
[1.11.5]: https://github.com/rcconsult/ppxai/releases/tag/v1.11.5
[1.11.4]: https://github.com/rcconsult/ppxai/releases/tag/v1.11.4
[1.11.3]: https://github.com/rcconsult/ppxai/releases/tag/v1.11.3
[1.11.2]: https://github.com/rcconsult/ppxai/releases/tag/v1.11.2
[1.11.1]: https://github.com/rcconsult/ppxai/releases/tag/v1.11.1
[1.11.0]: https://github.com/rcconsult/ppxai/releases/tag/v1.11.0
[1.10.8]: https://github.com/rcconsult/ppxai/releases/tag/v1.10.8
[1.10.7]: https://github.com/rcconsult/ppxai/releases/tag/v1.10.7
[1.10.6]: https://github.com/rcconsult/ppxai/releases/tag/v1.10.6
[1.10.5]: https://github.com/rcconsult/ppxai/releases/tag/v1.10.5
[1.10.4]: https://github.com/rcconsult/ppxai/releases/tag/v1.10.4
[1.10.3]: https://github.com/rcconsult/ppxai/releases/tag/v1.10.3
