# A removed behavior leaves its tests behind — and they still "pass" as fences

**TL;DR:** When a change deliberately *removes* a behavior, the tests that
asserted it don't fail loudly and get fixed — they either fail forever as
assumed-environmental noise, or (worse) keep passing against a path that no
longer exists, guarding nothing.

**Verify with:** `grep -rn "agent-run-controller.js" tests/` — several
sentinels point at a file whose user-facing verb (`/agentrun`) was retired
in v1.19.1 U3; the class survives only as a base class.

## Why this trips people up

A red test after a deliberate removal looks identical to a red test from an
environment quirk. Both fail on a clean checkout, so both attract the same
dismissal: *"pre-existing, not mine."* That label is triage, not a
resolution — and on this repo it has been wrong in both directions:

- **`tests/test_web_tools_ssl.py::TestGetWeatherHTTPFallback`** asserted the
  https→plain-http retry that ADR 0009 §2 (debt Item 52) **removed on
  purpose** — the scheme downgrade made `get_weather` un-allowlistable under
  the per-run `NetworkPolicy`. Three tests demanded the vulnerability back.
- **`TestAgentRunFireAndForget`** guarded a real property (the one-off launch
  verb must not block the chat prompt) but named the retired `/agentrun`
  surface. One test failed; **two others passed while reading a stale
  path** — a fence that cannot fail is indistinguishable from a fence that
  is holding.

The second case is the dangerous one. Renaming a surface silently converts
its sentinels into no-ops, and the suite stays green.

## What's actually true

Deleting behavior is not done when the code is deleted. The test either

1. **inverts** — assert the new contract *and* add a sentinel that fails if
   the old behavior returns (e.g. `assert "http://wttr.in" not in src`, so a
   reintroduced cleartext URL is caught at the source level), or
2. **retargets** — same property, new names, with the surface history in the
   docstring so the next reader knows why the file moved, or
3. **is deleted with the behavior** — only when the property itself is gone.

Two habits make this checkable:

- **Mutation-test a fence you just wrote or moved.** Break the guarded
  property on purpose; if the test stays green, it was never a fence.
- **Read the failure, don't classify it.** `WinError 1314` (Windows symlinks
  need Developer Mode) is a legitimate `pytest.skip`; a hardcoded `/`-joined
  path compared against `str(Path(...))` is a real cross-platform test bug
  that only shows on Windows. Both look like "environmental."

Stale tests also hide *production* bugs. `test_config_error_fails_to_defaults`
was order-dependent because `get_execution_run_config()` patched only one of
its **two** config sources — the legacy `tools.web_search.oneshot_grounding`
dual-read stayed readable, so a box whose config failed to load kept native
grounding ON. The flaky test was the symptom; the incomplete fail-safe was
the bug (`ppxai/config/execution.py`, `_ConfigUnavailable`).

## Related

- [ADR 0009](../decisions/0009-task-execution-profiles.md) §2 — the
  `get_weather` https-only change (debt Item 52)
- [ADR 0011](../decisions/0011-command-taxonomy-streamline.md) — the
  `/agentrun` → `/run` rename that orphaned the sentinels
- [CLAUDE.md](../../CLAUDE.md) §"Verify, Don't Assume" — the general rule
  this lesson is a specific, expensive instance of
