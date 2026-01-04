# Release Notes - v1.13.1

**Release Date:** 2026-01-04

## Overview

v1.13.1 introduces the **ppxai Desktop Web App** - a standalone browser-based chat interface that provides the same experience as the VSCode extension without requiring VSCode. This release also includes UI improvements to the web interface.

## New Features

### Desktop Web App

**Double-click to chat with AI** - No IDE required:

- **`ppxai-desktop` binary** - Launches server and opens browser automatically
- **macOS `.app` bundle** - Drag to Applications, launch from Launchpad
- **macOS DMG installer** - `ppxai-VERSION-macos-arm64.dmg`
- **Cross-platform** - Binaries for Linux, Windows, and macOS (ARM + Intel)

The desktop app:
1. Checks if `ppxai-server` is already running
2. Starts server in background if needed
3. Opens default browser to `http://127.0.0.1:54320`
4. Installs web UI files to `~/.ppxai/web/` on first run

### Web UI Features

Full feature parity with VSCode extension:

- **Chat interface** - Real-time SSE streaming with markdown rendering
- **Provider/model switching** - Dropdown selectors in header
- **Project selector** - Quick switch between project directories
- **Tools & Agent mode** - Toggle buttons with consent dialogs
- **Usage tracking** - Token counts and cost in header badge
- **Slash commands** - Full `/help`, `/usage`, `/tools`, etc. support
- **File autocomplete** - `@filename` reference with suggestions
- **Syntax highlighting** - Code blocks with highlight.js
- **Dark/light themes** - Toggle or follow system preference
- **Settings modal** - Configure server URL, checkpoint mode

### Installation Options

**Option A: macOS DMG (Recommended for Mac users)**
```bash
# Download from GitHub Releases
open ppxai-1.13.1-macos-arm64.dmg
# Drag ppxai.app to Applications
```

**Option B: Install Script**
```bash
curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash -s -- --with-desktop --with-web-ui
ppxai-desktop
```

**Option C: Manual Binary**
```bash
# Download ppxai-desktop-{platform} and ppxai-server-{platform}
chmod +x ppxai-desktop-macos-arm64 ppxai-server-macos-arm64
./ppxai-desktop-macos-arm64
```

## UI Improvements

### Tool Call Display
- Tool calls now appear **before** the answer (matching VSCode extension behavior)
- Fixed ordering issue where tool calls appeared after the response

### Visual Badge States
- Tools badge turns **green** when enabled
- Agent badge turns **green** when enabled
- Clear visual feedback for active state

### Usage Tables
- `/usage` command now displays formatted markdown tables
- Matches VSCode extension format with Provider | Model | In | Out | Cost columns
- Thousand separators for token counts (38,402 vs 38402)
- TOTAL row with bold values

### Project Selector
- New project selector in web UI header
- Quick switch between recent projects
- Recent projects list with remove button
- Path input with tilde expansion support

## Release Assets

| Asset | Description |
|-------|-------------|
| `ppxai-1.13.1.vsix` | VSCode extension |
| `ppxai-macos-arm64` | TUI binary (macOS ARM) |
| `ppxai-macos-intel` | TUI binary (macOS Intel) |
| `ppxai-linux-amd64` | TUI binary (Linux) |
| `ppxai-windows.exe` | TUI binary (Windows) |
| `ppxai-server-macos-arm64` | Server binary (macOS ARM) |
| `ppxai-server-macos-intel` | Server binary (macOS Intel) |
| `ppxai-server-linux-amd64` | Server binary (Linux) |
| `ppxai-server-windows.exe` | Server binary (Windows) |

## Known Limitations

### Shared Server Context
The web app and VSCode extension share the same `ppxai-server` instance. This means:
- Working directory changes in one client affect the other
- Tool state (enabled/disabled) is shared
- Conversation history is per-session, not per-client

This will be addressed in v1.13.2 with session-scoped context.

## Upgrade Instructions

### From v1.13.0

No breaking changes. Simply update binaries:

```bash
# Re-run install script
curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash -s -- --with-desktop --with-web-ui

# Or update VSCode extension
code --install-extension ppxai-1.13.1.vsix
```

### Configuration

No configuration changes required. Existing `~/.ppxai/.env` and `~/.ppxai/ppxai-config.json` files work unchanged.

## Documentation

- [Installation Guide](INSTALLATION.md) - Updated with desktop app instructions
- [Agent Mode Guide](AGENT_MODE_GUIDE.md) - Works in web app
- [Checkpoint Guide](CHECKPOINT_GUIDE.md) - Works in web app

## Testing

- 512 tests passing
- Manual testing on macOS Intel
- Web UI tested in Chrome, Firefox, Safari
