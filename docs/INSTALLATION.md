# Installation Guide

This guide covers installing ppxai for terminal (TUI), Desktop Web App, and VSCode extension use.

## Installation Locations Summary

| Item | Linux | macOS | Windows |
|------|-------|-------|---------|
| **Binaries** | `~/.local/bin/` | `~/.local/bin/` | `~/.ppxai/bin/` |
| **App bundle** | - | `/Applications/ppxai.app` | - |
| **Config** | `~/.ppxai/ppxai-config.json` | `~/.ppxai/ppxai-config.json` | `~/.ppxai/ppxai-config.json` |
| **API keys** | `~/.ppxai/.env` | `~/.ppxai/.env` | `~/.ppxai/.env` |
| **Data** | `~/.ppxai/` | `~/.ppxai/` | `~/.ppxai/` |

## Quick Install

### Linux / macOS

```bash
curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash
```

This installs `ppxai` (Rich TUI), `ppxaide` (Textual TUI - v1.15.0+), `ppxai-server`, and `ppxai-desktop` (Desktop Web App) to `~/.local/bin`.

#### Installation Options

```bash
# Install latest version (TUI + server + desktop)
curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash

# Install with config files (recommended for first-time setup)
curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash -s -- --with-config

# Install specific version
curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash -s -- --version v1.15.0

# Install with VSCode extension
curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash -s -- --with-extension

# Install with Linux desktop integration (adds to app menu)
curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash -s -- --with-desktop

# macOS: Install app bundle to /Applications
curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash -s -- --with-macos-app

# macOS: Full installation with app, config, and auto-start server
curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash -s -- --with-macos-app --with-config --with-launchagent

# Install only the server (for VSCode users who don't need TUI)
curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash -s -- --server-only

# Install only TUI (no server or desktop)
curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash -s -- --tui-only

# Install to custom directory
curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash -s -- --install-dir /usr/local/bin

# Uninstall ppxai
curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash -s -- --uninstall
```

### Windows

Open PowerShell and run:

```powershell
# Download and run the installer
irm https://raw.githubusercontent.com/rcconsult/ppxai/master/scripts/install.ps1 | iex
```

Or download and run manually:

```powershell
# Download the installer
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/rcconsult/ppxai/master/scripts/install.ps1" -OutFile "install.ps1"

# Run it (may require: Set-ExecutionPolicy RemoteSigned -Scope CurrentUser)
.\install.ps1

# Install specific version
.\install.ps1 -Version v1.15.0

# Force overwrite existing installation
.\install.ps1 -Force
```

This installs to `%USERPROFILE%\.ppxai\`:
- Binaries: `~\.ppxai\bin\`
- Config: `~\.ppxai\ppxai-config.json`
- API keys: `~\.ppxai\.env`

## Post-Installation Setup

### 1. Add to PATH

#### Linux / macOS

If `~/.local/bin` is not in your PATH, add it:

**Bash (~/.bashrc or ~/.bash_profile):**
```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

**Zsh (~/.zshrc):**
```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

**Fish (~/.config/fish/config.fish):**
```fish
echo 'set -gx PATH $HOME/.local/bin $PATH' >> ~/.config/fish/config.fish
source ~/.config/fish/config.fish
```

#### Windows

The installer automatically adds `~\.ppxai\bin` to your user PATH. Restart your terminal to apply.

Or update PATH manually in PowerShell:
```powershell
$env:PATH = [Environment]::GetEnvironmentVariable("PATH", "User")
```

### 2. Set Up API Key

#### Linux / macOS

```bash
mkdir -p ~/.ppxai
echo 'PERPLEXITY_API_KEY=your-key-here' > ~/.ppxai/.env
```

#### Windows

```powershell
# The installer creates a template .env file
# Edit it with your API keys:
notepad $env:USERPROFILE\.ppxai\.env
```

Get your API key at: https://www.perplexity.ai/settings/api

### 3. Verify Installation

```bash
# Check Rich TUI
ppxai --version

# Check Textual TUI (v1.15.0+)
ppxaide --version

# Check server
ppxai-server --version

# Check Desktop Web App
ppxai-desktop --version
```

## Using the Terminal UI (TUI)

Start the terminal chat interface:

```bash
# Rich TUI (original)
ppxai

# Or Textual TUI (v1.15.0+ - modern async architecture)
ppxaide
```

**ppxaide features:**
- Real-time streaming with async event loop
- 17+ themes (vs 6 in Rich TUI) - cycle with Ctrl+T or `/theme`
- Advanced file viewers (tree/table toggle, image support, syntax highlighting)
- Real-time token/cost tracking in status bar
- Tool execution display with formatted arguments/results
- Bootstrap context auto-loading from AGENTS.md

### Basic Commands

| Command | Description |
|---------|-------------|
| `/help` | Show all commands |
| `/model list` | List available models |
| `/provider list` | List available providers |
| `/tools on` | Enable AI tools |
| `/clear` | Clear conversation |
| `/save` | Save session |
| `Ctrl+C` (x2) | Exit |

## Using the Desktop Web App

The Desktop Web App (v1.13.1+) launches a browser-based chat interface:

```bash
ppxai-desktop
```

This opens your default browser to the ppxai web UI. Features:
- Full slash command support (`/provider`, `/model`, `/tools`, etc.)
- Same `@file`, `@git`, `@tree` context injection as TUI
- Markdown rendering with syntax highlighting
- Agent mode with tool execution

### macOS DMG Installer

macOS users can download the `.dmg` installer from [GitHub Releases](https://github.com/rcconsult/ppxai/releases):

**Option A: Automated Installation**

```bash
# Install app bundle to /Applications (auto-removes quarantine)
curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash -s -- --with-macos-app

# Full macOS setup with config files and LaunchAgent
curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash -s -- --with-macos-app --with-config --with-launchagent
```

**Option B: Manual Installation**

1. Download `ppxai-VERSION-macos-arm64.dmg` (or `macos-intel` for Intel Macs)
2. Open the DMG and drag `ppxai.app` to Applications
3. **Important**: Remove quarantine attribute before first launch:
   ```bash
   xattr -cr /Applications/ppxai.app
   ```
4. Launch from Applications or Spotlight

The app bundle includes both `ppxai-desktop` and `ppxai-server`.

### macOS LaunchAgent (Auto-Start Server)

To have `ppxai-server` start automatically (useful for VSCode integration):

```bash
# Install LaunchAgent
curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash -s -- --with-launchagent

# Or manually create ~/Library/LaunchAgents/com.ppxai.server.plist
```

LaunchAgent commands:
```bash
# Start server
launchctl load ~/Library/LaunchAgents/com.ppxai.server.plist

# Stop server
launchctl unload ~/Library/LaunchAgents/com.ppxai.server.plist

# Enable at login (edit plist and change RunAtLoad to true)
```

### Linux Desktop Integration

Add ppxai to your application menu:

```bash
# Install with desktop integration
curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash -s -- --with-desktop
```

This installs:
- `~/.local/share/applications/ppxai.desktop` - Desktop entry
- `~/.local/share/icons/hicolor/128x128/apps/ppxai.png` - App icon

## Using the VSCode Extension

### Option A: Install from VSIX (Downloaded with --with-extension)

```bash
# Install the extension
code --install-extension ~/.local/bin/ppxai-1.15.1.vsix

# Or drag and drop the .vsix file into VSCode
```

### Option B: Download VSIX from GitHub Releases

1. Go to [GitHub Releases](https://github.com/rcconsult/ppxai/releases)
2. Download `ppxai-VERSION.vsix`
3. Install: `code --install-extension ppxai-VERSION.vsix`

### Starting the Server

The VSCode extension requires `ppxai-server` to be running. There are two ways to start it:

**Option 1: Automatic (v1.13.8+)**

The extension auto-starts `ppxai-server` when you open the chat panel. Just open the ppxai chat and wait a few seconds.

**Option 2: Click the Server Badge**

In the ppxai chat panel, click the "Disconnected" badge to start the server.

**Option 3: Start Manually**

```bash
ppxai-server
```

The server runs on `http://127.0.0.1:54320` by default.

### Extension Features

- **Chat Panel** - Full AI chat interface in the sidebar
- **Server Control** - Auto-start server from the UI
- **Tools** - Enable AI tools (file reading, shell commands, etc.)
- **Agent Mode** - Autonomous task execution with checkpoints
- **Code Actions** - Explain, generate tests, generate docs from context menu
- **Session Management** - Save, load, and restore conversations
- **Real-time Streaming** - SSE-based streaming with instant responses

## Alternative: Install with pip/uv

For Python developers who prefer package managers:

```bash
# With pip
pip install ppxai[server]

# With uv
uv pip install ppxai[server]

# Run TUI
ppxai

# Run server
ppxai-server
```

## Alternative: Download Binaries Manually

Pre-built binaries are available for all platforms:

| Platform | Rich TUI | Textual TUI | Server | Desktop |
|----------|---------|-------------|--------|---------|
| macOS ARM (M1/M2) | `ppxai-macos-arm64` | `ppxaide-macos-arm64` | `ppxai-server-macos-arm64` | `ppxai-desktop-macos-arm64` |
| macOS Intel | `ppxai-macos-intel` | `ppxaide-macos-intel` | `ppxai-server-macos-intel` | `ppxai-desktop-macos-intel` |
| Linux x64 | `ppxai-linux-amd64` | `ppxaide-linux-amd64` | `ppxai-server-linux-amd64` | `ppxai-desktop-linux-amd64` |
| Windows | `ppxai-windows.exe` | `ppxaide-windows.exe` | `ppxai-server-windows.exe` | `ppxai-desktop-windows.exe` |

**Additional downloads:**
- `ppxai-VERSION.vsix` - VSCode extension
- `ppxai-VERSION-macos-arm64.dmg` - macOS app bundle installer
- `ppxai-web-ui-VERSION.zip` - Web UI files (for self-hosting)

**Note:** ppxaide (Textual TUI) is new in v1.15.0 and offers a modern async architecture with advanced features.

Download from [GitHub Releases](https://github.com/rcconsult/ppxai/releases).

### Linux/macOS

```bash
chmod +x ppxai-linux-amd64 ppxaide-linux-amd64
mv ppxai-linux-amd64 ~/.local/bin/ppxai
mv ppxaide-linux-amd64 ~/.local/bin/ppxaide
```

### Windows

```powershell
# Move to installation directory
Move-Item ppxai-windows.exe $env:USERPROFILE\.ppxai\bin\ppxai.exe
Move-Item ppxaide-windows.exe $env:USERPROFILE\.ppxai\bin\ppxaide.exe
```

## Configuration

### Quick Setup with --with-config

The easiest way to set up configuration is to use the `--with-config` flag:

```bash
curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash -s -- --with-config
```

This creates:
- `~/.ppxai/ppxai-config.json` - Provider configuration with all built-in providers
- `~/.ppxai/.env` - Template with all API key options documented
- `~/.ppxai/sessions/` - Session storage
- `~/.ppxai/exports/` - Exported answers
- `~/.ppxai/checkpoints/` - Agent checkpoints

Then edit `~/.ppxai/.env` to uncomment and add your API keys.

### API Keys

ppxai supports multiple AI providers. Add keys to `~/.ppxai/.env`:

```bash
# Perplexity (default - includes web search)
PERPLEXITY_API_KEY=pplx-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Google Gemini (free tier available)
GEMINI_API_KEY=AIzaxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# OpenAI
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# OpenRouter (access multiple providers)
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### Provider Configuration

For advanced provider configuration, create `~/.ppxai/ppxai-config.json`:

```json
{
  "default_provider": "perplexity",
  "providers": {
    "custom-vllm": {
      "name": "Local vLLM",
      "base_url": "http://localhost:8000/v1",
      "api_key_env": "VLLM_API_KEY",
      "default_model": "meta-llama/Llama-3.1-70B-Instruct"
    }
  }
}
```

## Terminal Image Display (v1.15.2+)

ppxai supports inline image rendering in terminals that support image protocols. This section covers configuration for users who want to enable image display or use multiple terminals.

### Supported Terminals and Protocols

| Terminal | Platform | Protocol | Auto-Detected |
|----------|----------|----------|---------------|
| **WezTerm** | Windows/macOS/Linux | iTerm2 | ⚠️ Requires config |
| **Windows Terminal** | Windows | Sixel | ✅ Yes |
| **iTerm2** | macOS | iTerm2/TGP | ✅ Yes |
| **Kitty** | macOS/Linux | Kitty TGP | ✅ Yes |
| **Konsole** | Linux | Sixel | ✅ Yes |
| **xterm** (sixel build) | Linux | Sixel | ✅ Yes |

### Checking Terminal Detection

Use the `/terminal` command in ppxai to see current detection status:

```
/terminal
```

Or check with `/status`:
```
/status

  ...
  Terminal      : Windows Terminal
  True Color    : yes
  Images        : sixel
  Hyperlinks    : yes
```

### Terminal-Specific Configuration

#### WezTerm Setup

WezTerm requires `TERM_PROGRAM` to be set for auto-detection. Add to `~/.wezterm.lua` (or `%USERPROFILE%\.wezterm.lua` on Windows):

```lua
local wezterm = require 'wezterm'
local config = {}

-- Required for ppxai terminal detection
config.set_environment_variables = {
  TERM_PROGRAM = 'WezTerm',
}

return config
```

After this change, ppxai will automatically use the iTerm2 image protocol in WezTerm.

#### Windows Terminal Setup

Windows Terminal auto-detection works out of the box via the `WT_SESSION` environment variable. No configuration needed.

**Optional:** To explicitly set the image protocol, add to your Windows Terminal `settings.json` (Ctrl+Shift+, in Windows Terminal):

```json
{
  "profiles": {
    "defaults": {
      "environment": {
        "PPXAI_IMAGE_PROTOCOL": "sixel"
      }
    }
  }
}
```

Or for a specific profile only:

```json
{
  "profiles": {
    "list": [
      {
        "name": "PowerShell",
        "guid": "{your-profile-guid}",
        "environment": {
          "PPXAI_IMAGE_PROTOCOL": "sixel"
        }
      }
    ]
  }
}
```

### Environment Variable Overrides

For advanced users or when auto-detection doesn't work, you can override terminal detection via environment variables. These can be set in:
- Terminal-specific config (recommended for multi-terminal setups)
- `~/.ppxai/.env` (applies to all terminals)
- Shell profile (`~/.bashrc`, `~/.zshrc`, PowerShell profile)

| Variable | Values | Description |
|----------|--------|-------------|
| `PPXAI_TERMINAL` | `WezTerm`, `iTerm.app`, `kitty`, `Windows Terminal`, `auto` | Override terminal identification |
| `PPXAI_IMAGE_PROTOCOL` | `iterm2`, `kitty`, `sixel`, `none`, `auto` | Override image protocol |

**Example in ~/.ppxai/.env:**
```bash
# Force iTerm2 protocol (for WezTerm users)
PPXAI_IMAGE_PROTOCOL=iterm2

# Or disable images entirely
PPXAI_IMAGE_PROTOCOL=none
```

### Multi-Terminal Setup (Windows)

If you use both WezTerm and Windows Terminal on Windows, configure each terminal separately rather than using `~/.ppxai/.env`:

1. **WezTerm** - Set `TERM_PROGRAM=WezTerm` in `.wezterm.lua` (see above)
2. **Windows Terminal** - Auto-detects via `WT_SESSION` (no config needed)

This way, each terminal automatically uses the correct protocol:
- WezTerm → iTerm2 protocol
- Windows Terminal → Sixel protocol

### Windows Desktop Shortcuts

When launching ppxai from a Windows shortcut, you must launch via a modern terminal (Windows Terminal or WezTerm) to get image support. Direct shortcuts to `ppxai.exe` run in the legacy console (`conhost.exe`) which doesn't support image protocols.

#### Creating a Proper Shortcut

**For Windows Terminal:**

1. Right-click Desktop → New → Shortcut
2. Set target to:
   ```
   wt.exe -d "%USERPROFILE%\.ppxai" -- "%USERPROFILE%\.ppxai\bin\ppxai.exe"
   ```
3. Or for a specific starting directory:
   ```
   wt.exe -d "C:\Projects\MyProject" -- "%USERPROFILE%\.ppxai\bin\ppxai.exe"
   ```

**For WezTerm:**

1. Right-click Desktop → New → Shortcut
2. Set target to:
   ```
   wezterm.exe start --cwd "%USERPROFILE%\.ppxai" -- "%USERPROFILE%\.ppxai\bin\ppxai.exe"
   ```

**Shortcut Properties:**
- **Start in:** Leave empty (the `-d` flag sets the working directory)
- **Run:** Normal window
- **Icon:** Optionally set to `ppxai.exe` for the ppxai icon

#### ppxaide (Textual TUI) Shortcuts

Replace `ppxai.exe` with `ppxaide.exe` in the above examples:

```
wt.exe -d "%USERPROFILE%\.ppxai" -- "%USERPROFILE%\.ppxai\bin\ppxaide.exe"
```

### macOS Terminal Configuration

macOS users have several terminal options with different image protocol capabilities.

#### Terminal Comparison (macOS)

| Terminal | Protocol | Image Support | Performance | Installation | Recommendation |
|----------|----------|---------------|-------------|--------------|----------------|
| **iTerm2** | iTerm2 (OSC 1337) | ✅ Excellent | Good | [iterm2.com](https://iterm2.com/) | Best native macOS |
| **WezTerm** | iTerm2 | ✅ Excellent | Excellent | [wezfurlong.org](https://wezfurlong.org/wezterm/) | Best cross-platform |
| **Kitty** | Kitty TGP | ✅ Excellent | Excellent | [sw.kovidgoyal.net](https://sw.kovidgoyal.net/kitty/) | Linux-focused, works on macOS |
| **Terminal.app** | None | ❌ No support | Good | Built-in | Text-only |

**Recommendation:** Use iTerm2 for the best native macOS experience, or WezTerm for cross-platform consistency.

#### iTerm2 Setup

iTerm2 supports image display out of the box with no configuration needed. ppxai automatically detects iTerm2 via the `TERM_PROGRAM` environment variable.

**Verify detection:**
```bash
echo $TERM_PROGRAM
# Should output: iTerm.app
```

If not set (e.g., when using tmux), you can force iTerm2 protocol:

```bash
# In ~/.zshrc or ~/.bash_profile
export PPXAI_IMAGE_PROTOCOL=iterm2
```

**Optional: iTerm2 Profile Optimization**

For best results with ppxai image rendering:

1. Open iTerm2 → Preferences (⌘,)
2. Go to **Profiles** → **Terminal**
3. Ensure these settings:
   - **Report Terminal Type:** `xterm-256color` or `xterm-256color-italic`
   - **Character Encoding:** UTF-8
4. Go to **Profiles** → **Text**
   - Use a font with good Unicode support (e.g., SF Mono, Menlo, Fira Code)

#### WezTerm Setup (macOS)

WezTerm requires `TERM_PROGRAM` to be set for auto-detection. Add to `~/.wezterm.lua`:

```lua
local wezterm = require 'wezterm'
local config = {}

-- Required for ppxai terminal detection
config.set_environment_variables = {
  TERM_PROGRAM = 'WezTerm',
}

return config
```

After this change, ppxai will automatically use the iTerm2 image protocol in WezTerm.

#### Kitty Setup (macOS)

Kitty is auto-detected via the `KITTY_WINDOW_ID` environment variable. No configuration needed.

Install via Homebrew:
```bash
brew install kitty
```

#### Terminal.app (Not Recommended for Image Display)

Apple's built-in Terminal.app **does not support** image display protocols (Sixel, iTerm2, or Kitty). If you need image rendering:

1. Install iTerm2 (recommended): `brew install --cask iterm2`
2. Or install WezTerm: `brew install --cask wezterm`

You can still use ppxai in Terminal.app for text-only chat.

### macOS Desktop Launchers

#### Option 1: Automator Application

Create a native macOS app that launches ppxai in your preferred terminal:

**For iTerm2:**

1. Open **Automator.app** (Applications → Automator)
2. Choose **New Document** → **Application**
3. Search for "Run AppleScript" and drag it to the workflow
4. Replace the script with:

```applescript
on run {input, parameters}
    tell application "iTerm"
        activate
        create window with default profile
        tell current session of current window
            write text "ppxai"
        end tell
    end tell
    return input
end run
```

5. Save as `ppxai.app` in `/Applications/` or `~/Applications/`
6. **Optional:** Right-click → Get Info → drag custom icon

**For WezTerm:**

```applescript
on run {input, parameters}
    do shell script "/Applications/WezTerm.app/Contents/MacOS/wezterm start --always-new-process -- ~/.local/bin/ppxai"
    return input
end run
```

**For ppxaide (Textual TUI):**

Replace `ppxai` with `ppxaide` in the scripts above.

#### Option 2: Alfred Workflow

Create an Alfred workflow for quick launch:

1. Open **Alfred Preferences** → **Workflows**
2. Click **+** → **Blank Workflow**
3. Add **Hotkey** trigger (e.g., ⌥⌘P)
4. Add **Run Script** action:

```bash
osascript -e 'tell application "iTerm" to create window with default profile command "ppxai"'
```

5. Connect trigger to action

#### Option 3: Raycast Script Command

Create `~/.config/raycast/scripts/ppxai.sh`:

```bash
#!/bin/bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Launch ppxai
# @raycast.mode silent
# @raycast.packageName ppxai

# Launch ppxai in iTerm2
osascript -e 'tell application "iTerm" to create window with default profile command "ppxai"'
```

Make it executable:
```bash
chmod +x ~/.config/raycast/scripts/ppxai.sh
```

#### Option 4: Dock Icon

To add ppxai to the Dock:

1. Create Automator app (see Option 1)
2. Drag `ppxai.app` from `/Applications/` to Dock
3. **Optional:** Add custom icon:
   - Download ppxai icon from GitHub releases
   - Right-click app → Get Info
   - Drag icon to the icon area in top-left

### macOS Shell Profile Examples

Add environment variable overrides to your shell profile for persistent configuration.

#### Zsh (Default on macOS Catalina+)

Add to `~/.zshrc`:

```bash
# ppxai Terminal Configuration
# Force terminal identification (if auto-detection fails)
export PPXAI_TERMINAL=iTerm.app

# Force image protocol (if auto-detection fails)
export PPXAI_IMAGE_PROTOCOL=iterm2

# Or disable images entirely
# export PPXAI_IMAGE_PROTOCOL=none
```

Apply changes:
```bash
source ~/.zshrc
```

#### Bash (Legacy)

Add to `~/.bash_profile` or `~/.bashrc`:

```bash
# ppxai Terminal Configuration
export PPXAI_TERMINAL=iTerm.app
export PPXAI_IMAGE_PROTOCOL=iterm2
```

Apply changes:
```bash
source ~/.bash_profile
```

#### Per-Terminal Configuration (Recommended)

For users who switch between multiple terminals (e.g., iTerm2 + WezTerm), configure each terminal separately rather than using shell profile:

**iTerm2:**
1. Open **Preferences** → **Profiles** → **Your Profile**
2. Go to **General** → **Environment**
3. Click **+** and add:
   - `PPXAI_TERMINAL=iTerm.app`
   - `PPXAI_IMAGE_PROTOCOL=iterm2`

**WezTerm:**
Use `.wezterm.lua` config (see WezTerm Setup section above).

This way, each terminal automatically uses the correct protocol without conflicts.

### Multi-Terminal Setup (macOS)

If you use multiple terminals on macOS, configure image protocols per-terminal to avoid conflicts:

| Terminal | Configuration Method | Priority |
|----------|---------------------|----------|
| **iTerm2** | iTerm2 Profile → Environment variables | High |
| **WezTerm** | `~/.wezterm.lua` → `set_environment_variables` | High |
| **Kitty** | Auto-detected via `KITTY_WINDOW_ID` | Auto |
| **Terminal.app** | No configuration (images not supported) | N/A |

**Avoid** setting `PPXAI_TERMINAL` or `PPXAI_IMAGE_PROTOCOL` in `~/.zshrc` when using multiple terminals, as it forces the same protocol for all terminals.

**Example Multi-Terminal Workflow:**

1. **Daily work (iTerm2)** - Auto-detected, iTerm2 protocol for images
2. **SSH sessions (WezTerm)** - Configured in `.wezterm.lua`, iTerm2 protocol
3. **Quick scripts (Terminal.app)** - Text-only, no image support

### Verifying Image Support

After configuration, verify image support:

1. Start ppxai in your configured terminal
2. Run `/status` and check:
   - `Terminal` shows the correct terminal name
   - `Images` shows `sixel` or `iterm2` (not `none`)
3. Test with `/display <path-to-image>` (if you have an image file)

**Expected output for Windows Terminal:**
```
Terminal      : Windows Terminal
Images        : sixel
```

**Expected output for WezTerm:**
```
Terminal      : WezTerm
Images        : iterm2
```

If `Terminal` shows `unknown` and `Images` shows `none`, you're running in the legacy console - use a proper terminal shortcut.

## Troubleshooting

### "command not found: ppxai"

**Linux/macOS:** Add `~/.local/bin` to your PATH (see Post-Installation Setup above).

**Windows:** Restart your terminal after installation, or run:
```powershell
$env:PATH = [Environment]::GetEnvironmentVariable("PATH", "User")
```

### "Could not connect to ppxai-server"

Make sure the server is running:
```bash
ppxai-server
```

Or wait for the VSCode extension to auto-start it (v1.13.8+).

### "No API key configured"

Add your API key to `~/.ppxai/.env`:

**Linux/macOS:**
```bash
echo 'PERPLEXITY_API_KEY=your-key-here' > ~/.ppxai/.env
```

**Windows:**
```powershell
notepad $env:USERPROFILE\.ppxai\.env
```

### Server Port Already in Use

**Linux/macOS:**
```bash
pkill -f ppxai-server
ppxai-server
```

**Windows:**
```powershell
# Find and kill existing server
Get-Process | Where-Object {$_.ProcessName -like "*ppxai-server*"} | Stop-Process
ppxai-server
```

### Windows: First Run is Slow

Windows Defender may scan the binary on first run. This is normal and should only happen once. The VSCode extension has retry logic to handle this delay.

### Windows: SSL Certificate Errors (Corporate Proxy)

If you're behind a corporate proxy with SSL inspection, add to your `.env`:
```
SSL_VERIFY=false
```

### Windows: ExecutionPolicy Error

If PowerShell blocks the install script:
```powershell
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Terminal Shows "unknown" and Images "none"

This means ppxai is running in a terminal that doesn't support image protocols (likely the legacy Windows console).

**Solution:** Launch ppxai via Windows Terminal or WezTerm:
```powershell
# Windows Terminal
wt.exe -- ppxai

# WezTerm
wezterm.exe start -- ppxai
```

See [Terminal Image Display](#terminal-image-display-v1152) for shortcut configuration.

### WezTerm Not Detected (Shows "unknown")

WezTerm doesn't set `TERM_PROGRAM` by default. Add to `~/.wezterm.lua`:

```lua
config.set_environment_variables = {
  TERM_PROGRAM = 'WezTerm',
}
```

Restart WezTerm after making this change.

### Images Don't Render in Windows Terminal

1. Ensure Sixel is enabled in Windows Terminal settings (`settings.json`):
   ```json
   {
     "profiles": {
       "defaults": {
         "experimental": {
           "enableImages": true
         }
       }
     }
   }
   ```
2. Check `/status` shows `Images: sixel`
3. Windows Terminal Preview may have better image support than stable

### Images Don't Render in WezTerm

1. Check `TERM_PROGRAM` is set (run `/terminal` to verify)
2. Ensure you're using a recent WezTerm version (iTerm2 protocol support)
3. Try forcing the protocol in `.wezterm.lua`:
   ```lua
   config.set_environment_variables = {
     TERM_PROGRAM = 'WezTerm',
     PPXAI_IMAGE_PROTOCOL = 'iterm2',
   }
   ```

## Platform-Specific Notes

### Clipboard Support

**Windows:**
- Clipboard functionality works out of the box (uses `pyperclip` auto-installed with dependencies)
- Copy/paste operations in ppxaide work with standard Windows clipboard (Ctrl+C/Ctrl+V)

**macOS:**
- Clipboard functionality works out of the box
- Copy/paste operations use native macOS clipboard (Cmd+C/Cmd+V)

**Linux (GUI Desktop):**
- Clipboard functionality works out of the box for most desktop environments (GNOME, KDE, XFCE)
- Uses `pyperclip` which detects available clipboard backends automatically

**Linux (Headless/SSH):**
- Requires `xclip` or `xsel` for clipboard operations:
  ```bash
  # Ubuntu/Debian
  sudo apt install xclip

  # Fedora/RHEL
  sudo dnf install xclip

  # Arch
  sudo pacman -S xclip
  ```
- Without these tools, clipboard operations will gracefully fail (copy returns false, paste returns None)
- This is expected behavior - clipboard requires X11 or Wayland display server

### Signal Handling (Ctrl+C / Process Termination)

**v1.15.3+:** All platforms support graceful shutdown

- **SIGINT (Ctrl+C):** Supported on Windows, macOS, Linux
  - Gracefully terminates ppxaide without corrupting sessions
  - Double Ctrl+C pattern in ppxaide (first cancels current operation, second quits)

- **SIGTERM (Process Termination):** Supported on Windows, macOS, Linux
  - Sent by Task Manager "End Task" (Windows) or `kill <pid>` (Unix)
  - Triggers graceful cleanup and session save

- **Previous versions (≤v1.15.2):** Windows did not support SIGINT - required task kill

### Binary Search Path Optimization

**v1.15.3+:** Platform-aware path filtering for faster startup

- **Windows:** Only checks Windows-specific paths (`~/.ppxai/bin/`, `~/AppData/Local/ppxai/`)
  - Skips Unix system paths (`/usr/local/bin`, `/usr/bin`) for efficiency

- **Linux/macOS:** Only checks Unix-specific paths (`~/.local/bin/`, `/usr/local/bin/`)
  - Skips Windows paths (`AppData/Local/ppxai`) for efficiency

This reduces unnecessary filesystem checks and improves startup time (~10-20% faster on first run).

---

## Updating

### Linux / macOS

```bash
curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash
```

### Windows

```powershell
.\install.ps1 -Force
```

This will download and replace the binaries with the latest version.

## Uninstalling

### Linux / macOS (Automated)

```bash
# Uninstall ppxai (preserves config files)
curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash -s -- --uninstall
```

### Linux / macOS (Manual)

```bash
# Remove binaries
rm ~/.local/bin/ppxai
rm ~/.local/bin/ppxaide
rm ~/.local/bin/ppxai-server
rm ~/.local/bin/ppxai-desktop
rm ~/.local/bin/ppxai-*.vsix

# Remove Linux desktop integration (if installed)
rm ~/.local/share/applications/ppxai.desktop
rm ~/.local/share/icons/hicolor/128x128/apps/ppxai.png

# Remove macOS app (if installed)
rm -rf /Applications/ppxai.app

# Remove macOS LaunchAgent (if installed)
launchctl unload ~/Library/LaunchAgents/com.ppxai.server.plist 2>/dev/null
rm ~/Library/LaunchAgents/com.ppxai.server.plist

# Remove configuration (optional)
rm -rf ~/.ppxai
```

### Windows

```powershell
# Run uninstaller
.\install.ps1 -Uninstall

# Or manually remove
Remove-Item -Recurse $env:USERPROFILE\.ppxai
```

### VSCode Extension

```bash
code --uninstall-extension ppxai.ppxai
```
