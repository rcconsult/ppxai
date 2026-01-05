# Installation Guide

This guide covers installing ppxai for both terminal (TUI) and VSCode extension use.

## Quick Install

### Linux / macOS

```bash
curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash
```

This installs both the terminal app (`ppxai`) and the server (`ppxai-server`) to `~/.local/bin`.

#### Installation Options

```bash
# Install specific version
curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash -s -- --version v1.13.2

# Install with VSCode extension
curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash -s -- --with-extension

# Install only the server (for VSCode users who don't need TUI)
curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash -s -- --server-only

# Install to custom directory
curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash -s -- --install-dir /usr/local/bin
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
.\install.ps1 -Version v1.13.2

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
# Check TUI
ppxai --version

# Check server
ppxai-server --version
```

## Using the Terminal UI (TUI)

Start the terminal chat interface:

```bash
ppxai
```

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

## Using the VSCode Extension

### Option A: Install from VSIX (Downloaded with --with-extension)

```bash
# Install the extension
code --install-extension ~/.local/bin/ppxai-1.13.2.vsix

# Or drag and drop the .vsix file into VSCode
```

### Option B: Download VSIX from GitHub Releases

1. Go to [GitHub Releases](https://github.com/rcconsult/ppxai/releases)
2. Download `ppxai-VERSION.vsix`
3. Install: `code --install-extension ppxai-VERSION.vsix`

### Starting the Server

The VSCode extension requires `ppxai-server` to be running. There are two ways to start it:

**Option 1: Automatic (v1.13.2+)**

The extension auto-starts `ppxai-server` when you open the chat panel. Just open the ppxai chat and wait a few seconds.

**Option 2: Click the Server Badge (v1.13.1+)**

In the ppxai chat panel, click the "Disconnected" badge to start the server.

**Option 3: Start Manually**

```bash
ppxai-server
```

The server runs on `http://127.0.0.1:54320` by default.

### Extension Features

- **Chat Panel** - Full AI chat interface in the sidebar
- **Server Control** - Auto-start server from the UI (v1.13.2+)
- **Tools** - Enable AI tools (file reading, shell commands, etc.)
- **Agent Mode** - Autonomous task execution with checkpoints
- **Code Actions** - Explain, generate tests, generate docs from context menu

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

| Platform | TUI Binary | Server Binary |
|----------|------------|---------------|
| macOS ARM (M1/M2) | `ppxai-macos-arm64` | `ppxai-server-macos-arm64` |
| macOS Intel | `ppxai-macos-intel` | `ppxai-server-macos-intel` |
| Linux x64 | `ppxai-linux-amd64` | `ppxai-server-linux-amd64` |
| Windows | `ppxai-windows.exe` | `ppxai-server-windows.exe` |

Download from [GitHub Releases](https://github.com/rcconsult/ppxai/releases).

### Linux/macOS

```bash
chmod +x ppxai-linux-amd64
mv ppxai-linux-amd64 ~/.local/bin/ppxai
```

### Windows

```powershell
# Move to installation directory
Move-Item ppxai-windows.exe $env:USERPROFILE\.ppxai\bin\ppxai.exe
```

## Configuration

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

Or wait for the VSCode extension to auto-start it (v1.13.2+).

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

### Linux / macOS

```bash
# Remove binaries
rm ~/.local/bin/ppxai
rm ~/.local/bin/ppxai-server
rm ~/.local/bin/ppxai-*.vsix

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
