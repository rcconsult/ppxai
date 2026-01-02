# ppxai - Multi-LLM Interface for Developers

**Open-source AI assistant with zero vendor lock-in.** Use your favorite LLM provider in the terminal or VSCode—switch models mid-session, run locally, pay only for what you need.

## Why ppxai?

| Problem | ppxai Solution |
|---------|----------------|
| Locked to one AI vendor | Switch between Perplexity, Gemini, OpenAI, OpenRouter, Ollama anytime |
| Expensive API costs | Use local models, free tiers, or cheapest provider that works |
| Closed-source tools | Fully OSS—inspect, modify, self-host |
| Terminal OR IDE | Same experience in both—TUI + VSCode extension |

## Quick Start

### Option 1: Standalone Binary (No Python Required)

1. Download from [Releases](../../releases):
   - `ppxai-{platform}` (TUI binary)
   - `ppxai-server-{platform}` + `ppxai-1.12.1.vsix` (for VSCode)

2. Create `.env` with your API key:
   ```bash
   PERPLEXITY_API_KEY=pplx-xxxxx   # or GEMINI_API_KEY, OPENAI_API_KEY, etc.
   ```

3. Run: `./ppxai` (TUI) or `./ppxai-server` + install VSIX (VSCode)

### Option 2: From Source

```bash
git clone https://github.com/rcconsult/ppxai.git && cd ppxai
python scripts/bootstrap.py --all   # Auto-downloads uv, installs deps
cp .env.example .env                # Add your API keys
uv run ppxai                        # Start TUI
```

## Features

### Multi-Provider Support
- **Perplexity AI** - Real-time search with citations
- **Google Gemini** - 2.5 Flash/Pro with 1M context
- **OpenAI** - GPT-4o, o1
- **OpenRouter** - Claude, Llama, 100+ models
- **Local** - Ollama, vLLM, llama.cpp

Switch providers anytime: `/provider gemini` or `/model gpt-4o`

### Dual Interface
| TUI (Terminal) | VSCode Extension |
|----------------|------------------|
| Rich markdown rendering | Webview chat panel |
| Tab autocomplete for `/` commands | Right-click: Explain, Test, Docs |
| `@file`, `@git`, `@tree` context | Same context injection |
| Status bar with provider/model | Provider/model switcher |
| Streaming responses | SSE streaming |

### UX Highlights
- **Full Markdown Rendering** - Tables, code blocks with syntax highlighting, clickable links (OSC 8), citations with URLs
- **Context Preservation** - Switch providers/models mid-conversation without losing history. Start with cheap model, switch to powerful one when needed
- **Smart Context Injection** - `@file` for code, `@git` for uncommitted changes, `@tree` for project structure
- **Cost Control** - Use Perplexity for research, Gemini for long context, local models for sensitive code—all in one session

### Agent Mode (v1.11.9)
Enable with `/agent on` or click the Agent button in VSCode:
- Iterative tool execution with automatic re-prompting
- AI decides when to use tools and chains multiple calls
- Consent-based safety for file edits and shell commands
- Works with any provider that supports tool calling

See [docs/AGENT_MODE_GUIDE.md](docs/AGENT_MODE_GUIDE.md) for details.

### AI Tools
Enable with `/tools enable` (or use Agent Mode):
- `search_files`, `read_file`, `list_directory` - Filesystem access
- `execute_shell_command` - With consent system (safe/dangerous/blocked)
- `apply_patch`, `replace_block`, `insert_text` - File editing with consent
- `calculator`, `get_datetime`, `web_search` - Utilities

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
- Token usage and cost tracking

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
- `~/.ppxai/usage.json` - Usage stats

No telemetry. No tracking. Data only goes to the LLM provider you choose.

## Documentation

| Guide | Description |
|-------|-------------|
| [VSCode Extension](vscode-extension/README.md) | Installation and usage |
| [Agent Mode](docs/AGENT_MODE_GUIDE.md) | Iterative tool execution |
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
│   └── server/               # HTTP + JSON-RPC servers
├── vscode-extension/         # VSCode extension (TypeScript)
├── tests/                    # 340+ tests
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

**ppxai** is not trying to be an autonomous coding agent. It's a simple, flexible interface for chatting with LLMs—use whatever model fits your task and budget, in terminal or IDE.
