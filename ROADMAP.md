# ppxai Development Roadmap

## Current Release: v1.6.0

**Status**: ✅ Complete - Multi-Provider Configuration & Tool Improvements

Features implemented:
- Hybrid configuration: `ppxai-config.json` for providers + `.env` for secrets
- JSON config file search order: `PPXAI_CONFIG_FILE` env → `./ppxai-config.json` → `~/.ppxai/ppxai-config.json` → built-in defaults
- New config functions: `get_config_source()`, `get_available_providers()`, `set_active_provider()`, `reload_config()`, `validate_config()`
- Backward compatibility with legacy `CUSTOM_*` env vars
- Support for multiple providers: Perplexity, OpenAI, OpenRouter, local models
- 172+ tests passing (including 48 new config tests, 25 shell command tests)

Bug fixes in this release:
- Fixed tool call JSON parsing for flat format (model outputting `{"tool": "...", "command": "..."}` instead of nested format)
- Fixed message alternation error when max tool iterations reached (Perplexity API 400 error)
- Fixed missing `export_conversation()`, `save_session()`, `get_usage_summary()` methods in PerplexityClientPromptTools
- Increased default `tool_max_iterations` from 5 to 15
- Added `/tools config` command to adjust max_iterations at runtime (1-50 range)

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

### v1.7.0: Per-Provider Tool Configuration (Priority: Medium)

**Goal**: Configure which tools are available for each provider

#### Features

1. **Tool Configuration Per Provider**
   - Enable/disable specific tools for each provider
   - Different tool sets for different use cases
   - Example use cases:
     - Disable shell commands on production endpoints
     - Enable only file operations for code review bots
     - Full tool access for development/testing

2. **Configuration Format**
   ```bash
   # Provider 1 tools configuration
   CUSTOM_PROVIDER_1_TOOLS=file,shell,calculator,datetime
   # or disable specific tools
   CUSTOM_PROVIDER_1_TOOLS_DISABLE=web_search,fetch_url

   # Provider 2 tools (minimal set)
   CUSTOM_PROVIDER_2_TOOLS=file,calculator

   # Provider 3 tools (all)
   CUSTOM_PROVIDER_3_TOOLS=all
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
- [ ] Define tool configuration schema
- [ ] Create `parse_provider_tools()` function
- [ ] Add tool categories mapping
- [ ] Update provider config structure

**Phase 2: Tool Manager Enhancement (2-3 hours)**
- [ ] Modify `ToolManager` to support provider-specific tools
- [ ] Implement tool filtering based on provider config
- [ ] Add runtime enable/disable functionality
- [ ] Create tool category groups

**Phase 3: Commands (1-2 hours)**
- [ ] Implement `/tools available` command
- [ ] Implement `/tools enabled` command
- [ ] Implement `/tools enable/disable <tool>` commands
- [ ] Update `/tools` command help text

**Phase 4: Validation & Security (1 hour)**
- [ ] Validate tool names in configuration
- [ ] Prevent enabling unavailable tools
- [ ] Add warnings for dangerous tool combinations
- [ ] Implement tool access logging (optional)

**Phase 5: Testing (2 hours)**
- [ ] Test tool filtering per provider
- [ ] Test runtime enable/disable
- [ ] Test tool category groups
- [ ] Integration tests with multiple providers

**Phase 6: Documentation (1 hour)**
- [ ] Update TOOLS.md with configuration guide
- [ ] Add security best practices
- [ ] Document tool categories
- [ ] Update `.env.example`

**Estimated Total**: 8-11 hours

---

### v1.8.0: Enhanced Tool System (Priority: Low)

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

### v1.9.0: Web Terminal & Launcher Options (Priority: Medium)

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

### v2.0.0: IDE Integration & Major Enhancements (Long-term)

**Goal**: Provide seamless IDE integration similar to Claude Code CLI and Gemini CLI

#### IDE Integration Features

1. **VS Code Extension**
   - Native VS Code extension for ppxai
   - Integrated terminal panel within VS Code
   - File context awareness (open files, workspace structure)
   - Inline code suggestions and completions
   - Side panel for chat interface
   - Command palette integration (`Ctrl+Shift+P` → "ppxai: ...")

2. **Editor Protocol Support**
   - Language Server Protocol (LSP) integration
   - Editor-agnostic communication protocol
   - Support for multiple editors:
     - VS Code (primary)
     - JetBrains IDEs (IntelliJ, PyCharm, WebStorm)
     - Neovim/Vim
     - Sublime Text
     - Cursor IDE

3. **Workspace Awareness**
   - Automatic project context detection
   - Git status and diff awareness
   - Dependency analysis (package.json, requirements.txt, etc.)
   - Project structure understanding
   - `.ppxai` config file per project

4. **Code Actions**
   - `/edit <file>` - AI-assisted file editing with diff preview
   - `/refactor` - Refactoring suggestions with apply/reject
   - `/explain` - Inline code explanations
   - `/test` - Generate tests for selected code
   - `/fix` - Fix errors/warnings in current file
   - `/review` - Code review for staged changes

5. **Context Sharing**
   - Share selected code with ppxai
   - Share terminal output
   - Share error messages and stack traces
   - Automatic file inclusion based on imports
   - @-mentions for files (`@src/utils.py explain this`)

6. **IDE-Specific Features**
   - Diagnostic integration (show AI suggestions for errors)
   - CodeLens for AI actions
   - Hover providers for explanations
   - Quick fixes powered by AI
   - Git integration (commit message generation, PR descriptions)

#### Implementation Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    VS Code / IDE                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
│  │  Extension  │  │  Terminal   │  │  Side Panel │     │
│  │   (UI)      │  │  (Embedded) │  │   (Chat)    │     │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘     │
└─────────┼────────────────┼────────────────┼─────────────┘
          │                │                │
          ▼                ▼                ▼
┌─────────────────────────────────────────────────────────┐
│              ppxai Language Server / Daemon             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
│  │  LSP Server │  │  WebSocket  │  │   JSON-RPC  │     │
│  │             │  │   Server    │  │   Handler   │     │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘     │
└─────────┼────────────────┼────────────────┼─────────────┘
          │                │                │
          ▼                ▼                ▼
┌─────────────────────────────────────────────────────────┐
│                   ppxai Core Engine                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
│  │  AI Client  │  │    Tools    │  │   Session   │     │
│  │  (Multi-    │  │  (File,     │  │  Management │     │
│  │  Provider)  │  │   Shell)    │  │             │     │
│  └─────────────┘  └─────────────┘  └─────────────┘     │
└─────────────────────────────────────────────────────────┘
```

#### Implementation Plan

**Phase 1: Daemon Mode (4-5 hours)**
- [ ] Create ppxai daemon that runs in background
- [ ] Implement JSON-RPC or WebSocket API
- [ ] Add `ppxai --daemon` and `ppxai --connect` modes
- [ ] Implement health check and auto-restart

**Phase 2: VS Code Extension - Basic (6-8 hours)**
- [ ] Create VS Code extension scaffold
- [ ] Implement terminal integration
- [ ] Add basic chat panel
- [ ] Connect to ppxai daemon
- [ ] Publish to VS Code Marketplace

**Phase 3: Workspace Context (4-5 hours)**
- [ ] Implement workspace file scanning
- [ ] Add git integration (status, diff, blame)
- [ ] Create project context builder
- [ ] Add @-mention file references

**Phase 4: Code Actions (6-8 hours)**
- [ ] Implement `/edit` with diff preview
- [ ] Add CodeLens providers
- [ ] Create diagnostic integration
- [ ] Implement quick fixes

**Phase 5: LSP Integration (8-10 hours)**
- [ ] Create LSP server wrapper
- [ ] Implement completion provider
- [ ] Add hover provider for explanations
- [ ] Create signature help provider

**Phase 6: Multi-IDE Support (6-8 hours)**
- [ ] Create JetBrains plugin (Kotlin)
- [ ] Add Neovim plugin (Lua)
- [ ] Document generic editor integration

**Estimated Total**: 34-44 hours

**Dependencies:**
- `pygls` (Python LSP server framework)
- VS Code Extension API
- `watchdog` (file system monitoring)

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

### Completed (v1.6.0) ✅
- ✅ **Done**: Hybrid configuration (ppxai-config.json + .env)
- ✅ **Done**: Multiple provider support
- ✅ **Done**: Config validation and reload

### Immediate (v1.7.0)
- ⚠️ **Must Have**: `/provider` commands (list, switch, info)
- ⚠️ **Must Have**: Per-provider tool configuration
- ⚠️ **Should Have**: Tool categories

### Short-term (v1.8.0)
- ⚠️ **Nice to Have**: Tool aliases
- ⚠️ **Nice to Have**: Tool presets
- ⚠️ **Nice to Have**: Usage statistics

### Medium-term (v1.9.0)
- 🌐 **Nice to Have**: Web terminal interface (browser-based)
- 🖥️ **Nice to Have**: Configurable terminal launcher
- 📱 **Nice to Have**: Cross-platform terminal support

### Long-term (v2.0.0+)
- 🔌 **Future**: VS Code extension & IDE integration
- 🔌 **Future**: LSP server for editor-agnostic support
- 💡 **Future**: Plugin system
- 💡 **Future**: Multi-modal support
- 💡 **Future**: Workflow automation

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

**Last Updated**: November 29, 2025
**Current Version**: v1.6.0
**Next Target**: v1.7.0 (Provider Commands & Per-Provider Tools)
