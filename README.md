# ppxai - Multi-LLM Interface for Developers

![Version](https://img.shields.io/badge/version-1.15.0--dev-blue) ![Tests](https://img.shields.io/badge/tests-1105%20passing-green) ![License](https://img.shields.io/badge/license-MIT-brightgreen) [![Docs](https://img.shields.io/badge/docs-rcconsult.github.io%2Fppxai-blue)](https://rcconsult.github.io/ppxai/)

> **Development Branch:** This is the `feature/new-tui-command` branch with the new type-based renderer architecture. See the [v1.15.0 release notes](docs/RELEASE-NOTES-v1.15.0.md) for details on the 17 CommandResult types and mechanical UI dispatch.

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

**Linux / macOS:**
```bash
curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash
```

**Windows (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/rcconsult/ppxai/master/scripts/install.ps1 | iex
```

This installs `ppxai` (Rich TUI), `ppxaide` (Textual TUI), `ppxai-server`, and `ppxai-desktop`. Then:

```bash
# Add to PATH (if not already)
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc

# Set up API key
echo 'PERPLEXITY_API_KEY=pplx-xxxxx' > ~/.ppxai/.env

# Run Rich TUI (original)
ppxai

# Or run Textual TUI (new in v1.15.0)
ppxaide

# Or run Desktop Web App (browser-based UI)
ppxai-desktop
```

**Installation options (Linux/macOS):**
- With config templates: `curl -sSL ... | bash -s -- --with-config` (recommended for first-time setup)
- With VSCode extension: `curl -sSL ... | bash -s -- --with-extension`
- With Linux desktop integration: `curl -sSL ... | bash -s -- --with-desktop`
- macOS app bundle: `curl -sSL ... | bash -s -- --with-macos-app`
- Full macOS setup: `curl -sSL ... | bash -s -- --with-macos-app --with-config --with-launchagent`
- Uninstall: `curl -sSL ... | bash -s -- --uninstall`

**Windows options:** `install.ps1 -Force` (reinstall), `-Version v1.15.0` (specific version), `-Uninstall`

See [docs/INSTALLATION.md](docs/INSTALLATION.md) for detailed installation options including Windows.

### Option 2: Download Binaries

Download from [Releases](../../releases):
- `ppxai-{platform}` - Rich TUI (original)
- `ppxaide-{platform}` - Textual TUI (new in v1.15.0)
- `ppxai-server-{platform}` - HTTP server for VSCode
- `ppxai-desktop-{platform}` - Desktop Web App
- `ppxai-1.15.0.vsix` - VSCode extension
- `ppxai-*-macos-arm64.dmg` - macOS app bundle installer

### Option 3: From Source

```bash
git clone https://github.com/rcconsult/ppxai.git && cd ppxai
python scripts/bootstrap.py --all   # Auto-downloads uv, installs deps
cp .env.example .env                # Add your API keys
uv run ppxai                        # Start Rich TUI
uv run ppxaide                      # Or start Textual TUI
```

## Features

### v1.15.0 Architecture: Type-Based Renderer Dispatch

The core innovation in v1.15.0 is a revolutionary renderer architecture that **completely decouples command logic from UI presentation**:

- **17 CommandResult types** - Structured data for all command outputs (MessageResult, TableResult, CodeResult, ErrorResult, etc.)
- **Mechanical dispatch** - `isinstance()` checks route results to renderers, zero conditionals
- **2 renderer implementations** - RichRenderer (legacy TUI) + TextualRenderer (ppxaide)
- **UI-agnostic commands** - Same command code works in TUI, VSCode, Web, future GUIs
- **100% testable** - Commands tested without UI framework dependencies

**Example:**
```python
# Command returns typed result
result = show_command.execute("file.py")
# → Returns CodeResult(content="...", language="python")

# Renderer mechanically dispatches
if isinstance(result, CodeResult):
    renderer.render_code(result)  # TUI uses Rich syntax highlighting
```

This enables **single-source command logic** that renders correctly in any UI—terminal, VSCode webview, or browser—just by swapping the renderer implementation.

See [Architecture Docs](docs/ARCHITECTURE.md) and [v1.15.0 Release Notes](docs/RELEASE-NOTES-v1.15.0.md) for details.

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
| **ppxai** - Rich TUI (original) | Browser-based UI | Webview chat panel |
| **ppxaide** - Textual TUI (v1.15.0+) | Full slash commands | Right-click: Explain, Test, Docs |
| Tab autocomplete for `/` commands | Same context injection | Same context injection |
| `@file`, `@git`, `@tree` context | Provider/model badges | Provider/model switcher |
| Status bar with provider/model | SSE streaming | SSE streaming |

**ppxaide features (v1.15.0+):**
- **Type-based renderer architecture** - All 32 commands return structured result objects (17 types), enabling mechanical UI dispatch without conditionals
- **Modern async architecture** with real-time streaming
- **17+ themes** (vs 6 in Rich TUI) - cycle with Ctrl+T or Ctrl+P for palette
- **Advanced file viewers** with tree/table/image support via typed results
- **Real-time token/cost tracking** in status bar with smart formatting
- **Tool execution display** with formatted arguments/results
- **Bootstrap context auto-loading** from AGENTS.md
- **UI-agnostic commands** - Same command logic works in TUI, VSCode, and Web

**Desktop Web App (v1.13.1+):** Run `ppxai-desktop` to launch a browser-based chat interface. macOS users can download the `.dmg` installer for a native app experience.

### UX Highlights
- **Full Markdown Rendering** - Tables, code blocks with syntax highlighting, clickable links (OSC 8), citations with URLs
- **Context Preservation** - Switch providers/models mid-conversation without losing history. Start with cheap model, switch to powerful one when needed
- **Smart Context Injection** - `@file` for code, `@git` for uncommitted changes, `@tree` for project structure, `@clipboard` for clipboard text, `@url` for web content. Hash-based deduplication prevents duplicate injections.
- **Context Management** - `/context` shows usage vs model limit, `/context show` displays bootstrap hierarchy, `/context clear` removes injected files. Context badge shows percentage in TUI status line and VSCode header.
- **Cost Control** - Use Perplexity for research, Gemini for long context, local models for sensitive code—all in one session
- **Real-time Usage Tracking** - Token counts and cost estimates in status line (`1.2K↓/0.5K↑ $0.0045`)
- **Themed TUI Panels** - Rich TUI: 6 themes; Textual TUI (ppxaide): 17+ themes (`/theme` to cycle or Ctrl+T)

### Agent Mode
Enable with `/agent on` or click the Agent button in VSCode:
- Iterative tool execution with automatic re-prompting
- AI decides when to use tools and chains multiple calls
- Consent-based safety for file edits and shell commands
- Works with any provider that supports tool calling

See [docs/AGENT_MODE_GUIDE.md](docs/AGENT_MODE_GUIDE.md) for details.

### Bootstrap Context (v1.14.0+)
Load project-specific instructions from `AGENTS.md` or `CLAUDE.md`:
- **Hierarchical scopes** (v1.14.2) - Global (`~/.ppxai/AGENTS.md`), project (git root), subdirectory (cwd)
- **Auto-discovery** - Looks for `AGENTS.md`, then `CLAUDE.md` in each scope
- **Provider hints** - Different instructions for Ollama vs Gemini vs OpenAI
- **Model hints** - Pattern-matched guidance (e.g., `deepseek-r1*` gets reasoning prompts)
- **`local` inheritance** - Ollama, vLLM, LMStudio inherit from `local` hints
- **Include directive** (v1.14.2) - `<!-- include: ./docs/style.md -->` for modular configs
- **Hint templates** (v1.14.2) - Reusable hints in `~/.ppxai/hint-templates.yaml`

Example `AGENTS.md`:
```markdown
---
provider_hints:
  local:
    - "Complete tasks fully without stopping on empty responses."
  ollama:
    - "Keep responses concise - limited context window."
model_hints:
  "deepseek-r1*":
    - "Show reasoning before taking actions."
---

# Project Instructions
Python 3.11+, type hints required, pytest for testing.
```

Use `/context hints` to see active hints, `/context show` to see bootstrap hierarchy.

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
| [Architecture](docs/ARCHITECTURE.md) | Type-based renderer design (v1.15.0) |
| [Release Notes v1.15.0](docs/RELEASE-NOTES-v1.15.0.md) | Latest development features |

## Project Structure

```
ppxai/
├── ppxai/                    # Core package
│   ├── rich/main.py          # Rich TUI entry point (legacy)
│   ├── tui/                  # Textual TUI (ppxaide - v1.15.0+)
│   │   ├── app.py            # Main Textual application
│   │   ├── widgets/          # UI components (chat_view, code_editor, etc.)
│   │   └── renderer.py       # TextualRenderer - type-based dispatch
│   ├── engine/               # EngineClient, providers, tools
│   ├── commands/             # 32 UI-agnostic command implementations
│   │   └── types.py          # 17 CommandResult types
│   ├── renderers/            # Renderer implementations
│   │   ├── rich_renderer.py  # RichRenderer for legacy TUI
│   │   └── base.py           # BaseRenderer interface
│   ├── server/               # HTTP + JSON-RPC servers
│   ├── web/                  # Desktop Web App static files
│   └── common/               # Shared utilities (logger, event handler)
├── vscode-extension/         # VSCode extension (TypeScript)
├── scripts/                  # Build, release, install scripts
├── resources/                # Icons (PNG, ICO, ICNS) and desktop files
├── tests/                    # 1105 tests
└── docs/                     # Documentation
```

## Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md).

```bash
uv run pytest tests/ -v       # Run tests
uv run ppxai                  # Rich TUI
uv run ppxaide                # Textual TUI (v1.15.0+)
uv run ppxai-server           # Start server for VSCode dev
```

## License

MIT

---

**ppxai** is a flexible interface for chatting with LLMs—with optional agent capabilities when you need them. Use whatever model fits your task and budget, in terminal or IDE, with full control over when AI can modify your files.
