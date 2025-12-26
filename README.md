# ppxai - Perplexity AI Text UI

A terminal-based interface for interacting with Perplexity AI models.

## Features

### Core Features
- 🤖 Interactive chat with Perplexity AI models
- 🔄 Model selection (Sonar, Sonar Pro, Sonar Reasoning, and more)
- ⚡ Streaming responses for real-time interaction
- 🎨 Rich terminal UI with markdown rendering (headings, lists, tables, code blocks)
- 🔗 Clickable source citations in terminal
- 📝 Command history support
- 📦 Standalone executables available (no Python required!)
- 🆕 **VS Code Extension** - Full-featured chat panel in your IDE

### VS Code Extension 🆕
- 💬 **Chat Panel** - Interactive AI chat in the sidebar with markdown rendering
- 📎 **Context Injection** - Type `@filename` for files, `@git` for changes, `@tree` for project structure
- ⌨️ **Autocomplete** - Tab completion for `/` commands and `@` references
- 🛠️ **Tools Toggle** - Click badge to enable/disable AI tools
- 🖱️ **Context Menu** - Right-click commands: Explain, Generate Tests, Generate Docs
- 🔄 **Multi-Provider** - Supports all configured providers (Perplexity, OpenAI, etc.)
- 📦 **Standalone server available** - No Python needed! Download `ppxai-server` binary from releases

### Session Management
- 💾 Auto-save sessions every 10 messages
- 📂 Load and continue previous conversations
- 📤 Export conversations to markdown files
- 🗂️ Session browser with metadata

### Usage Tracking
- 📊 Real-time token usage monitoring
- 💰 Cost estimation based on model pricing
- 📈 Global usage statistics and history
- 📅 Daily usage tracking by model

### Code Generation & Analysis Tools
- 🔨 `/generate` - Generate code from natural language descriptions
- 🧪 `/test` - Generate comprehensive unit tests for code files
- 📚 `/docs` - Generate documentation for existing code
- 🏗️ `/implement` - Implement features from detailed specifications
- 🐛 `/debug` - Analyze errors, exceptions, and bugs with solutions
- 📖 `/explain` - Explain code logic and design decisions step-by-step
- 🔄 `/convert` - Convert code between programming languages
- 📋 `/spec` - Access specification templates and guidelines
- 🎯 `/autoroute` - Smart model routing for coding tasks (auto-enabled)

See [SPECIFICATIONS.md](SPECIFICATIONS.md) for detailed guides on writing effective specifications for code generation.

### AI Tools (Experimental) 🆕
- 🛠️ `/tools enable` - Enable AI tools (file search, calculator, code analyzer, etc.)
- 📋 `/tools list` - Show available tools
- ✅ `/tools status` - Check tools status
- ⚙️ `/tools config` - Configure tool settings (e.g., max iterations)
- ❌ `/tools disable` - Disable tools

**Built-in Tools:**
- `search_files` - Find files by pattern
- `read_file` - Read file contents
- `list_directory` - List directory contents
- `calculator` - Evaluate mathematical expressions
- `execute_shell_command` - Execute system commands with consent (v1.11.2) 🔒
- `get_datetime` - Get current date/time with timezone support
- Plus web tools (for custom provider): weather, web search, URL fetch

**Shell Command Consent (v1.11.2) 🔒**
- **Safe by Design:** User consent required for dangerous shell commands
- **Smart Classification:** Regex-based command risk assessment (safe/dangerous/never)
- **Session-Scoped:** Consent persists across commands in the same session
- **Configurable:** Customize allowed/dangerous/forbidden patterns in ppxai-config.json
- **Examples:**
  - ✅ Auto-approved: `ls`, `cat`, `pwd`, `grep` (read-only operations)
  - ⚠️ Requires consent: `rm`, `mv`, `chmod`, `sudo`, `curl | bash`
  - ❌ Always blocked: `rm -rf /`, `dd of=/dev/`, fork bombs

**File Editing Tools (v1.11.1) 🎯**
- `apply_patch` - Apply unified diff patches to files
- `replace_block` - Search and replace exact text blocks
- `insert_text` - Insert text at specific line numbers
- `delete_lines` - Delete line ranges from files
- **Safe by Design:** User consent required before any file edits (y/n/always/never)
- **Session-Scoped:** Consent persists across edits in the same session
- **Atomic Operations:** All edits include automatic rollback on failure

**Extensible System:**
- Add custom Python tools in minutes
- Optional MCP (Model Context Protocol) server support
- See [docs/TOOL_CREATION_GUIDE.md](docs/TOOL_CREATION_GUIDE.md) for details

**Learn More:** [Tool Documentation](docs/README.md) | [Shell Consent Guide](docs/SHELL_CONSENT_GUIDE.md) | [File Editing Guide](docs/FILE_EDITING_GUIDE.md)

## Quick Start

### Option 1: Download Standalone Executable (Recommended for Users)

**No Python installation required!**

1. Download the appropriate executable for your platform from [Releases](../../releases)
2. Create a `.env` file with your API key:
   ```
   PERPLEXITY_API_KEY=your_api_key_here
   ```
3. Run the executable:
   - **macOS/Linux:** `./ppxai`
   - **Windows:** `ppxai.exe`

### Option 2: VSCode Extension with Standalone Server 🆕 v1.11.2

**No Python installation required!** Pre-built server binaries available!

1. Download from [Releases](../../releases):
   - `ppxai-server-{platform}` (server binary for macOS ARM/Intel, Linux, Windows)
   - `ppxai-1.11.6.vsix` (VSCode extension)
2. Create a `.env` file with your API key (in project folder or `~/.ppxai/.env`)
3. Install the extension: `code --install-extension ppxai-1.11.6.vsix`
4. Start the server: `./ppxai-server-macos-arm64` (or your platform's binary)
5. Open VSCode and click the ppxai icon in the sidebar

**What's New in v1.11.6:**
- 🔧 **Bug Fix** - `/tools list` and `/tools status` now work after switching providers
- 🔧 **Bug Fix** - Ctrl-C during streaming no longer causes 400 message alternation errors
- 🔧 **Bug Fix** - Status line correctly shows "Tools: ON" after enabling
- 🎯 **@git Context Injection** - Type `@git` to inject git diff (staged + unstaged changes)
- 🌳 **@tree Context Injection** - Type `@tree` to inject directory tree structure
- 🔗 **Combined Contexts** - Use `@file`, `@git`, and `@tree` together in one message
- 🏗️ **Unified Architecture** - TUI and VSCode now both use shared EngineClient

See [vscode-extension/README.md](vscode-extension/README.md) for detailed instructions.

### Option 3: Run from Source (For Developers)

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd ppxai
```

2. **Recommended: Using Bootstrap Script** (easiest, no prerequisites)
```bash
# First-time setup (auto-downloads uv + installs dependencies)
python scripts/bootstrap.py

# Include server dependencies for HTTP + SSE
python scripts/bootstrap.py --server

# Include all optional dependencies
python scripts/bootstrap.py --all
```

This creates a local `.uv/` cache with the uv binary - no system-wide installation needed.

**Or using uv directly** (if you have uv installed):
```bash
uv sync                      # Basic install
uv sync --extra server       # With HTTP server support
uv sync --all-extras         # All optional features
```

**Or using pip** (traditional):
```bash
python3 -m venv venv
source venv/bin/activate  # On macOS/Linux (Windows: venv\Scripts\activate)
pip install -r requirements.txt
```

3. Set up configuration:

**Simple setup (Perplexity only):**
```bash
cp .env.example .env
# Edit .env and add your Perplexity API key:
# PERPLEXITY_API_KEY=your_api_key_here
```

**Multi-provider setup (OpenAI, Claude via OpenRouter, local models, etc.):**
```bash
# Copy both configuration files
cp .env.example .env
cp ppxai-config.example.json ppxai-config.json

# Edit .env with your API keys (secrets only)
# Edit ppxai-config.json for provider settings
```

See [Configuration](#configuration) section for details.

## Usage

Run the application:
```bash
# With uv (recommended)
uv run ppxai

# Or with pip/venv
python ppxai.py
```

Run tests:
```bash
uv run pytest tests/ -v
```

### Available Commands

While in the chat interface:

#### General Commands
- Type your question or prompt to chat with the AI
- `/help` - Show help message with all commands
- `/provider` - Switch AI provider (interactive picker)
- `/provider list` - List all available providers
- `/provider <id>` - Switch directly to a provider (e.g., `/provider gemini`)
- `/model` - Change the current model (interactive picker)
- `/model list` - List all models for current provider
- `/model <id>` - Switch directly to a model (e.g., `/model gemini-2.5-pro`)
- `/clear` - Clear conversation history
- `/quit` or `/exit` - Exit the application (auto-saves session)
- `/debug-log [on|off|show|clear]` - 🆕 TUI debug logging (logs to `~/.ppxai/logs/tui-debug.log`)
- **Context Injection** - Type `@filename` for files, `@git` for git changes, `@tree` for directory structure
- **Autocomplete** - Tab/type to complete `/` commands and `@` references

#### Session Management
- `/save` - Save session to JSON file (~/.ppxai/sessions/)
- `/export [filename]` - Export last answer to markdown file (~/.ppxai/exports/)
- `/sessions` - List all saved sessions
- `/load <session>` - Load and continue a previous session
- `/usage` - Show token usage and cost statistics

#### Code Generation & Analysis Tools
- `/generate <description>` - Generate code from natural language
  - Example: `/generate a function to validate email addresses in Python`
- `/test <file>` - Generate unit tests for a code file
  - Example: `/test ./src/utils.py`
- `/docs <file>` - Generate documentation for a code file
  - Example: `/docs ./src/api.py`
- `/implement <specification>` - Implement a feature from detailed spec
  - Example: `/implement a REST API endpoint for user authentication`
- `/debug <error>` - Analyze and fix errors with explanations
  - Example: `/debug TypeError: 'NoneType' object is not subscriptable at line 42`
- `/explain <file>` - Explain code logic and design decisions
  - Example: `/explain ./src/algorithm.py`
- `/convert <from> <to> <file>` - Convert code between languages
  - Example: `/convert python javascript ./utils.py`
  - Example: `/convert go rust 'func hello() { fmt.Println("Hi") }'`
- `/spec [type]` - Show specification guidelines and templates
  - Types: `api`, `cli`, `lib`, `algo`, `ui`
  - See [SPECIFICATIONS.md](SPECIFICATIONS.md) for details
- `/autoroute [on|off]` - Toggle smart model routing for coding tasks
  - Auto-routes coding commands to Sonar Pro for best results
  - Enabled by default, can be disabled for manual control

### Available Models

1. **Sonar** - Lightweight search model with real-time grounding
2. **Sonar Pro** - Advanced search model for complex queries
3. **Sonar Reasoning** - Fast reasoning model for problem-solving with search
4. **Sonar Reasoning Pro** - Precision reasoning with Chain of Thought capabilities
5. **Sonar Deep Research** - Exhaustive research with comprehensive reports

## Use Cases

ppxai is particularly useful for:

- **Research & Learning**: Leverage Perplexity's real-time search for up-to-date information
- **Code Development**: Generate code, tests, and documentation with specialized prompts
- **Debugging**: Get help analyzing errors and finding solutions with root cause analysis
- **Code Understanding**: Explain complex codebases and design decisions
- **Architecture Planning**: Use specification templates to design features before coding
- **Code Review**: Generate documentation and tests for existing code
- **Language Migration**: Convert code between programming languages with idiomatic patterns
- **Quick Prototypes**: Rapidly generate boilerplate code and implementations

## Example Outputs

### `/explain` - Code Explanation

When you run `/explain ./ppxai.py`, you get comprehensive analysis like:

> **High-Level Structure & Purpose**
>
> This code implements a comprehensive command-line interface (CLI) application for interacting with Perplexity AI models, providing tools for conversational AI, code generation, documentation, debugging, and session management—all from the terminal.
>
> **Key Design Patterns:**
> - Separation of concerns (UI, business logic, API communication)
> - Dependency injection for extensibility
> - Defensive programming with comprehensive error handling
> - Modern CLI design with rich terminal UI
>
> **Core Components:**
> 1. **Session Management** - Persistent conversation state with save/load/export
> 2. **Usage Tracking** - Real-time token and cost monitoring per model
> 3. **Auto-routing** - Smart model selection for coding tasks
> 4. **Coding Tools** - Specialized commands with tailored system prompts
>
> [Full detailed explanation with architecture diagrams, component interaction, and best practices...]

The explanation includes citations from official documentation and explains not just *what* the code does, but *why* it's designed that way.

### `/debug` - Error Analysis

Provide error details:
```
/debug TypeError: 'NoneType' object is not subscriptable at line 42
```

Get comprehensive debugging help:
> **Root Cause:** You're trying to access an index on a None object, which occurs when a function returns None instead of the expected list/dict.
>
> **Why This Happened:** The variable is None because [specific reason based on context]
>
> **Solution:**
> ```python
> # Before (causes error)
> result = get_data()
> value = result[0]  # Error if result is None
>
> # After (fixed)
> result = get_data()
> if result is not None:
>     value = result[0]
> else:
>     value = default_value
> ```
>
> **Preventive Measures:**
> - Add type hints and validation
> - Use Optional[] types
> - Implement proper error handling
>
> [Additional debugging techniques and best practices...]

### `/convert` - Language Translation

Convert Python to JavaScript:
```
/convert python javascript "def hello(name): return f'Hello, {name}!'"
```

Get idiomatic translation:
```javascript
// Converted from Python to JavaScript
function hello(name) {
    return `Hello, ${name}!`;
}

// Usage example:
console.log(hello("World")); // Output: Hello, World!
```

The conversion uses proper JavaScript conventions (arrow functions, template literals, etc.) rather than direct literal translation.

## Data Storage

ppxai stores data locally in `~/.ppxai/`:

- `~/.ppxai/sessions/` - Saved conversation sessions (JSON)
- `~/.ppxai/exports/` - Exported markdown files
- `~/.ppxai/usage.json` - Token usage and cost tracking
- `~/.ppxai/ppxai-config.json` - User-specific provider configuration (optional)

All data stays on your machine. No data is sent anywhere except to the configured AI provider's API during chat.

## Configuration

ppxai uses a **hybrid configuration** approach that separates secrets from settings:

### Files

| File | Purpose | Version Control |
|------|---------|-----------------|
| `.env` | API keys only (secrets) | ❌ Never commit |
| `ppxai-config.json` | Provider definitions, models, pricing | ✅ Can commit |

### Config File Search Order

1. `PPXAI_CONFIG_FILE` environment variable (if set)
2. `./ppxai-config.json` (project-specific, for teams)
3. `~/.ppxai/ppxai-config.json` (user-specific)
4. Built-in defaults (Perplexity + Gemini)

### Simple Setup (Perplexity + Gemini)

Just create `.env` with your API keys:
```bash
PERPLEXITY_API_KEY=pplx-xxxxxxxxxxxxx
GEMINI_API_KEY=AIza-xxxxxxxxxxxxx
```

No `ppxai-config.json` needed - built-in Perplexity and Gemini configurations are used. Use `/provider list` to see available providers.

### Multi-Provider Setup

**1. Create `.env` with API keys:**
```bash
# API Keys (referenced by api_key_env in ppxai-config.json)
PERPLEXITY_API_KEY=pplx-xxxxxxxxxxxxx
OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxx
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxxx

# Optional: Override default provider
MODEL_PROVIDER=openai
```

**2. Create `ppxai-config.json` with providers:**
```json
{
  "version": "1.0",
  "default_provider": "perplexity",
  "providers": {
    "perplexity": {
      "name": "Perplexity AI",
      "base_url": "https://api.perplexity.ai",
      "api_key_env": "PERPLEXITY_API_KEY",
      "default_model": "sonar-pro",
      "models": {
        "sonar-pro": {
          "name": "Sonar Pro",
          "description": "Advanced search model"
        }
      },
      "capabilities": {
        "web_search": true,
        "realtime_info": true
      }
    },
    "openai": {
      "name": "OpenAI ChatGPT",
      "base_url": "https://api.openai.com/v1",
      "api_key_env": "OPENAI_API_KEY",
      "default_model": "gpt-4o",
      "models": {
        "gpt-4o": {"name": "GPT-4o", "description": "Latest flagship model"},
        "gpt-4o-mini": {"name": "GPT-4o Mini", "description": "Fast and affordable"}
      }
    }
  }
}
```

See `ppxai-config.example.json` for a complete example with multiple providers.

### Supported Providers

Any OpenAI-compatible API works, including:
- **Perplexity AI** - Built-in web search
- **OpenAI** - GPT-4o, GPT-4 Turbo, o1
- **Google Gemini** - Via OpenAI-compatible endpoint
- **OpenRouter** - Claude, Gemini, Llama, and 100+ models
- **Local models** - vLLM, Ollama, llama.cpp
- **Self-hosted** - Any OpenAI-compatible endpoint

**📖 [Provider Setup Guide](docs/PROVIDER_SETUP.md)** - Detailed configuration examples for each provider including OpenAI, Gemini, OpenRouter, and local models.

## API Keys

Get API keys from:
- **Perplexity:** [perplexity.ai](https://www.perplexity.ai/)
- **OpenAI:** [platform.openai.com](https://platform.openai.com/)
- **OpenRouter:** [openrouter.ai](https://openrouter.ai/) (for Claude, Gemini, etc.)

## Building Executables

Want to build your own standalone executable? See [BUILD.md](BUILD.md) for detailed instructions on building for:
- Windows 11
- macOS (Intel & Apple Silicon)
- Linux

**Quick build:**
```bash
# macOS/Linux
./build.sh

# Windows
build.bat
```

## Requirements

- **For standalone executable:** None! Just download and run.
- **For running from source:** Python 3.10+ (dependencies managed via `pyproject.toml` / `uv.lock`)

## Terminal Compatibility

Clickable links work best in modern terminals:
- **macOS:** Terminal.app, iTerm2 (Cmd+Click)
- **Windows:** Windows Terminal (Ctrl+Click)
- **Linux:** GNOME Terminal, Konsole, etc. (Ctrl+Click)

## Project Structure

```
ppxai/
├── ppxai.py                              # Entry point wrapper
├── ppxai/                                # Main package
│   ├── __init__.py                       # Package exports (v1.11.1)
│   ├── main.py                           # CLI application
│   ├── client.py                         # AI client for API communication
│   ├── config.py                         # Hybrid configuration system
│   ├── commands.py                       # Command handlers
│   ├── ui.py                             # Terminal UI/display
│   ├── prompts.py                        # Coding prompts & templates
│   ├── utils.py                          # Utility functions
│   ├── tui_logger.py                     # TUI debug logging (v1.11.1)
│   ├── markdown_tables.py                # Markdown table rendering (v1.10.4)
│   ├── server/                           # Server implementations
│   │   ├── http.py                       # FastAPI HTTP + SSE server (v1.9.0)
│   │   └── jsonrpc.py                    # JSON-RPC server for IDE integration
│   └── engine/                           # Core engine (v1.7.0+)
│       ├── types.py                      # Shared types (Event, Message, etc.)
│       ├── client.py                     # EngineClient facade
│       ├── session.py                    # Session management
│       ├── context.py                    # Context management
│       ├── providers/                    # Provider implementations
│       │   ├── base.py                   # BaseProvider abstract class
│       │   ├── perplexity.py             # Perplexity AI provider
│       │   └── openai_compat.py          # OpenAI-compatible provider
│       └── tools/                        # Tool system
│           ├── base.py                   # BaseTool abstract class
│           ├── manager.py                # ToolManager with provider filtering
│           └── builtin/                  # Built-in tools
│               ├── calculator.py         # Calculator tool
│               ├── datetime_tool.py      # DateTime tool
│               ├── editor.py             # File editing tools (v1.11.0)
│               ├── filesystem.py         # Filesystem tools
│               ├── shell.py              # Shell command tool
│               └── web.py                # Web tools
├── vscode-extension/                     # VS Code Extension (v1.11.1)
│   ├── src/
│   │   ├── extension.ts                  # Extension entry point
│   │   ├── chatPanel.ts                  # Webview chat UI
│   │   ├── httpClient.ts                 # HTTP + SSE client (v1.9.0)
│   │   ├── backend.ts                    # Python process manager (legacy)
│   │   ├── aiClient.ts                   # AI client interface
│   │   ├── config.ts                     # Configuration management
│   │   └── sessionsProvider.ts           # Session tree view
│   └── package.json                      # Extension manifest
├── ppxai-config.json                     # Provider configuration (optional)
├── ppxai-config.example.json             # Configuration template
├── demo/
│   └── demo_tools_working.py             # Working demo
├── tests/                                # 322 tests passing (v1.11.7)
│   ├── test_config.py                    # Configuration tests (48 tests)
│   ├── test_commands.py                  # Command tests
│   ├── test_engine_streaming.py          # Engine streaming tests
│   ├── test_engine_tool_parsing.py       # Tool parsing tests
│   ├── test_file_editing_tools.py        # File editing tests
│   ├── test_markdown_tables.py           # Markdown table tests
│   └── ...                               # Additional test modules
├── docs/
│   ├── README.md                         # Documentation index
│   ├── FILE_EDITING_GUIDE.md             # File editing guide
│   ├── v1.11.0-agentic-workflow-plan.md  # Agentic workflow plan
│   └── archive/                          # Archived documentation
├── pyproject.toml                        # Project metadata & dependencies
├── uv.lock                               # Dependency lockfile
├── scripts/
│   ├── bootstrap.py                      # Dev environment bootstrap
│   └── build-intel.sh                    # macOS Intel build script (v1.9.0)
├── SPECIFICATIONS.md                     # Code generation specs
├── ROADMAP.md                            # Development roadmap
└── README.md                             # This file
```

## Documentation

- **Main Guide:** [README.md](README.md) (this file)
- **VS Code Extension:** [vscode-extension/README.md](vscode-extension/README.md)
- **Provider Setup:** [docs/PROVIDER_SETUP.md](docs/PROVIDER_SETUP.md)
- **Tool System:** [docs/README.md](docs/README.md)
- **Tool Creation:** [docs/TOOL_CREATION_GUIDE.md](docs/TOOL_CREATION_GUIDE.md)
- **Shell Consent:** [docs/SHELL_CONSENT_GUIDE.md](docs/SHELL_CONSENT_GUIDE.md) ⭐ NEW (v1.11.2)
- **File Editing:** [docs/FILE_EDITING_GUIDE.md](docs/FILE_EDITING_GUIDE.md)
- **Code Generation:** [SPECIFICATIONS.md](SPECIFICATIONS.md)
- **Development Roadmap:** [ROADMAP.md](ROADMAP.md)
- **Building:** [BUILD.md](BUILD.md)
- **Contributing:** [CONTRIBUTING.md](CONTRIBUTING.md)
- **Security:** [SECURITY.md](SECURITY.md)

## License

MIT
