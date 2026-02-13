# Release Notes: v1.11.9

**Release Date:** 2025-12-27

## Summary

Critical safety fixes for Agent Mode. The `/agent on|off` commands now correctly toggle agent mode instead of being misinterpreted as tasks. Added configurable agent settings and enhanced shell command safety.

## Critical Fix

- **`/agent on|off` now correctly toggles agent mode** instead of being interpreted as tasks
  - Previously, typing `/agent off` would cause AI to search for things to turn "off" (including killing server processes!)
  - Now properly recognized as toggle commands in both TUI and VSCode extension

## Security Improvements

- **Minimum word count validation** (default: 3 words) rejects vague single-word tasks
- **`kill`, `pkill`, `killall` added to built-in dangerous shell patterns**
- Built-in defaults ensure safety even without config file

## New Features

- **Configurable agent settings** via `ppxai-config.json`:
  - `tools.agent.max_iterations` (default: 10) - Maximum agent loop iterations
  - `tools.agent.context_char_limit` (default: 2000) - Character limit for context display
  - `tools.agent.min_task_words` (default: 3) - Minimum words required for agent tasks
- **`/agent/config` API endpoint** for retrieving agent configuration
- **Full `/tools` command parity** between TUI and VSCode extension
  - Added `/tools agent`, `/tools set verbose on|off`, `/tools help <tool>` to extension

## Documentation

- Updated [Agent Mode Guide](docs/AGENT_MODE_GUIDE.md) with configuration section explaining:
  - Why each setting exists
  - Safe value ranges
  - Warnings about extreme configurations

## Testing

- 337 tests passing

## Upgrade Notes

This is a drop-in replacement for v1.11.8. No configuration changes required.

New optional configuration in `ppxai-config.json`:
```json
{
  "tools": {
    "agent": {
      "max_iterations": 10,
      "context_char_limit": 2000,
      "min_task_words": 3
    }
  }
}
```

## Links

- **GitHub Release:** https://github.com/rcconsult/ppxai/releases/tag/v1.11.9
- **Full Changelog:** https://github.com/rcconsult/ppxai/compare/v1.11.8...v1.11.9
