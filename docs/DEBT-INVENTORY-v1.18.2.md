# v1.18.2 Debt Inventory — Deferred Open Items

**Created:** 2026-04-26 (end of `bugfix/v1.18.2` branch)
**Status:** Tracking. Items here are explicitly deferred — not bugs blocking
release, but real follow-up work surfaced by the gpt-5.5 codebase critique
([session_20260419_182942.json](../README.md#related-docs)) and the test
sweep that closed critique items #1, #2, #3, #4, #5, #9, #10.

This file is the canonical home for the remaining deferred items. Each entry
links back to its critique number, gives the trigger condition for revisiting,
and estimates effort so the next contributor can scope a focused branch
without re-discovering the context.

## How to use this file

- **Update on every release.** When an item lands, move it under
  "## Closed" with the commit hash + date. When new debt surfaces, add
  it to the appropriate section.
- **Don't merge debt items into release-note TODOs.** Those describe
  in-flight work for a specific version (`TODO-v1.18.2-*.md`); this
  describes work intentionally **not** in any version's plan yet.
- **Keep entries scannable.** One short paragraph + a "trigger to
  revisit" line + an effort estimate. Long context goes in linked docs.

---

## Open

### Item 1 — God node refactoring [Critique #6]

**Affected modules:** `ppxai/tui/app.py::PPXAIDEApp` (508 inbound edges),
`ppxai/engine/client.py::EngineClient` (474 edges, partially decomposed in
v1.17.x via `ops` modules), `ppxai/tui/widgets/message_box.py::MessageBox`
(474 edges), `ppxai/tui/widgets/chat_view.py::ChatView` (443 edges).

**What the critique said:** these classes have too many responsibilities;
extract narrower services so future changes don't cascade. Specifically:
- Move session-restore + state-sync orchestration out of `PPXAIDEApp`.
- Extract rendering + state-update helpers from `MessageBox` and `ChatView`.
- Split `EngineClient` further into: chat streaming, session restore, tool
  registry, state/event queue, provider/model switching.

**Why deferred:** refactor work that doesn't fit on a bugfix branch.
Decomposing `EngineClient` already shipped 6 ops modules in v1.17.x; the
remaining hot spots are UI classes whose tests are flakier and whose
external API breaks easily.

**Trigger to revisit:** when adding a new client (Slack bot, mobile app,
CLI agent) that needs to reuse engine logic without dragging the TUI
machinery, OR when a refactor touching `PPXAIDEApp` causes its 5th
regression in a release.

**Effort:** ~1-2 weeks for a careful pass. Best done as 4 separate PRs
(one per class), each landing with new test coverage for the extracted
service.

**Branch when ready:** `refactor/god-nodes-v1.19.0` (or later).

---

### Item 2 — VSCode `resolveWebviewView` refactor [Critique #7]

**Affected file:** `vscode-extension/src/chatPanel.ts::ChatViewProvider.resolveWebviewView`.

**What the critique said:** highest criticality flow in the
code-review-graph (criticality 0.723, 84 nodes / 6 files). Function does
too much in one place: webview HTML/content construction, message
handlers, API client wiring, state subscriptions, lifecycle/disposal.
Recommended split into setup phases.

**Why deferred:** VSCode extension is lower-traffic than TUI; refactor is
maintainability-driven, not correctness-driven. Tests around it would
need a VSCode test runner setup.

**Trigger to revisit:** when adding a new client-server message kind
requires another large change to the function, OR when the function
crosses 200 LOC.

**Effort:** ~half day for the split + ~half day for tests. Output a
companion `docs/TODO-v1.18.x-vscode-webview-refactor.md` with the phase
breakdown when starting.

**Branch when ready:** `refactor/vscode-webview-v1.19.0`.

---

### Item 3 — k8s session-manager security tests [Critique #8]

**Affected files:** `deploy/images/session-manager/main.py` (648 LOC),
`deploy/images/session-manager/ldap_auth.py` (130 LOC).

**What the critique said:** untested high-risk functions in the
multi-tenant deployment service:
- `_list_sessions` (risk 0.85), `_teardown_session` (risk 0.7)
- `create_session`, `delete_session`, `heartbeat`, `startup`
- `LDAPAuthenticator._hash_password`, `authenticate`

Recommended test scenarios: auth failure, timing-safe hash comparison,
K8s resource naming validation (escape via `..`/`/` in usernames),
teardown idempotency, stale heartbeat cleanup, permissions/secrets
handling.

**Why deferred:** zero blast radius for single-user macOS/Windows
ppxai installs (the mainline use case). Only deployers running the
Helm chart in a multi-tenant K8s cluster touch this code.

**Trigger to revisit:** when a third-party deploys ppxai
multi-tenant, OR when a security audit demands LDAP/RBAC test
coverage, OR when CVE disclosure procedures need this code to
have minimum test coverage.

**Effort:**
- Quick pass (~1 hour): 10 unit tests around `_hash_password`
  (timing-safe), `authenticate` (denial fail-closed), naming validation.
- Full pass (~half day): 30-50 tests with mocked `kubernetes.client`,
  covering all 8 functions.
- Defensive sweep (+ ~half day): LDAP injection patterns,
  secret-in-log scrubbing, kubeconfig path validation.

**Branch when ready:** `feat/k8s-session-manager-tests`.

---

### Item 5 — Bundle the VSCode extension

**Affected files:** `vscode-extension/package.json`, `vscode-extension/.vscodeignore`,
no esbuild/webpack config currently in use (compile is just `npx tsc -p ./`).

**What the warning says:** every `vsce package` run prints
> "This extension consists of 804 files, out of which 397 are JavaScript
> files. For performance reasons, you should bundle your extension."

The 804 files come from the runtime deps (`dotenv`, `highlight.js`,
`marked`, `openai`) being shipped as raw `node_modules/` trees. Webpack
+ ts-loader are already installed as devDependencies but unused.

**Concrete fix (esbuild — VSCode's recommended bundler):**

1. `npm i -D esbuild` in `vscode-extension/`.
2. Add `vscode-extension/esbuild.js`:
   ```js
   const esbuild = require("esbuild");
   const production = process.argv.includes("--production");
   esbuild.build({
     entryPoints: ["src/extension.ts"],
     bundle: true, format: "cjs", platform: "node",
     external: ["vscode"], outfile: "dist/extension.js",
     minify: production, sourcemap: !production,
   }).catch(() => process.exit(1));
   ```
3. `package.json`: switch `main` from `./out/extension.js` to
   `./dist/extension.js`; replace `compile` with `node esbuild.js` and
   add `package: "node esbuild.js --production"` +
   `vscode:prepublish: "npm run package"`.
4. `.vscodeignore`: replace the per-package excludes with `node_modules/**`,
   `out/**`, `src/**`.

**Why deferred:** maintenance-driven, not correctness-driven. Every
release ships fine without bundling — the warning has been there for
months. Risk: bundling can subtly break runtime imports of native
modules or dynamic-loaded files; needs activate/deactivate testing.

**Trigger to revisit:** when extension activation latency becomes a
user complaint, OR when the `.vsix` size crosses 2 MB, OR when a CI
gate is added for extension performance.

**Effort:** ~30 minutes for the config + ~1 hour testing the
activate/deactivate paths against `dotenv`, `marked`, `openai`,
`highlight.js`. Expected outcome: 804 files → ~3 files,
1.1 MB → ~300-500 KB, faster activation.

**Branch when ready:** `feat/bundle-vscode-extension`.

---

### Item 6 — Windows `code` CLI shim resolution

**Affected:** developer environment only (Git Bash on Windows). Not in
the repo, but documented here so the next developer doesn't waste time
debugging the symptom.

**What's wrong:** `code --install-extension foo.vsix` fails with
`bad option: --install-extension`. Root cause: on Windows the user
PATH lists `C:\...\Microsoft VS Code\` (containing the GUI `code.exe`)
*before* `C:\...\Microsoft VS Code\bin\` (containing the proper sh
shim that delegates to `code.cmd`). Bash strips the `.exe`, so the
GUI launcher wins and rejects unknown flags.

**Concrete fix (pick one, smallest blast radius first):**

(a) **Shell-local alias** — reversible, no system change. Add to
    `~/.bashrc`:
    ```bash
    alias code='/c/Users/$USER/AppData/Local/Programs/Microsoft\ VS\ Code/bin/code'
    ```

(b) **PATH reorder for this user** — open Windows env var settings,
    move `...\Microsoft VS Code\bin` above `...\Microsoft VS Code` in
    user `Path`. Permanent; affects every shell. Restart Git Bash.

(c) **Symlink in early-PATH dir** — if `~/.local/bin/` is already
    ahead of the VSCode dirs:
    ```bash
    ln -s "/c/.../Microsoft VS Code/bin/code.cmd" ~/.local/bin/code
    ```

**Why deferred:** purely a dev-environment ergonomics issue. Workaround
exists (use `bin/code.cmd` explicitly). Doesn't affect builds, CI, or
shipped artifacts.

**Trigger to revisit:** when another contributor hits the same
"bad option" error and pings the team, OR when adding install steps
to `docs/INSTALLATION.md` that need a working `code` CLI on Windows.

**Effort:** ~5 minutes per developer to apply locally. No upstream
fix needed unless we want to document it in `docs/INSTALLATION.md`
under a "Windows developer setup" subsection (~15 minutes).

**Branch when ready:** none required for the env fix; if documenting,
fold into a future `docs:` commit.

---

### Item 7 — `/command/{name}` route emits no request log

**Affected file:** [ppxai/server/routes/commands.py:46](../ppxai/server/routes/commands.py#L46).

**What's wrong:** the canonical v1.18.1 slash-command dispatch path
has zero `logger.info(...)` instrumentation. Every sibling route
([files.py:439](../ppxai/server/routes/files.py#L439),
[files.py:307](../ppxai/server/routes/files.py#L307),
[files.py:165](../ppxai/server/routes/files.py#L165),
[context.py:195](../ppxai/server/routes/context.py#L195)) logs
`HTTP {METHOD} /<path>` on entry; `commands.py` does not.

In the 2026-04-27 webapp session (`webapp-f2d045de`), `/save`,
`/usage`, and `/usage 24h` were issued 8 times across a 21-minute
session and `server-debug.log` shows only the client-echo lines
(`CLIENT[web]: > /save`). The server-side dispatch is invisible.

**Why this matters:** v1.18.1 unification was specifically meant to
prevent commands from silently falling back to bespoke endpoints —
the failure mode that caused 9/10 builtin command modules to be
missing from PyInstaller specs for six releases. Without route
logging we can't *prove* the unification holds in production; the
exact regression we built to detect would slip through again.

**Concrete fix:** add one line at the top of `execute_command`:
```python
logger.info(f"HTTP POST /command/{name} from session={s.id}")
```
plus a debug line for `request.args` truncated to ~120 chars.

**Effort:** ~5 minutes + a unit test asserting the log line is
emitted (mirror the pattern in `tests/test_files_routes.py` if one
exists, otherwise a `caplog.text` assertion is enough).

**Branch when ready:** small enough to fold into the next bugfix
branch — does not need its own.

---

### Item 8 — Version banner shows `commit n/a, source n/a` for shipped binaries

**Affected file:** [ppxai/version.py:21-69](../ppxai/version.py#L21-L69).

**What's wrong:** `_git_commit_hash()` runs `git rev-parse --short
HEAD` against `Path(__file__).resolve().parent.parent`, and
`_source_mtime()` walks engine + clients dirs. Both fall back to
`None` (rendered as "n/a") when the running process is a
PyInstaller binary in `~/.ppxai/bin/` — no `.git/`, no source tree
in the expected layout. Confirmed in the 2026-04-27 session
banner: `ppxai v1.18.2 (commit n/a, source n/a, python 3.13.13,
windows-AMD64)`.

**Why this matters:** the v1.18.2 banner feature
(commit `b3deca6b`) was specifically designed to "make it obvious
which code state is actually running — particularly important
after editable installs where a stale Python process can outlive
its source." For end-users on shipped binaries (the largest
audience), the two diagnostic fields that actually answer "what
am I running" are gone. The feature works only for dev runs from
source.

**Concrete fix:** bake the build-time commit into the binary:

(a) In `scripts/release.py` (or PyInstaller pre-build hook), write
    `ppxai/_build_info.py` with:
    ```python
    BUILD_COMMIT = "b3deca6b"
    BUILD_DATE = "2026-04-25T18:30:00Z"
    BUILD_VERSION = "1.18.2"
    ```
(b) `version.py` checks for `_build_info.py` first; falls back to
    `git rev-parse` only when it's absent (dev runs).
(c) `.gitignore` excludes `_build_info.py` so it's regenerated on
    every build and never committed.

Alternative (lighter): set `PPXAI_BUILD_COMMIT` env var in the
PyInstaller spec via `--add-data` or `runtime_hooks`, read it in
`version.py`.

**Effort:** ~30 minutes for the file-injection variant + a smoke
test that the binary's `--version` output includes a real commit
hash. Slightly more if we want CI to verify it.

**Branch when ready:** `feat/version-banner-binary-injection` or
fold into the next release-tooling pass alongside
[docs/TODO-release-tooling.md](TODO-release-tooling.md).

---

### Item 9 — `/state` re-anchor not observable in production logs

**Affected:** v1.18.1 Phase A wiring (web `visibilitychange`
listener, VSCode `onDidChangeWindowState`) → `GET /state` → AppState
re-anchor. Likely in [ppxai/web/app.js](../ppxai/web/) and
[vscode-extension/src/chatPanel.ts](../vscode-extension/src/chatPanel.ts).

**What's wrong:** the 2026-04-27 webapp session ran 21 minutes,
involved 5 provider switches, 3 saves, and 8 `/usage` checks, yet
`server-debug.log` shows zero `GET /state` requests. The Phase A
contract says the listener fires on tab focus/blur transitions.
Either:
1. The listener is not wired in the deployed `~/.ppxai/web/app.js`
   (deployment drift between repo source and `~/.ppxai/web/`).
2. `_reanchorFromServer` is wired but `GET /state` lacks logging
   (same instrumentation gap as Item 7).
3. The user genuinely never blurred the tab — possible but
   unlikely across 21 minutes with multiple terminal switches.

**Why this matters:** v1.18.1 spent significant effort on
state-sync determinism (Phases A–D) precisely so that drift
between engine state and client mirrors becomes named, surfaced,
recoverable. If Phase A doesn't fire, we lose the front-line
defence. We currently can't tell whether it's broken or just
silent.

**Concrete fix (in order):**

(a) Add `logger.info(f"HTTP GET /state from session={s.id}")` to
    `ppxai/server/routes/state.py` — same pattern as Item 7.
    Eliminates ambiguity #2.
(b) Diff deployed `~/.ppxai/web/app.js` against repo
    `ppxai/web/app.js` — confirm `_reanchorFromServer` and the
    `visibilitychange` listener are present in the deployed file.
    Eliminates ambiguity #1.
(c) If the listener is wired but never fires, add a one-line
    `console.debug("visibilitychange:", document.visibilityState)`
    so we can correlate browser events with server logs.

**Effort:** ~15 minutes for (a) + (b). (c) is optional and only
needed if (b) confirms the wiring is correct.

**Branch when ready:** fold into the same observability pass as
Item 7 — both are one-line `logger.info` additions.

---

## Closed

(Move items here as they land. Format: `### Item X — title — closed YYYY-MM-DD in commit-hash`)

### Item 4 — Focused-subtree graphify runs — closed 2026-04-28

Built per-subtree AST-only graphs to `graphify-out-{engine,server,commands,vscode}/`
(gitignored). Diagnostic only — no fix branch needed.

Per-subtree shape:

| Subtree | Files | Nodes | Edges | Communities | Top hub (degree) |
|---|---:|---:|---:|---:|---|
| `ppxai/engine/` | 48 | 1,356 | 5,029 | 23 | `Event` / `EventType` (208) |
| `ppxai/server/` | 27 | 478 | 904 | 23 | `Session` (109) |
| `ppxai/commands/` | 16 | 430 | 1,847 | 25 | `CommandResult` (169) |
| `vscode-extension/src/` | 19 | 285 | 566 | 15 | `HttpClient` (69) |

What the subtree views surfaced that the whole-repo graph (cohesion ≈ 0.0
across 12,781 nodes) could not:

- **commands/** has the densest hub-and-spoke shape: edges-per-node 4.3
  vs ~1.5–3.5 in other subtrees. Every handler module touches
  `CommandResult` (169) + `CommandFactory` (127) + `CommandSpec` (99) +
  `ResultStatus` (99) — confirms the v1.18.1 unification reach.
  Communities cluster cleanly around shape: handler families
  (agent/checkpoint/attach/show/edit), result types, context adapters,
  factory plumbing. Cohesion 0.04–0.19, much higher than whole-repo.
- **engine/** confirms the event-driven hub-and-spoke. The two largest
  communities are 221 + 160 nodes around `EngineClient` / `AppState` /
  tool base — exactly the hub-and-spoke pattern CLAUDE.md says is
  *deliberate* and not to be "decomposed" based on graphify cohesion
  alone. Subtree communities show 0.02–0.22 cohesion vs ~0.0 in the
  whole-repo. The misreading risk is real; the subtree view should be
  the default reading lens for this subsystem.
- **server/** Session as the single dominant hub (109 inbound) — every
  route resolves through it. Communities split cleanly along route
  modules: file-ops, completion, agent, checkpoint, consent, static.
  Cohesion peaks at 0.18 (file-ops) and 0.20 (checkpoint) — these are
  genuinely well-encapsulated subsystems.
- **vscode-extension/src/** — `ChatViewProvider` shows up at degree 56
  in its own community of size 1 (cohesion 0.11), which independently
  corroborates Item 2 (`resolveWebviewView` refactor) without needing
  the gpt-5.5 critique to flag it. Anyone reading the subtree report
  cold sees the smell.

Surprising connections per subtree are minor (mostly INFERRED
`uses` edges already obvious from imports). The signal is in the
hubs + community split, not the surprises.

Reusable: `c:\tmp\subtree_build.py` — small wrapper around
`graphify.{detect,extract,build,cluster,analyze,report,export}` that
runs the AST-only pipeline against an arbitrary `<input_path>
<output_dir>`, no LLM cost.

### Critique items closed in v1.18.2

All entries below were originally listed as critique items #1-#10. The
ones not in "Open" above were closed during the test sweep on
2026-04-26.

| Critique # | What | Commits |
|---|---|---|
| #1 | Graph hygiene + rebuild both graphs | `.graphifyignore` expanded, 17,853→12,781 nodes |
| #2 | server/state.py — 28 tests across 4 classes | f8e913d9 |
| #3 | Session persistence — 44 tests + path-traversal fix in `load()` | 34377a40, c5cb8b7e, be8de79c |
| #4 | `_execute_ai_task` — 20 tests across 7 sub-cases | 7f7a578d |
| #5 | Tool security pass + `docs/CONSENT-CONTRACT.md` (18 tests) | 79b54757 |
| #9 | Server route edges (a, d, f) — 17 tests; (b, c, e) already covered | 36c73777 |
| #10 | Improve graph/report usefulness — absorbed into #1 | (with #1) |

### Side-track items closed in v1.18.2

| Item | What | Commits |
|---|---|---|
| Config defaults | gpt-4.1-mini → gpt-5.4-mini, gpt-5.1-codex-mini → gpt-5.4-mini | 57c45fdc |
| Benchmark CI gate | Source-level invariant assertion in `engine_runner.py` | 2736f8e9 |
| Gemini provider | None-iter defensive guards in `_convert_tools_to_gemini` etc. | 2736f8e9 |
| container.py:104 audit | Confirmed by-design (abstract base) + regression test | 2736f8e9 |

### Bug fixes from production testing on 2026-04-26

| Bug | What | Commits |
|---|---|---|
| Orphan tool_calls | Ctrl+C mid-tool-iteration → next API call rejected; `validate_and_fix_alternation` now drops orphans | be8de79c |
| Usage round-trip | `session.load()` was wiping `usage_by_model` + `tool_calls`; now hydrates them | be8de79c |
| Per-turn ledger flush | Rich + Textual TUIs now call `save_usage_to_persistent_storage` per turn (server already did) | f73627a2 |
| Version banner | Runtime version + commit + source mtime in terminal startup AND debug log headers | b3deca6b |

---

## Related documents

- [docs/CONSENT-CONTRACT.md](CONSENT-CONTRACT.md) — security boundary for tool execution (created with critique #5)
- [docs/MODEL-SELECTION-GUIDE.md](MODEL-SELECTION-GUIDE.md) — planner/executor pricing strategy
- [docs/TODO-v1.18.2-agent-loop-unification.md](TODO-v1.18.2-agent-loop-unification.md) — separate in-flight work (HTTP-streaming agent loop)
- [docs/TODO-v1.18.2-keys-binding-registries.md](TODO-v1.18.2-keys-binding-registries.md) — separate in-flight work
- [docs/TODO-v1.18.2-prompt-text-kind.md](TODO-v1.18.2-prompt-text-kind.md) — separate in-flight work
- [docs/TODO-v1.18.2-inline-markdown-images-tui.md](TODO-v1.18.2-inline-markdown-images-tui.md) — separate in-flight work

The `TODO-v1.18.2-*.md` files describe in-flight planning for v1.18.2.
This doc tracks debt **not** in any version's plan yet — items needing
their own future branch.
