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

### Item 12 — GitHub Actions Node.js 20 deprecation warnings (cosmetic)

**Affected files:** [.github/workflows/build.yml](../.github/workflows/build.yml),
[.github/workflows/docs.yml](../.github/workflows/docs.yml).

**What's wrong:** every CI run still emits a deprecation banner for
`actions/checkout@v4`, `actions/setup-node@v4`, and
`actions/upload-artifact@v4`:

> "Node.js 20 actions are deprecated. The following actions are
> running on Node.js 20 ... To opt into Node.js 24 now, set the
> FORCE_JAVASCRIPT_ACTIONS_TO_NODE24=true environment variable..."

**State today.** Commit `67b0774a` (2026-04-25) already set
`FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: 'true'` at the workflow `env`
level in both files, **forcing the runtime to Node.js 24**. The
actions DO run on Node 24 today — the deprecation is observed only
as a cosmetic banner because GitHub's runner reads the action's
`action.yml` manifest (which still declares `using: 'node20'`)
when emitting the warning. The runtime override doesn't change
the manifest text.

**Why this is cosmetic, not an error.** Build artifacts, tests,
and release publishing all succeed today. GitHub's hard cutoff is
2026-09-16 (when Node 20 is removed from runners) — until then
the env-var override is effective. The warning is informational
noise for CI log readers.

**Concrete fix:** bump pins to v5 versions whose manifests declare
`using: 'node24'`:

```diff
-      uses: actions/checkout@v4
+      uses: actions/checkout@v5
-      uses: actions/setup-node@v4
+      uses: actions/setup-node@v5
-      uses: actions/upload-artifact@v4
+      uses: actions/upload-artifact@v5
```

`actions/setup-python@v5` is already current.

After bumping, the `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24` env var
becomes redundant — drop it in the same commit. Per the original
commit message: "Removal plan: drop the env once every referenced
action has shipped a v5+ release running natively on Node 24, and
we've verified each in CI."

**Why deferred:** noticed mid-release on `bugfix/v1.18.2`. Bumping
action pins would have added an unrelated change to master after
the release-prep commits, risking the asset-build CI run we were
already waiting on. Filed for next branch.

**Trigger to revisit:**
- Convenient: any next release branch (v1.18.3 or v1.19.0).
- Forced: 2026-06-02 (GitHub forces Node 24 default — env-var
  override stops being needed; bump pins to silence warnings).
- Hard deadline: 2026-09-16 (Node 20 removed from runners).

**Effort:** ~10 minutes — three pin bumps + one env removal +
one CI run to verify nothing breaks. v5 versions of all three
actions ship Node 24 manifests and are backwards-compatible at
the input level.

**Branch when ready:** fold into the first commit on the next
release branch — too small to need its own.

---

### Item 13 — `scripts/release.py` step 15 fails silently when `gh release view` errors

**Affected file:** [scripts/release.py](../scripts/release.py),
specifically the "Step 15/15: Verifying Release" block.

**What's wrong:** when `gh release view v<version> --json assets`
returns "release not found" (because CI failed and the `release`
job was skipped, OR because the release was never created), step
15 prints `❌ Could not fetch release info` but the script
**continues to print `✅ Release v1.18.2 complete!`** and exits
with status 0. Operators who trust the green checkmark + exit
code don't realise the release page never materialised.

**Observed twice now:**

- **v1.18.1** retag cycles (4 attempts) — captured in
  `memory/release-lessons.md`. Multiple runs reported success
  while the actual release was incomplete or absent.
- **v1.18.2 today (2026-04-29)** — `build-dmg` failed with
  `hdiutil: Resource busy` (transient macOS CI flake), which
  caused `release` job to skip, which meant no GitHub Release
  was created. release.py's "Step 15: Verify" printed the
  "Could not fetch release info" warning, then printed the
  green completion banner anyway. Caught only because we ran
  `gh release view` ourselves per the project's "don't trust
  release.py's release complete" rule.

**Why this matters:** the fix to v1.18.1's silent-failure mode
was discipline (`gh release view` after every release). That's
not robust — it relies on the operator remembering. The script
has all the information it needs to fail loudly; it just doesn't.

**Concrete fix:**

In `scripts/release.py`, find the verification step and change:

```python
# Current (approximate shape — gracefully degrades on failure)
result = run(["gh", "release", "view", f"v{version}", "--json", "assets"])
if result.returncode != 0:
    print("  ❌ Could not fetch release info")
else:
    # check assets ...
```

To:

```python
result = run(["gh", "release", "view", f"v{version}", "--json", "assets"])
if result.returncode != 0:
    print("  ❌ FATAL: gh release view failed — release was NOT created.")
    print("     Most common cause: a CI job failed (build-dmg flake,")
    print("     test failure, etc.) and the `release` job was skipped.")
    print("     Run: gh run list --workflow='Build Executables' --limit 3")
    print("     If a job failed, re-run it: gh run rerun <RUN_ID> --failed")
    sys.exit(1)
asset_count = len(json.loads(result.stdout)["assets"])
if asset_count < EXPECTED_ASSET_COUNT:  # 15 as of v1.18.2
    print(f"  ❌ FATAL: only {asset_count} assets attached, expected {EXPECTED_ASSET_COUNT}.")
    sys.exit(1)
print(f"  ✅ {asset_count} assets verified.")
```

Plus: bump `EXPECTED_ASSET_COUNT` constant when assets change
(currently 15: 13 binaries + 1 dmg + 1 vsix). The constant lives
at module scope so changes are reviewed alongside CI matrix
changes in `.github/workflows/build.yml`.

**Why deferred:** noticed during the v1.18.2 release recovery,
just after the release was confirmed working. Bumping
`scripts/release.py` after the release would have been a
post-release commit on master — fine, but better batched with
related release-tooling improvements (e.g. the `_build_info.py`
integration noted in Item 8).

**Trigger to revisit:** any v1.18.3+ release prep — bundle this
fix with the Item 8 build-info integration and any other
release-tooling polish.

**Effort:** ~30 minutes — one function change + one constant +
one test that asserts the script `sys.exit(1)`s when `gh release
view` mocks return a non-zero exit code.

**Branch when ready:** fold into a `chore/release-tooling-v1.18.3`
branch alongside Item 8's build-info integration. Or stand alone
as a `fix/release-py-verify-fail-loud` branch if Item 8 isn't
ready.

---

## Closed

(Move items here as they land. Format: `### Item X — title — closed YYYY-MM-DD in commit-hash`)

### Item 1 — God node refactoring [Critique #6] — closed 2026-04-29

**Verification killed most of the original framing.** The 507/473/442
"god class" edges on `PPXAIDEApp`/`MessageBox`/`ChatView` were
**71-79% test-coverage volume from a single 4,788-line `tests/test_tui.py`**.
After excluding tests via `.graphifyignore` (2026-04-29), those
classes disappeared from the post-exclusion top 15. Channel-ratio
audit confirmed `app.py` uses EventBus (17) + AppState (30) + 54
direct widget calls (passing simple data) — healthy orchestrator
pattern. `MessageBox` (203 LoC, 8 methods) and `ChatView` (76 LoC,
8 methods) are tiny leaf widgets — never god classes.

**Two narrow extraction PRs landed (real signal that survived
verification):**

1. **`tui/session_restore_ops`** (272 LoC) extracted from
   `app.py:_check_session_restoration` + `_restore_session` — mirrors
   the engine's `session_ops.py` pattern. `app.py` shrank 1947 → 1744
   LoC. The methods on PPXAIDEApp became thin wrappers (8 lines
   each). All 276 TUI tests pass.

2. **Dead `TextualCommandContext` deleted** from
   `commands/context.py`. It was created in v1.15.0, never wired
   into `app.py` (which passes `self` directly), and survived 13
   releases as dead code. Removed with documentation in
   ADR 0002 explaining why the three-pattern split (Rich proxy,
   Textual no-adapter, Server explicit) is deliberate.

**The 16 inline CommandContext methods on PPXAIDEApp stay** — they
are the actual Pattern A implementation, NOT boilerplate to remove.
ADR 0002 pins this so it doesn't get re-litigated. Memory entry
[reference_command_context_adr.md] is the thinking-shortcut for
future readers.

**Pre-existing `TestKillPreviewBackend` failures fixed** —
7 tests that try to `patch("ppxai.server.state.os.getpgid")` failed
on Windows because `os.getpgid` doesn't exist on Windows. Added
`@_unix_only` skipif decorator with documentation. Linux CI (where
preview-backend subprocess management actually runs) keeps full
coverage; Windows devs get green local runs.

**Three lessons captured for future refactor decisions:**
- `feedback_verify_both_directions.md` — verify code BOTH when a
  signal flags a problem AND when pushback says the signal is wrong.
- `reference_graphify_noise.md` — `.graphifyignore` exclusions
  added; whole-repo node count dropped 11.6k → 4.5k.
- `reference_command_context_adr.md` — Pattern A vs B vs no-adapter
  is deliberate; don't re-litigate.

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
