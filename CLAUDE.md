# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ppxai is a terminal-based UI application for interacting with multiple AI providers (Perplexity AI, OpenAI, OpenRouter, local models). It provides an interactive chat interface with model selection, conversation history, streaming responses, and AI-powered tools.

**Current Version:** v1.13.5

**Post-v1.13.5 fixes (on master, pending next release):**
- **FIX:** Release script Windows compatibility for `gh` CLI commands
  - Uses Python environment variables instead of Unix shell syntax
- **FIX:** UTF-8 encoding for release scripts on Windows
  - `release.py` and `validate-release.py` now configure stdout/stderr for UTF-8

**Version Alignment:**
- Python package (pyproject.toml): v1.13.5
- VSCode extension (package.json): v1.13.5
- Git tag: v1.13.5

For detailed release history, see [CHANGELOG.md](CHANGELOG.md) and `docs/RELEASE-NOTES-v*.md`.

## Development Setup

### File Encoding: UTF-8 without BOM

**IMPORTANT**: All source files MUST be UTF-8 encoded **without** BOM (Byte Order Mark).

- Windows PowerShell's `Out-File` cmdlet adds BOM by default - avoid using it
- Use `Set-Content -Encoding UTF8` or write files via Python with `encoding='utf-8'`
- The config loader uses `utf-8-sig` to handle BOM gracefully when reading

### Quick Start with uv (recommended)

```bash
# First-time setup
python scripts/bootstrap.py --all

# Or manual setup
uv sync --all-extras

# Configure API keys
cp .env.example .env
# Edit .env and add your API keys

# Run
uv run ppxai           # TUI
uv run ppxai-server    # HTTP server for VSCode

# Test
uv run pytest tests/ -v
```

### Alternative: pip

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python ppxai.py
```

## Architecture

Layered architecture with clear separation of concerns:

```
ppxai/
├── engine/              # Core business logic (no UI)
│   ├── client.py        # EngineClient facade
│   ├── types.py         # Message, Event, UsageStats
│   ├── session.py       # Session management
│   ├── providers/       # Perplexity, OpenAI-compat
│   └── tools/           # Tool system + builtins
├── server/              # HTTP/SSE server for IDE
│   └── http.py          # FastAPI endpoints
├── main.py              # TUI entry point
├── commands.py          # Slash command handlers
└── config.py            # Configuration system

vscode-extension/        # TypeScript VSCode extension
├── src/
│   ├── extension.ts     # Entry point
│   ├── httpClient.ts    # HTTP + SSE client
│   └── chatPanel.ts     # Webview chat UI
└── package.json
```

### Configuration Files

| File | Purpose | Git |
|------|---------|-----|
| `.env` | API keys (secrets) | ❌ Never commit |
| `ppxai-config.json` | Provider definitions | ✅ Can commit |

## Common Commands

```bash
# Run application
uv run ppxai                    # TUI
uv run ppxai-server             # HTTP server
uv run ppxai-desktop            # Desktop web app

# Testing
uv run pytest tests/ -v

# Build binaries (Windows with corporate proxy)
SSL_CERT_FILE="C:/.ssh/Fortinet_CA_SSL.cer" .uv/uv run pyinstaller ppxai.spec --noconfirm

# Build VSCode extension
cd vscode-extension && npm run compile && npx vsce package --allow-missing-repository

# Copy beta binaries to external drive (Windows)
# Will prompt for destination if not provided
powershell -File scripts/copy-beta.ps1 -TargetDir "I:\Software\ppxai"
```

## Release Process

**CRITICAL: Always use the `/release` skill for releases.**

```bash
/release v1.x.x
# Or: uv run python scripts/release.py v1.x.x
```

**NEVER manually:** update version files, create git tags, run `gh release create`, or upload assets.

### Files Updated by Release Script

| File | Pattern |
|------|---------|
| `pyproject.toml` | `version = "X.Y.Z"` |
| `ppxai/__init__.py` | `__version__ = "X.Y.Z"` |
| `vscode-extension/package.json` | `"version": "X.Y.Z"` |
| `vscode-extension/package-lock.json` | `"version": "X.Y.Z"` |
| `ppxai/common/event_handler.py` | `Version: vX.Y.Z` |
| `README.md` | `ppxai-X.Y.Z.vsix` |
| `vscode-extension/README.md` | `ppxai-X.Y.Z.vsix` |
| `CLAUDE.md` | `**Current Version:** vX.Y.Z` |
| `ROADMAP.md` | `**Current Version**: vX.Y.Z` |

### Pre-Release Checklist

1. Create CHANGELOG entry: `## [X.Y.Z] - YYYY-MM-DD`
2. Write release notes: `docs/RELEASE-NOTES-vX.Y.Z.md`
3. Merge feature branch to master
4. Run: `python scripts/validate-release.py vX.Y.Z`

### Release Assets (Built by CI)

- `ppxai-{version}.vsix` - VSCode extension
- `ppxai-{platform}` - TUI binaries (linux-amd64, macos-arm64, macos-intel, windows.exe)
- `ppxai-server-{platform}` - Server binaries
- `ppxai-desktop-{platform}` - Desktop web app binaries
- `ppxai-{version}-macos-arm64.dmg` - macOS installer

## GitHub CLI Authentication

Use token from `.github/gh-token.env` (gitignored):

```bash
GH_TOKEN=$(cat .github/gh-token.env) gh release list
```

## Key Design Decisions

1. **Layered Architecture** - Engine (no UI) → Server (HTTP/SSE) → Clients (TUI, VSCode, Web)
2. **Provider Abstraction** - All providers implement `BaseProvider` interface
3. **Event-Based Communication** - Engine emits events; clients render them
4. **OpenAI SDK for all providers** - OpenAI-compatible API format
5. **Hybrid config** - Secrets (`.env`) separate from settings (`ppxai-config.json`)
6. **Built-in providers** - Perplexity and Gemini always available without config

## VSCode Extension

### Installation

Download from [GitHub Releases](https://github.com/rcconsult/ppxai/releases):
- `ppxai-server-{platform}` - Server binary
- `ppxai-{version}.vsix` - Extension

```bash
code --install-extension ppxai-X.Y.Z.vsix
./ppxai-server-{platform}
```

### Extension Settings

- `ppxai.serverUrl` - Server URL (default: `http://127.0.0.1:54320`)
- `ppxai.defaultProvider` - Default AI provider
- `ppxai.defaultModel` - Default model
- `ppxai.enableTools` - Enable AI tools

### Commands

- `ppxai.openChat` - Open chat panel
- `ppxai.explainSelection` - Explain selected code
- `ppxai.generateTests` - Generate tests
- `ppxai.switchProvider` / `ppxai.switchModel` - Switch provider/model

## Known Issues

**Accepted behavior:**
- Perplexity/Gemini may use shell commands for web data instead of native search when tools enabled

**Resolved:** TUI Markdown Tables (v1.10.4), Ctrl-C Message Alternation (v1.10.5)

## Commit Guidelines

- Do NOT include Claude credits or co-authored-by lines. Keep commit messages clean.
- **Never commit sensitive information:** tokens, API keys, passwords, hostnames, usernames, file paths with usernames, or other environment-specific details.
- In PRs and documentation, use generic placeholders (e.g., `your-token`, `/path/to/project`) instead of real values.
