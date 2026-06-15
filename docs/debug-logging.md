# Debug Logging

ppxai writes detailed runtime logs (message flow, API requests/responses,
tool invocations, session-recovery decisions) to files under
`~/.ppxai/logs/` when debug logging is **enabled**.

| Log file | Emitted by |
|----------|-----------|
| `tui-debug.log` | Rich TUI (`ppxai`) and Textual TUI (`ppxaide`) |
| `server-debug.log` | `ppxai-server` + `ppxai-desktop` |
| `chat-debug.log`, `validator-debug.log` | Engine components |

## Default: OFF

A fresh install has debug logging **disabled**. The verbose payloads
(full API request bodies, tool outputs) aren't what a new user wants in
their home directory by default. Turn it on deliberately.

## Turning it on / off

| Client | Command |
|--------|---------|
| Rich TUI (`ppxai`) | `/debug-log on` &nbsp;·&nbsp; `/debug-log off` &nbsp;·&nbsp; `/debug-log show` |
| Textual TUI (`ppxaide`) | `/debug-log on` &nbsp;·&nbsp; `/debug-log off` |
| Web / VSCode | `POST /config/debug-log` with `{"enabled": true|false}` |
| Any client | `PPXAI_DEBUG=1` env var (per-process, not persisted) |

The command writes `tui.debug_log: true|false` to
`~/.ppxai/ppxai-config.json` and flips the active logger immediately.

## Persistence

The `tui.debug_log` flag is **global and persistent** — not per-session.

- Set once with `/debug-log on`, and every subsequent ppxai startup
  (Rich, Textual, web server, benchmarks) has logging enabled from
  the very first line of execution.
- Restored inside `config.initialize()`, which every client calls
  first — so the logger is writing **before** the session-recovery
  prompt, provider selection, or any other interactive step.
- Turning debug off (`/debug-log off`) persists the same way.
- `PPXAI_DEBUG=1` is a per-process override that does **not** write
  to config. Useful for one-off runs.

### Why persistence matters

Several classes of early-startup bug — silent session-recovery
regressions, provider-selection Ctrl+C paths, config-load failures —
happen **before** the user has a chance to type `/debug-log on`. If
logging were transient, these regressions would leave no trace.

Because the flag survives restarts, the workflow for reproducing an
early-startup bug is:

1. `/debug-log on` (in any working session)
2. Quit ppxai.
3. Reproduce the bug on next launch.
4. `~/.ppxai/logs/tui-debug.log` contains the full decision path.

The regression pattern this catches: debug-log state is restored inside
`config.initialize()`, so logging is active **before** any client code
runs — critical for diagnosing early-startup regressions like silent
session-recovery failures (where recovery must run before
provider/model selection). See the "Debug Logging" section of
[CLAUDE.md](../CLAUDE.md) for the ordering invariant.

## Disabling it cleanly

```bash
# From inside ppxai
/debug-log off

# Or edit the config directly
# ~/.ppxai/ppxai-config.json → "tui": { "debug_log": false }
```

Log files are **not** auto-pruned. Delete them manually if they grow
large: `rm ~/.ppxai/logs/*.log`.

## Implementation notes (for contributors)

- **Flag lives in config**, not in `AppState` or session state, because
  it's a cross-session preference (like `tui.theme`), not per-session
  state.
- **Restored in `ppxai/config/__init__.py::initialize()`** via a lazy
  import of `common.logger.Logger.enable_all()`. Lazy to avoid a
  circular dep with the logger module.
- **Every client calls `initialize()` first** — Rich
  (`ppxai/rich/main.py`), Textual (`ppxai/tui/__init__.py`), server
  (`ppxai/server/http.py`), benchmark runner
  (`benchmarks/llm-eval/engine_runner.py`). Adding a new entry point?
  Call `initialize()` before anything else.
- **Writes go through `set_tui_config("debug_log", bool)`** which uses
  `ensure_ascii=False` + trailing newline so em-dashes and other
  non-ASCII content in `ppxai-config.json` aren't mangled on save.
