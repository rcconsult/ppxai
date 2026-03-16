# TODO: AppState Phase 4 — VSCode Extension

**Status:** Open
**Priority:** MEDIUM — proves TS generation, distinct event model
**Depends on:** Phase 3 (Web App — cross-language parity proven)
**Target:** v1.17.2

---

## Why Fourth

VSCode is a distinct codebase (TypeScript, VS Code API, different event model)
with more unknowns than k8s (which is just the web app + runtime config).
Better to tackle these unknowns before the k8s deployment test where stability
matters.

Key differences from web app:
- **TypeScript** — needs typed `IAppState` interface + generic `get<K>()`/`set<K>()`
- **VS Code EventEmitter** — VS Code convention for observables, may coexist with
  or replace AppState `on()`/`off()`
- **No Proxy** — TS doesn't have JS Proxy ergonomics, so property shorthand needs
  explicit getter/setter generation
- **Webview boundary** — extension host (TS) and webview (HTML/JS) communicate
  via `postMessage`, state lives on extension host side

## Current State

| File | Lines | State fields |
|------|------:|--------------|
| `vscode-extension/src/config.ts` | ~270 | `currentProvider`, `currentModel` on `ConfigManager` class |
| `vscode-extension/src/chatPanel.ts` | ~2,700 | Reads from `ConfigManager` + HTTP responses |
| `vscode-extension/src/handlers/eventBus.ts` | ~200 | `ChatEventBus` — typed event emitter |
| `vscode-extension/src/handlers/agentStateMachine.ts` | ~370 | `toolsEnabled` from HTTP status |

### State Management Today

The VSCode extension doesn't have centralized state. It has:
- `ConfigManager` — owns `currentProvider`, `currentModel`
- HTTP responses — `GET /status` returns tools/agent/checkpoint state on demand
- `ChatEventBus` — typed events for stream/consent/agent communication
- Local variables — `toolsEnabled` fetched per-request, not cached

This is the most loosely coupled client — it reads state from the server on demand
rather than maintaining a local mirror.

## Implementation Steps

### Step 1: Generate `appState.ts`

**Files:** `vscode-extension/src/shared/appState.ts` (new)

Generator produces:
```typescript
// GENERATED from ppxai-state.schema.yaml — do not edit
export interface IAppState {
    currentProvider: string;
    currentModel: string;
    toolsEnabled: boolean;
    agentMode: boolean;
    isStreaming: boolean;
    cancelRequested: boolean;
    // ... all schema fields with correct TS types
}

export class AppState {
    private _data: IAppState;
    private _listeners: Map<string, Set<(value: any) => void>>;

    constructor(initial?: Partial<IAppState>);
    get<K extends keyof IAppState>(key: K): IAppState[K];
    set<K extends keyof IAppState>(key: K, value: IAppState[K]): void;
    on<K extends keyof IAppState>(key: K, fn: (value: IAppState[K]) => void): () => void;
    off<K extends keyof IAppState>(key: K, fn: (value: IAppState[K]) => void): void;
    update(partial: Partial<IAppState>): void;
    snapshot(): IAppState;
    loadRuntime(name: string): void;
}
```

Key TS-specific decisions:
- `get<K>()` / `set<K>()` are generic → return types are inferred from key
- `on()` returns an unsubscribe function (VS Code convention)
- No Proxy — use explicit accessor generation or stick with `get()`/`set()`

### Step 2: Wire AppState into ConfigManager

**Files:** `vscode-extension/src/config.ts`

- Replace `private currentProvider` / `private currentModel` with AppState
- `ConfigManager` methods delegate to `state.set()` / `state.get()`
- Verify provider/model switching still works

### Step 3: Wire AppState into ChatPanel

**Files:** `vscode-extension/src/chatPanel.ts`

- Replace ad-hoc HTTP status reads with state observers where appropriate
- State is synced from server responses: when `GET /status` returns,
  call `state.update({...})` from the response data
- Webview messages use state for current provider/model

### Step 4: Coexistence with ChatEventBus

`ChatEventBus` handles **stream events** (chunks, tool calls, consent).
`AppState` handles **state observation** (provider changed, tools toggled).
Same separation as Python EventBus + AppState:
- EventBus: `bus.emit('stream:chunk', content)` → handler processes chunk
- AppState: `state.on('isStreaming', fn)` → UI toggles spinner

Verify no overlap, no duplicate handling.

### Step 5: Compile and test

```bash
cd vscode-extension && npm run compile
npx vsce package --allow-missing-repository
code --install-extension ppxai-*.vsix --force
```

Manual smoke test:
- Open chat panel
- Chat with streaming
- Switch provider/model
- Toggle tools/agent
- Consent dialogs
- Session load/restore

## Acceptance Criteria

- [ ] Generated `appState.ts` compiles without TS errors
- [ ] `IAppState` interface has all schema fields with correct types
- [ ] `ConfigManager` uses `state.get()`/`state.set()` for provider/model
- [ ] `ChatEventBus` and `AppState` coexist cleanly
- [ ] Extension compiles and packages successfully
- [ ] Manual smoke test passes all flows
- [ ] `SCHEMA_VERSION` matches Python and JS versions

## What NOT to Do

- Don't rewrite `chatPanel.ts` — just wire in AppState for state fields
- Don't replace `ChatEventBus` — it handles stream events, not state
- Don't add complex state sync from server — keep it simple (update from HTTP responses)

## Estimated Effort

~3 hours (TS generation + wiring + testing)

## Lessons Learned

*(To be filled during/after implementation)*

### From Phase 1–3
*(Copy relevant lessons)*

### TypeScript-Specific Issues
- ...

### VS Code API Constraints
- ...

### What to Do Differently Next Time
- ...
