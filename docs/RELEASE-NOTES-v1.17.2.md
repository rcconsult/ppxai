# Release Notes — v1.17.2

**Release date:** 2026-03-27
**Type:** Bugfix + architecture alignment
**Focus:** AppState consistency across all 5 clients, thread-safety, iTerm2 image rendering

## Highlights

### AppState Aligned Across All Clients

All 5 clients (Rich TUI, Textual TUI, Web app, VSCode extension, HTTP server)
now read and write state exclusively through AppState. No more direct
`engine.provider_name` or `engine.tools_enabled` field access — everything goes
through `state.get()` / `state.set()` / `state.snapshot()`.

All 17 AppState fields are now wired:
- Session usage (tokens, cost, context%) synced via `session.on_usage_updated` callback
- Session name synced via `on_name_changed` callback
- Debug log toggle synced in Textual TUI

### SSE State Sync

Engine pushes `STATE_SYNC` events via SSE side-channel when key fields change
during streaming. Connected web and VSCode clients update their local AppState
automatically — fixes desync when state changes mid-stream or from another client.

Synced fields: provider, model, tools_enabled, tools_verbose, agent_mode,
auto_route, working_dir, session_name, debug_log.

### Thread-Safety Hardened

- AppState dispatches listeners OUTSIDE the lock (was inside RLock)
- Event queue protected by `threading.Lock` with `enqueue_event()`/`drain_events()` API
- Fixes race condition between SSE drain loop and AppState observer callbacks

### iTerm2 Image Rendering Fixed

ppxaide was incorrectly using Kitty Graphics Protocol (TGP) for iTerm2 terminals.
Now uses native iTerm2 inline image protocol (OSC 1337). Also works without
Pillow — image dimensions read from PNG/JPEG/GIF file headers via `struct`.

## Bug Fixes

- **ppxaide file tree** not syncing with AppState when working directory changed
- **Preview --serve** failing with venv projects (now auto-detects `venv/bin/python`)
- **Preview command parsing** not accepting single-quoted commands
- **Event router** — strategy dispatch dicts replace if/elif chains in EventHandler
- **16 unused imports** removed across engine and TUI modules

## Upgrade

Drop-in replacement for v1.17.1. No config changes needed.

```bash
# Binary: download from releases page
# pip: pip install --upgrade ppxai
# VSCode: install ppxai-1.17.2.vsix
```
