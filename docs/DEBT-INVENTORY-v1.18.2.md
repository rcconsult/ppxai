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

## Closed

(Move items here as they land. Format: `### Item X — title — closed YYYY-MM-DD in commit-hash`)

### Item 5 — Bundle the VSCode extension — closed 2026-04-29

Bundled via [esbuild](https://esbuild.github.io/) (VSCode's recommended
bundler). Configuration in
[vscode-extension/esbuild.js](../vscode-extension/esbuild.js) — pure
Node, no shell-isms, works on Linux/macOS/Windows. esbuild's
`optionalDependencies` install the right native binary per host on
`npm install`.

**Build flow:**

| Script | Action |
|---|---|
| `npm run typecheck` | `tsc -p ./ --noEmit` (no JS output, types only) |
| `npm run compile` | typecheck + dev bundle (sourcemaps, no minify) |
| `npm run package` | typecheck + production bundle (minified, no sourcemap) |
| `npm run watch` | esbuild watch mode (rebuilds on change) |
| `vscode:prepublish` | runs `npm run package` so `vsce package` always ships the production bundle |

**Bundle stats** (108 KB minified, 200 KB dev):

| Metric | Pre | Post | Δ |
|---|---:|---:|---:|
| `.vsix` size | ~1.1 MB | **128 KB** | **−88%** |
| `.vsix` file count | 804 | **15** | **−98%** |
| `vsce package` warning | yes | gone | — |

**.vscodeignore** rewritten to use the bundle-friendly shape:
exclude `node_modules/**`, `out/**`, `src/**`, `esbuild.js`,
`build-hljs.cjs`, `scripts/**`, `TESTING.md`, `.claude/**`.
The 15 files that DO ship: `dist/extension.js`, the 5 webview
assets in `media/`, package metadata + license + README +
THIRD_PARTY_LICENSES + 2 `resources/` icons + `app-state-schema.json`.

**Why webview libs aren't bundled:** `marked` and `highlight.js`
are loaded by the webview's `media/main.js` as static assets via
`<script>` tags — they never enter the extension host's
`require` graph. `dotenv` is the only third-party module bundled;
`openai` is listed in `package.json` but unused by extension code
(it's a string literal in `config.ts` provider defaults).

**CI alignment** in
[`.github/workflows/build.yml`](../.github/workflows/build.yml):

- Replaced explicit `npm run compile` step with `npm run typecheck`
  (catches type errors fast; the bundle itself is built by
  `vscode:prepublish` during `vsce package`).
- Added a **bundle-size budget gate** — fails the build if the
  VSIX exceeds 500 KB. Detects accidental bloat (e.g. a new
  dependency dragging in a heavy transitive tree) the next time
  it happens, not in user reports months later.

**Cross-platform verified:**
- esbuild script: pure Node, platform-agnostic file paths.
- npm scripts: chained with `&&` (works in cmd.exe / bash /
  PowerShell via npm's shell wrapper).
- CI step uses `shell: bash` for `stat -c%s || stat -f%z` so the
  size check works on Linux runners *and* future macOS runners
  if anyone moves the job.

**Smoke checks:**
- `npm run package` reproduces the bundle from a clean `dist/`.
- Bundle parses as valid JS (`new Function(code)`).
- Bundle exports `activate` + `deactivate`, requires `vscode` as
  external, contains `HttpClient` + `ChatViewProvider` + dotenv
  parser code.
- The only `node_modules/` reference in the bundle is a string
  literal inside a `findFiles` exclusion pattern (not a require).

**Deferred testing:** activate/deactivate against a live VSCode
host is a manual step — install the VSIX (`code --install-extension
vscode-extension/ppxai-1.18.2.vsix`), open chat panel, verify
streaming + slash commands + dotenv-loaded API key. The
auto-checks above cover everything that can fail at build time;
runtime exercises require human eyes.

### Item 2 — VSCode `resolveWebviewView` refactor — closed 2026-04-28

Refactored to a **contract-based** design rather than private-method
decomposition (which the user rejected as code relocation, not real
decoupling). The 98-line monolith with no internal structure
(criticality 0.723 in the gpt-5.5 review-graph; singleton community
in the graphify VSCode subtree) became a 21-line orchestrator
composing four typed contracts.

**The contracts** (declared at module level, above `ChatViewProvider`):

1. **`type WebviewMessage`** — discriminated union of every inbound
   webview message. Adding a new message type means adding a member.
2. **`type WebviewMessageHandlers`** — `Required<{ [K in
   WebviewMessage['type']]: (m: Extract<WebviewMessage, { type: K }>)
   => Promise<void> }>`. The `Required<>` wrap makes the dispatch
   table exhaustive at compile time — adding a `WebviewMessage`
   variant fails the build until a handler is registered.
3. **`function configureWebview(webview, extensionUri, renderHtml)`**
   — pure side effect on the webview. Phase 1.
4. **`function installMessageRouter(webview, handlers): vscode.Disposable`**
   — registers the type-keyed dispatch table, returns the Disposable
   the caller owns. Phase 3.
5. **`function installFocusReanchor(onFocused: () => void):
   vscode.Disposable`** — registers the focus listener, returns its
   Disposable. Phase 4.

The 16-case `switch` is gone — replaced by a typed handler map
returned from `_buildMessageHandlers()`. Each entry is keyed by
message type, narrowed to its specific variant via `Extract`.
Adding a message type is now: `WebviewMessage` member + map entry.

**`resolveWebviewView` body becomes:**
```typescript
public resolveWebviewView(webviewView, _context, _token) {
    this._view = webviewView;
    configureWebview(webviewView.webview, this._context.extensionUri,
                     (w) => this._getHtmlForWebview(w));
    try {
        this.wireUISubscriptions();
    } catch (e) { console.error('[ppxai] Error:', e); }
    const messageRouter = installMessageRouter(
        webviewView.webview, this._buildMessageHandlers());
    const focusReanchor = installFocusReanchor(
        () => this._reanchorFromServer());
    webviewView.onDidDispose(() => {
        messageRouter.dispose();
        focusReanchor.dispose();
    });
}
```

**Tests updated** in
[`tests/test_vscode_visibility_reanchor.py`](../tests/test_vscode_visibility_reanchor.py)
to validate the **contract**, not the old code pattern:

- `test_listener_guards_on_focused` — splits into two
  contract-side checks: `installFocusReanchor` checks `focused`
  internally AND the orchestrator passes
  `() => this._reanchorFromServer()` as the callback.
- `test_listener_is_disposed_with_webview` — checks the
  installer's return-type signature is `vscode.Disposable` AND
  the orchestrator captures + disposes that handle inside
  `webviewView.onDidDispose`.

The new tests can survive shape changes that preserve the
contract (different variable names, different handler-table
shape) — they pin the *what*, not the *how*.

**Compile:** `npx tsc -p ./ --noEmit` clean. Tests: 2842/2842
pass on the full non-TUI sweep (7 pre-existing Unix-only
`TestKillPreviewBackend` failures verified against master).

### Item 6 — Windows `code` CLI shim resolution — closed 2026-04-28 (per-developer)

Applied fix variant (a) — shell-local alias in `~/.bashrc`:
```bash
alias code='/c/Users/<user>/AppData/Local/Programs/Microsoft\ VS\ Code/bin/code'
```

This bypasses the default Windows PATH ordering where `Microsoft VS Code\`
(GUI launcher `code.exe`) precedes `Microsoft VS Code\bin\` (CLI shim).
Bash strips `.exe`, so the GUI launcher would otherwise win and reject
flags like `--install-extension`. With the alias, `code --install-extension foo.vsix`
and `code --version` work directly from Git Bash.

Verified `code --version` returns `1.117.0` (the proper CLI shim
output) after `bash -i -c 'code --version'`. No repo-level commit
needed — `~/.bashrc` is per-developer config, not project state.

**For other contributors who hit this:** the recipe in this entry's
prior text (variants a / b / c) has the smallest-blast-radius fix
first. If a second developer reports the issue, that's the trigger
to fold a "Windows developer setup" subsection into
`docs/INSTALLATION.md` per the original "trigger to revisit"
condition.

### Item 11 — Latent AttributeError in `agent.py` Rich-TUI path — closed 2026-04-28

[`ppxai/commands/agent.py:680`](../ppxai/commands/agent.py#L680)
swapped from `context.engine_client.logger` (which did not exist
on `EngineClient`) to a module-level `get_logger("tui")` import. The
old construction would have raised `AttributeError` mid-`/agent`
run; tests passed because they substituted `Mock()` for the logger
arg, masking the missing attribute.

Regression tests in
[`tests/test_agent_logger_attribute.py`](../tests/test_agent_logger_attribute.py)
pin four contracts:
- `EngineClient` still has no `logger` attribute (catches drift if
  someone re-adds it).
- `get_logger("tui")` exposes the methods `TUIEventHandler` actually
  calls (`log_assistant_message`, `log_tool_call`, etc.).
- `TUIEventHandler` constructs cleanly with a REAL `EngineClient`
  + real `get_logger("tui")` — the exact construction shape the
  agent loop performs. No mocks. The bug existed precisely because
  mocks substituted the missing attribute.
- The original buggy access pattern (`engine.logger`) still raises
  AttributeError, documenting the failure mode.

The fix is intentionally narrow — it does not refactor the agent
loop, just corrects the logger handoff. The "agent loop unification
across HTTP clients" work tracked in
[docs/TODO-v1.18.2-agent-loop-unification.md](TODO-v1.18.2-agent-loop-unification.md)
remains separate; this fix lets the existing TUI path actually run.

### Item 10 — Introduce `EngineClientProtocol` for the commands layer — closed 2026-04-28

Added [`EngineClientProtocol`](../ppxai/engine/types.py) alongside
the existing `ToolEngineProtocol` / `ToolManagerProtocol`. Enumerates
~30 properties + methods that commands actually call on the engine,
grouped functionally (AppState access, provider/model switching,
working dir, tools/agent management, bootstrap/context, checkpoints,
chat). [`commands/protocol.py`](../ppxai/commands/protocol.py) and
[`commands/context.py`](../ppxai/commands/context.py) now type
against the protocol; both files dropped their
`from ..engine.client import EngineClient` import.

Sentinel tests in
[`tests/test_engine_client_protocol.py`](../tests/test_engine_client_protocol.py)
pin three contracts:
- `EngineClient` satisfies the protocol structurally
  (`isinstance` runtime check).
- `EngineClient` does NOT inherit from the protocol (the whole
  point of structural Protocol-DI).
- Neither `commands/protocol.py` nor `commands/context.py` slip
  back to importing the concrete `EngineClient` class.

**Verified via graphify edge reduction (rebuild after the change):**

| Metric | Pre-Item 10 | Post-Item 10 | Δ |
|---|---:|---:|---:|
| `EngineClient` total inbound | 56 | 39 | −17 |
| `protocol.py` → `EngineClient` | 21 | 4 | −17 (~80% reduction) |
| `context.py` → `EngineClient` | 7 | 7 | 0* |
| `EngineClientProtocol` inbound | — | 32 | new |

*context.py's 7 remaining edges are method-call references
(`self._engine.set_model(...)`) that graphify pins to the concrete
class; only the import was decoupled. Expected — the protocol
removes nominal coupling, not the runtime call references.

Tier 2 prediction "~20 fewer edges" → actual −17. Mission accomplished.

**Latent bug spotted during the protocol enumeration step:**
[`agent.py:680`](../ppxai/commands/agent.py#L680) accesses
`engine_client.logger` which doesn't exist on `EngineClient`. Filed
as Item 11. Item 10 dropped `logger` from the protocol's surface
rather than wishful-list it.

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
