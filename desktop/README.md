# Linux Desktop Integration

Desktop integration files for ppxai applications on Linux.

## Quick Start

```bash
# Install desktop integration (icons + .desktop files)
./install-desktop-integration.sh

# Uninstall desktop integration
./uninstall-desktop-integration.sh
```

## ⚠️ Terminal Requirements

**ppxaide requires Ghostty terminal** for Ctrl+Enter support.

- **Install Ghostty:** See [LINUX-TERMINAL-SETUP.md](../docs/LINUX-TERMINAL-SETUP.md)
- **Configure Ghostty:** Add keybind to `~/.config/ghostty/config`
- **Why:** Standard Linux terminals (GNOME Terminal, Konsole) don't support Ctrl+Enter

**Quick Ghostty setup:**
```bash
# 1. Install Ghostty (AppImage)
wget https://github.com/pkgforge-dev/ghostty-appimage/releases/latest/download/Ghostty-1.2.3-x86_64.AppImage
mv Ghostty-1.2.3-x86_64.AppImage ~/.local/bin/ghostty
chmod +x ~/.local/bin/ghostty

# 2. Configure Ctrl+Enter
mkdir -p ~/.config/ghostty
echo 'keybind = ctrl+enter=text:\x1b[13;5u' >> ~/.config/ghostty/config

# 3. Install desktop integration
./install-desktop-integration.sh
```

For detailed terminal setup, see **[Linux Terminal Setup Guide](../docs/LINUX-TERMINAL-SETUP.md)**.

## What Gets Installed

### Applications

Three `.desktop` files are installed to `~/.local/share/applications/`:

| Application | Name | Type | Description |
|------------|------|------|-------------|
| **ppxai** | ppxai | Terminal (Rich CLI) | Terminal-based AI chat with markdown rendering |
| **ppxaide** | ppxaide | Terminal (Textual TUI) | Advanced TUI with syntax highlighting and themes |
| **ppxai Desktop** | ppxai-desktop | GUI (Web) | Browser-based desktop interface |

### Icons

Three PNG icons are installed to `~/.local/share/icons/`:

- `ppxai.png` - For ppxai (terminal CLI)
- `ppxaide.png` - For ppxaide (Textual TUI)
- `ppxai-desktop.png` - For ppxai-desktop (web app)

## After Installation

Once installed, you can:

1. **Launch from Application Menu**
   - Search for "ppxai", "ppxaide", or "ppxai Desktop" in your launcher
   - GNOME: Press Super key and type "ppxai"
   - KDE: Press Alt+F2 and type "ppxai"

2. **Pin to Dock/Taskbar**
   - Right-click the running application
   - Select "Pin to Dash" (GNOME) or "Add to Panel" (KDE)

3. **One-Click Execution**
   - Click the icon in your application menu to launch

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
