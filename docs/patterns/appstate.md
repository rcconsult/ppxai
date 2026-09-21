# Pattern: Cross-Client State Through AppState

**Added:** v1.17.4
**Status:** **CRITICAL — Required for every new piece of state that more than one client needs**
**Reference:** `ppxai/engine/app_state.py`, `ppxai/engine/client.py::_refresh_context_attachments`

## Problem

State that multiple clients need to read (Rich, Textual, Web, VSCode) tends to get re-implemented per client: each scans `session.messages` on demand, each keeps its own cache, each rerenders on its own schedule. This produces four near-identical bugs, four drift points, and four places to update when the shape changes.

## Solution: AppState owns the canonical value; clients subscribe

Any piece of state that more than one client needs to render or react to must live in `AppState.FIELDS` with these invariants:

1. **Stable JSON-serializable schema** — plain dicts, not dataclasses. The field round-trips through SSE `state_sync` events to `ppxai/web/shared/app-state.js` and `vscode-extension/src/appState.ts`, both of which DERIVE the same camelCase field names from `ppxai/engine/app_state_schema.json` at construction (web) or module init (VSCode) — neither hand-restates them. Cross-language schema drift is a production bug; see "Run-time skew (VSCode)" below for the one gap that derivation alone cannot close.

2. **Engine-owned invalidation** — `EngineClient` recomputes the field on mutation via a session callback. For `session.messages`, the callback is `SessionManager.on_messages_changed`, installed once and fired from every mutation site (`add_message`, `remove_last_message`, `clear`, `load`, `reset_for_model_switch`, `validate_and_fix_alternation`). When adding a new mutable store in the engine, give it an analogous `on_<thing>_changed` callback hook — never expect clients to poll.

3. **No client-side scanning** — clients read `state.get("field_name")` or subscribe via `state.on("field_name", listener)`. They never iterate `session.messages` (or the equivalent store) themselves.

4. **Equality-dedup on writes** — `AppState.set()` short-circuits when the new value equals the old, so callbacks stay quiet on no-op mutations. This matters for SSE: a conversation sending only text turns doesn't flood the wire with redundant `state_sync` events. Test this behavior explicitly when adding a new field.

5. **Defensive getter copies** — public getters (`engine_client.get_<thing>()`) return copies so external mutation can't corrupt canonical state. Callers that want to mutate must go through a proper write method.

## Worked Example: `context_attachments` (v1.17.4)

```python
# engine/app_state.py
"context_attachments": [],  # List of {name, kind, media_type, turn_index}
                            # Stable JSON schema — JS/TS mirrors in camelCase
```

```python
# engine/session.py — new callback, fired from 6 mutation sites
self.on_messages_changed: Optional[Callable[[], None]] = None

def add_message(self, message):
    self.messages.append(message)
    self.metadata["message_count"] = len(self.messages)
    self._notify_messages_changed()  # → engine refreshes AppState
```

```python
# engine/client.py — wire the callback, recompute on each mutation
self.session.on_messages_changed = self._refresh_context_attachments

def _refresh_context_attachments(self):
    """Walk session.messages, write to AppState — equality-dedup'd."""
    attachments = [...]  # scan once
    self.state.set("context_attachments", attachments)  # no-op if unchanged
```

```python
# rich/main.py — status bar reads AppState, never scans messages
attachments = state.get("context_attachments")
render_status_panel(..., pending_files=attachments)
```

## Rules

1. **Ask "does more than one client need this?"** before inventing per-client state. If yes, it goes in AppState.
2. **Schemas must be JSON-serializable plain dicts** — no dataclasses, no enums, no custom types. Document the schema inline in `FIELDS`.
3. **No mirror to maintain by hand, on either JS client.** Adding a field to `ppxai/engine/app_state_schema.json` is the only edit — `web/shared/app-state.js` reads `window.APP_STATE_SCHEMA` (injected at serve time) and derives its camelCase names/defaults at construction; VSCode's `AppState` class reads the bundled JSON copy the same way, and (since 2026-09-21) its TypeScript TYPE layer — `AppStateFields`, historically the one hand-written restatement in this contract — is generated too: `npm run sync-schema` regenerates `vscode-extension/src/appState.generated.ts` from the schema, and `tests/test_app_state_generated_types.py` fails the build if the tracked generated file and a fresh regeneration ever differ. Commit the regenerated file when you touch the schema.
4. **Invalidation is engine-side**, triggered by a single observable callback on the mutable store. Never have clients call a "refresh state" method manually.
5. **Test the dedup path** — write a test that verifies a no-op mutation does NOT fire the field's listeners. Without this test, regressions that spam SSE events go unnoticed until production.
6. **Bump `len(AppState.FIELDS)` sentinel test** in `tests/test_app_state.py` when adding a new field — intentional friction so every addition gets reviewed against the cross-client schema contract.

## Run-time skew (VSCode)

Build-time derivation (rule 3 above) guarantees the extension's bundled
schema matches the schema it was compiled against — it says nothing
about the SERVER it connects to at run time, since a VSIX and a
`ppxai-server` install version independently. Since 2026-09-21,
`vscode-extension/src/schemaGuard.ts` closes that gap: on every
(re)connect it fetches `GET /schema/app-state` and compares FIELDS with
the bundled schema (`chatPanel.ts::initializeBackend`, right after the
roster load).

| Server declares | Verdict | Behaviour |
|---|---|---|
| Same fields | `identical` | Silent — the normal case must produce no log line |
| Extra fields this build doesn't know | `extra-only` | Adopted for the connection (`AppState.adoptFields`) + one log line; state is stored, never rendered, because rendering code is compiled in |
| A compiled-against field missing, or retyped | `incompatible` | ONE visible `showWarningMessage`, naming the fields and both versions |
| 404 / fetch failure | `unverified` | One log line, nothing blocked — state must NOT fail closed (opposite posture from the command roster's fail-closed gate, deliberately: `AppState` is constructed before any server exists) |

`version` is not the signal — the schema's `"version"` key has read
`"1.0"` since the file was created and none of the five field-changing
commits since bumped it; the guard compares fields and reports the
version strings only as context. `tests/test_vscode_schema_guard_behavior.py`
drives the real compiled module under Node.

**Web has no equivalent run-time check.** The web page gets the schema
injected once at page load (`server/routes/static.py`); it recovers from
a server restart WITHOUT a page reload (`app.js`'s heartbeat watchdog →
`connectToServer(true)` / `_reanchorFromServer()`), but that re-anchor
only re-fetches `GET /state`, never the schema. A tab left open across a
server upgrade keeps the OLD injected schema against the NEW server: an
unknown pushed field gives a `console.warn`; a removed/renamed field is
silent. Open owner decision — see `docs/plan-adr-0007-completion-service.md`
§"Open owner decisions" item 9.

## Reading the graphify signal about this pattern (don't misdiagnose)

The community-detection graph at `graphify-out/GRAPH_REPORT.md` consistently shows AppState's host community (typically the largest one, e.g. "Engine + AppState Core") with **cohesion ≈ 0.0** and ~1,000–1,500 nodes pulled into it. This is **expected, not a smell.**

Why it shows that way: AppState is hub-and-spoke by design (one canonical engine-side store, four renderers subscribing). Louvain sees no internal subgroup boundaries inside the hub and assigns minimum cohesion. The graph is correctly describing the topology — it is *not* labelling the design as broken.

**Do not** propose to "decompose" or "refactor" this community based on the graphify reading alone. The pattern was deliberately chosen to eliminate cross-client drift (4 clients re-implementing the same state-derivation = 4 places to fix when the shape changes).

**Do** use the graph as a steady-state gauge:
- C0 size growing rapidly between rebuilds → AppState may be absorbing state that doesn't need cross-client parity. That belongs in a non-AppState observable.
- A new top-10 god node appearing inside C0 *without* a corresponding entry in `SSE_SYNC_FIELDS` (`ppxai/engine/client.py`) → cross-client state escaped the contract. Investigate.
- If C0 ever splits into multiple communities of comparable size, the hub-and-spoke contract has eroded — that *is* a design regression.

The misreading to avoid: "C0 has cohesion 0.0 → leaky abstraction → let's redesign." That was a verify-don't-assume miss caught on 2026-04-27. The graph signal is honest; the *interpretation* matters.
