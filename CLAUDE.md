# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ppxai is a terminal-based UI application for interacting with multiple AI providers (Perplexity AI, OpenAI, OpenRouter, local models). It provides an interactive chat interface with model selection, conversation history, streaming responses, and AI-powered tools.

**Current Version:** v1.11.9

**What's New in v1.11.9 (Released 2025-12-27):**
- **CRITICAL FIX:** `/agent on|off` now correctly toggles agent mode instead of being interpreted as tasks
  - Previously, typing `/agent off` would cause AI to search for things to turn "off" (including killing server processes)
  - Now properly recognized as toggle commands in both TUI and VSCode extension
- **SECURITY:** Added safety mitigations for agent mode
  - Minimum word count validation (default: 3 words) rejects vague single-word tasks
  - `kill`, `pkill`, `killall` added to built-in dangerous shell patterns
  - Built-in defaults ensure safety even without config file
- **NEW:** Configurable agent settings via `ppxai-config.json`
  - `tools.agent.max_iterations` (default: 10) - Maximum agent loop iterations
  - `tools.agent.context_char_limit` (default: 2000) - Character limit for context display
  - `tools.agent.min_task_words` (default: 3) - Minimum words required for agent tasks
- **NEW:** `/agent/config` API endpoint for retrieving agent configuration
- **NEW:** Full `/tools` command parity between TUI and VSCode extension
  - Added `/tools agent`, `/tools set verbose on|off`, `/tools help <tool>` to extension
- **Tests:** 337 tests passing

**Previous Release (v1.11.8 - 2025-12-27):**
- **NEW:** Agent Mode for autonomous task execution in VSCode extension
  - Agent toggle button in extension header
  - `GET /agent/status`, `POST /agent/enable`, `POST /agent/disable` API endpoints
  - Agent mode automatically enables tools when activated
  - Comprehensive guide at [docs/AGENT_MODE_GUIDE.md](docs/AGENT_MODE_GUIDE.md)
- **FIX:** GitHub releases now correctly marked as "Latest"
  - Added `make_latest: true` to CI workflow
  - Release script uses `--latest` flag when publishing notes
- **FIX:** 12 broken documentation links corrected
  - `custom-tools-guide.md` → `CUSTOM_TOOL_DEVELOPMENT_GUIDE.md`
  - Archived docs now properly reference `docs/archive/` paths
- **Tests:** 337 tests passing

**Previous Release (v1.11.7 - 2025-12-26):**
- **MAJOR:** All legacy code removed - EngineClient is now the only client interface
  - Deleted: `ppxai/client.py` (AIClient), `perplexity_tools_prompt_based.py`, `tool_manager.py`
  - ~2,100 lines of legacy code removed
  - Tests migrated to EngineClient (337 tests passing)
- **NEW:** `/tools help <tool-name>` command for detailed tool documentation
- **NEW:** Autocomplete for `/tools` subcommands and tool names
- **NEW:** Custom tool development guide at [docs/CUSTOM_TOOL_DEVELOPMENT_GUIDE.md](docs/CUSTOM_TOOL_DEVELOPMENT_GUIDE.md)
- **FIX:** Perplexity citations now clickable in both TUI and VSCode extension
- **FIX:** TUI markdown links now clickable via OSC 8 hyperlinks
- **FIX:** VSCode extension now displays responses when tools are used
- **FIX:** `/tools list` and `/tools status` now work correctly after switching providers

**Previous Release (v1.11.5 - 2025-12-26):**
- **CRITICAL FIX:** Ctrl-C during streaming no longer causes 400 message alternation errors 🔧
- **FIX:** `/tools enable` now correctly shows "ON" in status line
- **Tests:** 377 tests passing (2 new session cleanup tests)

**Previous Release (v1.11.4 - 2025-12-24):**
- **NEW:** `@git` context provider - Include git diff (staged + unstaged changes) in messages 🔀
- **NEW:** `@tree` context provider - Include project directory structure in messages 🌳
- **Context Injection:** Type `@git` to inject current git changes, `@tree` for project structure
- **Auto-Detection:** Automatically injects git diff or tree structure based on message context
- **Smart Filtering:** Tree view respects .gitignore patterns and filters common ignore directories
- **Configurable:** Tree depth configurable (default: 3 levels deep)
- **Integrated:** Works seamlessly with existing `@file` references
- **Combined Usage:** Use `@git`, `@tree`, and `@file` together in the same message
- **Tests:** 31/31 context injection tests passing, including 9 new tests for @git/@tree

**Previous Release (v1.11.2.1 - 2025-12-23):**
- **CRITICAL FIX:** Autorouter now respects current provider for coding commands 🔧
- **Bug:** When using Gemini/OpenAI/OpenRouter with coding commands (/convert, /generate, etc.), autorouter would incorrectly try to use Perplexity's sonar-pro model causing 404 errors
- **Root Cause:** 7 command handlers missing provider parameter, falling back to stale global variable
- **Fixed:** All coding command handlers now pass self.provider to send_coding_task()
- **Impact:** Fixes 404 errors when using coding commands with non-Perplexity providers
- **NEW:** Comprehensive autorouter configuration guide at [docs/AUTOROUTER-CONFIG.md](docs/AUTOROUTER-CONFIG.md)
- **NEW:** Users can customize coding_model per provider in ppxai-config.json
- **Tests:** 308/308 tests passing (100%), including new Gemini autorouter regression test
- **Backward Compatible:** Drop-in replacement for v1.11.2

**Previous Release (v1.11.2 - 2025-12-22):**
- **NEW:** Shell command consent system for secure AI command execution 🔒
- **Smart Classification:** Regex-based command risk assessment (safe/dangerous/never)
- **Safe Commands:** Auto-approved read-only operations (ls, cat, grep, pwd)
- **Dangerous Commands:** Require user consent (rm, mv, chmod, sudo, curl | bash)
- **Never-Allow Commands:** Always blocked (rm -rf /, dd of=/dev/, fork bombs)
- **Session-Scoped:** Consent persists across commands in the same session (y/n/always/never)
- **Configurable:** Customize allowed/dangerous/forbidden patterns in ppxai-config.json
- **TUI + VSCode:** Consent prompts in both interfaces with full context
- **Documentation:** Comprehensive shell consent guide at [docs/SHELL_CONSENT_GUIDE.md](docs/SHELL_CONSENT_GUIDE.md)
- **Security:** Protects against destructive commands while allowing safe operations
- **Tests:** All integration tests passing, consent flow verified end-to-end

**Previous Release (v1.11.1 - 2025-12-22):**
- **CRITICAL FIX:** TUI now displays AI responses when tools are enabled (v1.11.0 regression)
- **Architecture:** Unified TUI and VSCode to both use event-based streaming
- **Performance:** No performance impact - EngineClient is 16.5% faster than legacy (2446ms vs 2929ms)
- **Event Handling:** TUI now handles STREAM_CHUNK, TOOL_CALL, TOOL_RESULT, CONSENT_REQUEST, and ERROR events
- **Real-time UX:** TUI shows streaming chunks, tool calls, and consent prompts in real-time
- **Code Quality:** Eliminates architectural divergence between TUI and VSCode extension
- **FIXED:** Conversation history sync - Fixed 400 error when using tools with conversation history
  - Engine client and legacy client now properly sync history when enabling tools and after each response
  - Fixes message alternation errors ("user or tool message(s) should alternate with assistant message(s)")
- **FIXED:** Inline markdown in tables - File names and inline code now render properly
  - Inline code (`` `text` ``) renders with cyan monospace on grey background (GitHub-like)
  - Bold (`**text**`) and italic (`*text*`) also supported in table cells
- **NEW:** `/tools set verbose` command to inspect tool inputs/outputs
  - `/tools set verbose on` - Show tool arguments and results during execution
  - `/tools set verbose off` - Hide detailed tool information (default)
  - Useful for debugging and understanding AI tool calls
- **Tests:** 296/301 tests passing (same as v1.11.0 - 5 pre-existing failures in custom endpoint tests)
- **Backwards Compatible:** Legacy tool system still works when EngineClient not available

**Earlier Release (v1.11.0 - 2025-12-21):**
- **NEW:** 4 file editing tools with user consent (apply_patch, replace_block, insert_text, delete_lines)
- **NEW:** Per-file session consent system (y/n/always/never)
- **NEW:** Atomic file operations with automatic rollback on failure
- **NEW:** Consent prompts in both TUI and VSCode extension
- **Safe:** User consent required before any file modification
- **Session-scoped:** Consent persists across tool calls in same session
- **TUI:** Interactive consent prompts with prompt_toolkit validation
- **VSCode:** Modal consent dialogs with 4 options
- **Fixed:** Markdown code block rendering in VSCode for Gemini models (uses hex escapes to unwrap ```markdown blocks)
- **Tests:** 262 total tests passing (25 new file editing regression tests)
- **Performance:** TTFT 1453ms, Total 2446ms (0.84x baseline - improved!), 64.0 tok/s
- **Architecture:** Event-driven consent via SSE for VSCode, async callbacks for TUI
- **Details:** See [docs/v1.11.0-agentic-workflow-plan.md](docs/v1.11.0-agentic-workflow-plan.md)
- **Release:** https://github.com/rcconsult/ppxai/releases/tag/v1.11.0
- **Known Issue:** TUI doesn't display responses when tools enabled (fixed in v1.11.1)

**Earlier Release (v1.10.8 - 2025-12-21):**
- **Unified:** `/save` and `/export` commands now behave consistently across TUI and VSCode extension
- **New:** `/export [filename]` command to export last answer to markdown (~/.ppxai/exports/)
- **Changed:** `/save` now saves session to JSON (~/.ppxai/sessions/) for persistence
- **Enhanced:** VSCode extension "Save Answer" button now saves to exports folder with auto-generated filenames
- **Improved:** VSCode extension interrupt UX - orange pulsing "⏹ Streaming..." badge in header
- **Fixed:** VSCode extension interrupt no longer shows red error message on user-initiated stop
- **Added:** Clear separation between session persistence (JSON) and answer export (markdown)

**Earlier Release (v1.10.7 - 2025-12-20):**
- **Fixed:** Perplexity API compatibility - removed deprecated `sonar-reasoning` model (now returns 400 error)
- **Updated:** Model documentation to reflect current Perplexity API supported models
- **Validated:** Against official Perplexity docs (sonar-reasoning page returns 404)
- **Supported Models:** sonar, sonar-pro, sonar-reasoning-pro, sonar-deep-research

**Earlier Release (v1.10.6 - 2025-12-20):**
- **New:** Gemini 3 Flash Preview - Speed-optimized with frontier intelligence and 1M context
- **New:** Gemini 3 Pro Preview - Most powerful agentic model with code execution and search grounding
- **Enhanced:** Updated all Gemini model descriptions with detailed capabilities
- **Added:** Preview pricing estimates for Gemini 3 models

**Earlier Release (v1.10.5 - 2025-12-20):**
- **Fixed:** Ctrl-C during streaming no longer causes message alternation errors
- **New:** TUI Ctrl-C double-press pattern (2s timeout) - first press warns, second press exits
- **New:** Conversation history cleanup on interrupt maintains LLM message alternation
- **New:** Status bar showing provider, model, and tools status
- **New:** VSCode extension interrupt support via Esc key and Command Palette
- **Fixed:** Gemini tools None content handling
- **Fixed:** FastAPI deprecation warnings (migrated to lifespan pattern)
- **Added:** 7 new interrupt handling tests (235/241 tests passing)

**Earlier Release (v1.10.4 - 2025-12-19):**
- **Fixed:** Markdown tables now render properly in TUI (no more raw `|:---|:---|` syntax)
- Tables support left/center/right alignment (`:---`, `:---:`, `---:`)
- Handles emojis, code, and complex content in table cells
- `/show` command now renders markdown files with formatted tables
- All AI responses across all clients render tables correctly
- 27 new regression tests ensure table rendering stays fixed

**Earlier Release (v1.10.3 - 2025-12-18):**
- Standalone `ppxai-server` executables for all platforms (no Python required for VSCode extension)
- Automated GitHub Actions CI/CD for multi-platform builds (macOS ARM/Intel, Linux, Windows)

**Version Alignment:**
- Python package (pyproject.toml): v1.11.9
- VSCode extension (package.json): v1.11.9
- Git tag: v1.11.9 (released 2025-12-27)
- GitHub Release: https://github.com/rcconsult/ppxai/releases/tag/v1.11.9

## Development Setup

### Recommended: Using Bootstrap Script (easiest)

The bootstrap script automatically downloads uv if not present and sets up the project:

```bash
# First-time setup (downloads uv + installs dependencies)
python scripts/bootstrap.py

# Include server dependencies for HTTP + SSE
python scripts/bootstrap.py --server

# Include all optional dependencies
python scripts/bootstrap.py --all
```

This creates a local `.uv/` cache with the uv binary - no system-wide installation needed.

### Alternative: Manual uv Installation

If you prefer to install uv system-wide:

1. Install uv (one-time):
   ```bash
   # macOS/Linux
   curl -LsSf https://astral.sh/uv/install.sh | sh

   # Or with Homebrew
   brew install uv
   ```

2. Set up project (creates venv, installs deps, generates lockfile):
   ```bash
   uv sync
   ```

3. Install with optional dependencies:
   ```bash
   uv sync --extra server   # HTTP + SSE server support
   uv sync --extra mcp      # MCP tool support
   uv sync --dev            # Development tools (pytest, ruff)
   uv sync --all-extras     # Everything
   ```

4. Set up configuration:
   ```bash
   cp .env.example .env
   # Edit .env and add your API keys (e.g., PERPLEXITY_API_KEY)
   ```

5. Run the application:
   ```bash
   uv run ppxai
   # Or run directly
   uv run python ppxai.py
   ```

6. Run tests:
   ```bash
   uv run pytest tests/ -v
   ```

### Alternative: Using pip (traditional)

If you don't have uv installed:

1. Create and activate virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On macOS/Linux
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Set up configuration:
   ```bash
   cp .env.example .env
   # Edit .env and add your API keys (e.g., PERPLEXITY_API_KEY)

   # Optional: For multi-provider setup
   cp ppxai-config.example.json ppxai-config.json
   # Edit ppxai-config.json for provider settings
   ```

4. Run the application:
   ```bash
   python ppxai.py
   ```

5. Run tests:
   ```bash
   python -m pytest tests/ -v
   ```

## Architecture

The application uses a layered architecture with clear separation of concerns:

### Engine Layer (`ppxai/engine/`)

The engine is the core business logic with no UI dependencies:

- **`types.py`** - Shared types (Message, Event, UsageStats, etc.)
- **`client.py`** - `EngineClient` facade for all functionality
- **`session.py`** - Session management and persistence
- **`providers/`** - Provider implementations
  - `base.py` - `BaseProvider` abstract class
  - `perplexity.py` - Perplexity AI provider (native search)
  - `openai_compat.py` - OpenAI-compatible provider (works with OpenAI, Gemini, OpenRouter, local)
- **`tools/`** - Tool system
  - `base.py` - `BaseTool` abstract class
  - `manager.py` - `ToolManager` with provider-aware filtering
  - `builtin/` - Built-in tools (filesystem, shell, calculator, datetime, web)

### Server Layer (`ppxai/server/`)

JSON-RPC server for IDE integration:

- **`jsonrpc.py`** - JSON-RPC 2.0 server over stdio using `EngineClient`

### TUI Layer (`ppxai/`)

Terminal UI using Rich/prompt_toolkit:

- **`main.py`** - CLI entry point and main loop
- **`ui.py`** - Rich console components
- **`commands.py`** - Slash command handlers

### Supporting Modules

- **`config.py`** - Configuration system (used by both engine and TUI)
- **`server.py`** - Backward-compatible import from `server/jsonrpc.py`

### Configuration Files

- **`ppxai-config.json`** - Provider configuration (JSON, can be version controlled)
- **`.env`** - API keys only (secrets, never commit)

## Configuration System

ppxai uses a hybrid configuration approach:

| File | Purpose | Git |
|------|---------|-----|
| `.env` | API keys (secrets) | ❌ Never commit |
| `ppxai-config.json` | Provider definitions | ✅ Can commit |

### Adding a New Provider

1. Add provider definition to `ppxai-config.json`:
   ```json
   {
     "providers": {
       "my-provider": {
         "name": "My Provider",
         "base_url": "https://api.example.com/v1",
         "api_key_env": "MY_PROVIDER_API_KEY",
         "default_model": "model-id",
         "models": {
           "model-id": {"name": "Model Name", "description": "Description"}
         }
       }
     }
   }
   ```

2. Add API key to `.env`:
   ```bash
   MY_PROVIDER_API_KEY=your-key-here
   ```

## Common Commands

### With uv (recommended)

```bash
# Run the application
uv run ppxai

# Run tests
uv run pytest tests/ -v                    # All tests
uv run pytest tests/test_config.py -v      # Config tests only

# Install/update dependencies
uv sync                      # Sync from lockfile
uv sync --extra server       # Add server dependencies
uv add <package>             # Add new dependency

# Run HTTP server (v1.9.0+)
uv run ppxai-server

# Run tools without installing
uvx ruff check ppxai/        # Linter
uvx pyinstaller ppxai.spec   # Build executable

# Validate configuration
uv run python -c "from ppxai.config import validate_config; print(validate_config())"
```

### With pip (alternative)

```bash
# Run the application
python ppxai.py

# Run tests
python -m pytest tests/ -v                    # All tests
python -m pytest tests/test_config.py -v      # Config tests only
python -m pytest tests/ --ignore=tests/test_custom_endpoint_integration.py  # Skip custom endpoint tests

# Install/update dependencies
pip install -r requirements.txt

# Validate configuration
python -c "from ppxai.config import validate_config; print(validate_config())"
```

## Testing

- **262 tests** across multiple test modules (25 new file editing tests in v1.11.0)
- **48 config tests** for the hybrid configuration system
- Tests use `pytest` with `unittest.mock` for mocking
- Custom endpoint integration tests require vLLM/Ollama running locally

## GitHub CLI Authentication

When using `gh` commands for releases and repository operations, **always use the project token file** to avoid conflicts with stale environment variables:

```bash
# Standard pattern for all gh commands
unset GITHUB_TOKEN && source .github/gh-tokenv.env && export GH_TOKEN && gh <command>

# Examples
unset GITHUB_TOKEN && source .github/gh-tokenv.env && export GH_TOKEN && gh release list
unset GITHUB_TOKEN && source .github/gh-tokenv.env && export GH_TOKEN && gh release create v1.x.x
```

**Why this is needed:**
- The `gh` CLI checks `GITHUB_TOKEN` env var first, then falls back to `GH_TOKEN`
- Stale `GITHUB_TOKEN` values in the environment can cause 401 Unauthorized errors
- The token in `.github/gh-tokenv.env` is the valid project token
- Always unset `GITHUB_TOKEN` before sourcing to ensure clean state

**Build scripts** (like `scripts/build-intel.sh`) handle this automatically.

## Recent Features (v1.10.2)

- **URL Rendering Fix**: Fixed URL rendering and citation system prompts for VSCode extension
- **Citation System Prompts**: Improved citation handling in AI responses

## Known Issues

None currently. Previous issues resolved:
- **TUI Markdown Tables**: Fixed in v1.10.4
- **Ctrl-C Message Alternation**: Fixed in v1.10.5

## Recent Features (v1.10.1)

- **Message Timestamps**: Each message shows time and date (HH:MM:SS Mon DD format)
- **Time Dividers**: Visual separators between conversation turns (after 5min gap or date change)
- **Tools Persistence**: Tools enable/disable setting now persists across VSCode restarts
- **/generate Command**: New slash command for code generation from descriptions
- **HTTP Client Improvements**: Implemented setToolConfig, setWorkingDir, setAutoInject endpoints

## Recent Features (v1.10.0)

- **VSCode Extension CI/CD**: Extension VSIX built and released via GitHub Actions
- **HTTP Backend**: Extension now uses HTTP + SSE to communicate with `ppxai-server`
- **Simplified Installation**: Download VSIX from releases, start `ppxai-server`

## Recent Features (v1.9.x)

- **uv Migration**: Package manager migrated from pip to uv
- **FastAPI HTTP Server**: `ppxai-server` with SSE streaming for IDE integration
- **Latency Benchmarking**: Track provider performance across releases

## Recent Features (v1.11.4)

- **Context Injection**: `@filename` for files, `@git` for changes, `@tree` for structure (TUI + Extension)
- **Git Integration**: Automatically include staged and unstaged changes with `@git`
- **Project Structure**: Visualize directory tree with `@tree` (respects .gitignore)
- **VSCode Extension**: Full chat UI in sidebar with markdown rendering
- **Autocomplete**: Tab completion for `/` commands and `@` references in TUI, live suggestions in Extension
- **Tools Toggle**: Clickable button in extension to enable/disable tools
- **File Search**: Fuzzy file matching for `/show` command
- **Gemini Built-in**: Google Gemini added as built-in provider (2.0 Flash, 2.5 Flash, 2.5 Pro)
- **Provider/Model Commands**: `/provider list`, `/provider <id>`, `/model list`, `/model <id>` for quick switching

## Key Design Decisions

1. **Layered Architecture** - Engine (no UI) → Server (HTTP/SSE) → Clients (TUI, VSCode, Web)
2. **Provider Abstraction** - All providers implement `BaseProvider` interface
3. **Tool Independence** - Tools can be enhanced independently; provider-aware filtering
4. **Event-Based Communication** - Engine emits events; clients render them
5. **OpenAI SDK for all providers** - All providers use OpenAI-compatible API format
6. **Hybrid config** - Separates secrets (`.env`) from settings (`ppxai-config.json`)
7. **Backward compatible** - Legacy `CUSTOM_*` env vars still work
8. **Built-in providers** - Perplexity and Gemini always available without config file

## VSCode Extension

A TypeScript VSCode extension is available in `vscode-extension/`:

### Structure
```
vscode-extension/
├── src/
│   ├── extension.ts       # Extension entry point, command registration
│   ├── httpClient.ts      # HTTP + SSE client for ppxai-server
│   ├── chatPanel.ts       # Webview chat UI provider
│   └── sessionsProvider.ts  # Session tree view
├── package.json           # Extension manifest, commands, views
└── .vscodeignore          # Package exclusions
```

### Installation (v1.10.6+)

**Option A: Pre-built Binaries (No Python Required)**

1. Download from [GitHub Releases](https://github.com/rcconsult/ppxai/releases):
   - `ppxai-server-{platform}` (server binary for your OS)
   - `ppxai-1.10.6.vsix` (VSCode extension)

2. Create `.env` with API key (in project folder or `~/.ppxai/.env`)

3. Install extension and start server:
   ```bash
   code --install-extension ppxai-1.10.6.vsix
   chmod +x ppxai-server-macos-arm64  # macOS/Linux only
   ./ppxai-server-macos-arm64
   ```

**Option B: Install from PyPI (Python Required)**

1. Install ppxai with server support:
   ```bash
   pip install ppxai[server]
   # Or: uv pip install ppxai[server]
   ```

2. Download and install the VSIX from GitHub Releases:
   ```bash
   code --install-extension ppxai-1.10.6.vsix
   ```

3. Start ppxai-server before using the extension:
   ```bash
   ppxai-server
   # Or: uv run ppxai-server
   ```

### Building from Source
```bash
cd vscode-extension
npm install
npm run compile
npx vsce package --allow-missing-repository
```

### Configuration
The extension connects to `ppxai-server` which reads API keys from:
1. Workspace `.env`
2. Project root `.env`
3. `~/.ppxai/.env`

Extension settings:
- `ppxai.serverUrl` - ppxai-server URL (default: `http://127.0.0.1:54320`)
- `ppxai.defaultProvider` - Default AI provider
- `ppxai.defaultModel` - Default model
- `ppxai.enableTools` - Enable AI tools

### Commands
- `ppxai.openChat` - Open chat panel
- `ppxai.explainSelection` - Explain selected code
- `ppxai.generateTests` - Generate tests
- `ppxai.generateDocs` - Generate documentation
- `ppxai.debugError` - Debug an error
- `ppxai.implement` - Implement from description
- `ppxai.switchProvider` - Switch AI provider
- `ppxai.switchModel` - Switch model

## Engine Layer (v1.7.0 - Complete)

The engine layer has been implemented. See `docs/architecture-refactoring.md` for details.

### New Engine Structure

```
ppxai/engine/
├── __init__.py          # Public exports
├── types.py             # Shared types (Event, Message, etc.)
├── client.py            # EngineClient facade
├── session.py           # Session management
├── providers/           # Provider implementations
│   ├── base.py          # BaseProvider abstract class
│   ├── perplexity.py    # Perplexity (native search)
│   └── openai_compat.py # OpenAI-compatible
└── tools/               # Tool system
    ├── base.py          # BaseTool abstract class
    ├── manager.py       # ToolManager
    └── builtin/         # Built-in tools
```

### Using the Engine

```python
from ppxai.engine import EngineClient, EventType

# Create engine
engine = EngineClient()

# Set provider and model
engine.set_provider("perplexity")
engine.set_model("sonar-pro")

# Enable tools
engine.enable_tools()

# Chat (async with events)
async for event in engine.chat("Hello"):
    if event.type == EventType.STREAM_CHUNK:
        print(event.data, end="")
    elif event.type == EventType.TOOL_CALL:
        print(f"Calling tool: {event.data['tool']}")

# Or sync chat
response = engine.chat_sync("What time is it?")
```

### JSON-RPC Server

The server now uses `EngineClient` internally:

```python
from ppxai.server import JsonRpcServer

server = JsonRpcServer()
server.run()  # Reads JSON-RPC from stdin, writes to stdout
```

Available methods: `chat`, `coding_task`, `get_providers`, `set_provider`, `get_models`, `set_model`, `enable_tools`, `disable_tools`, `list_tools`, `get_status`, etc.
