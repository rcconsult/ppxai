# TUI Debug Logging Guide

**Version**: v1.11.1+
**Date**: 2025-12-22
**Feature**: Debug logging for TUI troubleshooting

---

## Overview

The TUI now has a comprehensive debug logging system that logs all message flow, API requests, tool executions, and errors to a file with timestamps. This mirrors the logging capabilities available in the VSCode extension (extension logs + server logs).

## Quick Start

### Enable Logging

```bash
# Option 1: Use command in TUI
/debug-log on

# Option 2: Set environment variable
export PPXAI_DEBUG=1
ppxai
```

### View Logs

```bash
# Show recent entries (last 50 lines)
/debug-log show

# Or view the file directly
tail -f ~/.ppxai/logs/tui-debug.log
```

### Disable Logging

```bash
/debug-log off
```

---

## Commands

### `/debug-log` - Main Command

```bash
/debug-log              # Show status
/debug-log on           # Enable logging
/debug-log off          # Disable logging
/debug-log show         # View recent log entries (last 50 lines)
/debug-log clear        # Clear the log file
```

**Aliases**:
- `on`: `enable`, `1`, `true`, `yes`
- `off`: `disable`, `0`, `false`, `no`
- `show`: `view`, `cat`
- `clear`: `clean`, `reset`

---

## What Gets Logged

### 1. Session Events

```
18:42:15.234 | INFO     | ================================================================================
18:42:15.234 | INFO     | TUI DEBUG SESSION STARTED - 2025-12-22 18:42:15
18:42:15.234 | INFO     | ================================================================================
```

### 2. User Input

```
18:42:20.123 | INFO     | USER INPUT: review the roadmap items
18:42:25.456 | INFO     | COMMAND: /tools enable
```

### 3. Conversation History Sync

```
18:42:25.460 | INFO     | HISTORY SYNC: legacy=2, engine=2
18:42:25.461 | DEBUG    |   [0] user      : review the roadmap items
18:42:25.461 | DEBUG    |   [1] assistant : Here is the roadmap review...
```

### 4. API Requests

```
18:42:30.789 | INFO     | API REQUEST: iteration=1, messages=4
18:42:30.790 | DEBUG    |   [0] system    : You are a helpful AI assistant with access to tools...
18:42:30.791 | DEBUG    |   [1] user      : review the roadmap items
18:42:30.792 | DEBUG    |   [2] assistant : Here is the roadmap review...
18:42:30.793 | DEBUG    |   [3] user      : use tools to review the current project
```

### 5. API Responses

```
18:42:32.456 | INFO     | ASSISTANT RESPONSE: I'll use the read_file tool to review the project files...
```

### 6. Tool Execution

```
18:42:32.500 | INFO     | TOOL CALL: read_file
18:42:32.501 | DEBUG    |   Arguments: {'path': 'ROADMAP.md'}
18:42:32.650 | INFO     | TOOL RESULT: read_file
18:42:32.651 | DEBUG    |   Result: # ROADMAP\n\n## Current Release: v1.11.0...
```

### 7. Errors

```
18:42:35.123 | ERROR    | API ERROR 400: After the (optional) system message(s), user or tool message(s) should alternate with assistant message(s).
```

---

## Use Cases

### 1. Debugging 400 Errors

When you get a 400 error about message alternation:

```bash
# Enable logging
/debug-log on

# Reproduce the error
review the roadmap items
/tools enable
use tools to review the project

# View the log
/debug-log show
```

The log will show:
- Exact conversation history when tools were enabled
- Message sequence sent to API
- Which message caused the alternation error

### 2. Debugging Tool Execution

When tools don't behave as expected:

```bash
/debug-log on
/tools set verbose on

# Use tools
list files in current directory
```

The log will show:
- Which tool was called
- Exact arguments passed
- Tool execution result or error

### 3. Performance Analysis

To see how long operations take:

```bash
tail -f ~/.ppxai/logs/tui-debug.log
```

Timestamps show when each operation starts, allowing you to measure:
- API request latency
- Tool execution time
- Total conversation turn time

### 4. Comparing TUI vs VSCode Behavior

To debug behavioral differences:

1. Enable TUI logging: `/debug-log on`
2. Run operation in TUI
3. Compare TUI log (`~/.ppxai/logs/tui-debug.log`) with VSCode server logs

---

## Log File Location

```
~/.ppxai/logs/tui-debug.log
```

The log file:
- Appends to existing content (not overwritten)
- Uses consistent timestamp format (HH:MM:SS.mmm)
- Includes log levels (INFO, DEBUG, WARNING, ERROR)
- Survives session restarts (helpful for debugging crashes)

---

## Log Format

```
<timestamp> | <level> | <message>

18:42:30.789 | INFO     | API REQUEST: iteration=1, messages=4
18:42:30.790 | DEBUG    |   [0] system    : You are a helpful AI assistant...
```

- **Timestamp**: `HH:MM:SS.mmm` (24-hour format with milliseconds)
- **Level**: `INFO`, `DEBUG`, `WARNING`, `ERROR` (8 chars padded)
- **Message**: Log entry (truncated for readability in logs, full content in DEBUG entries)

---

## Environment Variable

Instead of using `/debug-log on` every time, set the environment variable:

```bash
# Bash/Zsh
export PPXAI_DEBUG=1
ppxai

# Fish
set -x PPXAI_DEBUG 1
ppxai

# Add to shell RC file for permanent effect
echo 'export PPXAI_DEBUG=1' >> ~/.bashrc
```

Valid values: `1`, `true`, `yes`, `on` (case-insensitive)

---

## Performance Impact

- **Negligible**: Logging is asynchronous and buffered
- **File I/O**: Logs are written to disk, but this happens in the background
- **Disk Space**: Log file grows over time; use `/debug-log clear` to reset

---

## Best Practices

### 1. Enable Only When Debugging

Don't leave logging enabled permanently unless you need it:

```bash
# Debugging session
/debug-log on
[reproduce issue]
/debug-log show
/debug-log off
```

### 2. Clear Old Logs Periodically

```bash
/debug-log clear
```

### 3. Use With Verbose Mode

For maximum debugging information:

```bash
/debug-log on
/tools set verbose on
```

### 4. Share Logs When Reporting Issues

When reporting bugs:

1. Enable logging
2. Reproduce the issue
3. Save the log: `cp ~/.ppxai/logs/tui-debug.log issue-reproduction.log`
4. Attach to GitHub issue (redact any sensitive information first!)

---

## Comparison with VSCode Extension

| Feature | TUI | VSCode Extension |
|---------|-----|------------------|
| **Enable Logging** | `/debug-log on` or `PPXAI_DEBUG=1` | DevTools Console + Server logs |
| **Log Location** | `~/.ppxai/logs/tui-debug.log` | VSCode Output panel + server stdout |
| **View Logs** | `/debug-log show` or `tail -f` | Output panel: "ppxai" + "ppxai server" |
| **Message Flow** | ✅ Logged | ✅ Logged |
| **API Requests** | ✅ Logged | ✅ Logged |
| **Tool Execution** | ✅ Logged | ✅ Logged |
| **Timestamps** | ✅ Millisecond precision | ✅ Millisecond precision |

---

## Troubleshooting

### "No log file found"

The log file is created when logging is first enabled:

```bash
/debug-log on
```

### "Permission denied"

Ensure `~/.ppxai/logs/` directory is writable:

```bash
mkdir -p ~/.ppxai/logs
chmod 755 ~/.ppxai/logs
```

### Log file too large

Clear it:

```bash
/debug-log clear
```

Or manually:

```bash
rm ~/.ppxai/logs/tui-debug.log
```

---

## Implementation Details

### Architecture

1. **Singleton Logger** (`ppxai/tui_logger.py`):
   - Global instance accessed via `get_logger()`
   - No-op logger when disabled (zero overhead)
   - File handler with custom formatting

2. **Integration Points**:
   - `main.py`: User input, commands, events
   - `commands.py`: History sync, command execution
   - `engine/client.py`: API requests

3. **Lazy Initialization**:
   - Logger is created only when needed
   - Environment variable checked on first import
   - Can be enabled/disabled at runtime

### Code Example

```python
from ppxai.tui_logger import get_logger

logger = get_logger()
logger.log_user_message("Hello, AI!")
logger.log_api_request(iteration=1, messages=[...])
logger.log_tool_call("read_file", {"path": "README.md"})
```

---

## Future Enhancements

Potential improvements:

- [ ] Log rotation (keep last N MB)
- [ ] Multiple log levels (`--debug-level DEBUG|INFO|WARNING`)
- [ ] JSON format option for machine parsing
- [ ] Log viewer TUI (like `htop` for logs)
- [ ] Integration with VSCode extension logs (unified view)

---

## Related Documentation

- [TUI_VSCODE_CONSISTENCY_ANALYSIS.md](TUI_VSCODE_CONSISTENCY_ANALYSIS.md) - Behavioral consistency analysis
- [FILE_EDITING_GUIDE.md](FILE_EDITING_GUIDE.md) - Tool execution and consent system
- [architecture-refactoring.md](architecture-refactoring.md) - Engine layer architecture

---

**Last Updated**: 2025-12-22
**Author**: Claude Code
**Version**: v1.11.1+
