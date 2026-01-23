# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ppxai is a terminal-based UI application for interacting with multiple AI providers (Perplexity AI, OpenAI, OpenRouter, local models). It provides an interactive chat interface with model selection, conversation history, streaming responses, and AI-powered tools.

**Current Version:** v1.14.2

**v1.14.2 highlights:**
- **NEW:** Hierarchical context scopes - global (`~/.ppxai/`), project (git root), subdir (cwd)
- **NEW:** `/context show` command - displays bootstrap sources with scope labels
- **NEW:** `@clipboard` and `@url` context providers - inject clipboard text or web content
- **NEW:** Include directive - `<!-- include: ./file.md -->` for modular AGENTS.md
- **NEW:** Hint templates - reusable hints in `~/.ppxai/hint-templates.yaml`
- **CHANGE:** Gemini default model updated to `gemini-2.5-flash` (2.0 deprecated March 2026)
- **CHANGE:** Provider/model hints from all scopes merge additively

**v1.14.1 highlights:**
- `/edit` command for VSCode - opens files in native editor with line:col support
- `/edit` command for Web App - Monaco-style editor with syntax highlighting
- `/context reload` command - refresh AGENTS.md without restarting session

**v1.14.0 highlights:**
- AGENTS.md/CLAUDE.md bootstrap context support - project-specific instructions loaded on startup
- YAML front matter for provider/model-specific hints (dynamic prompt assembly)
- `local` provider inheritance - ollama, vllm, lmstudio inherit from `local` hints

**Version Alignment:**
- Python package (pyproject.toml): v1.14.2
- VSCode extension (package.json): v1.14.2
- Git tag: v1.14.2

For detailed release history, see [CHANGELOG.md](CHANGELOG.md) and `docs/RELEASE-NOTES-v*.md`.

## Codebase Statistics (v1.14.0)

| Language | Files | Lines |
|----------|------:|------:|
| Python (core) | 66 | ~24,100 |
| Python (tests) | 30 | ~11,800 |
| TypeScript (VSCode) | 17 | ~8,300 |
| JavaScript (Web) | 7 | ~5,200 |
| CSS | 3 | ~2,000 |
| **Total** | **~123** | **~51,400** |

Breakdown: ~70% Python, ~16% TypeScript, ~10% JavaScript, ~4% CSS/HTML

## Installation Locations (CRITICAL)

**IMPORTANT: Follow these exact paths. NEVER use `AppData\Local\ppxai` on Windows.**

| Item | Linux | macOS | Windows |
|------|-------|-------|---------|
| **Binaries** | `~/.local/bin/` | `~/.local/bin/` | `~/.ppxai/bin/` |
| **App bundle** | - | `/Applications/ppxai.app` | - |
| **Config** | `~/.ppxai/ppxai-config.json` | `~/.ppxai/ppxai-config.json` | `~/.ppxai/ppxai-config.json` |
| **API keys** | `~/.ppxai/.env` | `~/.ppxai/.env` | `~/.ppxai/.env` |
| **Data** | `~/.ppxai/` | `~/.ppxai/` | `~/.ppxai/` |
| **Web UI** | `~/.ppxai/web/` | `~/.ppxai/web/` | `~/.ppxai/web/` |

**Windows structure (`%USERPROFILE%\.ppxai\`):**
```
~/.ppxai/
├── bin/                    # Binaries
│   ├── ppxai.exe          # TUI binary
│   ├── ppxai-server.exe   # Server binary
│   └── ppxai-desktop.exe  # Desktop app binary
├── web/                    # Web UI files (app.js, index.html, lib/)
│   ├── lib/               # JavaScript libraries (js-yaml, toml, hcl2-parser, etc.)
│   └── shared/            # Shared command definitions
├── sessions/              # Saved sessions
├── exports/               # Exported markdown files
├── checkpoints/           # File-based undo snapshots
├── logs/                  # Debug logs
├── usage/                 # Usage statistics
├── ppxai-config.json      # User configuration
└── .env                   # API keys
```

**Linux/macOS structure:**
```
~/.local/bin/
├── ppxai                   # TUI binary
├── ppxai-server            # Server binary
└── ppxai-desktop           # Desktop app binary

~/.ppxai/
├── web/                    # Web UI files
├── sessions/              # Saved sessions
├── exports/               # Exported markdown files
├── checkpoints/           # File-based undo snapshots
├── logs/                  # Debug logs
├── usage/                 # Usage statistics
├── ppxai-config.json      # User configuration
└── .env                   # API keys
```

**When deploying/copying files:**
- **Windows**: Use `~/.ppxai/bin/` for binaries, `~/.ppxai/` for data + web
- **Linux/macOS**: Use `~/.local/bin/` for binaries, `~/.ppxai/` for data + web

The `AppData\Local\ppxai` path exists only as a **search path** for finding binaries, NOT as an installation target.

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
│   ├── chatPanel.ts     # Webview chat UI
│   └── handlers/        # Extracted handlers (Phase 2-4)
│       ├── eventBus.ts  # Pub/sub communication
│       ├── stream.ts    # Stream event processing
│       ├── consent.ts   # Consent dialog handlers
│       └── agentStateMachine.ts  # Agent loop state
├── media/webview/       # External CSS/JS (Phase 1)
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

## vLLM/GPT-OSS Tool Calling Reference

**Problem:** vLLM with GPT-OSS models can hit `HarmonyError: unexpected tokens remaining in message header` when using native tool calling (`--enable-auto-tool-choice --tool-call-parser openai`). This is a known vLLM/Harmony library issue ([vLLM #23567](https://github.com/vllm-project/vllm/issues/23567)).

**ppxai supports two tool calling modes:**

| Mode | Config | vLLM Flags | Reliability |
|------|--------|------------|-------------|
| **Native** | `native_tool_calling: true` | `--enable-auto-tool-choice --tool-call-parser openai` | ⚠️ HarmonyError risk |
| **Prompt-Based** | `native_tool_calling: false` | None required | ✅ Stable |

**Key insight:** vLLM only triggers Harmony parsing when `request.tools` is provided. With `native_tool_calling: false`, ppxai doesn't send `tools` parameter, so vLLM returns plain text that ppxai parses client-side.

**Implementation details:**
- Tool prompt injection: `ppxai/engine/tools/manager.py:get_tools_prompt()`
- Multi-strategy parser: `ppxai/engine/tools/parser.py:parse_tool_call()`
- GPT-OSS nested unwrapping: `ppxai/engine/tools/parser.py:_normalize_tool_call()`
- Parameter aliasing: `ppxai/engine/tools/manager.py:PARAM_ALIAS_GROUPS`

**Documentation:**
- [docs/vllm-tool-calling-guide.md](docs/vllm-tool-calling-guide.md) - ppxai-specific guide
- [docs/prompt-based-tool-calling.md](docs/prompt-based-tool-calling.md) - General developer guide
- [examples/prompt_based_tools.py](examples/prompt_based_tools.py) - Standalone example

**Current production setup:**
- vLLM 0.11.x nightly with LMCache
- `--tool-call-parser openai` (correct flag)
- Model: `openai/gpt-oss-120b`
- ppxai default: `native_tool_calling: true`

**For developers hitting HarmonyError:** Set `native_tool_calling: false` in provider config, or use the standalone example for non-ppxai applications.

## Commit Guidelines

- Do NOT include Claude credits or co-authored-by lines. Keep commit messages clean.
- **Never commit sensitive information:** tokens, API keys, passwords, hostnames, usernames, file paths with usernames, or other environment-specific details.
- In PRs and documentation, use generic placeholders (e.g., `your-token`, `/path/to/project`) instead of real values.
