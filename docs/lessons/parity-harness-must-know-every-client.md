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

## The sharper version (2026-08-10): a STATIC harness cannot catch a policy hole

Both harnesses above read client sources and assert a code shape is present.
That is the right tool for wiring drift, and it is the wrong tool for
*authorization* drift — a file can contain a plausible-looking call and still
admit the request.

The Critical finding in `docs/archive/branch-review-v1.19.1.md` proved it. The TUI's
in-process `/task` reached the runner with **no** tier gate, **no** shell
reject, and raw `--skill` strings mounted as filesystem read roots. Both
static parity files were green. So was the whole suite — 4951 tests.

What actually catches this is **behavioral** parity: drive the SAME request
through every admission path and assert the refusals match.

```bash
# The behavioral fence, and the shape to copy for a 4th client
grep -n "REFUSAL_CASES\|def _engine_refusal" -A6 \
  tests/test_task_authorization_parity.py
```

Two properties make it work, both worth copying:

- It asserts **status AND the substring a user would act on**, so a refusal
  that happens for the wrong reason still fails.
- It asserts **no run was minted** on refusal. A gate that refuses *after*
  minting leaves an orphan run record — a different bug that a
  status-code-only assertion happily passes.

Corollary for the design, not just the test: if a second entry point can reach
a privileged operation, the fix is one shared admission boundary
(`engine/task_authorizer.py`), not a second copy of the checks. A copy is a
parity problem with a countdown on it.

## The corollary has teeth (2026-08-10, same day)

Having written that sentence, the next change proposed an
`authorize_oneshot()` "sibling" for the second tier and wrote 120 lines that
re-derived provider resolution and re-implemented the egress assembly. Same
countdown, one function later. The owner rejected it on sight:

> code re-use via parametrization is OK, code duplication is not as it spreads
> error prone code base as candidate for ommission errors and hard to debug
> run-time issues

Comparing the two tiers gate by gate showed only three of ten gates actually
differed, and two of those were "skip a step". That is a table, not a second
function:

```bash
# The differences, as data
grep -n "class TierPolicy" -A 40 ppxai/engine/task_authorizer.py
```

**What the merge found that neither copy would have.** Duplication does not
just risk future drift — it hides present bugs, because nobody diffs two
files that are supposed to be different. Forcing the tiers into one gate
order surfaced three defects immediately, none of which was in the review:
the operator kill-switch (`tools.web_search.enabled=false`) silently did not
cover the one-off tier; the in-process `/run` used the chat pane's provider
where ADR 0003 §9 requires injected intent; and a grant constant lived in the
route layer. Copying the route would have preserved all three.

## A policy field that changes no behaviour is worse than no field

`TierPolicy.honors_client_fallback` was gated at the merge call — and a
mutation proved the whole suite passed with it removed, because the
config-granted branch never read those parameters anyway. It read like
enforcement and enforced nothing.

The fix was to make it load-bearing: offering UI context to a tier that must
not take one is now a **refusal**, not a silent drop.

```bash
# Every table field must be reachable by a mutation that fails a test
grep -n "honors_client_fallback" ppxai/engine/task_authorizer.py
grep -n "injected intent" tests/test_task_authorization_parity.py
```

Mutation-test the *table*, not only the gates. A descriptive-looking config
row that no test can kill is documentation pretending to be a control.

## The structural assertion that ends the whole class

The bypass existed because `AuthorizedTask` could be built by hand — the type
existed without the checks that give it meaning. One test now pins that:

```bash
grep -n "only_one_construction_site" -A 20 \
  tests/test_task_authorization_parity.py
```

Production code may construct the authorized-result type in exactly **one**
place: the `return` inside `authorize()`. Reintroducing the original bug shape
(verified by mutation) fails that test. When a type means "these gates
passed", make it un-forgeable and assert the count — it is cheaper than
auditing every future call site.
