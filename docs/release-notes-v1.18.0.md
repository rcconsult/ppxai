# Release Notes — v1.18.0

> **Scope:** P0 agent heartbeat primitives + v1.18.0 stabilization
> pass ([docs/STABILIZATION-v1.18.0.md](STABILIZATION-v1.18.0.md)).
>
> **Deferred to v1.18.1:** AppState codegen
> ([docs/TODO-appstate-codegen.md](TODO-appstate-codegen.md)) and
> multi-model routing infrastructure
> ([docs/TODO-routing.md](TODO-routing.md)). Both are substantial
> enough to deserve dedicated release notes; bundling them with
> heartbeat would produce a release nobody can review in one sitting.

## Summary

**P0 — Agent heartbeat primitives.** ppxai's agent tool loop now has
a structured, observable heartbeat that every client can render
without scraping events. `EventType.AGENT_BEAT` fires once per tool
iteration; `AGENT_RUN_START` / `AGENT_RUN_COMPLETE` / `AGENT_RUN_ERROR`
bracket the run; `AGENT_ZOMBIE` fires when a new circuit-breaker
trips after N consecutive failed iterations. The latest beat is
mirrored to `AppState.agent_beat` (schema-driven, cross-client) and
cleared on run completion, so Rich, ppxaide, the web app, and the
VSCode extension all render from one canonical field.

Together these primitives turn three recurring failure modes into
observable events:

1. **Silent multi-minute tool loops** where the user couldn't tell
   if the agent was still working. Heartbeat events fire on every
   iteration with elapsed time.
2. **"apply_patch fails 10× with hallucinated variations"** sessions
   that burned the full `max_iterations` budget before giving up.
   The zombie breaker stops them after 3 consecutive failures.
3. **Cross-client renderer drift** where each UI client scraped
   different events to approximate agent progress. Now every client
   subscribes to one AppState field.

No breaking changes. No migration needed. Existing consumers that
ignore the new events continue to work.

## What's new

### Engine

- **`EventType.AGENT_BEAT`, `AGENT_RUN_START`, `AGENT_RUN_COMPLETE`,
  `AGENT_RUN_ERROR`, `AGENT_ZOMBIE`** — new lifecycle events emitted
  by `ppxai/engine/chat.py::chat_with_tools`. Payloads are
  JSON-serializable dicts; see `ppxai/engine/types.py::AgentBeatState`
  for the canonical shape.
- **`AgentBeatState` dataclass** — tracks iteration, beat sequence,
  last tool name, per-beat ok flag, consecutive-failure streak, and
  wall-clock elapsed. `as_event_data()` is the single stable payload
  helper consumed by every observer.
- **Zombie circuit-breaker** — new config key
  `tools.agent.zombie_threshold` (default **3**, `0` disables).
  When the agent loop hits the threshold of consecutive failed
  iterations it emits `AGENT_ZOMBIE`, `AGENT_RUN_ERROR`, and
  returns cleanly. Prevents runaway retries from burning the full
  `max_iterations` budget on hallucinated variations.

### AppState

- **`agent_beat` field** added to `ppxai/engine/app_state_schema.json`
  (`"type": "object"`, `"default": {}`). Mirrored automatically in
  the JS + TypeScript AppState implementations — they derive fields
  from the schema at module init.
- **SSE state_sync whitelist** (`_SSE_SYNC_FIELDS` in
  `ppxai/engine/client.py`) includes `agent_beat`, so the server
  pushes heartbeat updates over the existing `state_sync` event
  stream with zero per-route changes.
- **Engine-side invalidation** — `EngineClient._chat_with_tools`
  writes the latest beat to AppState on every `AGENT_BEAT` event
  and clears the field (empty dict) on `AGENT_RUN_COMPLETE` /
  `AGENT_RUN_ERROR` / legacy `AGENT_COMPLETE`. Clients never scan
  events themselves.

### Client renderers

All four clients render the heartbeat from the same AppState field.
Visuals differ per host, but the data source is identical.

- **Rich TUI (`ppxai`)** — dim one-liner
  `⚙ iter N · tool · status · Xs` printed after each tool group by
  `TUIEventHandler`. Circuit-breaker trips render as a red
  `⚠ Agent stopped — {reason} · last: {tool} · {elapsed}s`.
  `AGENT_RUN_START` / `AGENT_RUN_COMPLETE` / `AGENT_RUN_ERROR`
  themselves are silent — they exist for observers; user-visible
  signal is the existing ERROR event plus BEAT / ZOMBIE.
- **Textual TUI (`ppxaide`)** — persistent status-bar badge
  `⚙ iN · tool · Xs` with variant colouring: `success` (ok),
  `error` (single failed beat), `warning` (≥2 consecutive failures —
  approaching the zombie threshold). Cleared automatically when the
  engine empties `agent_beat` on run end.
- **Web (`ppxai-server` + browser)** — header badge (`#agentBeatBadge`)
  between the streaming-badge and usage-badge. Same variant logic
  via `.warn` / `.error` CSS classes against the existing VSCode-style
  badge palette. Auto-hidden while idle.
- **VSCode extension** — identical badge in the webview header,
  styled with `vscode-badge-background` / `vscode-editorWarning` /
  `vscode-errorForeground` theme tokens. The extension host forwards
  the payload over the existing `stateSync` postMessage channel —
  no new message types.

## Configuration

New config key in `~/.ppxai/ppxai-config.json`:

```jsonc
{
  "tools": {
    "agent": {
      "max_iterations": 10,
      "max_tool_iterations": 15,
      "max_same_tool_calls": 3,
      "zombie_threshold": 3   // NEW in v1.18.0 — 0 disables the breaker
    }
  }
}
```

A more aggressive setting is useful on locally-hosted models that
tend to get stuck in tool-retry loops:

```jsonc
{ "tools": { "agent": { "zombie_threshold": 2 } } }
```

## Test coverage

- **`tests/test_agent_beat_primitives.py`** — EventType membership,
  `AgentBeatState` field contract, elapsed computation, payload
  shape, mutation invariants.
- **`tests/test_agent_beat_emission.py`** — emission ordering in
  `chat_with_tools`, payload propagation through `EngineClient`,
  failure-counter reset semantics, mode-agnostic
  `AGENT_RUN_COMPLETE` firing.
- **`tests/test_agent_beat_zombie.py`** — circuit-breaker below /
  at / above threshold, custom threshold from config,
  `threshold=0` disables, `ConfigStore.set_for_testing()` round-trip.
- **`tests/test_agent_beat_sse.py`** — end-to-end integration through
  the real EngineClient + server `sse_event_generator` with a
  MockProvider; pins wire format, event ordering, and
  `state_sync` pass-through for `agent_beat`.
- **`tests/test_agent_beat_textual_renderer.py`** — ppxaide badge
  lifecycle (add / update / remove), variant selection across
  `ok` / single-fail / streak, `AppState`-driven end-to-end.
- **`tests/test_common_event_handler.py`** — Rich TUI renderer
  verifies dim-line format, failure-streak annotation, red zombie
  warning, silent-by-design run events.
- **`tests/test_stream_handler_dispatch.py`** — drift test updated;
  new EventType members are in the ppxaide `NOOP_EVENTS` set (TUI
  renders via AppState instead of the event bus).
- **`tests/test_app_state.py`** — sentinel field count bumped to 19;
  SSE sync whitelist sentinel bumped to 11.

**Heartbeat P0 alone: 2,458 passed, 2 skipped, 0 regressions** (+~120 vs v1.17.7).
After the stabilization pass: **2,591 passed**, 2 skipped, 0 failing
(+181 vs v1.17.7) — see [STABILIZATION-v1.18.0.md](STABILIZATION-v1.18.0.md)
for the per-phase breakdown.

## Architecture

See the new §"Agent Heartbeat Primitives (v1.18.0)" in
[docs/architecture.md](architecture.md) for:

- The emission contract for `chat_with_tools` (which events fire
  where, and what payload invariants to assume).
- The `AgentBeatState` → `AppState.agent_beat` lifecycle and why
  the engine — not clients — owns invalidation.
- The zombie-breaker decision flow.
- The cross-client renderer contract (what changes when a new
  client is added).

## Upgrade notes

Drop-in upgrade. No code changes required on consumer side.

Users who want the breaker more or less aggressive should add
`"zombie_threshold": N` under `tools.agent` in `ppxai-config.json`.

## Commits

### P0 heartbeat primitives

```
51c8ed54  feat(engine): P0 Stage 1 — agent heartbeat types + dataclass
26b73c20  feat(engine): P0 Stages 2+4 — emit agent lifecycle events, wire AppState.agent_beat
16496d40  feat(engine): P0 Stages 2+4 follow-up — SSE integration tests + AGENT_RUN_COMPLETE
5d0f7fc5  feat(engine): P0 Stage 3 — zombie detection / circuit breaker
c7c87850  feat(rich):    P0 Stage 5a — agent heartbeat renderer
ec37b677  feat(ppxaide): P0 Stage 5b — agent heartbeat status badge
c995ceae  feat(web):     P0 Stage 5c — agent heartbeat header badge
0dc148c9  feat(vscode):  P0 Stage 5d — agent heartbeat header badge
```

### v1.18.0 stabilization pass

```
3615dfe3  test(v1.18.0): AGENT_BEAT cross-client rendering parity
246c6035  fix(v1.18.0): clear 19 pre-existing test failures on Windows
0c4ac1f4  feat(v1.18.0): GET /state snapshot endpoint for SSE reconnect sync
012911f1  refactor(v1.18.0): last_message_role AppState field + Rich migration
a330c187  refactor(v1.18.0): unify token and usage-badge formatting across clients
9c997b32  docs(v1.18.0): stabilization pass summary
0ea64cd5  chore(v1.18.0): trivial cleanup — duplicate import, UTF-8 reads
6c530b80  refactor(v1.18.0): drop has_vision_model back-compat alias
62c661fa  build(v1.18.0): list every server route module in ppxai-server.spec
8fc0be9f  refactor(v1.18.0): unify usage badge to suppress $0.0000 when cost is zero
cdcc0369  docs(v1.18.0): AppState listener contract + error routing conventions
2d200718  fix(v1.18.0): surface sustained auto-save failures + narrow Textual excepts
6719c93e  refactor(v1.18.0): promote 6 pure helper functions to public API
502e4c0d  refactor(v1.18.0): extract I/O helpers to dedicated utility modules
```

See [STABILIZATION-v1.18.0.md](STABILIZATION-v1.18.0.md) for what
each commit changed and what the audit verified vs. left alone.
