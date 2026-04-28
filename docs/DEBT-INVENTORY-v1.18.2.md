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

### Item 1 — God node refactoring [Critique #6] — SCOPE NARROWED 2026-04-28

**Affected modules:** `ppxai/tui/app.py::PPXAIDEApp` (507 inbound edges),
`ppxai/tui/widgets/message_box.py::MessageBox` (473 edges),
`ppxai/tui/widgets/chat_view.py::ChatView` (was 443; now displaced from
top-10 — verify with subtree build before scheduling).

**EngineClient dropped from scope (2026-04-28).** A Tier 2 investigation
on `bugfix/v1.18.2` (commit `c6322dda`) found that the 474→489 edge
growth since the v1.17.x decomposition is fully attributable to v1.18.0
features that **belong** in EngineClient per the documented AppState
pattern: `_on_messages_changed` and `_refresh_last_message_role`
fan-out callbacks (CLAUDE.md AppState rule #2 — "Engine-owned
invalidation: EngineClient recomputes the field on mutation via a
session callback"). Production-code inbound edges are 35 across 3
importers (protocol, context, init re-export) — exactly what v1.17.x's
decomposition aimed for. Further splitting would re-introduce the
cross-client drift the AppState pattern was designed to eliminate.

**What the critique said:** these classes have too many responsibilities;
extract narrower services so future changes don't cascade. Specifically:
- Move session-restore + state-sync orchestration out of `PPXAIDEApp`.
- Extract rendering + state-update helpers from `MessageBox` and `ChatView`.

**Why deferred:** refactor work that doesn't fit on a bugfix branch.
The remaining hot spots are pure UI classes whose tests are flakier and
whose external API breaks easily. The AppState pattern doesn't
constrain UI decomposition, so this is the right scope for a refactor
branch.

**Trigger to revisit:** when adding a new TUI variant (different
framework, web-only, etc.) that needs to reuse the chat-rendering
logic without dragging Textual machinery, OR when a refactor touching
`PPXAIDEApp` causes its 5th regression in a release.

**Effort:** ~3–5 days for a careful pass (revised down from 1–2 weeks
since EngineClient is no longer in scope). Best done as 3 separate PRs
(one per class), each landing with new test coverage for the
extracted service.

**Branch when ready:** `refactor/god-nodes-v1.19.0` (or later).

**Subtree graph signal (built 2026-04-28 via `c:\tmp\subtree_build.py
ppxai/tui graphify-out-tui`):** the whole-repo god-node ranking is
misleading for refactor planning — most of `PPXAIDEApp`'s 507 edges
come from outside the TUI (tests, scripts, benchmarks). Inside the
TUI subtree, the actual hub ranking is:

| Node | Subtree degree | Notable |
|---|---:|---|
| `CodeEditor` | 176 | NOT in original critique — biggest UI hub |
| `MessageBox` | 120 | Confirmed |
| `FileTree` | 109 | NOT in original critique |
| `Events` | 96 | Event-bus, structural |
| `ChatView` | 92 | Confirmed but smaller than expected |

`PPXAIDEApp` lands as a **singleton community** (cohesion 1.0, size
1) — the same shape Item 2's `ChatViewProvider` shows in the VSCode
subtree. Pure god-class smell; no internal structure for clustering
to find.

**Natural decomposition seams** the subtree graph surfaces:
- **C0 (109 nodes, cohesion 0.03):** CodeEditor + DataViewer + viewer
  widgets cluster — already partly separate, needs further pull.
- **C1 (147 nodes, cohesion 0.04):** stream-handler + completion +
  slash-commands cluster — extract a `stream_handler` service.
- **C2 (107 nodes, cohesion 0.02):** MessageBox + ChatView + App
  internals — extract `message_rendering` helpers (Rich markup
  stripping, response-time badge update, etc.).
- **PPXAIDEApp itself:** extract session-restore + state-sync into
  TUI ops modules (mirror the `engine/ops_*` pattern).

**Healthy clean splits already done** (cohesion ≥ 0.09): keys.py
registry (C7), clipboard (C9), linkify (C10), input validation
(C11), display-mode detection (C12). These confirm the
extraction pattern works when applied with intent.

**Refactor PR plan:**
1. Extract `tui/stream_handler_ops` from C1 (largest win, lowest risk).
2. Extract `tui/message_rendering` helpers from C2.
3. Extract `tui/session_restore_ops` from PPXAIDEApp.
4. CodeEditor / DataViewer cluster cleanup is optional — already
   has internal structure, lower priority.

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

### Item 10 — Introduce `EngineClientProtocol` for the commands layer

**Affected files:**
[ppxai/commands/protocol.py:18,44](../ppxai/commands/protocol.py#L18),
[ppxai/commands/context.py:21,75](../ppxai/commands/context.py#L21),
new `EngineClientProtocol` to live in [ppxai/engine/types.py](../ppxai/engine/types.py).

**What's wrong:** `commands/protocol.py` is the canonical Protocol
layer for commands — it should be free of concrete engine types. It
currently imports `EngineClient` directly to type-annotate the
`engine_client` property. `commands/context.py` does the same for
`ServerCommandContext.__init__`. Per
[CLAUDE.md "Critical Architecture Pattern: Protocol-Based
Dependency Inversion"], the project pattern is to define a `*Protocol`
in `engine/types.py` (a leaf module) and have concrete classes satisfy
it structurally. Two such protocols exist already: `ToolEngineProtocol`
and `ToolManagerProtocol`. EngineClient does not have one.

**Why this matters:** the commands→engine boundary is the only
production importer surface where this rule slips. The graphify graph
attributes ~21 inbound edges to `EngineClient` from `protocol.py`
alone — most of those are method references that an
`EngineClientProtocol` would absorb cleanly. Surfaced during the
Tier 2 investigation on 2026-04-28 (commit `c6322dda`); the rest of
the EngineClient hub is structurally healthy.

**Why this is NOT a circular-import bug:** `engine.client` does not
import from `ppxai.commands`, so the strict Protocol-DI rule is
technically satisfied. The motivation here is consistency and edge-
count reduction, not a working defect.

**Concrete fix:**

(a) In [ppxai/engine/types.py](../ppxai/engine/types.py), add:
```python
@runtime_checkable
class EngineClientProtocol(Protocol):
    """The engine surface area that commands depend on.

    Define ONLY what commands actually use — chat, providers, tools,
    session management, working dir, agent mode. No streaming
    internals, no SSE machinery, no AppState mutation.
    """
    @property
    def session(self) -> Any: ...
    @property
    def state(self) -> Any: ...
    def get_working_dir(self) -> Optional[str]: ...
    def set_working_dir(self, path: str) -> None: ...
    def list_providers(self) -> list: ...
    def get_current_provider(self) -> str: ...
    # ... etc — match what protocol.py + context.py actually call
```

(b) Replace `EngineClient` annotations in `protocol.py` and
`context.py` with `EngineClientProtocol`.

(c) Drop the `from ..engine.client import EngineClient` lines from
both files; they no longer need the concrete class.

**Effort:** ~half day. Mostly mechanical — read what
`protocol.py` + `context.py` actually access on the engine, list the
union as protocol methods, replace annotations. Add a sentinel test
asserting `EngineClient` satisfies the protocol via
`isinstance(engine, EngineClientProtocol)` so future changes don't
silently break the contract. Expected outcome: ~20 fewer inbound
edges to `EngineClient` in the next graphify rebuild, and the
commands layer becomes engine-implementation-agnostic.

**Trigger to revisit:** when adding a fourth concrete CommandContext
adapter (e.g. mobile/Slack/CLI), OR when EngineClient gains a
breaking API change — both scenarios benefit from the indirection
already being in place.

**Branch when ready:** `refactor/engine-client-protocol`.

---

## Closed

(Move items here as they land. Format: `### Item X — title — closed YYYY-MM-DD in commit-hash`)

### Item 7 — `/command/{name}` route emits no request log — closed 2026-04-28

`ppxai/server/routes/commands.py:execute_command` now emits an
INFO-level log line on every dispatch:

```
HTTP POST /command/{name} from session={s.id} args={args_preview!r}
```

Plus a DEBUG line with `ok` flag and `side_effects` count, and a
WARNING when the command is unknown. The `args_preview` is
truncated to 120 chars so noisy `/agent` prompts don't dominate
the log.

Tests added in `tests/test_command_envelope.py::TestRouteLogging`:
- `test_route_logs_request` — INFO line emitted on POST
- `test_unknown_command_logs_warning` — 404 path emits WARNING
- `test_long_args_truncated_to_120_chars` — truncation guard

The Logger wrapper in `ppxai.common.logger` is no-op until
`/debug-log on` enables it (via env var or runtime toggle), so the
tests force-enable the existing singleton — popping the singleton
would orphan module-level `logger = get_logger("server")`
references. This is a real subtle gotcha worth documenting.

### Item 8 — Version banner shows `commit n/a, source n/a` for shipped binaries — closed 2026-04-28

`ppxai/version.py::_build_info()` now checks for an optional
`ppxai/_build_info.py` module before falling back to runtime probes
(`git rev-parse`, source-mtime scan). The build-info module is
generated by `scripts/write_build_info.py` and gitignored — release
tooling runs the script just before each PyInstaller invocation,
so the bundled binary carries the real commit + UTC build time.

Generated module shape (4 lines, plus docstring):
```python
BUILD_COMMIT = '7b13784f'
BUILD_MTIME = '2026-04-28 20:18:19 UTC'
```

Resolution order in `get_runtime_version_info()`:
1. `_build_info.py` if present (binary builds).
2. Runtime probes: `git rev-parse` + source mtime scan (dev runs).
3. `"n/a"` fallback (genuinely unavailable).

Partial build-info (missing `BUILD_MTIME`) falls through to runtime
probes — we don't ship half-populated banners.

Tests added in `tests/test_version_banner.py::TestBuildInfoInjection`:
- `test_build_info_takes_precedence_when_present`
- `test_falls_back_to_runtime_probes_when_absent`
- `test_partial_build_info_falls_through`

**Wiring into release tooling deferred** to whoever does the next
release: add `python scripts/write_build_info.py` as a step in
`scripts/release.py` before each `pyinstaller` invocation, OR add
it as a pre-build hook to each `.spec` file. The mechanism is
ready; the integration is one line.

### Item 9 — `/state` re-anchor not observable in production logs — closed 2026-04-28

`ppxai/server/routes/state.py::get_app_state` now emits an
INFO-level log line on every snapshot fetch:

```
HTTP GET /state from session={s.id}
```

Diagnostic clauses (b) from the original entry was also performed:
deployed `~/.ppxai/web/app.js` is byte-identical to repo source,
and contains 6 occurrences of `visibilitychange` /
`_reanchorFromServer` — the wiring IS present. The 21-minute
2026-04-27 session that showed zero `/state` hits was therefore
NOT a wiring break; the listener simply hadn't fired (most likely
the user genuinely kept the tab focused). The new log line is the
diagnostic for the next investigation: if `/state` lines appear,
the listener works; if they're absent across known focus changes,
we have a real wiring regression to chase.

Test added in `tests/test_server_routes.py::TestStateRoute::test_route_logs_request`.

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
