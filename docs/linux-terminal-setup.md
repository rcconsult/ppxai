# Linux Terminal Setup for ppxaide

ppxaide uses multi-line input where **Enter** adds newlines and **Ctrl+Enter** submits messages. However, not all terminal emulators support distinguishing Ctrl+Enter from plain Enter.

## Quick Summary

| Terminal | Ctrl+Enter Support | Status |
|----------|-------------------|--------|
| **Ghostty** | ✅ Yes (with config) | ⭐ Recommended |
| **Kitty** | ✅ Yes | Excellent |
| **WezTerm** | ✅ Yes | Excellent |
| **Alacritty** | ✅ Yes (recent versions) | Good |
| **GNOME Terminal** | ❌ No | Use Ctrl+J instead |
| **Konsole** | ❌ No | Use Ctrl+J instead |
| **xterm** | ❌ No | Use Ctrl+J instead |

---

## Recommended: Ghostty Terminal

Ghostty is a modern, fast terminal emulator with excellent keyboard protocol support.

### Installation

**AppImage (Universal):**
```bash
# Download latest AppImage
wget https://github.com/pkgforge-dev/ghostty-appimage/releases/latest/download/Ghostty-1.2.3-x86_64.AppImage

# Install to ~/.local/bin
mkdir -p ~/.local/bin
mv Ghostty-1.2.3-x86_64.AppImage ~/.local/bin/ghostty
chmod +x ~/.local/bin/ghostty

# Verify
ghostty --version
```

**Ubuntu/Debian .deb:**
```bash
# From mkasberg/ghostty-ubuntu repository
wget https://github.com/mkasberg/ghostty-ubuntu/releases/latest/download/ghostty_1.2.3_amd64.deb
sudo dpkg -i ghostty_1.2.3_amd64.deb
```

### Configuration for ppxaide

**Required:** Add Ctrl+Enter keybind to `~/.config/ghostty/config`:

```
# Ghostty configuration for ppxaide
# Location: ~/.config/ghostty/config

# Enable Ctrl+Enter support (sends CSI u sequence)
keybind = ctrl+enter=text:\x1b[13;5u

# Optional: Shift+Enter sends Escape+Enter
keybind = shift+enter=text:\x1b\r
```

**Why this is needed:**
- Ghostty 1.2.3 (AppImage) has incomplete Kitty keyboard protocol negotiation
- The explicit keybind bypasses protocol negotiation and sends the CSI u sequence directly
- Textual recognizes `\x1b[13;5u` as Ctrl+Enter

### Verify Configuration

```bash
# Test if Ctrl+Enter works
ghostty -e ppxaide --debug

# Type a message and press Ctrl+Enter
# Then check the log:
cat ~/.ppxai/logs/keys.log | grep ctrl+enter
```

**Expected output:**
```
key='ctrl+enter' character=None aliases=['ctrl+enter']
```

---

## Alternative: Kitty Terminal

Kitty is the original implementation of the enhanced keyboard protocol.

### Installation

**Ubuntu/Debian:**
```bash
sudo apt install kitty
```

**From Binary:**
```bash
curl -L https://sw.kovidgoyal.net/kitty/installer.sh | sh /dev/stdin
```

### Configuration

Kitty works out of the box with ppxaide - no additional configuration needed!

```bash
# Launch ppxaide in Kitty
kitty ppxaide
```

---

## Alternative: WezTerm

WezTerm is a Rust-based terminal with excellent keyboard support.

### Installation

**Ubuntu/Debian:**
```bash
curl -fsSL https://apt.fury.io/wez/gpg.key | sudo gpg --yes --dearmor -o /usr/share/keyrings/wezterm-fury.gpg
echo 'deb [signed-by=/usr/share/keyrings/wezterm-fury.gpg] https://apt.fury.io/wez/ * *' | sudo tee /etc/apt/sources.list.d/wezterm.list
sudo apt update && sudo apt install wezterm
```

### Configuration

Add to `~/.config/wezterm/wezterm.lua`:

```lua
local config = {}

-- Enable Kitty keyboard protocol
config.enable_kitty_keyboard = true

return config
```

---

## Fallback: Using Ctrl+J

If you prefer to use **GNOME Terminal**, **Konsole**, or other terminals that don't support Ctrl+Enter:

**Workaround:** Use **Ctrl+J** to submit messages (works in all terminals)

```bash
# ppxaide footer will show: "Ctrl+J: Send"
ppxaide
```

**Why Ctrl+J works:**
- Ctrl+J sends newline character (`\n`, 0x0A)
- Ctrl+Enter sends carriage return (`\r`, 0x0D) in old terminals
- These are different keycodes, so Ctrl+J is always distinguishable

---

## Desktop Integration

### Option 1: ppxaide Always Uses Ghostty

The desktop integration automatically uses Ghostty for ppxaide:

```bash
# Install desktop files
cd desktop
./install-desktop-integration.sh
```

This creates `~/.local/share/applications/ppxaide.desktop` with:
```
Exec=ghostty -e /home/user/.local/bin/ppxaide
```

**Result:** Clicking ppxaide in your app launcher always uses Ghostty (Ctrl+Enter works)

### Option 2: Set Ghostty as System Default

Make Ghostty your default terminal for **all** applications:

```bash
# Set Ghostty as default
sudo update-alternatives --install /usr/bin/x-terminal-emulator x-terminal-emulator $(which ghostty) 50

# Select it as default (interactive menu)
sudo update-alternatives --config x-terminal-emulator
```

**Result:** All terminal applications use Ghostty by default

### Option 3: Manual Launch

Keep your existing terminal as default, launch ppxaide in Ghostty manually:

```bash
# Add alias to ~/.bashrc or ~/.zshrc
alias ppxaide='ghostty -e ppxaide'
```

---

## Troubleshooting

### Ctrl+Enter Still Not Working

**Check Ghostty config:**
```bash
cat ~/.config/ghostty/config
```

Should contain:
```
keybind = ctrl+enter=text:\x1b[13;5u
```

**Test key capture:**
```bash
# Enable debug logging
ghostty -e ppxaide --debug

# Press Ctrl+Enter, then check log
grep "ctrl+enter" ~/.ppxai/logs/keys.log
```

### Ghostty Not Found

**Verify installation:**
```bash
which ghostty
ghostty --version
```

**Add to PATH if needed:**
```bash
# Add to ~/.bashrc or ~/.zshrc
export PATH="$HOME/.local/bin:$PATH"
```

### Desktop Integration Not Working

**Verify desktop file:**
```bash
cat ~/.local/share/applications/ppxaide.desktop
```

**Update desktop database:**
```bash
update-desktop-database ~/.local/share/applications/
```

---

## Technical Background

### Why Terminal Keyboard Support Varies

**VT100/ANSI Standard (1970s):**
- Enter → `\r` (carriage return, 0x0D)
- Ctrl+M → `\r` (same code - indistinguishable!)
- Ctrl+Enter → `\r` (same code in old terminals)

**Modern Enhanced Keyboard Protocol (Kitty Protocol, CSI u):**
- Enter → `\r` (0x0D)
- Ctrl+Enter → `\x1b[13;5u` (escape sequence - distinct!)
- Allows distinguishing all modifier+key combinations

**Textual Support:**
Textual (ppxaide's framework) unconditionally *enables* the Kitty keyboard
protocol — but it does not negotiate or verify support, so a terminal that
ignores the sequence simply never delivers Ctrl+Enter (see
[ppxaide-impl.md](ppxaide-impl.md#kitty-keyboard-protocol)):
```python
# From textual/drivers/linux_driver.py
self.write("\x1b[>1u")  # Enable Kitty keyboard protocol
```

**The Problem:**
- GNOME Terminal, Konsole, xterm don't implement the protocol
- They ignore `\x1b[>1u` and continue sending old VT100 codes
- Ghostty implements it but needs explicit keybind for AppImage version

---

## Recommendations

**For the best ppxaide experience:**

1. ⭐ **Use Ghostty** with the `ctrl+enter` keybind (best balance of speed and features)
2. **Or use Kitty** (works perfectly out of the box)
3. **Or use WezTerm** (great for customization)
4. **Or use Ctrl+J** in any terminal (universal fallback)

**What we use:**
- Development: Ghostty (fast, modern, great keyboard support)
- macOS: iTerm2 (native Ctrl+Enter support)
- Windows: Windows Terminal (aliased Ctrl+Enter to Ctrl+J)
