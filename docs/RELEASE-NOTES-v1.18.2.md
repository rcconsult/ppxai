# Release Notes — v1.18.2

> **Scope:** Verification + production hardening + observability.
> 30 commits over the v1.18.1 baseline. The "consolidation release"
> after v1.18.0/v1.18.1's two big architectural pushes.
>
> **Tests:** 3067 passing, 9 skipped (was 2591 at v1.18.1 → +476).
> 7 of the 9 skips are Unix-only `TestKillPreviewBackend`
> (Windows lacks the mock targets); fully covered on Linux CI.

## Summary

v1.18.2 is intentionally not a feature release. The branch closed
9 of 10 open items in [DEBT-INVENTORY-v1.18.2.md](archive/DEBT-INVENTORY-v1.18.2.md)
and added 476 tests via the gpt-5.5 critique sweep + production
testing on 2026-04-26. The user-visible product surface barely
changes; the codebase health and the discipline around it does.

The work clusters into five themes:

1. **Tier 1 observability** (Items 7, 8, 9). Three production silent
   paths gained log lines so the next investigation isn't blind.
2. **Critique sweep** (gpt-5.5). 476 tests across server/state,
   `_execute_ai_task`, tool security, server route edges, session
   persistence, benchmark CI gate.
3. **Production bug fixes** (caught by 2026-04-26 testing).
   Orphan tool_calls cleanup, usage_by_model round-trip, agent.py
   AttributeError on Rich-TUI `/agent`, per-turn usage flush parity.
4. **Architectural decoupling** (Items 5, 10, 2). VSCode esbuild
   bundle (-88% size), `EngineClientProtocol` formalising the
   commands→engine boundary, contract-based webview setup.
5. **Methodology pinning.** ADR 0002 (CommandContext three-pattern
   split — don't unify on speculation). Verify-don't-assume both
   directions discipline. `.graphifyignore` test exclusions
   (whole-repo god-node ranking now reflects actual architecture).

## What's new

### Tier 1 observability (Items 7, 8, 9)

The 2026-04-27 webapp debug-log review surfaced three silent paths
that hampered diagnostics. Each fix is a one-line `logger.info`
addition + a regression test:

- **`POST /command/{name}`** (Item 7) — the canonical v1.18.1
  dispatch path was invisible in `server-debug.log`. Every other
  route in `ppxai/server/routes/` logged entry; this one didn't.
  The 2026-04-27 webapp session showed only client-echo lines for
  8 slash commands across 21 minutes; nothing on the server side.
  Now: `HTTP POST /command/{name} from session={id} args={preview}`
  (INFO) plus `ok` + side-effect count (DEBUG) plus a WARNING for
  unknown commands. Args truncated to 120 chars.
- **`GET /state`** (Item 9) — same shape. Phase A re-anchor was
  wired but couldn't be observed. Wiring verified byte-identical
  between deployed `~/.ppxai/web/app.js` and repo source — the
  21-min silent session was the listener simply not firing, not a
  wiring break. The new log line is the diagnostic for next time.
- **Version banner build-info injection** (Item 8) — pre-fix,
  PyInstaller binaries reported `commit n/a, source n/a` because
  `git rev-parse` and source-mtime probes both fail at runtime
  inside the binary. New `scripts/write_build_info.py` writes
  `ppxai/_build_info.py` (gitignored) from current git state;
  `version.py::_build_info()` consults it before the runtime
  probes. Wiring into release tooling (`scripts/release.py`) is
  one line, deferred to whoever does the next release.

### `EngineClientProtocol` (Item 10)

`ppxai/engine/types.py` gains an `EngineClientProtocol` enumerating
the ~30 properties/methods commands actually call on the engine,
grouped functionally:

```python
@runtime_checkable
class EngineClientProtocol(Protocol):
    # AppState + session access (read-mostly)
    @property
    def session(self) -> Any: ...
    @property
    def state(self) -> Any: ...
    # Provider/model switching
    def set_model(self, model: str, reset_context: bool = True) -> None: ...
    def set_provider(self, provider: str) -> None: ...
    # Working directory, tools/agent, bootstrap/context, checkpoints, chat — see types.py
```

`commands/protocol.py` and `commands/context.py` now type against
the protocol; both files dropped `from ..engine.client import EngineClient`.
Three sentinel tests in `tests/test_engine_client_protocol.py` pin:

- Real `EngineClient` satisfies the protocol structurally
  (`isinstance(engine, EngineClientProtocol)`).
- Structural satisfaction, not inheritance — `EngineClientProtocol
  not in EngineClient.__mro__`.
- Neither `protocol.py` nor `context.py` slip back to importing the
  concrete class.

**Verified via graphify rebuild after the change:**
- `protocol.py` → `EngineClient` edges: **21 → 4** (~80% reduction).
- Total `EngineClient` inbound: 56 → 39.
- New `EngineClientProtocol` node: 32 inbound (from `protocol.py`
  + `context.py` + the engine `__init__.py` re-export).

### VSCode extension bundled via esbuild (Item 5)

`npm run typecheck` (`tsc --noEmit`) + `npm run package` (esbuild
`--production`) replace the prior `npx tsc -p ./` flow. New
`vscode-extension/esbuild.js` is pure Node — works on Linux,
macOS, Windows (esbuild's `optionalDependencies` install the right
native binary per host). `vscode:prepublish` runs the production
bundle so `vsce package` always ships minified.

CI gains a 500 KB VSIX size-budget gate using `stat -c%s ||
stat -f%z` (Linux+BSD compatible) so any future dep that bloats
the bundle fails the build instead of silently shipping.

| Metric | Pre | Post | Δ |
|---|---:|---:|---:|
| `dist/extension.js` (minified) | n/a | 108 KB | new |
| VSIX size | ~1.1 MB | **128 KB** | **−88%** |
| VSIX file count | 804 | **15** | **−98%** |
| `vsce package` warning | yes | gone | — |

Webview-side libraries (`marked`, `highlight.js`) are loaded as
static assets from `media/webview/`, never imported by extension
code, so they stay out of the bundle.

### Contract-based `resolveWebviewView` refactor (Item 2)

The 98-line monolith in `vscode-extension/src/chatPanel.ts` (criticality
0.723 in the gpt-5.5 review-graph; singleton community in the
graphify VSCode subtree) becomes a 21-line orchestrator composing
four typed contracts at module level:

| Contract | Shape | Enforces |
|---|---|---|
| `type WebviewMessage` | Discriminated union of 16 variants | Every inbound message has an explicit shape |
| `type WebviewMessageHandlers` | `Required<{ [K]: (m: Extract<...>) => Promise<void> }>` | Dispatch table is exhaustive at compile time — missing handler fails the build |
| `configureWebview()` | `(webview, extensionUri, renderHtml) => void` | Phase 1 — pure side effect |
| `installMessageRouter()` | `(webview, handlers) => vscode.Disposable` | Phase 3 — caller owns lifecycle |
| `installFocusReanchor()` | `(onFocused: () => void) => vscode.Disposable` | Phase 4 — caller owns lifecycle |

The 16-case switch is gone — replaced by a typed map returned
from `_buildMessageHandlers()`. Adding a message type means:
extend `WebviewMessage` + add a map entry. Compiler enforces both
via `Required<>`.

Tests in `tests/test_vscode_visibility_reanchor.py` updated to
validate the **contract** (installer signature + orchestrator
wiring) rather than the prior implementation pattern. They survive
shape changes that preserve behaviour.

### `tui/session_restore_ops.py` extracted (Item 1, narrowed)

`tui/app.py::_check_session_restoration` and `_restore_session`
(231 LoC combined) extracted to `tui/session_restore_ops.py`
(272 LoC including comments), mirroring the engine's
`session_ops.py` decomposition pattern. `app.py` shrinks
1947 → 1744 LoC. The methods on `PPXAIDEApp` become 8-line
wrappers calling into the ops module.

The original Item 1 framing ("PPXAIDEApp/MessageBox/ChatView are
god classes") was 71-79% test-coverage volume from a single
4,788-line `tests/test_tui.py`. After excluding tests via
`.graphifyignore`, those classes dropped from the post-exclusion
top 15. Channel-ratio audit confirmed `app.py` uses EventBus (17)
+ AppState (30) + 54 direct widget calls (passing simple data) —
healthy orchestrator pattern, refactor done correctly in v1.15.0
through v1.17.x. The narrow extraction landed; the larger
"refactor" framing was retired.

### ADR 0002 — CommandContext three-pattern split

[docs/decisions/0002-command-context-three-pattern-split.md](decisions/0002-command-context-three-pattern-split.md)
documents why the three contexts use three different patterns:

| Client | Pattern | Why |
|---|---|---|
| Rich TUI | A — `__getattr__` proxy via `RichCommandContext(handler)` | `CommandHandler` already implements protocol surface for direct callers |
| Textual TUI | None — `app.py` passes `self` directly | `PPXAIDEApp` IS the context; no benefit from wrapping |
| HTTP server | B — explicit `ServerCommandContext(engine)` | No UI handler exists to wrap |

The ADR pins this so reviewers (human and LLM) don't re-litigate
the question. Triggers to revisit: 4th context type, 5+ new
CommandContext members in one release, or external SDK consumer
needing `commands/`.

The unused `TextualCommandContext` Pattern-A wrapper class —
created v1.15.0, never wired (`app.py:1169` passes `self`),
survived 13 releases as dead code — removed in this release. The
16 inline `CommandContext` methods on `PPXAIDEApp` (~100 LoC)
**stay** — they're the actual Pattern A implementation, not
boilerplate.

### Production bug fixes (caught 2026-04-26)

- **Orphan tool_calls cleanup.** Ctrl+C mid-tool-iteration left
  assistant messages with `tool_calls` but no following `tool` role
  messages. The next API call rejected the malformed conversation
  history. `validate_and_fix_alternation` now drops orphans.
- **`usage_by_model` round-trip.** `session.load()` was wiping
  `usage_by_model` and `tool_calls` because deserialization rebuilt
  them as empty containers. Fix hydrates both from persisted JSON.
- **Per-turn usage flush parity.** Rich + Textual TUIs now call
  `save_usage_to_persistent_storage()` per turn, matching server
  behaviour. Pre-fix, TUI usage tracking only flushed on `/save` or
  exit — losing data on Ctrl+C interrupt.
- **`session.load()` rejects path-traversal names** (`..`, absolute
  paths, embedded separators). 21 persistence tests added.
- **Latent `agent.py:680` `AttributeError`** (Item 11) on Rich TUI
  `/agent <task>` — accessed `engine_client.logger` which doesn't
  exist on `EngineClient`. Tests substituted `Mock()` for the
  logger arg, masking the missing attribute. Fix: import
  `get_logger("tui")` directly. 4 regression tests use a REAL
  `EngineClient` instance — no mocks.

### Critique sweep (gpt-5.5)

The 2026-04-19 gpt-5.5 critique session identified untested
high-risk code via the code-review-graph. Closed by this release:

| Critique # | What | Tests |
|---|---|---:|
| #2 | `server/state.py` (Session, get_or_create_session, get_session_or_query, preview backend, kill_preview_backend) | 28 |
| #3 | Session persistence (write-failure propagation, symlinks, state-pointer staleness, concurrent IO, path-traversal in `load()`) | 44 |
| #4 | `_execute_ai_task` (model swap+restore, stream accumulation, async context, code blocks) | 20 |
| #5 | Tool security pass + new `docs/CONSENT-CONTRACT.md` | 18 |
| #9 | Server route edges (X-Session-Id edges, invalid restore, preview referer parsing) | 17 |

Plus 9 tests for the benchmark CI gate, gemini provider None-iter
guards, and `container.py:104` abstract-base regression.

**Net: 2591 → 3067 passing tests** (+476).

### Methodology pinning

Three discipline rules captured this release after pattern-matching
caught us out three times in the same shape:

- **Verify both directions, not just "is there a problem".**
  When a signal flags X as broken AND when someone pushes back
  saying the signal is wrong, both readings need the same Tier-2-style
  verification. We pattern-matched on `EngineClient` (Tier 2 — was
  design working as intended), `ChatViewProvider` (Item 2 — was a
  real refactor), `PPXAIDEApp` (Item 1 — was test-inflation
  noise). All three caught only because someone ran the
  production-code-only inbound count.
- **`.graphifyignore` excludes tests/benchmarks/scripts/examples.**
  A single 4,788-line `tests/test_tui.py` drove 71-79% of the
  "god class" edges on the TUI classes. Whole-repo god-node
  ranking with tests included is biased by test-coverage volume,
  not architecture. Whole-repo graph: 11,628 → 4,481 nodes (-61%);
  46,971 → 16,602 edges (-65%). Post-exclusion top hubs reflect
  the actual architecture (`EventType`, `CommandResult`,
  `SessionManager`, `BaseTool`, `BaseProvider`,
  `ToolManagerProtocol`).
- **Subtree-build pattern documented.** `c:\tmp\subtree_build.py
  <input_path> <output_dir>` runs the AST-only graphify pipeline
  against a subtree. Used 5 times this branch (`engine`, `server`,
  `commands`, `vscode`, `tui`) to surface subsystem-internal
  structure that the whole-repo graph hides.

## Tests

| Test file | Count | Coverage |
|---|---:|---|
| [test_server_state.py](../tests/test_server_state.py) | 28 | Session, get_or_create_session, get_session_or_query, preview backend, kill_preview_backend |
| [test_session_persistence.py](../tests/test_session_persistence.py) (additions) | 21 | Path traversal, write-failure propagation, symlinks, state-pointer staleness, concurrent IO |
| [test_execute_ai_task.py](../tests/test_execute_ai_task.py) | 20 | Model swap+restore, stream accumulation, async context, code blocks |
| [test_tool_security.py](../tests/test_tool_security.py) | 18 | Consent boundary, tool isolation, sandbox enforcement |
| [test_server_route_edges.py](../tests/test_server_route_edges.py) (additions) | 17 | X-Session-Id edges, invalid restore, preview referer parsing |
| [test_command_envelope.py](../tests/test_command_envelope.py) (additions) | 3 | `/command/{name}` route logging (Item 7) |
| [test_server_routes.py](../tests/test_server_routes.py) (additions) | 1 | `/state` route logging (Item 9) |
| [test_version_banner.py](../tests/test_version_banner.py) (additions) | 3 | `_build_info` precedence + fall-through (Item 8) |
| [test_engine_client_protocol.py](../tests/test_engine_client_protocol.py) | 9 | `EngineClientProtocol` surface + structural satisfaction + import hygiene (Item 10) |
| [test_agent_logger_attribute.py](../tests/test_agent_logger_attribute.py) | 4 | Real-engine regression for the `engine.logger` AttributeError (Item 11) |

**Suite: 3067 passing, 9 skipped.** The 7 skips are Unix-only
`TestKillPreviewBackend` (`patch()` can't mock `os.getpgid`/`killpg`
on Windows because those attrs don't exist there); the 2 others
are pre-existing.

## Deferred to v1.18.3 / future

- **Item 3 — k8s session-manager security tests.** Multi-tenant
  deploy code in `deploy/images/session-manager/`. Trigger-deferred
  per the user's note: address when in k8s context environment
  so tests can be exercised end-to-end. Quick pass: 10 unit tests
  around `_hash_password` (timing-safe), `authenticate`
  (denial fail-closed), naming validation. Full pass: 30-50
  tests with mocked `kubernetes.client`.
- **Agent loop unification across HTTP clients.** Inherited from
  v1.18.1 deferred list. Factory's `handle_agent` is TUI-shaped
  (`asyncio.run`, `console.print`); web/VSCode keep client-side
  loops. See [docs/TODO-v1.18.2-agent-loop-unification.md](TODO-v1.18.2-agent-loop-unification.md).
- **`prompt_text` side-effect kind** for free-text follow-ups when
  `prompt_quick_pick`'s finite-choice shape doesn't fit. See
  [docs/TODO-v1.18.2-prompt-text-kind.md](TODO-v1.18.2-prompt-text-kind.md).
- **AppState codegen + client wiring.** Inherited from v1.18.0
  deferred list. See `docs/TODO-appstate-codegen.md`.
- **Multi-model routing infrastructure.** `RoutingRole`,
  `ProviderPool`, `ModelRouter`, coding command routing. See
  `docs/TODO-routing.md`.

## Upgrade notes

- **For developers:** `.graphifyignore` now excludes
  `tests/benchmarks/scripts/examples/docs/archive`. If you've been
  using whole-repo graphify queries that depended on test-file
  edges, build a subtree explicitly with `subtree_build.py`.
- **For VSCode extension users:** the `.vsix` is now bundled
  (`dist/extension.js` is a single ~108 KB minified file). If you
  symlinked anything inside `node_modules/` from a previous install,
  rebuild — those modules are now inlined.
- **For PyInstaller-binary users:** the version banner mechanism is
  in place but not yet wired into release tooling — shipped binaries
  in v1.18.2 still report `commit n/a, source n/a`. The
  `scripts/write_build_info.py` integration into `scripts/release.py`
  is a one-line follow-up planned for v1.18.3.

## Commits

```
deb565c8 refactor(tui+commands): close Item 1 — extract session_restore_ops, ADR 0002
1745650c chore(graphify): exclude tests/benchmarks/scripts/examples/archive
5ca37c4b build(vscode): bundle extension via esbuild — close Item 5
f9cb57e5 refactor(vscode): contract-based resolveWebviewView — close Item 2
8f9d31c8 fix(agent): use get_logger('tui') not engine.logger — close Item 11
515f206f refactor(commands): EngineClientProtocol — close Item 10, file Item 11
909db8f3 docs(debt): scope-narrow Item 1, file Item 10, attach TUI subtree findings
7b13784f docs(debt): close Item 4 (focused-subtree graphify) with findings
c6322dda feat(observability): close debt items 7, 8, 9 (Tier 1 pass)
cbd84233 docs(debt): add observability gaps from webapp debug-log review
5e6933b8 docs(debt): track VSCode extension bundling + Windows code CLI shim
41e3ce45 docs(claude): add verify-don't-assume rule + graphify reading guide for AppState
1cfb61fc chore: sync uv.lock to v1.18.2
3b8996d0 release: v1.18.1 -> v1.18.2
2e52fb03 docs: capture deferred debt items in DEBT-INVENTORY-v1.18.2.md
b3deca6b feat(version): runtime banner with version + commit + source mtime
f73627a2 fix(rich+tui): flush usage to global ledger per-turn (parity with server)
be8de79c fix(session): orphan tool_calls cleanup + usage_by_model round-trip on load
2736f8e9 test+harden: 9 tests for benchmark CI gate, gemini None-iter guards
57c45fdc config(openai): default_model gpt-4.1-mini -> gpt-5.4-mini, coding gpt-5.4-mini
36c73777 test(server/routes): 17 tests for X-Session-Id edges, invalid restore (#9)
79b54757 test(tools)+docs: 18 security tests + CONSENT-CONTRACT.md (#5)
7f7a578d test(coding): 20 tests for _execute_ai_task — model swap+restore, stream accum
c5cb8b7e test(session): 23 tests for write-failure propagation, symlinks, state-pointer
f8e913d9 test(server/state): 28 tests for get_or_create_session, get_session_or_query
34377a40 fix(session): reject path-traversal names in load(); add 21 persistence tests
fa17ef2b docs(models): planner/executor selection guide + surgical hint strip validated
47e6c2ed bench(models): gpt-5.5 + gpt-5.3-codex 2026-04-26 — refine hints
c4b6f431 feat(models): register GPT-5.5, GPT-5.5-pro, GPT-5.3-codex, GPT-5-pro
```
