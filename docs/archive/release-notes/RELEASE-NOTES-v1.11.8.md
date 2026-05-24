# Release Notes: v1.11.8

**Release Date:** 2025-12-27

## Summary

This release introduces **Agent Mode** - a new autonomous task execution mode for the VSCode extension that enables multi-step tool usage with a single toggle. It also includes important fixes for GitHub release handling and documentation link maintenance.

## Major Changes

### Agent Mode (VSCode Extension)

- **NEW:** Agent toggle button in VSCode extension header
- **NEW:** `/agent/enable`, `/agent/disable`, `/agent/status` API endpoints
- **NEW:** Agent mode automatically enables tools when activated
- **NEW:** Visual indicator showing agent status in extension UI

Agent mode allows the AI to autonomously execute multi-step tasks using available tools (file operations, shell commands, web search) without requiring manual tool enabling.

## New Features

- **Agent Mode API:**
  - `GET /agent/status` - Check if agent mode is enabled
  - `POST /agent/enable` - Enable agent mode (auto-enables tools)
  - `POST /agent/disable` - Disable agent mode

- **VSCode Extension:**
  - Agent toggle button with on/off state
  - Real-time agent status display
  - Integrated with existing tools infrastructure

## Bug Fixes

- **FIX:** GitHub releases now correctly marked as "Latest"
  - Added `make_latest: true` to CI workflow
  - Release script now uses `--latest` flag when publishing notes
- **FIX:** 12 broken documentation links corrected
  - `custom-tools-guide.md` -> `custom-tool-development-guide.md`
  - Archived docs now properly reference `docs/archive/` paths

## Documentation Updates

- **NEW:** [docs/agent-mode-guide.md](agent-mode-guide.md) - Comprehensive agent mode documentation
- **NEW:** Agent flow diagrams (current-non-agentic-flow.png, future-agentic-flow.png)
- **FIXED:** All broken internal documentation links

## Testing

- 337 tests passing
- Agent mode API endpoints verified
- VSCode extension agent toggle tested

## Upgrade Notes

This is a drop-in replacement for v1.11.7. No configuration changes required.

To use Agent Mode in VSCode:
1. Restart ppxai-server to get new endpoints
2. Reload VSCode window
3. Click the "Agent" toggle button in the chat panel header

## Links

- **GitHub Release:** https://github.com/rcconsult/ppxai/releases/tag/v1.11.8
- **Full Changelog:** [CHANGELOG.md](../CHANGELOG.md)
- **Agent Mode Guide:** [agent-mode-guide.md](agent-mode-guide.md)
