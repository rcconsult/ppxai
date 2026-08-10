# Branch review: `bugfix/v1.19.1`

Reviewed 2026-08-10 against `origin/master`. This is an analysis-only review;
no production-code changes were made as part of the review.

## Scope and verification

- 215 files changed: approximately 21,708 additions and 2,737 deletions.
- The working tree was clean at review time.
- `uv lock --check` completed successfully, so the lockfile does not require a
  refresh for the current manifest.
- `git diff --check origin/master...HEAD` found one whitespace issue: an extra
  blank line at EOF in `docs/debt-inventory.md`.
- Focused test commands were initiated, but the execution environment lost the
  command handles before returning results. This report does not claim test
  success or failure.

## Status (updated 2026-08-10, after the fix)

| Finding | Status |
|---|---|
| Critical — in-process `/task` bypasses policy gates | ✅ **FIXED** |
| High — `--skill` expands read scope to arbitrary paths | ✅ **FIXED** |
| High — accepted `/task` flags silently ignored in the TUI | ✅ **FIXED** |
| High — in-process `/run` does not honour `execution.run.*` | ✅ **FIXED** |
| Medium — failed backend lifecycle wiring never retried | ⏳ open |
| Low — whitespace at EOF in debt-inventory | ⏳ open |

All four fixed findings shared one root cause and one fix: admission now lives
in `ppxai/engine/task_authorizer.py::authorize()`, which every client — both
HTTP routes, the TUI backend, SDK embedders — passes through. This is
precisely the review's own recommendation ("move request normalization and
preflight authorization into an engine-level service shared by the HTTP route
and in-process clients; leave the route responsible only for HTTP
adaptation"). `tests/test_task_authorization_parity.py` is the regression
fence, and the follow-up tests the review asked for are enumerated there.

**One boundary, not two.** `/run` was initially going to get an
`authorize_oneshot()` sibling. That was rejected as duplication: the first
attempt re-derived provider resolution and re-implemented the egress assembly
in 120 lines, and a copy of a security boundary drifts. What actually differs
between the tiers is now DATA — `TierPolicy` rows in `TIERS` — and the gates
below the grant (shell reject, operator kill-switch, provider validation,
egress assembly, ceiling) are shared unconditionally. The table is compiled
rather than operator-described on purpose: `grant_source` and
`allows_empty_grant` decide whether a request can widen its own privileges, so
a JSON typo there would be a privilege escalation no test could catch.

Three defects surfaced only because the merge forced the tiers to be compared
field by field, and none was in the review:

- **`tools.web_search.enabled=false` did not cover `/run`.** The operator
  kill-switch was a task-tier check, so a config-assembled `{web_search}`
  grant ignored an operator's explicit veto. Now checked for every tier.
- **In-process `/run` used the chat pane's provider.** ADR 0003 §9 makes a
  sub-agent's provider per-run injected intent. Offering UI context to that
  tier is now refused outright rather than silently dropped.
- **`ONESHOT_SEARCH_ITERATIONS` lived in the route layer** although it is part
  of the grant config decides. It is now `TIERS["oneshot"].iterations`, with
  `server/routes/oneshot.py` re-exporting for existing importers.

## Findings

### Critical: the in-process `/task` path bypasses task-tier policy gates

The HTTP task route is the policy boundary: it requires
`execution.task.enabled`, rejects `execute_shell_command`, enforces tool
kill-switches, validates the provider, and resolves the request into effective
task inputs before a run is created.

The Textual/Rich command path instead calls `InProcessTaskBackend.launch()`
directly. That backend builds a runner but does not perform the route's
preflight policy checks.

Consequences:

- `ppxaide` can create a tool-capable run although `execution.task.enabled` is
  false.
- A grant containing `execute_shell_command` can reach an in-process run,
  evading the explicit server-side prohibition. Shell commands can bypass the
  network policy chokepoint, which is the reason the HTTP route rejects that
  tool.
- Tool kill-switches and provider validation are bypassed or deferred until a
  run is already persisted.

The common command surface must not have a weaker policy path. Move request
normalization and preflight authorization into an engine-level service shared
by the HTTP route and in-process clients; leave the route responsible only for
HTTP adaptation.

Relevant code: `ppxai/server/routes/agent_v1.py` (`create_agent_task`) and
`ppxai/commands/task.py` (`_dispatch`).

### High: `--skill` can expand a sealed run's read scope to arbitrary paths

The shared task parser accepts any `--skill` value. The in-process command
passes those values directly as `extra_read_paths`, and the filesystem policy
adds every supplied value to its read roots.

The HTTP path instead resolves a *skill name* below the configured
`skills_dir`, validates it, and passes canonical resolved roots. The TUI path
therefore permits a command such as `--skill /arbitrary/path` to authorize
reads from that path when the in-process filesystem seal is enabled.

Do not treat command-line skill values as paths. Resolve them through the same
skill loader and name/path-traversal validation used by the API, then pass only
the resolved, approved read roots to the runner.

Relevant code: `ppxai/engine/task_grammar.py`, `ppxai/commands/task.py`, and
`ppxai/engine/tools/filesystem_policy.py`.

### High: several accepted `/task` flags are silently ignored in the TUI

The common parser accepts `--spec`, `--profile`, `--enrichment`, `--provider`,
and `--model`. The in-process dispatcher forwards none of the first three and
unconditionally takes provider/model from the current UI context.

Consequences:

- `--spec`, `--profile`, and `--enrichment` appear valid but do nothing.
- `--provider` and `--model` appear valid but are ignored.
- `--skill` does not load its `SKILL.md` or contribute its declared task
  settings; it only affects the read scope described above.

Either implement these flags through the shared normalization service or reject
them explicitly in the in-process TUI until they are supported. Silent success
is particularly misleading because help text advertises the flags.

Relevant code: `ppxai/engine/task_grammar.py` and
`ppxai/commands/task.py`.

### High: in-process `/run` does not honour `execution.run.*` — FIXED

The TUI command says its grant is determined by
`execution.run.web_search`, but it invokes the generic task runner with an
empty tool list. It does not execute the server's one-off-run logic that
applies `execution.run.web_search` and native grounding behavior.

Thus `/run` can be closed-book in the TUI when the configured server/UI
contract says it should use web search. Route `/run` through a common one-off
runner factory that resolves `execution.run` once, rather than duplicating its
launch mechanics.

Relevant code: `ppxai/commands/task.py` and
`ppxai/server/routes/agent_v1.py`.

### Medium: failed backend lifecycle wiring is never retried

`configure_task_backend()` marks the backend as `_lifecycle_wired` before it
tries to sweep orphaned runs and register the change callback. If either action
raises, the exception is logged at debug level and every later call returns
early because the backend is already marked wired.

This can leave orphaned runs unswept and the active-run badge mirror absent for
the lifetime of the process after one transient failure. Set the wired flag
only after successful setup, or track sweep and callback registration
independently and retry incomplete work.

Relevant code: `ppxai/engine/task_backend.py`.

### Low: whitespace failure

`git diff --check` reports a new blank line at EOF in
`docs/debt-inventory.md`.

## Design observations and follow-up tests

The branch's task behavior is split across the HTTP route, engine backend,
command parser, and three client implementations. The resulting duplication is
already causing policy and feature drift. A single engine-level request
normalizer/authorizer plus a single launch factory would make the server a
thin adapter and preserve parity by construction.

Add tests that exercise the same request through the API and in-process TUI
paths and assert identical outcomes for:

- `execution.task.enabled=false`;
- `execute_shell_command` and a disabled `web_search` tool;
- invalid providers and missing models;
- `--skill` traversal/absolute-path attempts under filesystem enforcement;
- `--spec`, `--profile`, `--enrichment`, `--provider`, and `--model`;
- `execution.run.web_search` and grounding behavior;
- recovery after `sweep_orphans()` or `on_change()` fails once.
