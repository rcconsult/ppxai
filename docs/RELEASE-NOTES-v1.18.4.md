# Release Notes — v1.18.4

> **Scope:** A bugfix release. Post-v1.18.3 fixes only — no new
> features. The v1 API gateway shape (`POST /v1/oneshot`, bearer-token
> auth) is load-bearing for ppxai-sre's outlook-monitor agent and is
> preserved byte-identical.
>
> **Two themes ran in parallel through this branch.** The first is a
> wave of correctness fixes that surfaced once v1.18.3 was actually
> running in user hands: a Linux-only SIGTERM regression in the new
> async shell tool that local macOS runs missed; a `/ls` web-renderer
> bug that turned out to be the canary for a systemic `to_dict()` +
> renderer-dispatch gap (10 more `CommandResult` subclasses + 6 more
> renderer-fall-through cases); a `list_directory` cwd-confabulation
> bug that turned out to be the canary for a defense-in-depth pass
> across seven cwd-relevant tools. Each fix landed alongside a
> sentinel test suite that catches the class of bug at PR-time. The
> second theme is release-tooling and documentation hygiene:
> `wait_for_ci` no longer trusts stale completed runs (the v1.18.3
> tag-cycle near-miss); web preview URLs handle absolute-vs-relative
> paths correctly across `working_dir`; deploy `values.yaml` no
> longer ships placeholder providers; the rolling
> `docs/DEBT-INVENTORY.md` replaces the per-version snapshot pattern;
> four closed TODOs moved to `docs/archive/` with all 17 inbound
> links rewritten; the `build-install` skill grew cross-platform
> coverage (with a Windows PowerShell `Start-Job` snippet bug fixed
> after running it end-to-end). Two new research notes capture
> v1.19.x planning (OpenShell coordination patterns; ppxai-sre
> support requirements) plus a ROADMAP section for the v1.19.x
> agent-platform work.
>
> **Tests:** runtime fixes ship with two new sentinel suites — 87
> parametrized cases in `test_command_result_serialization.py`
> structurally catching the `to_dict()` / renderer-dispatch gap, and
> 13 cases in `test_cwd_grounding.py` pinning every cwd-relevant
> tool's output shape plus the AppState→prompt sync invariant. Plus
> +12 tests for `/ls` `/tree` renderer dispatch, +8 for
> `list_directory` echo, +7 for `wait_for_ci` stale-run distrust.

## Summary

v1.18.4 is structured as bugfix-class follow-up to v1.18.3. Themes
1–6 are runtime correctness; themes 7–11 are release tooling, doc
hygiene, and v1.19.x planning. Every code-affecting commit is also
documented in `CHANGELOG.md` for the same date — these notes provide
the connective narrative.

1. **Linux SIGTERM process-group fix in async shell tool**
   (`0500d56f`). v1.18.3's async-shell-tool work spawns commands via
   `asyncio.create_subprocess_shell(..., start_new_session=True)`.
   The OS process tree is `/bin/sh -c "<command>"` →
   `<actual command>`. Calling `proc.terminate()` only sends SIGTERM
   to the shell wrapper; the child inherits the wrapper's
   stdout/stderr file descriptors, so even after the wrapper exits
   the FDs remain open in the child. `proc.communicate()` keeps
   waiting on EOF — i.e. for the child's natural timeout — instead
   of returning when the wrapper dies. **macOS happens to behave
   differently for orphan-with-inherited-FDs so the test passed
   locally; Linux CI failed at the v1.18.3 release tag.** Fix: send
   SIGTERM to the whole process group via `os.killpg(pgid, ...)` so
   both wrapper and child receive the signal. New helpers
   `terminate_subprocess_tree(proc)` and `kill_subprocess_tree(proc)`
   in `engine/tools/shell.py`; `interrupt_stream` and the
   timeout/cancel paths use them. This is a textbook "passes
   locally, fails in CI" cross-platform divergence — the lesson is
   captured in the trust-but-verify discipline already in CLAUDE.md.

2. **`wait_for_ci` no longer trusts stale completed runs** (`dc21c87f`).
   Surfaced by the v1.18.3 release tag-cycle: after `--redo` deleted
   the broken tag and re-pushed, `wait_for_ci` polled `gh run list`
   during the brief window when GitHub had not yet registered the
   new run. Only the OLD failed run from the previous tag-cycle was
   visible; the previous logic accepted its `conclusion="failure"`
   as authoritative — returning False before the new run started.
   The script then jumped to `publish_release_notes` which exhausted
   its 12 retries against a release object that didn't yet exist
   (CI's release job hadn't run because `wait_for_ci` wrongly
   declared CI failed). Real CI for the v1.18.3 redo finished
   successfully and created the release with all 20 assets — the
   script's exit-status was a false-negative. Fix: NEVER trust a
   "completed" status until we have observed the run go through
   "queued" or "in_progress". Treat both stale success and stale
   failure as untrustworthy and keep polling. The notes-publishing
   race is fixed transitively. +7 tests in
   `tests/test_release_wait_for_ci.py`.

3. **`/ls` and `/tree` web/VSCode renderer dispatch** (`462e6739`).
   Surfaced from a v1.18.3 user report: typing `/ls` in the web UI
   returned only `"44 items in /Users/rado/git/exps"` — the
   `result.message` — instead of the actual rows. Two related root
   causes: (a) Web/VSCode renderers dispatch on the wire `result.type`
   STRING, not Python class hierarchy. `DirectoryListingResult` is a
   Python `TableResult` subclass, so its serialized type is
   `"DirectoryListingResult"` — without an explicit handler,
   dispatch fell through to the unknown-type fallback that shows
   only `result.message`. The Python docstring's claim "Renderers
   that handle TableResult automatically handle this" was true for
   Rich/Textual (class-based dispatch) but false for the HTTP
   renderers. (b) `TreeResult` had NO `to_dict()` override at all —
   it inherited `CommandResult`'s base which only emits
   `type/status/message/metadata`. The `root` tree was silently
   dropped on the wire. Same class of bug as v1.18.3's
   `CompositeResult.to_dict()` fix (`848b4d99`). Fix: explicit
   handlers in both renderers + `TreeResult.to_dict()` override. +12
   tests in `tests/test_directory_result_renderers.py`.

4. **Systemic `to_dict()` and renderer-dispatch audit closed**
   (`1a81cb09`). The `/ls` symptom was the canary for a deeper bug.
   A scan of `ppxai/commands/results.py` confirmed 10 more
   `CommandResult` subclasses with the same `to_dict()` gap and 6
   more with the same renderer-dispatch gap (some overlapping). Mode
   A (dropped fields) added `to_dict()` overrides on:
   `NotificationResult`, `AIResponseResult`, `ListResult`,
   `FileViewResult`, `MarkdownResult`, `ImageResult`, `PreviewResult`,
   `ProgressResult`, `DiffResult`, `ConsentResult`, `PromptResult`,
   `ToolExecutionResult` (six fields incl. nested `to_dict()` for
   `artifacts` like `CompositeResult.results`), `TextResult`. Mode B
   (renderer falls through) added explicit handlers on web
   (`ppxai/web/shared/result-renderer.js`) and VSCode
   (`vscode-extension/src/commandRenderer.ts`) for: `AIResponseResult`,
   `ProgressResult`, `DiffResult`, `ConsentResult`, `PromptResult`,
   `ToolExecutionResult`. New sentinel suite
   `tests/test_command_result_serialization.py` (87 parametrized
   cases) walks `CommandResult.__subclasses__()` recursively and
   asserts: (1) every dataclass field appears in the result of
   `to_dict()`, with a copy-pasteable override stub in the failure
   message; (2) the wire-format `type` field is the concrete
   subclass name (renderer dispatch key); (3) every subclass has an
   explicit handler in `result-renderer.js` (or appears in
   `_SIDE_EFFECT_DRIVEN` opt-out for types that ride a side-effect
   kind); (4) every subclass has a case branch in VSCode's
   `commandRenderer.ts` switch. Plus tests that nested-result
   containers recurse via the children's own `to_dict()`. The class
   of bug that hit us 13 times historically is now structurally
   caught at PR-time, not in production.

5. **`list_directory` tool echoes the resolved path in its header**
   (`ee90bff4`). Reported 2026-05-04 from the web UI: after
   `/cd ppxai_demo`, asking the model "ls" produced
   `"/Users/rado/git/exps contains the files and folders listed
   above"` — the PARENT of the actual working dir. Root cause: the
   tool returned bare item names (e.g. `DIR foo\nFILE bar`) with no
   path header. The model called the tool with `path="."` (default)
   and had no way to know which directory it just listed, so it
   confabulated a path in its response. Fix: prefix the resolved
   absolute path in the tool's output (`Listing of /path:` /
   `Long-format listing of /path:`). Empty directories still emit
   the header followed by `(empty)`. +8 tests in
   `tests/test_list_directory_tool.py`.

6. **Cwd-grounding pass across cwd-relevant tools** (`1a301d4e`).
   The `list_directory` symptom was the canary for a deeper class of
   bug. Audit of every cwd-relevant tool found 7 more sites where
   output didn't ground the model in observable facts.

   Critically: **the v1.18.x AppState→client→UI sync invariant DID
   hold.** The system prompt at `tools/manager.py:357` correctly
   includes `**Current Working Directory:** /path` — programmatically
   verified by the new sentinel test
   `test_tools_prompt_includes_current_working_directory` in
   `tests/test_cwd_grounding.py`. But the LLM doesn't always obey
   the system prompt. **Defense-in-depth**: tool outputs are what
   the model summarizes from, so put the truth there too.

   Mode A (output lacks cwd grounding) — `ShellExecuteTool`
   foreground commands now prefix `[cwd: /path]\n` (or
   `[cwd: /path, exit: N]\n` on non-zero exit); stderr-only commands
   like `gh auth status` get explicit `--- stderr ---` separator
   even when stdout is empty so the model can tell the source.
   `SearchFilesTool` zero-match and match paths now prefix
   `Searched for '<pattern>' in <dir>:`. `DisplayFileTool` success
   message uses resolved absolute path instead of basename. Mode C
   (success message uses input arg, not resolved path) — editor
   tools `ApplyPatchTool`, `ReplaceBlockTool`, `InsertTextTool`,
   `DeleteLinesTool` now quote the resolved absolute `path` instead
   of the input `file_path` (often a relpath like `foo.py`); without
   the fix, after several edits across `/cd` boundaries the model
   could lose track of which on-disk file it actually wrote.

   System prompt strengthened from "do NOT rely on previous tool
   results" to "**This cwd is the ONLY source of truth for your
   current location.** ... When summarizing tool output that
   references a path or directory, verify against the cwd above
   before quoting any other path. If a tool's output starts with a
   header like `Listing of /path/to/dir:` or `[cwd: /path/to/dir]`,
   quote that path verbatim — do not substitute a path from memory."
   New `tests/test_cwd_grounding.py` (13 cases) pins every
   cwd-relevant tool's output shape AND the AppState→prompt sync
   invariant. Next time anyone reports "the LLM doesn't know my
   cwd," running these tests instantly distinguishes "the prompt is
   wrong" (test fails → bug in our sync layer) from "the LLM didn't
   obey" (test passes → model issue, not infra).

7. **Web preview URL handles absolute-vs-relative paths under
   `working_dir`** (`adfa90cf`, `d61571f9`). Two related fixes for
   the web preview iframe URL builder. (a) Strip the `working_dir`
   prefix from `filepath` when constructing the preview URL — the
   server already serves files relative to `working_dir`, so leaving
   the prefix in place produced double-prefixed paths. (b) Preserve
   absolute paths that lie OUTSIDE `working_dir` — the strip pass
   was overly aggressive and would mangle paths like
   `/etc/something` that have no relation to `working_dir`. Both
   fixes ship with renderer tests.

8. **Deploy `values.yaml` cleanup** (`16228ca5`). The Helm chart's
   default `values.yaml` shipped placeholder provider entries from
   the multi-tenant deploy work that got left in. Removed —
   deployers add their own provider config explicitly.

9. **Build-install skill: cross-platform coverage + PowerShell
   `Start-Job` bug fixed end-to-end** (`81763bbc`, `58975b07`). The
   `/build-install` skill (used to validate a release locally
   before tagging) grew explicit coverage for macOS Apple Silicon,
   macOS Intel, Linux, and Windows after originally being
   macOS-arm64-shaped. Then, running it end-to-end on Windows for
   v1.18.4 surfaced two real PowerShell bugs in the parallel-build
   `Start-Job` snippet: (1) `$jobs = @( Start-Job { ... }, ... )`
   array-literal form errors with `Cannot bind parameter because
   parameter 'Name' is specified more than once` because PowerShell
   parses the comma-list as one call with multiple `-ScriptBlock`
   arguments; (2) `Start-Job` runs in a child PowerShell process
   with CWD = `$HOME`, so a bare `.\.uv\uv.exe run ...` inside the
   scriptblock can't find the binary because the child isn't in the
   project dir. Fixed inline with the verified-working form (assign
   each job to its own variable; pass `$wd` via `-ArgumentList`;
   `Set-Location $wd` first thing in each scriptblock). Also added
   inline notes above the snippet explaining the gotchas, so a
   future reader who hits the failure mode finds the explanation.

10. **Doc hygiene: rolling DEBT-INVENTORY + 4 archived TODOs**
    (`95808272`, `8d06e1c0`, `bdabf511`). Three doc-organization
    moves landed during the branch. (a) `docs/DEBT-INVENTORY.md`
    becomes a rolling open-items list; per-version snapshots
    (`DEBT-INVENTORY-v1.18.2.md`, `DEBT-INVENTORY-v1.18.3.md`)
    moved to `docs/archive/` as historical "what closed in vX.Y.Z"
    rationales. (b) Four closed TODOs retired to `docs/archive/`:
    `TODO-v1.18.1-state-sync-determinism.md` (phases A–E shipped),
    `TODO-v1.18.1-command-unification.md` (shipped v1.18.1),
    `TODO-v1.18.2-prompt-text-kind.md` (closed 2026-05-03, landed
    v1.18.3), `TODO-v1.18.2-agent-loop-unification.md` (re-scoped,
    superseded by ADR 0003), `TODO-release-tooling.md` (closed
    2026-05-03, landed v1.18.3). 17 inbound links rewritten across
    CHANGELOG, 3 RELEASE-NOTES, ADR 0001 + 0003, archived
    DEBT-INVENTORY-v1.18.2.md so release-notes pointers stay valid.
    (c) Anthropic provider moved from debt inventory to
    `ROADMAP.md §"v1.19.x - Anthropic Provider (planned)"` — feature
    work, not bug-fix-class debt.

11. **v1.19.x planning captured: two research notes + ROADMAP entry**
    (`1dc161ea`, `b47d2907`). Reviewed NVIDIA's OpenShell
    multi-agent-notepad example
    (https://github.com/NVIDIA/OpenShell/tree/main/examples/multi-agent-notepad)
    in the context of ADR 0003 — Agent platform architecture. New
    `docs/research/2026-05-10-openshell-coordination-patterns.md`
    (271 lines) concludes most of OpenShell (containers, bash
    orchestration, credential broker, GitHub-as-substrate) doesn't
    fit ppxai's single-user shape, but three patterns lift cleanly:
    SHA-conditional 409-retry writes (already used in `cwd_anchor`),
    `runs/<run_id>/agent-<n>/` artifact namespace (collapses 4 ADR
    0003 "what's missing" items into one shape), and the map-reduce
    demo shape as canonical sub-agent example for v1.19.x docs. New
    `docs/research/2026-05-10-ppxai-sre-requirements.md` re-evaluates
    OpenShell through ppxai-sre's multi-tenant threat model and
    surfaces three more items that became load-bearing once the
    cluster shape was considered: network policy enforcement
    (must-have v1.19.x — load-bearing for ppxai-sre's policy engine),
    promote DEBT-INVENTORY Item 3 (k8s session-manager IS ppxai-sre's
    deployment substrate), credential broker (defer v1.20.x —
    operational maturity, not a Stage 2 blocker). New ROADMAP
    section "v1.19.x — Agent platform Stage 2 + v1 gateway
    extensions for ppxai-sre" between the Anthropic Provider and
    Prompt Analyzer entries: 6 must-have phases, 1 should-have, 5
    deferred-to-v1.20.x.

## Themes in detail

### Themes 1–6: runtime correctness

Every runtime fix on this branch traces to a v1.18.3-shipped artifact
running under real conditions and surfacing a defect:

- The Linux SIGTERM bug ships in v1.18.3's brand-new async shell
  tool and only manifests on Linux. Caught by CI on the v1.18.3
  release tag itself.
- The `/ls` web-renderer bug ships in the v1.18.3 web build and
  surfaces from a user typing `/ls` and getting only the message
  back. The audit that followed found 16 more sites with the same
  shape — 13 `to_dict()` gaps + 6 renderer-fall-through cases (some
  overlapping).
- The `list_directory` cwd-confabulation surfaces from a user typing
  `/cd ppxai_demo` then "ls" and getting the parent dir back. The
  audit that followed found 7 more cwd-relevant tools with the same
  shape across `ShellExecuteTool`, `SearchFilesTool`,
  `DisplayFileTool`, and the four editor tools.

The pattern in all three cases is **"canary symptom + audit + sentinel
suite + system-prompt strengthening."** The sentinel suites
(`test_command_result_serialization.py` 87 cases,
`test_cwd_grounding.py` 13 cases,
`test_directory_result_renderers.py` 12 cases,
`test_list_directory_tool.py` 8 cases,
`test_release_wait_for_ci.py` 7 cases) are the structural change —
each one catches its class of bug at PR-time so the next instance
fails the build instead of shipping.

### Themes 7–11: release tooling, doc hygiene, v1.19.x planning

These are non-runtime changes that don't affect the binary surface
at all:

- `wait_for_ci` distrust is the third release-tooling lesson from
  v1.18.0+v1.18.1+v1.18.3 to land — the others were the Linux-vs-Windows
  test divergence, the streaming latency tick from 6 weeks earlier,
  and the PyInstaller silent-dotenv-drop. Each one is captured in
  the trust-but-verify discipline.
- Web preview URL fixes are surface-level renderer adjustments — no
  schema changes, no event-type changes.
- `values.yaml` cleanup affects only the Helm chart's defaults; no
  one running v1.18.3 with a configured chart sees this.
- The `build-install` skill changes affect tooling, not output.
  Confidence-builder for "the v1.19.x release on Windows will be a
  one-shot."
- Doc hygiene closes 5 stale TODOs, makes the open-items list
  rolling instead of per-version snapshot, and rewires 17 inbound
  links so nothing rots. The two research notes + ROADMAP entry are
  v1.19.x planning anchors that don't change anything in v1.18.4.

## v1 API gateway stability commitment

`POST /v1/oneshot` and the bearer-token auth middleware ship in
v1.18.4 byte-identical to v1.18.3. No fields added, no fields
removed, no status-code changes, no header changes. The v1 stability
commitment per
[ADR 0004](decisions/0004-llm-gateway-features.md) is upheld.

ppxai-sre's outlook-monitor agent should consume v1.18.4 as a
drop-in replacement for v1.18.3. If you observe any v1 wire-shape
difference, that's a bug — file it.

## Upgrade notes

- **For ppxai users:** drop-in upgrade. No config changes, no
  breaking changes to slash commands, no breaking changes to the
  TUI/web/VSCode UX. The `/ls`, `/tree`, and editor-tool output
  shapes change (more grounding info in headers); if you have
  user-supplied prompts or tools that parsed the previous bare-name
  output, those need updating to skip the new header lines.
- **For ppxai-sre / external `/v1/oneshot` consumers:** no changes
  required. v1 surface preserved byte-identical.
- **For Helm chart deployers:** if you forked `values.yaml`, the
  placeholder provider entries no longer appear in the upstream
  default. Move your provider config into your fork before
  pulling v1.18.4.

## Internal

- 21 commits over the v1.18.3 release tag (`24bfe715`). All
  post-release fixes; no new features.
- Branch: `bugfix/v1.18.4`.
- Local install validation done on Windows via the `/build-install`
  skill end-to-end (caught the PowerShell `Start-Job` bug). All
  four binaries `1.18.4`; VSIX `ppxai-1.18.4.vsix` 128.88 KB / 15
  files (within CI 500 KB gate); web sync hash matches.
- `uv.lock` refreshed (`4914f06f`) — picked up via rtk-discipline
  audit during commit-flow review; revision 2→3 + ppxai editable
  entry 1.18.3→1.18.4. Should have landed with the version bump
  (`635b2cfc`) but didn't.
- v1.19.x planning (themes 11) is captured but not committed to;
  the two research notes are exploratory and the ROADMAP entry
  becomes load-bearing only when v1.19.x scope is committed.
