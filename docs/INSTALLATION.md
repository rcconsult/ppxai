# Installation Guide

This guide covers installing ppxai for both terminal (TUI) and VSCode extension use.

## Quick Install (Recommended)

The easiest way to install ppxai is using the one-line installer:

```bash
curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash
```

This installs both the terminal app (`ppxai`) and the server (`ppxai-server`) to `~/.local/bin`.

### Installation Options

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

## Post-Installation Setup

### 1. Add to PATH

If `~/.local/bin` is not in your PATH, add it to your shell configuration:

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

### 2. Set Up API Key

Create the ppxai config directory and add your API key:

```bash
mkdir -p ~/.ppxai
echo 'PERPLEXITY_API_KEY=your-key-here' > ~/.ppxai/.env
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

**Option 1: Click the Server Badge (v1.13.1+)**

In the ppxai chat panel, click the "Disconnected" badge to start the server automatically.

**Option 2: Start Manually**

```bash
ppxai-server
```

The server runs on `http://127.0.0.1:54320` by default.

### Extension Features

- **Chat Panel** - Full AI chat interface in the sidebar
- **Server Control** - Start/stop server from the UI (v1.13.1+)
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

Download from [GitHub Releases](https://github.com/rcconsult/ppxai/releases), make executable, and move to your PATH.

## Configuration

### API Keys

ppxai supports multiple AI providers. Add keys to `~/.ppxai/.env`:

```bash
# Perplexity (default)
PERPLEXITY_API_KEY=your-key-here

# Google Gemini
GEMINI_API_KEY=your-key-here

# OpenAI
OPENAI_API_KEY=your-key-here

# OpenRouter
OPENROUTER_API_KEY=your-key-here
```

### Provider Configuration

For advanced provider configuration, create `~/.ppxai/ppxai-config.json`:

```json
{
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

Add `~/.local/bin` to your PATH (see Post-Installation Setup above).

### "Could not connect to ppxai-server"

Make sure the server is running:
```bash
ppxai-server
```

Or click the server badge in VSCode to start it.

### "No API key configured"

Add your API key to `~/.ppxai/.env`:
```bash
echo 'PERPLEXITY_API_KEY=your-key-here' > ~/.ppxai/.env
```

### Server Port Already in Use

Kill any existing server process:
```bash
pkill -f ppxai-server
```

Then restart:
```bash
ppxai-server
```

## Updating

To update to the latest version:

```bash
curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash
```

This will download and replace the binaries with the latest version.

## Uninstalling

Remove the installed binaries:

```bash
rm ~/.local/bin/ppxai
rm ~/.local/bin/ppxai-server
rm ~/.local/bin/ppxai-*.vsix
```

Remove configuration (optional):
```bash
rm -rf ~/.ppxai
```

Uninstall VSCode extension:
```bash
code --uninstall-extension ppxai.ppxai
```
