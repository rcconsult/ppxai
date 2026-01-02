# Release Notes - v1.12.2

## Summary

Quality-of-life improvements focusing on TUI polish, logging unification, and bug fixes for tool parsing.

## New Features

### Emoji Toggle Command
- **`/theme emoji on|off`** - Toggle emoji display in panel badges
- Allows users to switch between emoji badges and text-only badges
- Useful for terminals with limited emoji support or consistent alignment preferences

## Bug Fixes

### Tool Call Parsing
- **Single-quote JSON handling** - Fixed parsing of tool calls that use single quotes instead of double quotes
- AI models sometimes generate JSON with single quotes; now properly handled

### Logging Unification
- **Common logger module** - TUI and engine now share the same logging system
- Eliminates duplicate logging code and ensures consistent log format
- Removed obsolete `tui_logger.py` (replaced by `ppxai/common/logger.py`)

### TUI Improvements
- **Checkpoint status symbol** - Shows `↶` symbol instead of full git hash for cleaner display
- **Panel alignment** - Replaced emojis with text symbols for consistent column alignment
- **Logger initialization** - Fixed missing `self.logger` initialization in CommandHandler

## Technical Details

### Files Changed
- `ppxai/commands.py` - Added `/theme emoji` command, fixed logger initialization
- `ppxai/engine/client.py` - Single-quote JSON handling in tool parsing
- `ppxai/main.py` - Unified logging, panel alignment fixes
- Deleted: `ppxai/tui_logger.py` - Replaced by common logger

### Commits
```
fix(tools): Handle single-quote JSON in tool call parsing
chore: Remove obsolete tui_logger.py
fix(logging): Unify TUI and engine to use common logger
fix(tui): Show ↶ symbol instead of git hash in checkpoint status
fix(commands): Initialize self.logger in CommandHandler
feat(tui): Add /theme emoji on|off command for emoji mode toggle
fix(tui): Replace emojis with text symbols for panel alignment
fix(tui): Normalize emoji widths for consistent panel alignment
```

## Compatibility

- All 377 tests passing
- Backward compatible with existing configurations
- No breaking changes to API or CLI

## Installation

```bash
# PyPI
pip install ppxai==1.12.2

# Or with uv
uv pip install ppxai==1.12.2
```

## Links

- [GitHub Release](https://github.com/rcconsult/ppxai/releases/tag/v1.12.2)
- [Full Changelog](https://github.com/rcconsult/ppxai/compare/v1.12.1...v1.12.2)
