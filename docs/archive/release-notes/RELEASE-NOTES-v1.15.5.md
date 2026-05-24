# Release Notes: v1.15.5

**Release Date:** 2026-02-15
**Branch:** feature/v1.15.5
**Focus:** Multi-Line Input, Escape Key Fix, Build Fix, Benchmark Improvements

---

## Overview

v1.15.5 brings multi-line chat input to ppxaide, fixing a long-standing UX limitation where users couldn't enter multi-line messages, code blocks, or formatted text. It also fixes Escape key handling, a PyInstaller build issue, and improves the benchmark system.

**Key Changes:**
- Multi-line input: Enter inserts newlines, Ctrl+Enter submits
- Escape key properly dismisses help panel, modals, and side panel
- PyInstaller build fix for missing `blinker` module
- Benchmark metadata and documentation improvements
- 15 new multi-line input tests (1,237+ total)

---

## Major Changes

### 1. Multi-Line Chat Input (Breaking UX Change)

**What changed:**
The ppxaide TUI input box has been replaced from a single-line `Input` widget to a multi-line `TextArea` widget (`ChatTextArea`).

| Action | Before (v1.15.4) | After (v1.15.5) |
|--------|-------------------|------------------|
| **Enter** | Submits message | Inserts newline |
| **Ctrl+Enter** | N/A | Submits message |
| **Multi-line** | Not possible | Supported |

**Why Ctrl+Enter?**
Shift+Enter was tried first but many terminal emulators (including Windows Terminal) do not distinguish Shift+Enter from Enter at the escape sequence level. Ctrl+Enter is the pattern used by VSCode, Jupyter, and other terminal applications.

**Auto-expansion:** The input box starts at 1 line and grows up to 18 lines as content is typed. Beyond 18 lines, a scrollbar appears.

**Footer hint:** "Ctrl+Enter: Send" is shown in the footer bar for discoverability.

**Preserved functionality:**
- Command history (Up/Down arrow keys)
- Tab completion (slash commands, @file references)
- Focus management between input and side panel

**Key files:**
- `ppxai/tui/widgets/input_box.py` — `ChatTextArea` class extending TextArea
- `ppxai/tui/app.py` — `action_submit_message` binding, `Ctrl+Enter` in BINDINGS
- `ppxai/tui/themes/layout.tcss` — TextArea styling with max-height and scrollbar

### 2. Escape Key Fix

The Escape key now works correctly for all dismissible UI elements with a clear priority order:

1. **Help panel** (Textual's built-in keys help) — dismissed first
2. **Modal screens** (command palette, dialogs) — dismissed second
3. **Side panel** (file viewer, editor) — dismissed third

Previously, the Escape key could get stuck or fail to dismiss certain UI elements due to event propagation issues between `ChatTextArea` and the app-level handler.

**Additional fixes:**
- `q` key binding added to close help panel (common convention)
- Command palette re-enabled
- Debug notifications from development removed

### 3. PyInstaller Build Fix

Added `blinker` to `ppxaide.spec` hiddenimports. The `blinker` library is used by the EventBus system (`ppxai/tui/event_bus.py`) but wasn't being detected by PyInstaller's dependency analysis, causing `ModuleNotFoundError` at runtime.

### 4. Benchmark Improvements

- **`tool_calling_method` metadata:** Benchmark results now automatically detect and record whether `native` or `prompt_based` tool calling was used, enabling better analysis across different configurations
- **BENCHMARKS.md guide:** Comprehensive 700+ line guide covering all 7 test categories, 28 tests, scoring system, and troubleshooting
- **Legacy archive:** 15 old benchmark JSON files archived to `benchmarks/llm-eval/docs/archive/legacy/`

### 5. Linux Desktop Integration (New)

**One-click app launcher integration** for Linux desktop environments (GNOME, KDE, Cinnamon, MATE):

**What's included:**
- `desktop/install-desktop-integration.sh` - One-click installer for `.desktop` files and icons
- `desktop/uninstall-desktop-integration.sh` - Clean uninstaller
- Three `.desktop` entries for app menu launching:
  - **ppxai** (Rich TUI) - Uses default terminal
  - **ppxaide** (Textual TUI) - Uses Ghostty for Ctrl+Enter support
  - **ppxai-desktop** (Web App) - Launches in browser
- Application icons (256×256 for ppxai, 1024×1024 for ppxaide, 128×128 logo for desktop)
- `docs/LINUX-TERMINAL-SETUP.md` - Comprehensive 293-line terminal setup guide

**Ghostty Terminal Configuration:**
ppxaide requires Ghostty (or Kitty/WezTerm) for proper Ctrl+Enter support. Standard terminals (GNOME Terminal, Konsole) send identical escape codes for Enter and Ctrl+Enter, making multi-line input impossible.

**Quick setup:**
```bash
# Install Ghostty AppImage
wget https://github.com/pkgforge-dev/ghostty-appimage/releases/latest/download/Ghostty-1.2.3-x86_64.AppImage
mv Ghostty-1.2.3-x86_64.AppImage ~/.local/bin/ghostty && chmod +x ~/.local/bin/ghostty

# Configure Ctrl+Enter keybind
mkdir -p ~/.config/ghostty
echo 'keybind = ctrl+enter=text:\x1b[13;5u' >> ~/.config/ghostty/config

# Install desktop integration
cd desktop && ./install-desktop-integration.sh
```

**Why Ghostty needs explicit keybind:**
Ghostty 1.2.3 AppImage has incomplete Kitty keyboard protocol negotiation. The explicit keybind bypasses protocol negotiation and sends the CSI u sequence (`\x1b[13;5u`) that Textual recognizes as Ctrl+Enter.

**Alternative terminals:**
- **Kitty** - Works out-of-the-box
- **WezTerm** - Add `enable_kitty_keyboard = true` to config
- **Alacritty** - Recent versions support it
- **GNOME Terminal/Konsole** - Use Ctrl+J as universal fallback

**Documentation updates:**
- `README.md` - Added Linux desktop integration section, terminal requirements, updated project structure
- `desktop/README.md` - Comprehensive terminal requirements guide with alternatives table
- `docs/INSTALLATION.md` - Added Linux terminal requirements section before TUI usage

**Key files:**
- `desktop/install-desktop-integration.sh` — Installer
- `desktop/uninstall-desktop-integration.sh` — Uninstaller
- `desktop/README.md` — Installation guide
- `docs/LINUX-TERMINAL-SETUP.md` — Terminal setup guide

---

## Testing

| Category | Count |
|----------|-------|
| **New multi-line input tests** | 15 |
| **Updated keybinding tests** | 2 (action_submit_message added to expected actions) |
| **Previous total** | 1,222 |
| **New total** | 1,236 |

---

## Migration Guide

### For ppxaide Users

The input behavior has changed:
- **To submit a message:** Press `Ctrl+Enter` (was: `Enter`)
- **To insert a newline:** Press `Enter` (was: not possible)

The footer bar shows the new keybinding hint.

### For Developers

- `InputBox` now yields `ChatTextArea` (a `TextArea` subclass) instead of `Input`
- `ChatTextArea.Submit` message replaces the old input submission mechanism
- `InputBox.Submitted` message interface is unchanged
- Tab completion and history navigation work the same way

---

## Known Issues

None specific to this release.

---

## Full Changelog

See [CHANGELOG.md](../CHANGELOG.md) for the complete list of changes.
