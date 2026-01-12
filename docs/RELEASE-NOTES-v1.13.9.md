# Release Notes - v1.13.9

**Release Date:** 2026-01-12

This release focuses on session persistence, crash recovery, and critical fixes for Windows and reasoning model support.

## Highlights

### Session Persistence & Auto-Recovery

Your chat sessions are now automatically saved and can be restored:

**Auto-Save**
- Sessions are saved after each chat exchange
- Command history is preserved per session
- Working directory (`cd` command) is remembered

**Crash Recovery**
- If ppxai crashes or is force-quit, the session is marked as "dirty"
- On next startup, dirty sessions are automatically recovered
- No more lost conversations due to crashes!

**Startup Restore**
- Choose how sessions are restored on startup:
  - `"always"` - Automatically restore last session
  - `"prompt"` - Ask whether to restore (default)
  - `"never"` - Always start fresh

**Configuration**
```json
{
  "session": {
    "auto_restore": "prompt",
    "auto_save_interval": 1
  }
}
```

### Windows & Reasoning Model Fixes

Critical fixes for Windows users and reasoning models like DeepSeek R1:

- **Tool parameter aliasing** - Models use different parameter names (`filepath` vs `file_path`). Now handled transparently.
- **Empty responses after tool calls** - Fixed issue where reasoning models would execute tools but return empty responses
- **Reasoning content support** - Handle models that return content in `reasoning_content` field
- **Context overflow prevention** - Friendly error when `@file` injections exceed 128K context limit

## New Features

### Session State File
- Location: `~/.ppxai/session-state.json`
- Tracks: session name, provider, model, message count, dirty state
- Updated on each save, cleared on graceful exit

### Command History Persistence
- User input history saved with each session
- Arrow keys navigate through session-specific history
- History restored when session is reloaded

### Working Directory Persistence
- `cd` command changes are saved with the session
- Restored automatically on session reload
- `@file` autocomplete uses the persisted working directory

## Bug Fixes

### TUI Fixes
- **@file autocomplete after cd** - Now correctly shows files from the new directory
- **/show command after cd** - Uses engine working directory, not process cwd
- **Desktop app data viewers** - CSS/JS files now properly bundled

### Model Compatibility
- **Tool parameter normalization** - Comprehensive alias mapping for all tool parameters
- **Reasoning models** - Support for models returning `reasoning_content`
- **Empty response handling** - Prompt model for summary if response is empty after tools

### Context Management
- **Token estimation** - Prevent context overflow errors from vLLM
- **Friendly errors** - Clear message when `@file` content exceeds limits

## Files Changed

### Core Files
- `ppxai/engine/session.py` - Session state file management, command history, working dir persistence
- `ppxai/config.py` - Session configuration options (`auto_restore`, `auto_save_interval`)
- `ppxai/main.py` - Startup recovery flow, auto-save after roundtrips, graceful exit handling
- `ppxai/commands.py` - Mark session clean on `/quit`

### Provider Files
- `ppxai/engine/providers/openai_compat.py` - Context overflow prevention, empty response handling

### Tool Files
- `ppxai/engine/tools/manager.py` - Parameter aliasing/normalization

## Upgrade Instructions

1. **Download new binaries** from GitHub Releases
2. **Replace existing binaries**:
   - Linux: `~/.local/bin/ppxai`, `~/.local/bin/ppxai-server`
   - Windows: Update executables in your install location
3. **Optional**: Add session config to `ppxai-config.json`:
   ```json
   {
     "session": {
       "auto_restore": "prompt"
     }
   }
   ```

## Testing

- 664 tests passing
- 27 new tests for session persistence
- Integration tests with reasoning models

## Known Issues

- Session restore may show stale provider if API key changed between sessions
- Very large command histories (>1000 entries) may slow startup slightly

## What's Next (v1.14.x)

- Agent mode with multi-step reasoning
- Enhanced MCP server support
- Conversation branching
