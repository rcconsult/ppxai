# TODO: AppState Schema + Code Generation

**Status:** Open
**Priority:** Medium — builds on hand-crafted implementations (v1.17.1)
**Target:** v1.18.0
**Created:** 2026-03-20 (consolidated from TODO-appstate-{0..5}.md on 2026-04-02)

---

## Overview

Hand-crafted AppState implementations are complete and wired across all 4 clients
(Python, JS, TS) since v1.17.1. This TODO covers the next step: a YAML schema that
generates those implementations, ensuring field parity and preventing drift.

**What exists today (v1.17.2):**
- `ppxai/engine/app_state.py` — Python (thread-safe, async listeners, 17 fields wired)
- `ppxai/web/shared/app-state.js` — JS (Proxy-based, observers)
- `vscode-extension/src/appState.ts` — TS (typed interface + class)
- All 4 clients (Rich, Textual, Web, VSCode) use AppState for all state access
- SSE `state_sync` push for cross-client alignment

**What this TODO adds:**
- YAML schema → codegen so field additions/changes propagate automatically
- Runtime schemas for k8s, vscode, desktop deployment-specific settings
- CI `--check` mode to catch hand-edits to generated files

---

## Phase 0: Schema + Generator

### Deliverables

**1. `ppxai-state.schema.yaml`**

Unified field set for all clients. Must cover the union of fields across
`app_state.py`, `app-state.js`, `appState.ts`, and EngineClient properties.

```yaml
version: "1.0"
fields:
  currentProvider:       { type: string,  default: "perplexity" }
  currentModel:          { type: string,  default: "sonar-pro" }
  workingDir:            { type: string,  default: null, nullable: true }
  sessionName:           { type: string,  default: null, nullable: true }
  messageCount:          { type: integer, default: 0 }
  toolsEnabled:          { type: boolean, default: false }
  toolsVerbose:          { type: boolean, default: false }
  agentMode:             { type: boolean, default: false }
  autoRoute:             { type: boolean, default: false }
  isStreaming:            { type: boolean, default: false }
  cancelRequested:       { type: boolean, default: false }
  autoInject:            { type: boolean, default: true }
  bootstrapLoaded:       { type: boolean, default: false }
  lastCheckpoint:        { type: string,  default: null, nullable: true }
  checkpointCount:       { type: integer, default: 0 }
  usagePromptTokens:     { type: integer, default: 0 }
  usageCompletionTokens: { type: integer, default: 0 }
  usageCost:             { type: number,  default: 0.0 }
  contextPercentage:     { type: number,  default: 0.0 }
  debugLog:              { type: boolean, default: false }

features:
  core:        [currentProvider, currentModel, workingDir, sessionName, messageCount]
  tools:       [toolsEnabled, toolsVerbose, agentMode, autoRoute]
  streaming:   [isStreaming, cancelRequested]
  context:     [autoInject, bootstrapLoaded]
  checkpoints: [lastCheckpoint, checkpointCount]
  usage:       [usagePromptTokens, usageCompletionTokens, usageCost, contextPercentage]
  debug:       [debugLog]
```

**2. Runtime schemas**

- `ppxai-runtime-k8s.schema.yaml` — sessionIsolation, maxSessions, ttlMinutes, ldapEnabled
- `ppxai-runtime-vscode.schema.yaml` — webviewReady, extensionVersion
- `ppxai-runtime-desktop.schema.yaml` — terminalProtocol

**3. `scripts/generate-state.py`**

Reads schemas and produces:
- `ppxai/engine/app_state.py` — Python (threading.Lock, async listener dispatch)
- `ppxai/web/shared/app-state.js` — JS (Proxy-based)
- `vscode-extension/src/appState.ts` — TS (typed IAppState interface + class)

Each output includes: `get()`/`set()`/`on()`/`off()`/`update()`/`snapshot()`,
property shorthand, `loadRuntime()`, no-op dedup, `SCHEMA_VERSION`.

**4. CI check mode:** `scripts/generate-state.py --check` — fails if generated
files differ from checked-in versions.

### Acceptance Criteria

- [ ] Schema covers all existing state fields across all clients
- [ ] Generator produces valid Python/JS/TS that passes lint/type checks
- [ ] Generated Python AppState passes thread-safety unit tests
- [ ] Generated JS AppState passes existing Playwright e2e tests (drop-in replacement)
- [ ] `--check` mode works for CI integration
- [ ] No client code changes yet — this phase is infrastructure only

### Effort: ~5 hours

---

## Phase 1: Rich TUI Integration

Wire `EngineClient` to use generated `AppState` internally. Rich TUI is the
simplest client (single thread, sync event handler), proving the core works.

**Steps:**
1. `EngineClient.__init__` creates `AppState({...})` with all schema fields
2. Existing properties (`provider_name`, `model`, etc.) become thin wrappers
3. `RichCommandContext` reads from `engine.state.get()` instead of direct fields
4. Add `test_app_state.py` — basic get/set, dedup, observers, snapshot

**Acceptance:** All existing tests pass, manual smoke test identical behavior.

### Effort: ~4 hours

---

## Phase 2: Textual TUI Integration

Replace 15+ `self._*` shadow state fields on `PPXAIDEApp` with AppState observers.
This is where thread-safety and `call_from_thread()` integration are proven.

**Steps:**
1. Replace `self._provider`, `self._model`, etc. with `engine.state` reads
2. Register observers in `on_mount()` that call `self.call_from_thread()` for UI updates
3. Remove ~30 manual `update_badge()` calls — observers handle them
4. Add thread-safety tests (concurrent R/W, no deadlocks, async dispatch)
5. Verify EventBus + AppState coexistence (complementary, not competing)

**Acceptance:** All shadow state removed, all badge updates via observers, thread-safe tests pass.

### Effort: ~4 hours

---

## Phase 3: Web App Integration

Replace hand-written `app-state.js` with generated version. Drop-in replacement —
the web app already uses the `state.on()` pattern.

**Steps:**
1. Generated `app-state.js` replaces hand-written version
2. Widget-local fields (theme, autocomplete, RPF state) added at construction time
3. Enforce public interface — no direct `_data` access
4. Run 200 Playwright e2e tests as regression safety net
5. Test `state.loadRuntime('ppxai-runtime-k8s')` for Phase 5

**Acceptance:** All 200 e2e tests pass, `SCHEMA_VERSION` matches Python/TS.

### Effort: ~3 hours

---

## Phase 4: VSCode Extension Integration

Generate typed `appState.ts` with `IAppState` interface. Wire into `ConfigManager`
and `ChatPanel`.

**Steps:**
1. Generated `appState.ts` with typed `get<K>()`/`set<K>()` generics
2. `ConfigManager` uses `state.get()`/`state.set()` for provider/model
3. `ChatEventBus` coexists with AppState (events vs state observation)
4. Extension compiles, packages, and passes manual smoke test

**Acceptance:** TS compilation clean, manual smoke test passes all flows.

### Effort: ~3 hours

---

## Phase 5: k8s Web App Verification

Same app as Phase 3 + runtime config injection. Lightest phase.

**Steps:**
1. Verify `state.loadRuntime('ppxai-runtime-k8s')` injects settings
2. Replace implicit k8s detection (`/s/<user>/` URL) with `state.get('sessionIsolation')`
3. Deploy to colima cluster, verify login → session → chat flow
4. Verify TTL watchdog and heartbeat work as before

**Acceptance:** End-to-end k8s flow works, runtime fields in `state.snapshot()`.

### Effort: ~2 hours

---

## Total Effort: ~21 hours (across 4-5 sessions)

## Dependency Chain

```
Phase 0 (schema + generator)
  └── Phase 1 (Rich TUI — proves core)
       └── Phase 2 (Textual TUI — proves threading)
            └── Phase 3 (Web App — proves JS codegen)
                 ├── Phase 4 (VSCode — proves TS codegen)
                 └── Phase 5 (k8s — verification only)
```
