# v1.18.1 — State-Sync Determinism

**Branch:** `feature/v1.18.1` (parallel workstream to command unification)
**Goal:** Make engine ↔ client state synchronization deterministic across the entire user session, not just during active `/chat` streams. Eliminate the "rare working-dir misalignment" + "file not found" class of bugs that block trustworthy agent execution.

## Why this is a v1.18.1 blocker for agents

Today the engine is the canonical source of state, but the only path that delivers state changes to clients is the SSE stream inside `POST /chat`. When no chat is active:

- `engine.set_working_dir()` enqueues `state_sync` + `working_dir_changed` events.
- The events sit in `engine._event_queue` until the next `/chat` opens an SSE generator that drains them.
- Anything else that mutates engine state (REST endpoints, agent tools, session restore) is invisible to the web mirror until the next chat.

Concrete failure modes the user has hit or will hit:

1. **File-tree entries stale after engine cwd change.** Web tree caches dir contents against `_fileTreeCurrentPath`. If engine cwd changes (agent loop, session restore, concurrent REST), the tree keeps showing old entries until SSE delivers `working_dir_changed` — usually fine during a chat, broken between chats. Clicking a stale entry sends a relpath that resolves against the new cwd → **404 file not found**.

2. **Right-click → preview / edit / show races with cd.** User does "cd here" on a folder, then immediately clicks a file in the tree before the 300ms debounced refresh completes. Tree renders against new cwd; its cached entries were loaded against the old cwd. Click → 404.

3. **Multi-tab divergence.** Tab A runs `/cd /x` (REST). Tab B's mirror is still on the old cwd. B's user previews a file by relpath → 404.

4. **Reconnect-only catch-up.** Web only calls `GET /state` after 2 consecutive heartbeat failures. Brief network blips, tab sleep, and page restores don't trigger that path — they leave the mirror silently stale.

5. **Agent tool fires after stream end.** A tool emits `working_dir_changed` *after* the SSE generator yields `STREAM_END` but before it exits. Timing-dependent loss.

For agents specifically: the engine state can drift arbitrarily far from the UI between chat turns. The user can't predict what state the agent saw vs. what the UI shows. That's the non-determinism — and it's why this work blocks confident agent development.

## Design principles

1. **Engine state is canonical. Always.** Web/VSCode are renderers, not co-owners. Any mutation that lands in engine MUST be observable to clients within one round-trip.
2. **Synchronization is many channels, but one truth.** SSE during chat, `/state` polls between chats, REST response piggyback for explicit mutations. Each channel updates the same AppState mirror; the mirror is the only thing the UI reads.
3. **Drift is detectable and recoverable, not silent.** When client and server disagree (e.g. stale relpath), the server returns a structured conflict that names the new state, not a generic "not found".
4. **Don't add new state channels until the existing ones are reliable.** The persistent-SSE channel option is tempting but expensive (long-lived connections, proxy quirks). Defer until polling + piggyback are proven insufficient.

## Phase A — Tab-visibility re-anchor (small, immediate)

**Problem.** Web only refreshes from `/state` on heartbeat reconnect. Tab sleep, focus restore, page navigation back/forward do not.

**Fix.** Subscribe to `document.visibilitychange`. On transition to `visible`:
- Call `apiClient.getState()` and feed through `state.updateFromPython()`.
- Trigger a single file-tree refresh keyed off the resulting `workingDir`.

**Code shape** (web `app.js`):
```js
document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
        this._reanchorFromServer();
    }
});

async _reanchorFromServer() {
    try {
        const snapshot = await this.apiClient.getState();
        this.state.updateFromPython(snapshot);  // existing facade
    } catch (e) {
        console.warn('[PpxaiApp] reanchor failed:', e);
    }
}
```

**Cost.** ~10 lines JS. `GET /state` is cheap (no DB, no LLM). VSCode extension does the same on `vscode.window.onDidChangeWindowState`.

**Tests.** Drift simulation: mutate engine state, verify web mirror updates after a synthetic `visibilitychange`. (Probably manual smoke + one playwright/jest sketch — full e2e covered in Phase E.)

## Phase B — REST response piggyback

**Problem.** `engine.set_working_dir()` (and similar) emit events into `_event_queue`. If no SSE generator is consuming, events accumulate. The REST response that triggered the mutation already returns the new value optimistically (`{"path": "/x", "success": true}`), but other clients of the same session don't see the change, and the calling client misses the broader effect (e.g. context attachments cleared, bootstrap context reloaded).

**Fix.** State-mutating REST endpoints drain the side-channel queue and include the events in the response:

```json
POST /context/working_dir
→ {
    "path": "/abs/new/cwd",
    "success": true,
    "session_id": "...",
    "events": [
        {"type": "state_sync", "data": {"working_dir": "/abs/new/cwd"}},
        {"type": "working_dir_changed", "data": {"path": "/abs/new/cwd"}}
    ]
}
```

The web/VSCode client feeds `events[]` through the same dispatcher that handles SSE events. Same code path, no new event semantics.

**Where to apply.** Every endpoint that calls `engine.set_*` or `engine.<verb>_*` where the verb mutates AppState fields:
- `POST /context/working_dir`
- `POST /providers` (set provider)
- `POST /models` (set model)
- `POST /tools` (toggle tools)
- `POST /agent/enable`, `POST /agent/disable`
- `POST /sessions/load/{name}`, `POST /sessions/save`, `POST /sessions/clear`
- `POST /sessions/restore`
- `POST /context/auto_inject`, `POST /context/clear`, `POST /context/reload`
- `POST /command/{name}` (envelope already has `result` + `side_effects`; add `events`)

**Implementation.** Helper in `ppxai/server/state.py`:
```python
def with_drained_events(payload: dict, engine: EngineClient) -> dict:
    payload["events"] = [e.to_dict() for e in engine.drain_events()]
    return payload
```

Each route's `return` becomes `return with_drained_events({...}, s.engine)`.

**Cost.** ~5 LoC per endpoint × ~12 endpoints. One helper. Web changes: extend the existing SSE dispatcher to accept an array of events, then teach the REST callers to feed it.

**Tests.** New unit tests under `tests/test_rest_event_piggyback.py` — mutate engine via REST, assert response includes the expected events, assert engine queue drained.

## Phase C — File-tree as AppState subscriber

**Problem.** `FileTreeComponent` keeps its own `_fileTreeCurrentPath` cache. The 300ms debounce on `working_dir_changed` is a workaround for spurious replays during session restore, not a sync mechanism. Because the cache is parallel state, it can disagree with `app.state.workingDir`.

**Fix.** The tree subscribes to `app.state` and re-derives root from it:

```js
this.app.state.on('workingDir', (newCwd) => {
    if (newCwd && newCwd !== this._fileTree.currentRoot) {
        this._fileTree.setRoot(newCwd);  // clears cache, reloads root
    }
});
```

Drop `_fileTreeCurrentPath` and `_fileTreeRefreshTimer` from `app.js`. The debounce moves into `setRoot()` and applies only when the same value arrives twice in quick succession (which is what session restore does — same value, three times, in 50ms).

**Cost.** ~15 LoC change in `app.js` + `file-tree.js`. Net negative complexity (removes parallel state).

**Tests.** Existing test pattern in `tests/test_app_state_dedup.py`-style: write `workingDir` twice with same value, assert `setRoot` called once.

## Phase D — Stale-relpath detection (`cwd_anchor`)

**Problem.** When the user clicks a file in a tree whose cache was loaded against an older cwd, the relpath sent to `/files/read` resolves against the *current* engine cwd. If `subdir/foo.py` doesn't exist there, response is "404 file not found" — confusing because the user can see the file in the tree.

**Fix.** Two-sided anchor:

**Server side** — `/files/list` response includes the cwd it resolved against:

```json
GET /files/list?path=src
→ {
    "path": "src",
    "working_dir": "/abs/cwd/at/load/time",
    "files": [...],
    "at_fs_root": false
}
```

**Client side** — `FileTreeComponent` stores `working_dir` per loaded directory. When a click translates to a `/files/read` or `/files/write` call, the client sends the anchor:

```json
POST /files/read
{
    "path": "subdir/foo.py",
    "cwd_anchor": "/abs/cwd/at/load/time"
}
```

**Server side** — if `cwd_anchor` is provided and doesn't match `engine.get_working_dir()`, return:

```json
HTTP 409 Conflict
{
    "detail": "working directory drift",
    "expected": "/abs/cwd/at/load/time",
    "actual": "/abs/new/cwd",
    "events": [...drained...]
}
```

The client treats 409 as "refresh tree from new cwd, retry the action against the new tree". Drift is now **named, surfaced, recoverable**.

**Cost.** Server: ~20 LoC across `/files/list`, `/files/read`, `/files/write`, `/files/serve`, `/files/preview`. Client: ~25 LoC in tree component + view base class to thread the anchor through.

**Tests.** `tests/test_files_cwd_anchor.py` — drive `/files/list`, mutate engine cwd, drive `/files/read` with stale anchor, assert 409.

## Phase E — End-to-end determinism tests

**Problem.** All four phases above need a regression guard that simulates a real drift scenario and proves the user-visible symptom is gone.

**Fix.** New file `tests/test_state_sync_e2e.py`. Same pattern as `test_server_smoke_e2e.py`: spawn a real `python -m ppxai.server.http`, then drive deterministic drift sequences:

1. **Tab-sleep simulation.** REST mutation → wait → call `/state` → assert client-shape matches engine snapshot.
2. **Multi-client simulation.** Open two `httpx.Client`s on the same session. Mutate from A, observe in B via `/state`.
3. **REST piggyback.** POST `/context/working_dir`, assert `events[]` in response, assert engine queue empty after.
4. **Stale anchor.** GET `/files/list`, mutate cwd, POST `/files/read` with old anchor, assert 409.
5. **Agent-tool race (synthetic).** Use a stub command that mutates engine state, verify the web client sees the new state via the next REST round-trip without needing a chat to run.

**Cost.** ~250 LoC test file. Reuses the smoke-test fixture pattern and `_can_spawn_server` skip logic.

## Phase F (deferred to v1.18.2) — Persistent SSE channel

If after phases A–E we still see drift in production, add `GET /events` — a persistent SSE channel separate from `/chat` that drains the side-channel queue continuously while a session is connected.

**Why deferred:** persistent connections add complexity (proxy keepalive, reconnect storms, idle-timeout coordination with autosave). Phases A–E close the deterministic gap without that surface area. Only escalate if observation says they're insufficient.

## Implementation order

The phases are **independent and additive** — each makes drift narrower. Pick based on user-visible payoff:

| Order | Phase | Closes | LoC | Risk |
|---|---|---|---|---|
| 1 | A | Tab sleep, focus restore | ~20 | trivial |
| 2 | B | REST mutation gaps | ~80 | low |
| 3 | C | File-tree parallel state | ~30 | low (deletes code) |
| 4 | D | Stale relpath 404 → 409 | ~50 | medium (touches files routes + views) |
| 5 | E | Regression guard | ~250 | none (test only) |
| later | F | Last-mile drift | ~400 | high |

Total for the durable fix (A–E): ~430 LoC, mostly tests. Less than Phase 1 of the command unification.

## Acceptance criteria

- [ ] Tab-sleep test passes: visibility transition triggers `/state` re-anchor.
- [ ] REST mutation test passes: `POST /context/working_dir` returns `events[]` carrying the state_sync.
- [ ] Multi-tab test passes: two web clients on same session converge within one round-trip after either mutates.
- [ ] Stale anchor test passes: `/files/read` with mismatched `cwd_anchor` returns 409 + new cwd, not 404.
- [ ] File tree has no parallel `_fileTreeCurrentPath` state — `app.state.workingDir` is the only source.
- [ ] e2e test suite proves no drift across the five named scenarios.
- [ ] No regression in the 61-endpoint smoke test suite.

## Relationship to command unification (v1.18.1 main plan)

The two workstreams are **complementary, not blocking**:

- Command unification routes commands through `POST /command/{name}` with an envelope.
- State-sync determinism makes that envelope's `events[]` field actually deliver canonical state to all listeners.

Phase B's "REST response piggyback" is the same shape as the command envelope's existing `side_effects[]` — they share the dispatcher on the client side. Implementing them in either order is fine; doing them together makes the wire contract cleaner because every state-mutating server response (commands or REST) has the same shape.

**Recommended interleave:**

1. Command Unification Phase 2 (server gaps) +
   State-Sync Phase A (visibility re-anchor)
2. Command Unification Phase 3 (web rewrite, includes side-effects/events handler) +
   State-Sync Phase B (REST piggyback) — same client dispatcher, do them together
3. State-Sync Phase C (tree subscribes)
4. State-Sync Phase D (cwd_anchor)
5. Command Unification Phase 4 (VSCode rewrite) — apply same patterns
6. Phase E e2e tests
7. Command Unification Phases 5–6 (tests, endpoint retirement)

That ordering keeps the client-side dispatcher consistent throughout — never a half-state where commands have envelopes but REST doesn't.

## Out of scope

- Two-way binding (UI mutates engine via subscriptions). The current REST + command surface is enough; subscriptions add reactive complexity without a present need.
- Cross-session synchronization. Each session is its own truth; sync between sessions is a v1.19+ concern if at all.
- Engine-side checkpoint/rollback for state mutations. The transactional pattern in `CLAUDE.md` is for UI badge updates, not engine state.
