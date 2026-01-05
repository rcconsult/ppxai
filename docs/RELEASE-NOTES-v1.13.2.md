# Release Notes - v1.13.2

**Release Date:** 2026-01-05

This is a bugfix release focusing on markdown rendering issues in both the Desktop Web App and VSCode extension, plus cross-platform compatibility improvements for Windows.

## Highlights

- 🔧 **Fixed markdown rendering** - `/usage` and other commands now render properly with tables and lists
- 🪟 **Windows compatibility** - Tests and configuration now work correctly on Windows
- 📦 **Shared modules** - New shared code ensures feature parity across all UIs

## Fixed - Markdown Rendering

### Bullet Lists
The root cause was using Unicode bullet character (`•`) instead of standard markdown dash (`-`). The `marked.js` library only recognizes `-`, `*`, or `+` as list markers.

**Before:** Lists appeared as plain text
**After:** Lists render as proper `<li>` elements

### `/usage` Tables
Both VSCode extension and Web App now display usage statistics in a formatted table:

| Provider | Model | In | Out | Cost |
|:---------|:------|---:|----:|-----:|
| perplexity | sonar-pro | 397 | 383 | $0.0069 |
| custom | openai | 1,470 | 1,466 | $0.0000 |
| **TOTAL** | | **1,867** | **1,849** | **$0.0069** |

### marked.js Update
- Web App upgraded from v9.1.6 to v11.1.1
- Now matches VSCode extension version
- Better GFM (GitHub Flavored Markdown) support

## Fixed - Desktop Web App

### Auto-detect Server URL
The Web UI now uses `window.location.origin` instead of hardcoded `http://127.0.0.1:54320`. This fixes issues when:
- Running on a different port
- Accessing via hostname instead of localhost
- Using behind a reverse proxy

### Favicon
Added proper favicon using the same icon as the VSCode extension. Previously showed browser default or 404.

### Markdown Preview
The file preview panel (`/show` command) now:
- Renders `.md` files with full markdown support (headers, code blocks, tables)
- Applies syntax highlighting to code blocks
- Intercepts relative link clicks to show linked files in preview

## New - Shared Modules

Created shared JavaScript/TypeScript modules to ensure identical behavior across:
- Terminal UI (TUI)
- VSCode Extension
- Desktop Web App

### Files Added
```
ppxai/web/shared/
├── commands.js      # Command definitions
├── formatters.js    # Response formatters
├── api-client.js    # HTTP client
└── index.js         # Module exports

vscode-extension/src/shared/
├── commands.ts      # TypeScript command definitions
├── formatters.ts    # TypeScript formatters
└── index.ts         # Module exports
```

### Benefits
- Single source of truth for command definitions
- Consistent markdown formatting everywhere
- Easier to add new commands (add once, works everywhere)

## Fixed - Windows Compatibility

### Test Improvements
- Use `tempfile.gettempdir()` instead of hardcoded `/tmp`
- Use filename only in assertions (avoids path separator issues)
- Added `legacy_windows=False` for Rich console tests

### PEP 735 Migration
Migrated from `[tool.uv].dev-dependencies` to standard `[dependency-groups].dev` format for better cross-tool compatibility.

## Test Results

```
553 passed in 14.39s
```

All tests pass on Linux and Windows.

## Upgrade Instructions

### From v1.13.1

This is a drop-in replacement. No configuration changes required.

```bash
# Update via pip
pip install --upgrade ppxai

# Or update via uv
uv pip install --upgrade ppxai
```

### Desktop Web App Users
The web UI files will auto-update on next launch. For immediate update:
```bash
# Force refresh in browser
Ctrl+Shift+R (Linux/Windows) or Cmd+Shift+R (macOS)
```

### VSCode Extension
Download the new VSIX from the GitHub release and install:
```bash
code --install-extension ppxai-1.13.2.vsix
```

## Files Changed

| File | Changes |
|------|---------|
| `ppxai/web/app.js` | Table format for /usage, markdown fixes, auto-detect URL |
| `ppxai/web/index.html` | PNG favicon, shared module scripts |
| `ppxai/web/styles.css` | Markdown preview styling |
| `ppxai/web/lib/marked.min.js` | Updated to v11.1.1 |
| `ppxai/web/shared/*` | New shared modules |
| `ppxai/server/http.py` | Favicon routes |
| `vscode-extension/src/chatPanel.ts` | Fixed /usage rendering |
| `vscode-extension/src/shared/*` | New shared modules |
| `tests/*` | Cross-platform fixes |
| `pyproject.toml` | PEP 735 dependency-groups |

## Known Issues

None.

## Contributors

- @rcconsult - Windows compatibility, markdown fixes

---

**Full Changelog:** [v1.13.1...v1.13.2](https://github.com/rcconsult/ppxai/compare/v1.13.1...v1.13.2)
