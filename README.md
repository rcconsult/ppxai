# ppxai - Multi-LLM Interface for Developers

![Version](https://img.shields.io/badge/version-1.13.3-blue) ![Tests](https://img.shields.io/badge/tests-583%20passing-green) ![License](https://img.shields.io/badge/license-MIT-brightgreen)

**Open-source AI assistant with zero vendor lock-in.** Use your favorite LLM provider in the terminal or VSCode—switch models mid-session, run locally, pay only for what you need.

## Why ppxai?

| Problem | ppxai Solution |
|---------|----------------|
| Locked to one AI vendor | Switch between Perplexity, Gemini, OpenAI, OpenRouter, Ollama anytime |
| Expensive API costs | Use local models, free tiers, or cheapest provider that works |
| Closed-source tools | Fully OSS—inspect, modify, self-host |
| Terminal OR IDE | Same experience everywhere—TUI, Desktop App, VSCode extension |

## Quick Start

### Option 1: One-Line Install (Recommended)

```bash
curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash
```

This installs `ppxai`, `ppxai-server`, and `ppxai-desktop` to `~/.local/bin`. Then:

```bash
# Add to PATH (if not already)
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc

# Set up API key
echo 'PERPLEXITY_API_KEY=pplx-xxxxx' > ~/.ppxai/.env

# Run TUI
ppxai

# Or run Desktop Web App (browser-based UI)
ppxai-desktop
```

**Installation options:**
- With config templates: `curl -sSL ... | bash -s -- --with-config` (recommended for first-time setup)
- With VSCode extension: `curl -sSL ... | bash -s -- --with-extension`
- With Linux desktop integration: `curl -sSL ... | bash -s -- --with-desktop`
- macOS app bundle: `curl -sSL ... | bash -s -- --with-macos-app`
- Full macOS setup: `curl -sSL ... | bash -s -- --with-macos-app --with-config --with-launchagent`
- Uninstall: `curl -sSL ... | bash -s -- --uninstall`

See [docs/INSTALLATION.md](docs/INSTALLATION.md) for detailed installation options.

### Option 2: Download Binaries

Download from [Releases](../../releases):
- `ppxai-{platform}` - Terminal UI
- `ppxai-server-{platform}` - HTTP server for VSCode
- `ppxai-desktop-{platform}` - Desktop Web App
- `ppxai-1.13.3.vsix` - VSCode extension
- `ppxai-*-macos-arm64.dmg` - macOS app bundle installer

### Option 3: From Source

```bash
git clone https://github.com/rcconsult/ppxai.git && cd ppxai
python scripts/bootstrap.py --all   # Auto-downloads uv, installs deps
cp .env.example .env                # Add your API keys
uv run ppxai                        # Start TUI
```

## Features

### Multi-Provider Support
- **Perplexity AI** - Real-time search with citations
- **Google Gemini** - 2.5 Flash/Pro with 1M context, Google Search Grounding
- **OpenAI** - GPT-4o, o1
- **OpenRouter** - Claude, Llama, 100+ models
- **Local** - Ollama, vLLM, llama.cpp

Switch providers anytime: `/provider gemini` or `/model gpt-4o`

**Enhanced Gemini support (v1.12.5+):** Install `pip install ppxai[gemini]` for native Google Search Grounding with citations. **v1.13.3+:** Tools and grounding now work together—use file editing tools while keeping native web search with citations.

### Triple Interface
| TUI (Terminal) | Desktop Web App | VSCode Extension |
|----------------|-----------------|------------------|
| Rich markdown rendering | Browser-based UI | Webview chat panel |
| Tab autocomplete for `/` commands | Full slash commands | Right-click: Explain, Test, Docs |
| `@file`, `@git`, `@tree` context | Same context injection | Same context injection |
| Status bar with provider/model | Provider/model badges | Provider/model switcher |
| Streaming responses | SSE streaming | SSE streaming |

**Desktop Web App (v1.13.1+):** Run `ppxai-desktop` to launch a browser-based chat interface. macOS users can download the `.dmg` installer for a native app experience.

### UX Highlights
- **Full Markdown Rendering** - Tables, code blocks with syntax highlighting, clickable links (OSC 8), citations with URLs
- **Context Preservation** - Switch providers/models mid-conversation without losing history. Start with cheap model, switch to powerful one when needed
- **Smart Context Injection** - `@file` for code, `@git` for uncommitted changes, `@tree` for project structure
- **Cost Control** - Use Perplexity for research, Gemini for long context, local models for sensitive code—all in one session
- **Real-time Usage Tracking** - Token counts and cost estimates in status line (`1.2K↓/0.5K↑ $0.0045`)
- **Themed TUI Panels** - 4 themes: Standard, Tron Legacy, Matrix, Nord (`/theme` to switch)

### Agent Mode
Enable with `/agent on` or click the Agent button in VSCode:
- Iterative tool execution with automatic re-prompting
- AI decides when to use tools and chains multiple calls
- Consent-based safety for file edits and shell commands
- Works with any provider that supports tool calling

See [docs/AGENT_MODE_GUIDE.md](docs/AGENT_MODE_GUIDE.md) for details.

### Checkpoint & Undo (v1.12.0+)
Atomic rollback for multi-file agent operations:
- `/undo` reverts all changes from the last agent task
- `/checkpoint` - Manage checkpoints (status, list, backend, clear, info)
- Git backend: auto-commits before tasks, `git revert` to undo
- File backend (fallback): snapshots to `~/.ppxai/checkpoints/`

See [docs/CHECKPOINT_GUIDE.md](docs/CHECKPOINT_GUIDE.md) for details.

### AI Tools
Enable with `/tools enable` (or use Agent Mode):
- `search_files`, `read_file`, `list_directory` - Filesystem access
- `execute_shell_command` - With consent system (safe/dangerous/blocked)
- `apply_patch`, `replace_block`, `insert_text`, `delete_lines` - File editing with consent
- `calculator`, `get_datetime`, `get_working_directory` - Utilities
- `web_search` - Premium web search (Perplexity/Gemini/DuckDuckGo fallback)

### Coding Commands
```
/generate   Generate code from description
/test       Generate unit tests
/docs       Generate documentation
/explain    Explain code logic
/debug      Analyze errors
/convert    Translate between languages
```

### Session Management
- Auto-save every 10 messages
- `/sessions` - Browse saved conversations
- `/export` - Export to markdown
- `/usage [24h|week|month|all]` - View token counts and cost estimates

## Configuration

**Simple (one provider):**
```bash
# .env
PERPLEXITY_API_KEY=pplx-xxxxx
```

**Multi-provider:**
```bash
# .env - API keys only
PERPLEXITY_API_KEY=pplx-xxxxx
GEMINI_API_KEY=AIza-xxxxx
OPENAI_API_KEY=sk-xxxxx
OPENROUTER_API_KEY=sk-or-xxxxx
```

```json
// ppxai-config.json - Provider definitions (optional, has defaults)
{
  "default_provider": "gemini",
  "providers": {
    "my-local": {
      "name": "Local Ollama",
      "base_url": "http://localhost:11434/v1",
      "api_key_env": "OLLAMA_API_KEY",
      "default_model": "llama3.2"
    }
  }
}
```

See [docs/PROVIDER_SETUP.md](docs/PROVIDER_SETUP.md) for detailed examples.

## Data Privacy

All data stays on your machine:
- `~/.ppxai/sessions/` - Conversation history
- `~/.ppxai/exports/` - Markdown exports
- `~/.ppxai/usage/` - Usage statistics
- `~/.ppxai/checkpoints/` - File-based undo snapshots
- `~/.ppxai/logs/` - Debug logs (when enabled)

No telemetry. No tracking. Data only goes to the LLM provider you choose.

## Documentation

| Guide | Description |
|-------|-------------|
| [VSCode Extension](vscode-extension/README.md) | Installation and usage |
| [Agent Mode](docs/AGENT_MODE_GUIDE.md) | Iterative tool execution |
| [Checkpoint & Undo](docs/CHECKPOINT_GUIDE.md) | Atomic rollback for agent tasks |
| [Provider Setup](docs/PROVIDER_SETUP.md) | Configure any OpenAI-compatible API |
| [Tool Development](docs/CUSTOM_TOOL_DEVELOPMENT_GUIDE.md) | Add custom tools |
| [Shell Consent](docs/SHELL_CONSENT_GUIDE.md) | Command safety system |
| [File Editing](docs/FILE_EDITING_GUIDE.md) | Consent-based file operations |
| [Specifications](SPECIFICATIONS.md) | Code generation templates |

## Project Structure

```
ppxai/
├── ppxai/                    # Core package
│   ├── main.py               # TUI entry point
│   ├── engine/               # EngineClient, providers, tools
│   ├── server/               # HTTP + JSON-RPC servers
│   ├── web/                  # Desktop Web App static files
│   └── common/               # Shared utilities (logger, event handler)
├── vscode-extension/         # VSCode extension (TypeScript)
├── scripts/                  # Build, release, install scripts
├── resources/                # Icons (PNG, ICO, ICNS) and desktop files
├── tests/                    # 579 tests
└── docs/                     # Documentation
```

## Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md).

```bash
uv run pytest tests/ -v       # Run tests
uv run ppxai-server           # Start server for VSCode dev
```

## License

MIT

---

**ppxai** is a flexible interface for chatting with LLMs—with optional agent capabilities when you need them. Use whatever model fits your task and budget, in terminal or IDE, with full control over when AI can modify your files.
