# Linux Desktop Integration

Desktop integration files for ppxai applications on Linux.

## Quick Start

```bash
# Install desktop integration (icons + .desktop files)
./install-desktop-integration.sh

# Uninstall desktop integration
./uninstall-desktop-integration.sh
```

## ⚠️ Terminal Requirements for ppxaide

**ppxaide uses multi-line input** where Enter adds newlines and Ctrl+Enter submits messages. This requires a terminal with enhanced keyboard protocol support.

### Why Standard Terminals Don't Work

Standard Linux terminals (GNOME Terminal, Konsole, xterm) send the same escape code for both Enter and Ctrl+Enter, making them indistinguishable to applications. This is a terminal emulator limitation, not a ppxai bug.

### Recommended: Ghostty Terminal

Ghostty is a modern, fast terminal with excellent keyboard protocol support.

**Quick Install:**
```bash
# 1. Download Ghostty AppImage
wget https://github.com/pkgforge-dev/ghostty-appimage/releases/latest/download/Ghostty-1.2.3-x86_64.AppImage
mv Ghostty-1.2.3-x86_64.AppImage ~/.local/bin/ghostty
chmod +x ~/.local/bin/ghostty

# 2. Configure Ctrl+Enter keybind
mkdir -p ~/.config/ghostty
cat >> ~/.config/ghostty/config << 'EOF'
# Enable Ctrl+Enter for ppxaide (sends CSI u sequence)
keybind = ctrl+enter=text:\x1b[13;5u
EOF

# 3. Install desktop integration (makes ppxaide use Ghostty by default)
./install-desktop-integration.sh
```

**Why the keybind is needed:**
Ghostty 1.2.3 AppImage has incomplete Kitty keyboard protocol negotiation. The explicit keybind bypasses this and sends the CSI u sequence (`\x1b[13;5u`) that Textual recognizes as Ctrl+Enter.

### Alternative Terminals

| Terminal | Ctrl+Enter Support | Configuration |
|----------|-------------------|---------------|
| **Ghostty** | ✅ Yes | Requires explicit keybind (see above) |
| **Kitty** | ✅ Yes | Works out-of-the-box |
| **WezTerm** | ✅ Yes | Add `enable_kitty_keyboard = true` to config |
| **Alacritty** | ✅ Yes | Recent versions support it |
| **GNOME Terminal** | ❌ No | Use Ctrl+J instead |
| **Konsole** | ❌ No | Use Ctrl+J instead |
| **xterm** | ❌ No | Use Ctrl+J instead |

### Fallback: Ctrl+J

If you prefer to use GNOME Terminal or Konsole, **Ctrl+J works universally** in all terminals as an alternative to Ctrl+Enter.

For detailed terminal setup instructions, see **[Linux Terminal Setup Guide](../docs/LINUX-TERMINAL-SETUP.md)**.

## What Gets Installed

### Applications

Three `.desktop` files are installed to `~/.local/share/applications/`:

| Application | Name | Type | Description | Terminal |
|------------|------|------|-------------|----------|
| **ppxai** | ppxai | Terminal (Rich CLI) | Legacy TUI with Rich markdown | Default terminal |
| **ppxaide** | ppxaide | Terminal (Textual TUI) | Modern TUI with multi-line input, 17+ themes | Ghostty (Ctrl+Enter) |
| **ppxai Desktop** | ppxai-desktop | GUI (Web) | Browser-based interface with full features | N/A (browser) |

**Note:** ppxaide is configured to use Ghostty terminal to ensure Ctrl+Enter works. The other apps use your default terminal/browser.

### Icons

Three PNG icons are installed to `~/.local/share/icons/`:

- `ppxai.png` - For ppxai (terminal CLI)
- `ppxaide.png` - For ppxaide (Textual TUI)
- `ppxai-desktop.png` - For ppxai-desktop (web app)

## After Installation

Once installed, you can:

1. **Launch from Application Menu**
   - Search for "ppxai", "ppxaide", or "ppxai Desktop" in your launcher
   - **GNOME:** Press Super key and type "ppxai"
   - **KDE Plasma:** Press Alt+F2 and type "ppxai"
   - **Cinnamon/MATE:** Open the menu and search "ppxai"

2. **Pin to Dock/Taskbar**
   - Right-click the running application
   - **GNOME:** Select "Pin to Dash" or "Add to Favorites"
   - **KDE Plasma:** Select "Pin to Panel" or "Add to Favorites"
   - **Cinnamon:** Select "Add to panel" or "Add to favorites"

3. **One-Click Execution**
   - Click the icon in your application menu to launch
   - ppxaide automatically launches in Ghostty (for Ctrl+Enter support)
   - ppxai and ppxai-desktop use your default terminal/browser

## Requirements

- ppxai binaries must be installed in `~/.local/bin/`
- Run the build/install process first: `/build` or `scripts/install-local.sh`

## Desktop File Locations

- **Desktop files**: `~/.local/share/applications/`
- **Icons**: `~/.local/share/icons/`
- **Source files**: `desktop/` directory in repository

## Troubleshooting

**Icons not showing up?**
- Try logging out and back in
- Or run: `gtk-update-icon-cache ~/.local/share/icons/`

**Applications not appearing in launcher?**
- Wait a few seconds for the desktop database to update
- Or run: `update-desktop-database ~/.local/share/applications/`

**Terminal applications not launching?**
- Make sure your default terminal emulator is set
- The Terminal=true flag requires a terminal emulator to be configured
