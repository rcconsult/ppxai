# Pattern: Cross-Client State Through AppState

**Added:** v1.17.4
**Status:** **CRITICAL — Required for every new piece of state that more than one client needs**
**Reference:** `ppxai/engine/app_state.py`, `ppxai/engine/client.py::_refresh_context_attachments`

## Problem

State that multiple clients need to read (Rich, Textual, Web, VSCode) tends to get re-implemented per client: each scans `session.messages` on demand, each keeps its own cache, each rerenders on its own schedule. This produces four near-identical bugs, four drift points, and four places to update when the shape changes.

## Solution: AppState owns the canonical value; clients subscribe

Any piece of state that more than one client needs to render or react to must live in `AppState.FIELDS` with these invariants:

1. **Stable JSON-serializable schema** — plain dicts, not dataclasses. The field round-trips through SSE `state_sync` events to `ppxai/web/shared/app-state.js` and `vscode-extension/src/appState.ts`, which mirror the same field names in camelCase. Cross-language schema drift is a production bug.

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
3. **Mirror the field in `web/shared/app-state.js` and `vscode-extension/src/appState.ts`** when adding to Python. Use camelCase. The three implementations are copies of the same contract.
4. **Invalidation is engine-side**, triggered by a single observable callback on the mutable store. Never have clients call a "refresh state" method manually.
5. **Test the dedup path** — write a test that verifies a no-op mutation does NOT fire the field's listeners. Without this test, regressions that spam SSE events go unnoticed until production.
6. **Bump `len(AppState.FIELDS)` sentinel test** in `tests/test_app_state.py` when adding a new field — intentional friction so every addition gets reviewed against the cross-client schema contract.

## Reading the graphify signal about this pattern (don't misdiagnose)

The community-detection graph at `graphify-out/GRAPH_REPORT.md` consistently shows AppState's host community (typically the largest one, e.g. "Engine + AppState Core") with **cohesion ≈ 0.0** and ~1,000–1,500 nodes pulled into it. This is **expected, not a smell.**

Why it shows that way: AppState is hub-and-spoke by design (one canonical engine-side store, four renderers subscribing). Louvain sees no internal subgroup boundaries inside the hub and assigns minimum cohesion. The graph is correctly describing the topology — it is *not* labelling the design as broken.

**Do not** propose to "decompose" or "refactor" this community based on the graphify reading alone. The pattern was deliberately chosen to eliminate cross-client drift (4 clients re-implementing the same state-derivation = 4 places to fix when the shape changes).

**Do** use the graph as a steady-state gauge:
- C0 size growing rapidly between rebuilds → AppState may be absorbing state that doesn't need cross-client parity. That belongs in a non-AppState observable.
- A new top-10 god node appearing inside C0 *without* a corresponding entry in `SSE_SYNC_FIELDS` (`ppxai/engine/client.py`) → cross-client state escaped the contract. Investigate.
- If C0 ever splits into multiple communities of comparable size, the hub-and-spoke contract has eroded — that *is* a design regression.

The misreading to avoid: "C0 has cohesion 0.0 → leaky abstraction → let's redesign." That was a verify-don't-assume miss caught on 2026-04-27. The graph signal is honest; the *interpretation* matters.
