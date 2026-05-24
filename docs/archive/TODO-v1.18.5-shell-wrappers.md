# TODO: v1.18.5 — Shell wrapper framework

**Status:** Implementation in progress (framework + rtk-as-config landed 2026-05-10)
**Target:** v1.18.5 point release
**Branch:** `feature/v1.18.5`

## Story

The original v1.18.5 ROADMAP entry was "optional rtk wrapping in
`execute_shell_command`" — a single rtk-specific implementation. The
plan went through three iterations during 2026-05-10:

1. **First implementation** — rtk-specific module
   `ppxai/engine/tools/rtk_integration.py` with hardcoded behavior. Worked
   end-to-end (smoke-tested against Gemini 3 Flash Preview); shipped the
   `git status` DANGEROUS-classification issue as a regression we
   surfaced via dogfooding.

2. **Generalize: factory pattern** — refactor into a wrapper framework so
   adding wrappers (`time`, `nice`, perf profilers) doesn't require
   ppxai code changes. rtk becomes a built-in subclass.

3. **Demote rtk further: just a JSON config entry** — no privileged
   classes; rtk's defaults ship in a Python constant
   (`DEFAULT_SHELL_WRAPPERS`) that's identical in shape to anything a
   user can add. Factory dispatches purely on `type` (`probe` /
   `always`); no Python is ever required for a wrapper that fits one
   of the two generic patterns.

This doc reflects the final shape (3).

## Architecture

```
ppxai/engine/tools/wrappers/
├── __init__.py        # public API
├── base.py            # Wrapper ABC, ProbeWrapper, AlwaysWrapper
├── factory.py         # make_wrapper(entry: dict) -> Wrapper
├── registry.py        # WrapperRegistry, get_registry(), set_registry()
└── RTK.md             # rtk's prompt-block content (loaded via importlib.resources)
```

**Two generic concrete classes** cover every realistic wrapper:

- `ProbeWrapper` — has its own dry-run command (e.g., `rtk hook check`).
  Subprocess call, parse stdout/exit, return rewritten or None.
- `AlwaysWrapper` — no dry-run; user opted in, wrap every command.
  Suitable for `time`, `nice`, sandboxers.

If a wrapper genuinely needs custom Python (rare — example: an IPC
protocol that's not stdout-based), drop a `Wrapper` subclass in the
package and register a new `type` value in `factory._TYPE_REGISTRY`.

**Three integration points** in the rest of ppxai:

| Site | Helper | Purpose |
|---|---|---|
| `engine/tools/builtin/shell.py` | `registry.find_first_rewrite(cmd)` | Pre-spawn rewrite chain (first match wins) |
| `engine/tools/manager.py::get_tools_prompt` | `registry.compose_prompt_blocks()` | Inject per-wrapper prompt-hint blocks |
| `common/consent.py::classify_shell_command` | `registry.strip_transparent_prefixes(cmd)` | Strip transparent wrapper prefixes before safety classification |

Plus thread-safe lazy init (`threading.Lock` around the registry
singleton + each wrapper's PATH-resolution cache) so future sub-agent
worker threads don't race.

## rtk as the first concrete wrapper

Ships in `DEFAULT_SHELL_WRAPPERS` (in `ppxai/config/defaults.py`):

```python
{
    "name": "rtk",
    "type": "probe",
    "binary": "rtk",
    "probe_args": ["hook", "check"],
    "no_rewrite_marker": "No rewrite for:",
    "transparent_for_safety": True,
    "prompt_block_path": "RTK.md",
    "enabled": "auto",
    "failure_markers": [],          # Phase 4 follow-up
    "retry_raw_on_failure": False,  # Phase 4 follow-up
}
```

Identical schema to anything a user adds. No Python class for rtk.
Future rtk-specific quirks (e.g., the deferred Phase 4 graceful
fallback) become **config fields** the framework consumes generically:
adding `failure_markers: ["rtk: error:", "rtk panicked"]` and
`retry_raw_on_failure: true` is the entire rtk-side opt-in.

## What landed in this commit

| File | Status | LoC |
|---|---|---|
| `ppxai/engine/tools/wrappers/{__init__,base,factory,registry}.py` | NEW | ~220 |
| `ppxai/engine/tools/wrappers/RTK.md` | NEW | ~22 |
| `ppxai/config/defaults.py` | extended (`DEFAULT_SHELL_WRAPPERS` + git/gh allowed-list) | +35 |
| `ppxai/config/tools.py` | new `wrappers` field + back-compat shim from `use_rtk` | +50 |
| `ppxai/engine/tools/builtin/shell.py` | wire to `find_first_rewrite()` | +18 |
| `ppxai/engine/tools/manager.py` | wire to `compose_prompt_blocks()` | +12 |
| `ppxai/common/consent.py` | wire to `strip_transparent_prefixes()` | +20 |
| `tests/test_wrapper_framework.py` | NEW (49 cases) | ~430 |
| `tests/test_consent_classification.py` | NEW (70 cases — git/gh verbs + transparent strip) | ~165 |
| `docs/shell-wrappers.md` | NEW (replaces RTK-INTEGRATION.md) | ~190 |
| this file | NEW (replaces `TODO-v1.18.5-rtk-integration.md`) | — |
| `ROADMAP.md` v1.18.5 entry | rewrite | — |
| `CLAUDE.md` | one-paragraph pointer update | — |
| `CHANGELOG.md [1.18.5]` | new | — |
| `AGENTS.md` | one short pointer section | — |

Net: ~+700 LoC including tests + docs. Single commit on a clean
`feature/v1.18.5` (the previous `5b900dbe` rtk-only implementation was
reset and replaced).

## Settled decisions (final)

- **Hybrid approach** (engine-side rewrite + system-prompt hint), not
  either alone.
- **Default `enabled: auto`** for rtk — wrap silently when rtk is on
  PATH; users who installed rtk likely want the savings.
- **Zero list maintenance** — `rtk hook check` (and any future probe
  wrapper's dry-run) is the source of truth for what's safely wrappable
  on the current platform.
- **Factory + JSON config**, not built-in Python classes per wrapper.
  Adding a wrapper that fits `probe` or `always` is config-only.
- **Thread-safe lazy init** via `threading.Lock` on both the registry
  singleton and each wrapper's PATH-resolution cache.
- **Back-compat shim** for `use_rtk` / `use_rtk_prompt_hint` config
  fields — translated internally into a wrappers entry. Plan to retire
  in v1.20.x.

## Phase 4 — graceful fallback (deferred)

The framework has the hooks (`failure_markers`, `retry_raw_on_failure`,
`Wrapper.is_wrapper_side_failure()`, `find_active_wrapper_by_prefix()`),
but the actual fallback wiring in `shell.py` (detect, retry once raw,
log) is deferred until there's evidence of rtk-side failures in real
use. Adding it later is a localized edit (~15 LoC + 6 tests) plus
populating `failure_markers` on the rtk default.

## Acceptance criteria

1. ✅ `WrapperRegistry.find_first_rewrite()` returns rtk's rewrite when rtk is on PATH and the rtk default isn't disabled.
2. ✅ Without rtk on PATH, behavior is byte-identical to v1.18.4 (no errors, no warnings, no prompt-block injection).
3. ✅ `enabled: never` for rtk → engine spawns raw, no prompt block.
4. ✅ `enabled: always` errors clearly when binary is missing.
5. ✅ User-declared wrapper with `type: probe` and a non-default name registers and runs end-to-end (covered by factory tests).
6. ✅ Safety classifier strips transparent wrapper prefixes via the registry; `rtk git status` classifies same as `git status`.
7. ✅ v1.18.4 sentinel suites green: `test_cwd_grounding` 13/13, `test_command_result_serialization` 87/87.
8. ✅ Existing `test_shell_tool` 32/32, `test_common_consent` 9/9 green.
9. ✅ New `test_wrapper_framework` 49/49 + `test_consent_classification` 70/70 green.
10. ✅ Read-only git verbs (`git status`, `git log`, etc.) classify as SAFE without consent prompt; mutating verbs (`git commit`, etc.) stay DANGEROUS.

## Cross-references

- [shell-wrappers.md](shell-wrappers.md) — user-facing documentation
- [ROADMAP.md](../ROADMAP.md) §"v1.18.5 - Shell wrapper framework — rtk as first wrapper"
- [reference_rtk_install.md](../../.claude/projects/-Users-rado-git-utils-ppxai/memory/reference_rtk_install.md) — host install state on rado's machine
- rtk upstream: https://github.com/rtk-ai/rtk
