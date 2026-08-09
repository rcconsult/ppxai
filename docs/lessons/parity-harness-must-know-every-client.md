# A parity harness that knows N-1 clients is a blind spot, not a safety net

**TL;DR:** `tests/test_vscode_task_controller.py` pins web ↔ VSCode: the same
`/v1/agent/*` endpoints, the same collect semantics, the same refusal hints.
It is a good harness and it has caught real drift. T8b added a **third**
client (the TUIs) and did not join it — so three capabilities the other two
clients have shipped missing, and **no test failed**. Adding a client means
joining the parity harness *first*, before the client works.

**Verify with:**
```bash
# The two-client harness, and what it already pins
grep -n "_ENDPOINTS\|test_collect_semantics_parity" -A12 \
  tests/test_vscode_task_controller.py

# The third column, added after the fact
grep -n "class Test" tests/test_client_parity_tui.py
```

## What it cost (2026-08-09/10)

Three defects, all the same shape — a primitive reused without the
integration the server wraps around it:

| Missing in the TUI | The other clients | Symptom |
|---|---|---|
| U4 merge on `collect` | `agent-run-controller.js:121`, `taskController.ts:596` | runs never entered the conversation → every TUI session was message-less → **"session restore is broken"** |
| registry `on_change` | `server/state.py:215` | `AppState.background_agents` never written, though `tui/app.py:254` already subscribes and renders a badge |
| `sweep_orphans()` | `server/state.py:209` | a run orphaned by a TUI exit stays `running`; `ls` lies after a restart |

Every one was found by a human trialling the app. None was found by the suite.

`test_collect_semantics_parity` **already asserted** the merge endpoint, the
config fetch, the "Collect is disabled" hint and the auto-merge hook — for the
two clients it knew about. The test that would have caught this on the day the
code was written existed; it just had a two-client blind spot.

## The trap inside the trap

The reported symptom was *"session restore does not work"*, and there is a
plausible-looking culprit: `session_restore_ops.py:70` skips sessions with
`message_count == 0`, which the server's restore path does not do. Removing
that gate looks like a parity fix.

It would have been wrong. The gate was **correctly** skipping sessions that
really were empty — empty because the merge was missing. "Fixing" the gate
would have made restore appear to work while the runs stayed absent from the
conversation.

A symptom that points at a real asymmetry can still be pointing at the wrong
one. Follow it to the thing that *produces* the state, not the thing that
*reads* it.

## The rule

- **Adding a client to a multi-client surface is a change to the parity
  harness first, and to the client second.** If the harness cannot fail for
  the new client, it is not covering it.
- Prefer sentinels that **scan** over sentinels that **enumerate**: the
  composition-root check in `test_client_parity_tui.py` finds callers of
  `default_run_registry()` rather than naming modules, so a fourth client is
  told what it is missing instead of discovering it in a trial.
- Guard against vacuity. Each sentinel there asserts it parsed a non-empty
  set, and one asserts the TUI still subscribes to `background_agents` — if
  that stops being true, delete the class rather than let it pass silently.
