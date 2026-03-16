# TODO: AppState Phase 0 — Schema + Generator

**Status:** Open
**Priority:** HIGH — prerequisite for all client migrations
**Depends on:** None
**Target:** v1.17.1

---

## Objective

Create the app state schema and code generator before touching any client code.
This phase produces the foundation that all subsequent phases build on.

## Deliverables

### 1. `ppxai-state.schema.yaml`

Unified field set for all clients. See `docs/TODO-refactoring.md` item 3 for
the full schema definition with types, defaults, and feature groups.

**Validation:** Fields must cover the union of:
- Web app `AppState` fields (`ppxai/web/app.js` lines 66–123)
- Textual TUI `self._*` fields (`ppxai/tui/app.py` lines 120–147)
- Rich TUI state (minimal — `EventHandler` internal accumulators)
- VSCode `config.ts` fields (lines 101–102)
- EngineClient properties (provider, model, tools, agent, streaming, etc.)

### 2. Runtime schemas

- `ppxai-runtime-desktop.schema.yaml` — terminal protocol detection
- `ppxai-runtime-k8s.schema.yaml` — session isolation, max sessions, TTL
- `ppxai-runtime-vscode.schema.yaml` — webview readiness

### 3. `scripts/generate-state.py`

Generator that reads schemas and produces:
- `ppxai/state.py` — Python AppState (thread-safe, async listeners)
- `ppxai/web/shared/app-state.js` — JS AppState (Proxy-based)
- `vscode-extension/src/shared/appState.ts` — TS AppState (typed interface + class)

Each output has:
- `get()` / `set()` / `on()` / `off()` / `update()` / `snapshot()` public interface
- Property shorthand (Python `__getattr__`/`__setattr__`, JS Proxy, TS accessors)
- `loadRuntime(name)` to plug in runtime schema fields
- No-op dedup on identical writes
- `SCHEMA_VERSION` constant
- Platform-specific: `threading.Lock` (Python), `Proxy` (JS), typed generics (TS)

### 4. `scripts/generate-state.py --check`

CI mode: regenerates in memory and compares to files on disk. Fails if someone
hand-edited a generated file instead of updating the schema.

## Acceptance Criteria

- [ ] Schema covers all existing state fields across all clients
- [ ] Generator produces valid Python/JS/TS that passes lint/type checks
- [ ] Generated Python AppState passes thread-safety unit tests
- [ ] Generated JS AppState passes existing Playwright e2e tests (drop-in replacement)
- [ ] `--check` mode works for CI integration
- [ ] No client code changes yet — this phase is infrastructure only

## Estimated Effort

~5 hours (schema 1h + runtime schemas 1h + generator 3h)

## Lessons Learned

*(To be filled during/after implementation)*

- ...
