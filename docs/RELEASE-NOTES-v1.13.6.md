# ppxai v1.13.6 Release Notes

**Release Date**: January 8, 2026

## TUI Status Bar Enhancements

This release enhances the TUI status bar with additional contextual information and improves shell command handling configurability.

### New Status Bar Badges

The TUI status bar now displays three new badges:

| Badge | Description | Example |
|-------|-------------|---------|
| **Version** | Current ppxai version | `v1.13.6` |
| **CWD** | Current working directory (basename) | `ppxai` |
| **DateTime** | Current date and time | `2026-01-08 14:30` |

These badges appear alongside existing provider, model, and tools status indicators.

## Configurable Shell Interactive Commands

Shell tool now reads interactive command lists from JSON config, allowing customization without code changes.

### New Configuration Options

In `ppxai-config.json` under `tools.shell`:

```json
{
  "tools": {
    "shell": {
      "interactive_commands": ["nano", "vim", "vi", "emacs", "less", "more", "top", "htop", "python", "python3", "node", "ssh", "telnet", "ftp", "sftp", "mysql", "psql", "bash", "zsh", "sh"],
      "non_interactive_with_args": ["python", "python3", "node", "bash", "zsh", "sh", "ssh", "mysql", "psql"]
    }
  }
}
```

### How It Works

- **interactive_commands**: Commands blocked by default because they require a TTY (terminal)
- **non_interactive_with_args**: Commands from the above list that become non-interactive when given arguments

Example: `ssh` is blocked (interactive), but `ssh server uptime` works because `ssh` is in `non_interactive_with_args` and has arguments.

### Default Lists

If not configured, sensible defaults are used:

**Interactive (blocked without args):**
- Editors: `nano`, `vim`, `vi`, `emacs`, `pico`, `joe`
- Pagers: `less`, `more`
- Monitors: `top`, `htop`, `btop`
- REPLs: `python`, `python3`, `ipython`, `node`, `irb`, `ruby`
- Network: `ssh`, `telnet`, `ftp`, `sftp`
- Databases: `mysql`, `psql`, `mongo`, `redis-cli`
- Shells: `bash`, `zsh`, `sh`, `fish`, `csh`, `tcsh`

**Non-interactive with args:**
- `python`, `python3`, `ipython`, `node`, `irb`, `ruby`
- `bash`, `zsh`, `sh`, `fish`, `csh`, `tcsh`
- `ssh`, `mysql`, `psql`

## Server Idle Timeout

HTTP server now supports configurable auto-shutdown after inactivity.

### Configuration

In `ppxai-config.json`:

```json
{
  "server": {
    "idle_timeout": 300
  }
}
```

- `idle_timeout`: Seconds of inactivity before auto-shutdown. Set to `0` to disable (server runs forever).
- Default: `300` (5 minutes)

### Use Case

Useful for VSCode extension users who want the server to automatically stop when not in use, freeing system resources.

## Custom System Prompts

Configure system prompts at global and per-provider levels.

### Global System Prompt

```json
{
  "system_prompt": "You are a helpful AI assistant. Be concise and direct.",
  "system_prompt_mode": "prepend"
}
```

### Per-Provider Override

```json
{
  "providers": {
    "perplexity": {
      "system_prompt": "You are a helpful AI assistant with web search. Cite sources as markdown links."
    }
  }
}
```

### Modes

- `prepend` (default): Custom prompt comes before tool instructions
- `append`: Custom prompt comes after tool instructions
- `replace`: Custom prompt replaces default (use with caution)

## Command Aliases

New shorter aliases for common commands:

| Command | Alias |
|---------|-------|
| `/tools enable` | `/tools on` |
| `/tools disable` | `/tools off` |

## Technical Details

### New Files

- `ppxai/config.py`: Added `get_shell_config()` function for shell configuration retrieval

### Modified Files

- `ppxai/engine/tools/builtin/shell.py` - Reads interactive commands from config
- `ppxai/main.py` - Status bar badge enhancements
- `ppxai/commands.py` - `/tools on|off` aliases
- `ppxai/server/http.py` - Idle timeout support
- `ppxai-config.example.json` - New configuration options documented

### Tests

- Added `TestShellConfig` class in `tests/test_config.py` with 6 new tests
- All 593 tests passing

## Upgrade Notes

- No breaking changes
- New config options are optional with sensible defaults
- Existing configurations continue to work unchanged

## Files Changed

| File | Change |
|------|--------|
| `ppxai/config.py` | Added `get_shell_config()` |
| `ppxai/engine/tools/builtin/shell.py` | Configurable interactive commands |
| `ppxai/main.py` | Status bar version, cwd, datetime badges |
| `ppxai/commands.py` | `/tools on\|off` aliases |
| `ppxai/server/http.py` | Idle timeout configuration |
| `ppxai-config.example.json` | New options documented |
| `tests/test_config.py` | New TestShellConfig tests |
