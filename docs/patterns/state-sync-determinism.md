# Pattern: State-Sync Determinism

**Added:** v1.18.1
**Status:** **CRITICAL — Engine state must be observable to clients within one round-trip**
**Reference:** `ppxai/web/app.js::_reanchorFromServer`, `vscode-extension/src/chatPanel.ts::_reanchorFromServer`

## Problem

Pre-v1.18.1, the only path that delivered engine state changes to clients was the SSE stream inside `POST /chat`. Outside an active chat, `engine.set_working_dir()` (and similar) enqueued `state_sync` events into `engine._event_queue`, but no consumer drained the queue until the next chat opened an SSE generator.

Drift symptoms:
- File-tree clicks against a stale cwd → 404 file-not-found.
- Multi-tab divergence: tab A runs `/cd /x`, tab B's mirror is still on the old cwd.
- Tab sleep / focus restore / browser back-forward: web only re-anchors after two consecutive heartbeat failures.
- Agent tool fires `working_dir_changed` after `STREAM_END` but before the SSE generator exits → timing-dependent loss.

This non-determinism makes confident agent execution impossible: the engine state can drift arbitrarily far from the UI between chat turns.

## Solution: Many channels, one truth

Engine state is canonical. Web/VSCode are renderers, not co-owners. Every mutation that lands in engine MUST be observable to clients within one round-trip via at least one of these channels:

1. **SSE during chat** — `state_sync` events on the `/chat` stream (existing).

2. **`/state` snapshot on demand** — `GET /state` returns the current values of every `SSE_SYNC_FIELDS` field. Clients call it on:
   - **Web**: `document.visibilitychange` → `visible` AND on heartbeat reconnect.
   - **VSCode**: `vscode.window.onDidChangeWindowState` → `focused` AND on reconnect.

3. **REST response piggyback** — state-mutating REST endpoints include drained events in the response body's `events: [...]` field. The client feeds them through the same dispatcher that handles live SSE.

4. **`cwd_anchor` for stale-relpath detection** — `/files/list` returns the `working_dir` it resolved against; `/files/read` returns 409 + new cwd if the client's anchor doesn't match.

## The `_reanchorFromServer` helper

Both web and VSCode have a private async helper named `_reanchorFromServer` that does:

```
GET /state → updateFromPython(snapshot)
```

The same helper is called from BOTH the visibility/focus path AND the heartbeat reconnect path. Tests (`tests/test_web_visibility_reanchor.py`, `tests/test_vscode_visibility_reanchor.py`) enforce that the shape stays parity across the two clients — if the helpers diverge in what they re-anchor, drift fixes won't compose.

## Rules

1. **Engine state is canonical.** Web/VSCode read AppState; they never invent their own copy of the same field. Optimistic client-side updates (e.g. set `state.workingDir = data.path` from a REST response) are fine but the server's value wins on the next sync.
2. **Visibility/focus events trigger re-anchor.** Any new client widget that depends on AppState must subscribe to AppState, not cache the value at mount time.
3. **No new state channels without justification.** Persistent `GET /events` is deferred until A–E prove insufficient. Polling + REST piggyback is enough for current needs.
4. **`cwd_anchor` instead of "404 file not found".** When a route resolves a relpath against a working dir, return the working dir it used in the response. Clients send back the anchor on follow-up calls; mismatch → 409 with the new cwd in the body. Drift becomes named, surfaced, recoverable.
