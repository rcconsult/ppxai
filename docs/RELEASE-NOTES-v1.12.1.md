# Release Notes - v1.12.1

## Summary

Enhanced TUI experience with themed panels, clickable file links, and visual improvements.

## New Features

### Themed TUI Panels
- **4 Distinctive Themes**: Standard, Tron Legacy, Matrix, and Nord
- **Rounded Panel Corners**: User, assistant, and system messages now have rounded borders
- **Theme Command**: `/theme` to list themes, `/theme <name>` to switch
- **Theme Autocomplete**: Tab completion for theme names

### Framed Status Panel
- **Badge Display**: Provider, model, tools status shown as colored badges
- **Visual Hierarchy**: Clear separation between header and chat content
- **Theme-Aware Styling**: Badges adapt to current theme colors

### Clickable File Links
- **OSC 8 Hyperlinks**: Markdown links in responses are now clickable in terminals
- **File URI Support**: Local file paths convert to `file://` URIs
- **VSCode Integration**: Clicking file links opens them in VSCode
- **/show Command**: File references in rendered markdown are clickable

## Bug Fixes

- **File Link Resolution**: Fixed relative paths in markdown not resolving correctly
- **Link Detection**: Fixed regex to match all markdown links, not just http/https URLs
- **Working Directory**: Pass file's parent directory for proper relative link resolution

## Technical Details

### New Files
- `ppxai/themes.py` - Theme dataclass and 4 built-in themes
- `ppxai/ui_components.py` - Reusable Rich UI components

### Modified Files
- `ppxai/main.py` - Theme integration and status panel
- `ppxai/commands.py` - Theme command and /show file link support
- `ppxai/markdown_tables.py` - Working directory support for file links
- `ppxai/common/event_handler.py` - TUIEventHandler with theme support

## Compatibility

- All 377 tests passing
- Backward compatible with existing configurations
- No breaking changes to API or CLI

## Installation

```bash
# PyPI
pip install ppxai==1.12.1

# Or with uv
uv pip install ppxai==1.12.1
```

## Links

- [GitHub Release](https://github.com/rcconsult/ppxai/releases/tag/v1.12.1)
- [Full Changelog](https://github.com/rcconsult/ppxai/compare/v1.12.0...v1.12.1)
