# ppxai Development Roadmap

## Current Release: v1.8.0

**Status**: ✅ Complete - VSCode Extension & Enhanced UX

Features implemented:
- **VSCode Extension** with full chat UI in sidebar
- **@filename file referencing** in chat messages (TUI + Extension)
- **Autocomplete** for `/` commands and `@` file references (Tab completion in TUI, live suggestions in Extension)
- **Tools toggle button** in extension UI (click to enable/disable)
- **Markdown rendering** improvements with proper heading sizes, code highlighting
- **File search** for `/show` command with fuzzy matching
- **Response timing** display in both TUI and extension

Extension features:
- Chat panel with streaming responses
- Provider/model switching
- Session save/load
- Slash commands (`/help`, `/show`, `/tools`, etc.)
- Context menu commands (Explain Selection, Generate Tests, etc.)

---

## Previous Release: v1.7.0

**Status**: ✅ Complete - Engine Refactoring

Features implemented:
- **Layered architecture**: Engine → Server → Clients
- **Engine layer** (`ppxai/engine/`) with no UI dependencies
- **JSON-RPC server** for IDE integration
- **Provider abstraction** with `BaseProvider` interface
- **Tool system** with `BaseTool` and `ToolManager`
- Event-based communication between layers

---

## Previous Release: v1.6.0

**Status**: ✅ Complete - Multi-Provider Configuration & Tool Improvements

Features implemented:
- Hybrid configuration: `ppxai-config.json` for providers + `.env` for secrets
- JSON config file search order: `PPXAI_CONFIG_FILE` env → `./ppxai-config.json` → `~/.ppxai/ppxai-config.json` → built-in defaults
- New config functions: `get_config_source()`, `get_available_providers()`, `set_active_provider()`, `reload_config()`, `validate_config()`
- Backward compatibility with legacy `CUSTOM_*` env vars
- Support for multiple providers: Perplexity, OpenAI, OpenRouter, local models
- 180+ tests passing (including 48 config tests, 25 shell command tests)

Bug fixes:
- Fixed tool call JSON parsing for flat format
- Fixed message alternation error when max tool iterations reached
- Added `/tools config` command to adjust max_iterations at runtime

---

## Previous Release: v1.5.0

**Status**: ✅ Complete - Shell commands & SSL fix

Features implemented:
- Shell command execution tool (`execute_shell_command`)
- SSL certificate verification fix for corporate proxies
- Unified `SSL_VERIFY` environment variable

---

## Completed: v1.6.0 Multi-Provider Configuration

**Goal**: Support multiple custom providers with easy switching using a hybrid configuration approach

#### Architecture: Hybrid Configuration

**Design Principle**: Separate sensitive data from configuration data
- **`.env`** - Only sensitive API keys (secrets, never committed to git)
- **`ppxai-config.json`** - Provider definitions, models, capabilities (can be version controlled)

#### Features

1. **JSON-Based Provider Configuration**
   - All provider settings in `ppxai-config.json`
   - Supports unlimited providers
   - Each provider can have:
     - Multiple models with descriptions
     - Custom pricing (or $0 for self-hosted)
     - Capability flags (web_search, realtime_info, etc.)
     - Tool configuration

2. **Configuration File Format**

   **`ppxai-config.json`** (can be committed to git):
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
           "sonar": {
             "name": "Sonar",
             "description": "Lightweight search model"
           },
           "sonar-pro": {
             "name": "Sonar Pro",
             "description": "Advanced search model"
           }
         },
         "pricing": {
           "sonar": {"input": 0.20, "output": 0.20},
           "sonar-pro": {"input": 3.00, "output": 15.00}
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
           "gpt-4o": {
             "name": "GPT-4o",
             "description": "Latest flagship model"
           },
           "gpt-4o-mini": {
             "name": "GPT-4o Mini",
             "description": "Fast and affordable"
           }
         },
         "pricing": {
           "gpt-4o": {"input": 2.50, "output": 10.00},
           "gpt-4o-mini": {"input": 0.15, "output": 0.60}
         },
         "capabilities": {
           "web_search": false,
           "realtime_info": false
         }
       },
       "openrouter": {
         "name": "OpenRouter (Claude)",
         "base_url": "https://openrouter.ai/api/v1",
         "api_key_env": "OPENROUTER_API_KEY",
         "default_model": "anthropic/claude-sonnet-4",
         "models": {
           "anthropic/claude-sonnet-4": {
             "name": "Claude Sonnet 4",
             "description": "Anthropic's balanced model"
           },
           "anthropic/claude-opus-4": {
             "name": "Claude Opus 4",
             "description": "Anthropic's most capable model"
           }
         },
         "pricing": {
           "anthropic/claude-sonnet-4": {"input": 3.00, "output": 15.00},
           "anthropic/claude-opus-4": {"input": 15.00, "output": 75.00}
         },
         "capabilities": {
           "web_search": false,
           "realtime_info": false
         }
       },
       "local-llama": {
         "name": "Local Llama (vLLM)",
         "base_url": "http://localhost:8000/v1",
         "api_key_env": "LOCAL_API_KEY",
         "default_model": "meta-llama/Llama-3-70b",
         "models": {
           "meta-llama/Llama-3-70b": {
             "name": "Llama 3 70B",
             "description": "Self-hosted Llama model"
           }
         },
         "pricing": {
           "meta-llama/Llama-3-70b": {"input": 0.0, "output": 0.0}
         },
         "capabilities": {
           "web_search": false,
           "realtime_info": false
         }
       }
     }
   }
   ```

   **`.env`** (secrets only, never commit):
   ```bash
   # API Keys only - referenced by api_key_env in ppxai-config.json
   PERPLEXITY_API_KEY=pplx-xxxxxxxxxxxxxxxx
   OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxxxxx
   OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxxxxxx
   LOCAL_API_KEY=dummy-key

   # Optional: Override default provider from config
   MODEL_PROVIDER=openai

   # Optional: SSL verification (for corporate proxies)
   SSL_VERIFY=true
   ```

3. **Configuration File Locations** (searched in order)
   1. `./ppxai-config.json` - Project-specific (for teams)
   2. `~/.ppxai/ppxai-config.json` - User-specific (personal setup)
   3. Built-in defaults (Perplexity only, backward compatible)

4. **Provider Management Commands**
   - `/provider list` - Show all configured providers with status
   - `/provider switch <name>` - Switch to a specific provider
   - `/provider info` - Show current provider details (endpoint, models, capabilities)
   - `/provider models` - List models for current provider
   - `/provider validate` - Check all provider configurations

5. **Backward Compatibility**
   - If no `ppxai-config.json` exists, fall back to current `.env` behavior
   - Existing `CUSTOM_*` env vars still work as a single custom provider
   - Perplexity provider always available as built-in default

#### Implementation Plan (✅ COMPLETED)

**Phase 1: Configuration Schema & Loading** ✅
- [x] Define JSON schema for `ppxai-config.json`
- [x] Create `load_config()` function with file location search
- [x] Implement config validation with helpful error messages
- [x] Add backward compatibility layer for existing `.env` setup
- [x] Create `ppxai-config.example.json` template

**Phase 2: Config Integration** ✅
- [x] Update `ppxai/config.py` to use JSON config
- [x] Merge JSON providers with built-in Perplexity config
- [x] Implement `api_key_env` lookup from environment
- [x] Add config reload capability

**Phase 3: UI/UX** (Partial - commands deferred to v1.7)
- [x] Config system supports multiple providers
- [ ] `/provider` command with subcommands (deferred)

**Phase 4: Client Management** ✅
- [x] Update client initialization to use config-based providers
- [x] Ensure session metadata tracks provider correctly
- [x] Test provider switching during session

**Phase 5: Testing** ✅
- [x] Add tests for JSON config loading and validation (48 tests)
- [x] Test config file location precedence
- [x] Test backward compatibility with `.env` only
- [x] Integration tests with multiple providers
- [x] Test missing API key handling

**Phase 6: Documentation** ✅
- [x] Update README.md with new configuration approach
- [x] Create `ppxai-config.example.json` with all provider examples
- [x] Document config file locations and precedence
- [x] Update CLAUDE.md with architecture overview

#### Benefits of This Approach

| Aspect | `.env` Only (old) | Hybrid `.env` + JSON (new) |
|--------|-------------------|---------------------------|
| Secrets safety | ✅ Good | ✅ Better (clear separation) |
| Version control | ❌ Can't share config | ✅ Config can be committed |
| Team sharing | ❌ Manual setup each | ✅ Share `ppxai-config.json` |
| Multiple models | ❌ One model per provider | ✅ Multiple models per provider |
| Readability | ❌ Flat key-value | ✅ Structured JSON |
| Validation | ❌ Runtime errors | ✅ Schema validation |
| Backward compat | N/A | ✅ Falls back to `.env` |

---

### v1.9.0: Modern Tooling & Performance (Priority: High)

This release focuses on modernizing the development infrastructure and improving runtime performance through two complementary migrations.

---

#### Part A: uv Migration - Modern Python Tooling

**Goal**: Migrate from `pip` + `requirements.txt` to `uv` for faster, reproducible builds

**Detailed Plan**: See [docs/uv-migration-plan.md](docs/uv-migration-plan.md)

##### Motivation

| Aspect | Current (`pip`) | With `uv` | Improvement |
|--------|-----------------|-----------|-------------|
| Fresh install | ~45s | ~3s | 15x faster |
| CI dependency step | ~60s | ~5s | 12x faster |
| Lockfile | None | `uv.lock` | Reproducible |
| Python management | External | Built-in | Simpler |
| Project metadata | `requirements.txt` | `pyproject.toml` | Standard |

##### Features

1. **pyproject.toml Configuration**
   - Standard Python packaging format (PEP 621)
   - Optional dependency groups: `server`, `mcp`, `dev`, `build`
   - Script entry points: `ppxai`, `ppxai-server`

2. **Lockfile Support**
   - `uv.lock` for reproducible builds
   - Commit lockfile to version control
   - `uv sync --frozen` for CI

3. **Faster Development Workflow**
   - `uv sync` - one command setup
   - `uv run` - run without activation
   - `uvx` - run tools without installing

##### Implementation Plan

**Phase 1: Create pyproject.toml & Bootstrap (1.5 hours)**
- [ ] Create `pyproject.toml` with all dependencies
- [ ] Define optional dependency groups (server, mcp, dev, build)
- [ ] Configure script entry points
- [ ] Add tool configurations (ruff, pytest)
- [ ] Create `scripts/bootstrap.py` (auto-downloads uv)
- [ ] Add `.uv/` to `.gitignore`

**Phase 2: Migration (1 hour)**
- [ ] Run `python scripts/bootstrap.py` to test bootstrap
- [ ] Verify app runs: `.uv/uv run ppxai`
- [ ] Verify tests pass: `.uv/uv run pytest tests/ -v`
- [ ] Regenerate `requirements.txt` for backward compat

**Phase 3: Documentation (1 hour)**
- [ ] Update `CLAUDE.md` with bootstrap script instructions
- [ ] Update `README.md` installation section
- [ ] Document manual uv installation as alternative

**Phase 4: CI/CD (1 hour)**
- [ ] Update GitHub Actions to use `astral-sh/setup-uv@v4`
- [ ] Use `uv sync --frozen` for reproducible CI builds
- [ ] Add caching for uv dependencies

**Estimated Total**: 4.5 hours

---

#### Part B: HTTP + SSE Backend Migration

**Goal**: Replace JSON-RPC over stdio with HTTP + Server-Sent Events for improved streaming performance

**Detailed Plan**: See [docs/sse-migration-plan.md](docs/sse-migration-plan.md)

##### Motivation

The current JSON-RPC/stdio architecture has inherent limitations:
- Synchronous `for line in stdin` with `asyncio.run()` per request
- Mixed stdout protocol (streaming events + JSON-RPC responses)
- ~50-200ms first token latency overhead
- No native request cancellation

##### Expected Improvements

| Metric | JSON-RPC (current) | HTTP + SSE (proposed) | Improvement |
|--------|-------------------|----------------------|-------------|
| First token latency | 50-200ms | 10-30ms | 3-10x faster |
| Throughput | ~1,000 msg/s | ~5,000 msg/s | 5x higher |
| Request cancellation | Kill process | AbortController | Native |
| Reconnection | Manual restart | Built-in SSE | Automatic |
| Debug tooling | Custom | Browser DevTools | Standard |

##### Features

1. **FastAPI HTTP Server** (`ppxai/server/http.py`)
   - SSE streaming for chat responses
   - REST endpoints for configuration
   - Native async request handling
   - CORS support for webview

2. **TypeScript HTTP Client** (`vscode-extension/src/backend-http.ts`)
   - Fetch API with streaming reader
   - AbortController for cancellation
   - Event mapping for compatibility

3. **Server Lifecycle Manager**
   - Automatic server startup
   - Health check monitoring
   - Graceful shutdown

4. **Backward Compatibility**
   - JSON-RPC backend retained as fallback
   - Auto-selection: HTTP preferred, JSON-RPC fallback
   - Configuration option: `ppxai.backend: auto | http | jsonrpc`

##### Implementation Plan

**Phase 1: Python HTTP Server (3-4 hours)**
- [ ] Install server dependencies: `uv sync --extra server`
- [ ] Create `ppxai/server/http.py` with SSE streaming
- [ ] Add `/chat`, `/coding_task` streaming endpoints
- [ ] Add REST endpoints for providers, models, tools, sessions
- [ ] Add health check endpoint
- [ ] Test independently: `uv run ppxai-server`

**Phase 2: TypeScript HTTP Client (2-3 hours)**
- [ ] Create `vscode-extension/src/backend-http.ts`
- [ ] Implement SSE stream processing with fetch
- [ ] Add AbortController support for cancellation
- [ ] Map event types for backward compatibility

**Phase 3: Server Management (2 hours)**
- [ ] Create `vscode-extension/src/serverManager.ts`
- [ ] Implement server startup with health check polling
- [ ] Add graceful shutdown on extension deactivate

**Phase 4: Backend Factory & Integration (2 hours)**
- [ ] Create `vscode-extension/src/backendFactory.ts`
- [ ] Implement auto-selection with fallback
- [ ] Update `chatPanel.ts` to use factory
- [ ] Add configuration options to `package.json`

**Phase 5: Testing & Validation (2 hours)**
- [ ] Benchmark latency comparison
- [ ] Test fallback to JSON-RPC
- [ ] Test cancellation mid-stream
- [ ] Verify tool calls work correctly

**Estimated Total**: 11-13 hours

---

#### v1.9.0 Combined Summary

| Component | Effort | Key Deliverable |
|-----------|--------|-----------------|
| uv Migration | 4.5 hours | `pyproject.toml`, `uv.lock`, bootstrap script, faster CI |
| HTTP + SSE | 11-13 hours | 3-10x latency improvement |
| **Total** | **15.5-17.5 hours** | Modern tooling + performance |

##### New Dependencies (via pyproject.toml)

```toml
[project.optional-dependencies]
server = [
    "fastapi>=0.104.0",
    "uvicorn[standard]>=0.24.0",
]
```

##### Installation After v1.9.0

```bash
# Basic installation
uv sync

# With HTTP server support
uv sync --extra server

# Run HTTP server
uv run ppxai-server
```

---

### v1.10.0: VSCode Extension CI/CD & Marketplace Publishing (Priority: High)

**Goal**: Automate VSCode extension builds and publishing to the marketplace

#### Features

1. **GitHub Actions Workflow**
   - Automated builds on push/PR to extension directory
   - Version bumping and changelog generation
   - Cross-platform testing (Windows, macOS, Linux)
   - VSIX artifact generation

2. **Marketplace Publishing**
   - Automated publishing to VS Code Marketplace
   - Publisher account setup and token management
   - Version tag-based releases
   - Pre-release channel support

3. **Quality Gates**
   - ESLint/TypeScript checks
   - Extension manifest validation
   - Bundle size monitoring
   - Automated testing (if applicable)

#### Implementation Plan

**Phase 1: CI Workflow (2-3 hours)**
- [ ] Create `.github/workflows/vscode-extension.yml`
- [ ] Setup Node.js environment and caching
- [ ] Add compile and lint steps
- [ ] Generate VSIX artifacts
- [ ] Upload artifacts to releases

**Phase 2: Marketplace Setup (1-2 hours)**
- [ ] Create Azure DevOps organization (if needed)
- [ ] Create VS Code Marketplace publisher account
- [ ] Generate Personal Access Token (PAT)
- [ ] Add PAT as GitHub secret (`VSCE_PAT`)
- [ ] Configure publisher in `package.json`

**Phase 3: Release Workflow (2-3 hours)**
- [ ] Create release workflow triggered by tags (`v*-ext`)
- [ ] Auto-increment version in `package.json`
- [ ] Generate changelog from commits
- [ ] Publish to VS Code Marketplace
- [ ] Create GitHub release with VSIX

**Phase 4: Pre-release Support (1 hour)**
- [ ] Configure pre-release channel
- [ ] Beta version naming convention
- [ ] Separate workflow for pre-releases

**Estimated Total**: 6-9 hours

#### Example Workflow

```yaml
# .github/workflows/vscode-extension.yml
name: VSCode Extension CI/CD

on:
  push:
    paths:
      - 'vscode-extension/**'
    tags:
      - 'v*-ext'
  pull_request:
    paths:
      - 'vscode-extension/**'

jobs:
  build:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: vscode-extension
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'
          cache-dependency-path: vscode-extension/package-lock.json
      - run: npm ci
      - run: npm run lint
      - run: npm run compile
      - run: npx vsce package
      - uses: actions/upload-artifact@v4
        with:
          name: ppxai-extension
          path: vscode-extension/*.vsix

  publish:
    if: startsWith(github.ref, 'refs/tags/v')
    needs: build
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@v4
      - run: npx vsce publish -p ${{ secrets.VSCE_PAT }}
```

---

### v1.11.0: Per-Provider Tool Configuration (Priority: Medium)

*Moved from v1.10.0*

**Goal**: Configure which tools are available for each provider

#### Features

1. **Tool Configuration Per Provider**
   - Enable/disable specific tools for each provider
   - Different tool sets for different use cases
   - Example use cases:
     - Disable shell commands on production endpoints
     - Enable only file operations for code review bots
     - Full tool access for development/testing

2. **Configuration Format** (in `ppxai-config.json`)
   ```json
   {
     "providers": {
       "perplexity": {
         "tools": {
           "disabled": ["web_search", "fetch_url"]
         }
       },
       "openai": {
         "tools": {
           "enabled": ["all"]
         }
       },
       "local": {
         "tools": {
           "enabled": ["file", "calculator", "datetime"]
         }
       }
     }
   }
   ```

3. **Tool Management Commands**
   - `/tools available` - Show all available tools in system
   - `/tools enabled` - Show tools enabled for current provider
   - `/tools enable <tool>` - Enable specific tool for current session
   - `/tools disable <tool>` - Disable specific tool for current session
   - `/tools reset` - Reset to provider defaults

4. **Tool Categories**
   - `file` - File operations (read, search, list_directory)
   - `shell` - Shell command execution
   - `web` - Web operations (search, fetch_url)
   - `data` - Data tools (calculator, datetime)
   - `weather` - Weather information
   - `all` - All available tools

#### Implementation Plan

**Phase 1: Configuration Schema (1-2 hours)**
- [ ] Define tool configuration schema in JSON config
- [ ] Add tool categories mapping
- [ ] Update provider config structure

**Phase 2: Tool Manager Enhancement (2-3 hours)**
- [ ] Modify `ToolManager` to support provider-specific tools
- [ ] Implement tool filtering based on provider config
- [ ] Add runtime enable/disable functionality

**Phase 3: Commands (1-2 hours)**
- [ ] Implement `/tools available` command
- [ ] Implement `/tools enable/disable <tool>` commands
- [ ] Update `/tools` command help text

**Phase 4: Testing & Documentation (2 hours)**
- [ ] Test tool filtering per provider
- [ ] Update documentation

**Estimated Total**: 6-9 hours

---

### v1.12.0: Enhanced Tool System (Priority: Low)

*Moved from v1.11.0*

**Goal**: Improve tool capabilities and user experience

#### Features

1. **Tool Aliases**
   - Short aliases for frequently used tools
   - User-configurable aliases
   - Example: `ls` → `list_directory`, `calc` → `calculator`

2. **Tool Presets**
   - Pre-defined tool combinations for specific tasks
   - `coding` preset: file + shell + calculator
   - `research` preset: web + fetch_url + calculator + datetime
   - `admin` preset: shell + file + datetime
   - `safe` preset: calculator + datetime only

3. **Tool Execution History**
   - Track which tools are used
   - Usage statistics per tool
   - Most used tools dashboard
   - `/tools stats` command

4. **Interactive Tool Configuration**
   - `/tools wizard` - Interactive tool setup
   - Guided configuration for beginners
   - Test tool functionality before enabling

5. **Tool Plugins**
   - Support for custom user-defined tools
   - Tool plugin directory (`~/.ppxai/tools/`)
   - Hot-reload tool plugins
   - Tool marketplace (future consideration)

#### Implementation Plan

**Phase 1: Tool Aliases (1 hour)**
- [ ] Add alias configuration to tool definitions
- [ ] Implement alias resolution in command handler
- [ ] Update tool help to show aliases

**Phase 2: Tool Presets (2 hours)**
- [ ] Define preset configurations
- [ ] Implement preset loading
- [ ] Add `/tools preset <name>` command
- [ ] Create preset templates

**Phase 3: Usage Tracking (2 hours)**
- [ ] Add tool execution logging
- [ ] Create usage statistics storage
- [ ] Implement `/tools stats` command
- [ ] Add visualization for stats

**Phase 4: Interactive Configuration (2-3 hours)**
- [ ] Create tool configuration wizard
- [ ] Implement interactive prompts
- [ ] Add tool testing functionality
- [ ] Build guided setup flow

**Phase 5: Plugin System (4-5 hours)**
- [ ] Design plugin interface
- [ ] Implement plugin discovery
- [ ] Add plugin loading mechanism
- [ ] Create plugin template/examples
- [ ] Add plugin validation

**Phase 6: Testing & Docs (2 hours)**
- [ ] Test all new features
- [ ] Write plugin development guide
- [ ] Update documentation
- [ ] Create example plugins

**Estimated Total**: 13-16 hours

---

### v1.13.0: Web Terminal & Launcher Options (Priority: Low)

*Moved from v1.12.0*

**Goal**: Provide flexible terminal launch options including web-based access

#### Features

1. **Web Terminal Interface**
   - HTML-based terminal emulator (xterm.js or similar)
   - Run ppxai in a browser tab
   - WebSocket-based communication with backend
   - Cross-platform access without native installation
   - Shareable session URLs (optional)

2. **Configurable Terminal Launcher**
   - Executable opens system default terminal or configured terminal
   - Configuration in `ppxai-config.json`:
     ```json
     {
       "terminal": {
         "mode": "native",  // "native", "web", or "auto"
         "native_terminal": {
           "macos": "Terminal.app",  // or "iTerm.app", "Warp.app"
           "linux": "gnome-terminal",  // or "konsole", "xterm"
           "windows": "wt.exe"  // Windows Terminal, or "cmd.exe"
         },
         "web": {
           "host": "localhost",
           "port": 8080,
           "auto_open_browser": true
         }
       }
     }
     ```

3. **Launch Modes**
   - `ppxai` - Launch in current terminal (default, current behavior)
   - `ppxai --terminal` - Launch in configured native terminal
   - `ppxai --web` - Start web server and open browser
   - `ppxai --web --port 3000` - Custom port for web mode
   - `ppxai --headless` - Web server only, no browser auto-open

4. **Web Terminal Features**
   - Full terminal emulation with ANSI color support
   - Copy/paste support
   - Responsive design for mobile access
   - Optional authentication for remote access
   - Theme customization (dark/light mode)

#### Implementation Plan

**Phase 1: Web Terminal Backend (4-5 hours)**
- [ ] Add WebSocket server (using `websockets` or `aiohttp`)
- [ ] Create PTY bridge for terminal I/O
- [ ] Implement session management for web clients
- [ ] Handle terminal resize events

**Phase 2: Web Terminal Frontend (4-5 hours)**
- [ ] Integrate xterm.js terminal emulator
- [ ] Create minimal HTML/CSS interface
- [ ] Implement WebSocket client connection
- [ ] Add copy/paste and keyboard handling
- [ ] Bundle frontend assets with PyInstaller

**Phase 3: Native Terminal Launcher (2-3 hours)**
- [ ] Detect available terminals per platform
- [ ] Implement terminal launch for macOS (Terminal.app, iTerm, Warp)
- [ ] Implement terminal launch for Linux (gnome-terminal, konsole, etc.)
- [ ] Implement terminal launch for Windows (Windows Terminal, cmd, PowerShell)
- [ ] Add configuration options in `ppxai-config.json`

**Phase 4: CLI Arguments & Config (2 hours)**
- [ ] Add `--terminal`, `--web`, `--headless` flags
- [ ] Implement `--port` option for web mode
- [ ] Read terminal preferences from config file
- [ ] Add `/config terminal` command for runtime changes

**Phase 5: Security & Polish (2-3 hours)**
- [ ] Add optional authentication for web mode
- [ ] Implement HTTPS support (self-signed or Let's Encrypt)
- [ ] Add rate limiting and connection limits
- [ ] Create connection status indicators

**Phase 6: Testing & Documentation (2 hours)**
- [ ] Test on all platforms (macOS, Linux, Windows)
- [ ] Test web terminal in major browsers
- [ ] Document all launch modes
- [ ] Update README with web terminal instructions

**Estimated Total**: 16-20 hours

**Dependencies:**
- `xterm.js` (frontend terminal emulator)
- `websockets` or `aiohttp` (WebSocket server)
- `ptyprocess` (Unix) / `winpty` (Windows) for PTY handling

---

## Additional Future Considerations

### v2.0.0: Advanced IDE Integration & Multi-Editor Support (Long-term)

**Goal**: Expand IDE integration beyond VS Code and add advanced features

**Note**: Basic VS Code extension is complete (v1.8.0). This phase focuses on advanced features and multi-IDE support.

#### Completed in v1.8.0 ✅
- ✅ VS Code extension with chat panel
- ✅ Side panel for chat interface
- ✅ Command palette integration
- ✅ @-mentions for files
- ✅ JSON-RPC server for IDE communication
- ✅ Streaming responses
- ✅ Session management
- ✅ Provider/model switching

#### Remaining Features

1. **Multi-Editor Support**
   - JetBrains IDEs plugin (IntelliJ, PyCharm, WebStorm)
   - Neovim/Vim plugin
   - Sublime Text plugin
   - Editor-agnostic LSP server

2. **Advanced Code Actions**
   - `/edit <file>` - AI-assisted file editing with diff preview
   - `/refactor` - Refactoring suggestions with apply/reject
   - `/fix` - Fix errors/warnings in current file
   - `/review` - Code review for staged changes
   - CodeLens integration for AI actions

3. **Enhanced Workspace Awareness**
   - Git status and diff awareness
   - Dependency analysis (package.json, requirements.txt, etc.)
   - Automatic context from imports
   - Diagnostic integration

4. **LSP Integration**
   - Language Server Protocol support
   - Completion provider
   - Hover provider for explanations
   - Signature help provider

#### Implementation Plan

**Phase 1: Advanced Code Actions (6-8 hours)**
- [ ] Implement `/edit` with diff preview
- [ ] Add inline code modifications
- [ ] Create diagnostic integration
- [ ] Implement quick fixes

**Phase 2: LSP Server (8-10 hours)**
- [ ] Create LSP server wrapper using `pygls`
- [ ] Implement completion provider
- [ ] Add hover provider for explanations
- [ ] Create signature help provider

**Phase 3: Multi-IDE Support (10-14 hours)**
- [ ] Create JetBrains plugin (Kotlin)
- [ ] Add Neovim plugin (Lua)
- [ ] Document generic editor integration

**Estimated Total**: 24-32 hours

---

#### Other v2.0.0 Enhancements

1. **Advanced Session Management**
   - Session branching and merging
   - Session templates
   - Collaborative sessions (multi-user)

2. **Enhanced Streaming**
   - Real-time tool execution visualization
   - Progress indicators for long-running commands
   - Streaming token cost estimation

3. **Advanced Context Management**
   - Automatic context pruning
   - Smart context summarization
   - Context compression strategies

4. **Multi-Modal Support**
   - Image analysis tools
   - Document processing (PDF, DOCX)
   - Code screenshot analysis

5. **Workflow Automation**
   - Macro recording and playback
   - Scheduled tasks
   - Batch processing

6. **Performance Optimization**
   - Async tool execution
   - Tool result caching
   - Request batching

---

## Development Priorities

### Completed ✅

**v1.8.0** - VSCode Extension & Enhanced UX
- ✅ VSCode extension with full chat UI
- ✅ @filename file referencing
- ✅ Autocomplete for / commands and @files
- ✅ Tools toggle button in extension
- ✅ Markdown rendering improvements
- ✅ File search for /show command

**v1.7.0** - Engine Refactoring
- ✅ Layered architecture (Engine → Server → Clients)
- ✅ JSON-RPC server for IDE integration
- ✅ Provider abstraction with BaseProvider interface

**v1.6.0** - Multi-Provider Configuration
- ✅ Hybrid configuration (ppxai-config.json + .env)
- ✅ Multiple provider support
- ✅ Config validation and reload

### Immediate (v1.9.0)
- 🛠️ **High Priority**: uv migration - modern Python tooling (15x faster installs)
- 🛠️ **High Priority**: pyproject.toml + lockfile for reproducible builds
- 🚀 **High Priority**: HTTP + SSE backend migration (3-10x latency improvement)
- 🚀 **High Priority**: FastAPI server with native streaming
- 📖 **Documentation**: [docs/uv-migration-plan.md](docs/uv-migration-plan.md), [docs/sse-migration-plan.md](docs/sse-migration-plan.md)

### Short-term (v1.10.0)
- 📦 **High Priority**: VSCode Extension CI/CD & Marketplace publishing
- 📦 **High Priority**: GitHub Actions workflow for extension builds
- 📦 **High Priority**: Automated VSIX packaging and releases

### Medium-term (v1.11.0 - v1.12.0)
- ⚠️ **Medium**: Per-provider tool configuration
- ⚠️ **Medium**: Tool categories (file, shell, web, data)
- 💡 **Nice to Have**: Tool aliases and presets
- 💡 **Nice to Have**: Tool usage statistics

### Long-term (v1.13.0 - v2.0.0+)
- 🌐 **Nice to Have**: Web terminal interface
- 🔌 **Future**: Multi-IDE support (JetBrains, Neovim, Sublime)
- 🔌 **Future**: LSP server for editor-agnostic support
- 💡 **Future**: Advanced code actions (edit, refactor, review)
- 💡 **Future**: Plugin system
- 💡 **Future**: Multi-modal support

---

## Contributing

Interested in working on any of these features?

1. Check the roadmap for the feature you want to implement
2. Create a feature branch: `git checkout -b feature/your-feature-name`
3. Follow the implementation plan outlined above
4. Write tests (maintain 100% pass rate)
5. Update documentation
6. Submit a pull request

---

## Notes

- All estimates are development time only (not including code review)
- Testing should maintain 100% test pass rate
- Documentation is mandatory for all new features
- Security considerations should be evaluated for each feature
- Backward compatibility must be maintained

---

**Last Updated**: December 8, 2025
**Current Version**: v1.8.0
**Next Target**: v1.9.0 (HTTP + SSE Backend Migration)
