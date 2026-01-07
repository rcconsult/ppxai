# Changelog

All notable changes to ppxai will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.13.3] - 2026-01-07

### Fixed - Session Management

- **TUI `/sessions` command** - Fixed KeyError 'saved_at' crash when listing sessions
- **Session data alignment** - All UIs (TUI, Web App, VSCode) now show consistent session info with Created and Last Saved timestamps
- **Robust session display** - `display_sessions()` now uses `.get()` for graceful handling of missing fields

### Changed - UI Consistency

- **Sessions table format** - All three UIs now display sessions in a markdown table with: Session, Messages, Provider/Model, Created, Last Saved columns
- **SessionInfo dataclass** - Added `saved_at` field to `SessionInfo` in engine types
- **HTTP endpoint** - `/sessions` endpoint now includes `saved_at` in response

### Fixed - File Editing Tools

- **Working directory resolution** - `apply_patch`, `replace_block`, `insert_text`, `delete_lines` now resolve relative paths against the engine's working directory instead of the process working directory
- **Critical fix** - Previously, when using file editing tools with a relative path like `task_analysis.ipynb`, the file would be created in `~/.ppxai/bin/` (where ppxai-server runs) instead of the project directory shown in the UI

### Fixed - Build/Release

- **validate-release.py** - Fixed UTF-8 encoding for Windows compatibility

## [1.13.2] - 2026-01-05

### Fixed - Desktop Web App & VSCode Extension

#### Markdown Rendering
- **Fixed bullet lists** - Changed from Unicode bullet (•) to markdown dash (-) for proper rendering
- **Fixed `/usage` tables** - Both VSCode extension and Web App now show usage breakdown in table format
- **Updated marked.js** - Upgraded Web App from v9.1.6 to v11.1.1 (matching VSCode extension)

#### Desktop Web App
- **Auto-detect server URL** - Web UI now uses `window.location.origin` instead of hardcoded port
- **Favicon** - Added proper favicon (same icon as VSCode extension)
- **Markdown preview** - File preview panel now renders `.md` files with full markdown support
- **Preview link clicks** - Clicking relative links in markdown preview opens files instead of 404

#### Shared Modules
- **Command parity** - New shared JS/TS modules ensure identical commands across TUI, VSCode, and Web App
- **Formatter parity** - Consistent markdown formatting for all command responses

### Fixed - Cross-Platform Compatibility (Windows)

#### Tests
- **Path handling** - Tests now use `tempfile.gettempdir()` instead of hardcoded `/tmp`
- **Filename references** - Tests use filename only, not full paths with platform-specific separators
- **Rich console** - Added `legacy_windows=False` for OSC 8 hyperlink tests

#### Configuration
- **PEP 735** - Migrated from `[tool.uv].dev-dependencies` to `[dependency-groups].dev`

### Added - Enhanced Install Script

#### New Flags
- **`--with-config`** - Generate `ppxai-config.json` and `.env` template with all providers
- **`--with-macos-app`** - Download and install DMG to `/Applications/ppxai.app`
- **`--with-launchagent`** - Install LaunchAgent for server auto-start (macOS)
- **`--uninstall`** - Remove ppxai installation (preserves config files)

#### macOS Improvements
- **Quarantine removal** - Automatically runs `xattr -cr` on downloaded binaries
- **DMG installation** - Downloads, mounts, copies app, removes quarantine attribute

#### Documentation
- **INSTALLATION.md** - Comprehensive guide with all new options and platform-specific instructions

---

## [1.13.1] - 2026-01-04

### Added - Desktop Web App

#### ppxai-desktop Launcher
- **Standalone launcher** - Start server and open browser with one click
- **macOS app bundle** - Native `.app` with DMG installer for drag-and-drop install
- **Cross-platform binaries** - Linux, Windows, macOS (ARM + Intel)
- **Auto-install** - Web UI files auto-copied to `~/.ppxai/web/` on first run

#### Web UI
- **Full-featured chat** - Browser-based chat interface with SSE streaming
- **Feature parity** - All slash commands, autocomplete, tools, agent mode, themes
- **Project selector** - Quick switch between recent project directories
- **Provider/model switching** - Dropdown selectors in header
- **Usage tracking** - Token counts and cost display

#### UI Improvements
- **Tool call ordering** - Tool calls now appear before the answer (matching VSCode)
- **Visual badge states** - Tools and Agent badges turn green when enabled
- **Usage tables** - Formatted markdown tables for `/usage` reports

### Documentation
- Updated INSTALLATION.md with desktop app instructions for all platforms
- Added Linux and Windows platform-specific behavior notes
- Added troubleshooting guide for desktop app

---

## [1.13.0] - 2026-01-03

### Added - Custom Provider Parity

#### Premium Web Search Tool
- **Custom provider support** - vLLM, Ollama, and other custom providers can now use premium web search
- **Priority fallback chain** - Perplexity Sonar > Gemini Grounding > DuckDuckGo (free)
- **Automatic detection** - Tool checks available API keys and uses best available option
- **Citation integration** - Web search results formatted consistently across all providers

#### SSL Proxy Support
- **`SSL_VERIFY` environment variable** - Disable SSL verification for corporate proxies
- **Corporate network compatible** - Works behind SSL-inspecting firewalls

#### Tool Usage Tracking
- **`ToolUsage` dataclass** - New type for tracking per-tool usage (calls, tokens, cost)
- **`/usage` enhancement** - Shows tool usage breakdown with provider info
- **Cost attribution** - Separate tracking for model costs vs tool costs

#### Native Tool Calling for Custom Providers
- **`native_tool_calling` capability** - Enable OpenAI-style function calling for vLLM endpoints
- **vLLM integration** - Works with `--enable-auto-tool-choice` flag
- **Streaming tool calls** - Full support for streaming responses with tool calls

#### Enhanced Tool Parsing
- **vLLM inference** - Infer tool names from argument patterns
- **Dispatcher pattern** - Match JSON arguments against registered tool schemas
- **Robust error handling** - Better recovery from malformed tool responses

### Testing
- 525 tests passing (119 new tests)
- Custom provider tool calling tests
- Tool parsing test coverage (440+ lines)
- Premium web search integration tests

---

## [1.12.5] - 2026-01-03

### Added - Native Gemini Provider

#### Google Search Grounding
- **Native Gemini SDK** - Direct integration with `google-genai` package
- **Google Search Grounding** - Real-time web search with citations (like Perplexity)
- **Streaming support** - Full async streaming with usage tracking
- **Graceful fallback** - Uses OpenAI-compatible API if `google-genai` not installed

#### Installation
```bash
pip install ppxai[gemini]   # For enhanced Gemini support
```

### Technical
- New provider: `ppxai/engine/providers/gemini.py`
- Auto-detection in provider factory
- No performance regression (benchmarked)

## [1.12.4] - 2026-01-03

### Added - Checkpoint Management & Web Search Improvements

#### `/checkpoint` Command
- **`/checkpoint status`** - View current checkpoint configuration
- **`/checkpoint list`** - List recent checkpoints (up to 10)
- **`/checkpoint backend <git|file|auto|none>`** - Switch checkpoint backend (session-only)
- **`/checkpoint clear`** - Clear old file-based checkpoint snapshots
- **`/checkpoint info <id>`** - Show details about a specific checkpoint
- **`/checkpoint undo`** - Alias for `/undo` command
- **Tab autocomplete** - Subcommands and backend options autocomplete in TUI

#### Web Search Tool Upgrade
- **`ddgs` package** - Upgraded to use `ddgs>=9.0.0` for more reliable DuckDuckGo search
- **Fallback chain** - Uses ddgs → duckduckgo-search → HTML scraping
- **No API key needed** - Works out of the box for all providers

### New Endpoints
- `GET /checkpoint/list` - List recent checkpoints
- `POST /checkpoint/backend` - Set checkpoint backend
- `POST /checkpoint/clear` - Clear file-based checkpoints

### VSCode Extension
- Full `/checkpoint` command support with all subcommands
- HTTP client methods for checkpoint management

### Testing
- 400 tests passing

---

## [1.12.3] - 2026-01-03

### Added - Time-Based Usage Analytics

#### Persistent Usage Storage
- **`~/.ppxai/usage/usage.json`** - Usage data now persists across sessions
- **Auto-save** - Usage saved after each chat (VSCode) or on exit (TUI)
- **Shared storage** - Both TUI and VSCode contribute to the same usage history
- **No duplicates** - Same session updates existing entry instead of appending

#### Time-Based Usage Commands
- **`/usage 24h`** - Usage for last 24 hours
- **`/usage week`** - Usage for last 7 days
- **`/usage month`** - Usage for last 30 days
- **`/usage year`** - Usage for last 365 days
- **`/usage all`** - All-time usage history

#### HTTP Endpoints
- **`GET /usage/report?period=week`** - Aggregated usage report by time period
- **`GET /usage/sessions?limit=20`** - List recorded sessions with usage data

### New Files
- `ppxai/usage.py` - Persistent usage storage module
- `tests/test_usage_persistence.py` - 14 new tests

### Testing
- 414 tests passing (14 new usage persistence tests)

---

## [1.12.2] - 2026-01-02

### Added - TUI Polish & Bug Fixes

#### Emoji Toggle
- **`/theme emoji on|off`** - Toggle emoji display in panel badges
- Switch between emoji badges and text-only badges for better alignment

### Fixed

#### Tool Call Parsing
- **Single-quote JSON** - Fixed parsing of tool calls using single quotes instead of double quotes

#### Logging & Initialization
- **Unified logging** - TUI and engine now share common logger module
- **Logger initialization** - Fixed missing `self.logger` in CommandHandler
- **Removed obsolete** `tui_logger.py` (replaced by `ppxai/common/logger.py`)

#### TUI Display
- **Checkpoint status** - Shows `↶` symbol instead of full git hash for cleaner display
- **Panel alignment** - Text symbols instead of emojis for consistent column alignment

### Testing
- All 377 tests passing

---

## [1.12.1] - 2026-01-02

### Added - Enhanced TUI Experience

#### Themed TUI Panels
- **4 Distinctive Themes** - Standard, Tron Legacy, Matrix, and Nord color schemes
- **Rounded Panel Corners** - User, assistant, and system messages have rounded borders
- **`/theme` Command** - List themes or switch with `/theme <name>`
- **Theme Autocomplete** - Tab completion for theme names

#### Framed Status Panel
- **Badge Display** - Provider, model, tools status as colored badges
- **Visual Hierarchy** - Clear separation between header and chat
- **Theme-Aware Styling** - Badges adapt to current theme colors

#### Clickable File Links
- **OSC 8 Hyperlinks** - Markdown links clickable in supported terminals
- **File URI Support** - Local paths convert to `file://` URIs
- **VSCode Integration** - Click file links to open in editor
- **`/show` Command** - File references in rendered markdown are clickable

### Fixed
- File link resolution for relative paths in markdown
- Link detection regex to match all markdown links (not just http/https)
- Working directory passed correctly for relative link resolution

### New Files
- `ppxai/themes.py` - Theme dataclass and 4 built-in themes
- `ppxai/ui_components.py` - Reusable Rich UI components

---

## [1.12.0] - 2025-12-29

### Added - Checkpoint System & Usage Tracking 🔒📊

This release introduces a checkpoint system for atomic multi-file rollback and real-time token usage tracking with cost estimation.

#### Checkpoint System
- **Git-based checkpoints** - Auto-commits changes before agent tasks for atomic rollback
- **`/undo` command** - Revert last agent task with single command (`git revert HEAD`)
- **File-based fallback** - Snapshots to `~/.ppxai/checkpoints/` when git unavailable
- **Auto-detection** - Automatically selects best backend (git → file → none)
- **Stale detection** - Checkpoints invalidated when new commits are made after them
- **VSCode Undo button** - One-click rollback with confirmation dialog

#### Token Usage & Cost Tracking
- **Real-time streaming usage** - Extract tokens from streaming responses
- **Cost estimation** - Automatic USD cost calculation based on per-model pricing
- **TUI status line** - Shows `1.2K↓/0.5K↑ $0.0045` in status bar
- **VSCode usage badge** - Live-updating badge with tooltip breakdown
- **All providers supported** - OpenAI, Perplexity, Gemini streaming

#### New Configuration Options
- `tools.agent.checkpoint_backend` - `"auto"` | `"git"` | `"file"` | `"none"`
- `tools.agent.checkpoint_message` - Custom commit message format
- `tools.agent.max_tool_iterations` - Max inner tool loop iterations

#### Bug Fixes
- Fixed `@tree` and `@git` context injection in VSCode (was treated as file search)
- Fixed usage badge not updating after responses
- Fixed table horizontal overflow in VSCode webview
- Fixed concurrent request causing 400 message alternation errors
- Session cleanup on interrupted requests

#### Documentation
- [CHECKPOINT_GUIDE.md](docs/CHECKPOINT_GUIDE.md) - Comprehensive checkpoint system guide
- [RELEASE-NOTES-v1.12.0.md](docs/RELEASE-NOTES-v1.12.0.md) - Full release notes

#### Testing
- 377+ tests passing (40 new checkpoint tests)

---

## [1.11.9] - 2025-12-27

### Fixed - Critical Agent Mode Safety 🔒

This release fixes a critical safety issue where `/agent on|off` commands were being interpreted as tasks instead of toggle commands.

#### Critical Fix
- **`/agent on|off` now correctly toggles agent mode** instead of being interpreted as tasks
  - Previously, typing `/agent off` would cause AI to search for things to turn "off" (including killing server processes!)
  - Now properly recognized as toggle commands in both TUI and VSCode extension

#### Security Improvements
- **Minimum word count validation** (default: 3 words) rejects vague single-word tasks
- **`kill`, `pkill`, `killall` added to built-in dangerous shell patterns**
- Built-in defaults ensure safety even without config file

#### New Features
- **Configurable agent settings** via `ppxai-config.json`:
  - `tools.agent.max_iterations` (default: 10) - Maximum agent loop iterations
  - `tools.agent.context_char_limit` (default: 2000) - Character limit for context display
  - `tools.agent.min_task_words` (default: 3) - Minimum words required for agent tasks
- **`/agent/config` API endpoint** for retrieving agent configuration
- **Full `/tools` command parity** between TUI and VSCode extension
  - Added `/tools agent`, `/tools set verbose on|off`, `/tools help <tool>` to extension

#### Documentation
- Updated [Agent Mode Guide](docs/AGENT_MODE_GUIDE.md) with configuration section

#### Testing
- 337 tests passing

---

## [1.11.8] - 2025-12-27

### Added - Agent Mode + Release Fixes 🤖

This release introduces Agent Mode for autonomous task execution in the VSCode extension.

#### Agent Mode
- **Agent Toggle Button** - New button in VSCode extension header to enable/disable agent mode
- **Agent Mode API** - New endpoints for agent control:
  - `GET /agent/status` - Check agent mode status
  - `POST /agent/enable` - Enable agent mode (auto-enables tools)
  - `POST /agent/disable` - Disable agent mode
- **EngineClient Support** - `agent_mode` property, `enable_agent_mode()`, `disable_agent_mode()` methods
- **Agent Mode Guide** - Comprehensive documentation at [docs/AGENT_MODE_GUIDE.md](docs/AGENT_MODE_GUIDE.md)

#### Release Process Fixes
- **GitHub "Latest" Release Tag** - Releases now correctly marked as latest
  - Added `make_latest: true` to GitHub Actions workflow
  - Release script now uses `--latest` flag when publishing notes
- **Documentation Links** - Fixed 12 broken internal links
  - `custom-tools-guide.md` → `CUSTOM_TOOL_DEVELOPMENT_GUIDE.md`
  - Archived docs now properly reference `docs/archive/` paths

### Fixed
- GitHub releases not being marked as "Latest" on repository page
- Broken documentation links pointing to moved/renamed files

## [1.11.6] - 2025-12-26

### Fixed - /tools Commands After Provider Switch 🔧

- **`/tools list` After Provider Switch** - Now correctly lists tools after `/provider gemini`
  - Root cause: `_list_tools()` checked `isinstance(self.client, PerplexityClientPromptTools)` which is False for non-Perplexity providers
  - Fix: Check `engine_client.tools_enabled` first, show engine tools for all providers

- **`/tools status` After Provider Switch** - Now correctly shows "Tools enabled" after switching providers
  - Same fix pattern applied

- **`/tools config` After Provider Switch** - Now works correctly after switching providers

### Testing
- 377 tests passing
- Manual TUI verification confirmed fix

---

## [1.11.5] - 2025-12-26

### Fixed - Ctrl-C and Tools Status Display 🔧

- **Ctrl-C Message Alternation Error** - Fixed 400 error after interrupting streaming with Ctrl-C
  - Root cause: Ctrl-C cleanup only removed user message from legacy `client.conversation_history`, not from `engine_client.session.messages`
  - Fix: Added `SessionManager.remove_last_message()` method and cleanup logic for both legacy and engine session

- **Tools Status Display** - `/tools enable` now correctly shows "ON" in status line
  - Root cause: `get_status_line()` checked legacy `client.enable_tools` instead of `engine_client.tools_enabled`
  - Fix: Check `handler.engine_client.tools_enabled` first, fallback to legacy client check

### Testing
- 377 tests passing (2 new session cleanup tests)

---

## [1.11.4] - 2025-12-24

### Added - @git and @tree Context Injection 📂

Automatic context injection for git changes and directory structure in AI messages.

#### New Features
- **@git injection**: Automatically includes `git diff` (staged + unstaged changes) when you type `@git` in messages
- **@tree injection**: Automatically includes directory tree structure when you type `@tree` in messages
- **Combined contexts**: Use `@file`, `@git`, and `@tree` together in the same message
- **Provider-agnostic**: Works with all providers (Perplexity, Gemini, OpenAI, custom)
- **TUI feedback**: Shows what was injected with size (e.g., "→ Injected context: @git (31 B)")

#### Architecture Changes
- **Unified TUI and VSCode**: Both now always use shared EngineClient (unified architecture)
- EngineClient now created at TUI startup (not just when tools enabled)
- Context injection works regardless of tools ON/OFF state

#### Testing
- 31 context injection tests passing (9 new @git/@tree tests)
- 70 command tests passing

---

## [1.11.7] - 2025-12-26

### Major - Legacy Code Removal + Clickable Citations 🎉🔗

This release completes the migration to EngineClient and adds clickable citations/links across all interfaces.

#### Legacy Code Removed
- **Deleted ~2,100 lines of legacy code**
  - `ppxai/client.py` (447 lines - AIClient)
  - `perplexity_tools_prompt_based.py` (1,342 lines - legacy tools client)
  - `tool_manager.py` (299 lines - legacy MCP loader)
- **EngineClient is now the only client interface**
- **337 tests passing** (migrated from legacy tests)

#### New Features
- **`/tools help <tool-name>`** - Detailed documentation for any tool
- **Autocomplete for `/tools`** - Tab completion for subcommands and tool names
- **Custom Tool Development Guide** - [docs/CUSTOM_TOOL_DEVELOPMENT_GUIDE.md](docs/CUSTOM_TOOL_DEVELOPMENT_GUIDE.md)

### Fixed - Clickable Citations 🔗

- **Perplexity Citations Clickable** - `inject_citation_urls()` converts `[1]` to `[1](url)` format
  - Perplexity API returns citations as separate metadata array
  - New function injects URLs into response text for clickable links
- **TUI Links Clickable** - OSC 8 hyperlinks via `convert_markdown_links_to_rich()`
  - Works in Ghostty, iTerm2, Kitty, Windows Terminal, GNOME Terminal 3.26+
  - Cross-platform support (macOS, Linux, Windows)
- **VSCode Tool Responses** - Added `fullResponse` message type for tool-using responses
- **`/tools list` After Provider Switch** - Now correctly lists tools after `/provider gemini`
- **Tool JSON Leak** - No longer leaks to VSCode during streaming

### Documentation
- Archived legacy documentation to `docs/archive/legacy-tools-docs/`
- Updated all guides for EngineClient architecture
- Autocomplete documentation across all relevant guides

## [1.11.3] - 2025-12-24

### Added - Foundation Refactoring + Critical Bugfixes ⚙️🔧

**Note:** This release consolidates v1.11.2.1 and v1.11.2.2 into v1.11.3 due to VSCode extension versioning constraints (only supports 3-part semantic versioning: major.minor.patch).

This release combines two critical patches: provider abstraction improvements and autorouter fixes, providing a solid foundation for adding new AI providers.

#### Autorouter Fix (from v1.11.2.1)

- **Fixed Provider Mismatch in Autorouter** - Coding commands now work with all providers
  - **Problem**: Using `/convert`, `/generate`, etc. with Gemini/OpenAI caused 404 errors
  - **Root Cause**: 7 coding command handlers didn't pass `self.provider` to `send_coding_task()`
  - **Fix**: All 7 handlers now pass current provider parameter
  - **Impact**: Autorouting now respects provider (Perplexity→sonar-pro, Gemini→gemini-2.5-pro, OpenAI→gpt-4o, etc.)

#### Provider Abstraction Improvements (from v1.11.2.2)

- **Configurable Default Provider** - No more hardcoded "perplexity"
  - New `get_default_provider()` function with smart fallback chain
  - `DEFAULT_PROVIDER` environment variable support (`.env`)
  - Fallback order: env var → first available provider → perplexity
  - Documented in `.env.example`

- **Provider-Specific Pricing** - Each provider can have its own pricing model
  - New `get_model_pricing(provider)` function for any provider
  - Backward compatible: Legacy `MODEL_PRICING` global still exists

- **AIClientWithTools Alias** - Better naming for provider-agnostic tool client
  - `AIClientWithTools` = `PerplexityClientPromptTools` (same class, clearer name)
  - Updated docstring: "works with ALL providers (not just Perplexity)"
  - Both names supported for backward compatibility

### Fixed - Critical TUI Bugs 🔧

**From branch `bugfix/gemini-tool-calling`**

- **Bug #1: Tools Status Not Persisting** - Tools now stay ON when switching providers
  - **Before**: Enable tools on Perplexity → switch to Gemini → Tools show OFF ❌
  - **After**: Tools remain ON across provider switches ✅
  - **Root Cause**: `handle_provider()` didn't check if tools were enabled before switching
  - **Fix**: Added tools persistence logic in `ppxai/commands.py` (lines 388-420)
  - **Testing**: Manual TUI testing confirms fix works

- **Bug #2: Gemini Tool Call Parsing Failure** - Fixed nested JSON parsing
  - **Before**: Gemini showed raw JSON instead of executing tools ❌
  - **After**: Gemini tool calls execute correctly ✅
  - **Root Cause**: Regex pattern `r'\{\s*"tool"\s*:\s*"[^"]+"\s*[^}]*\}'` broke on nested `arguments` object
  - **Fix**: Extract JSON using first/last brace positions instead of regex (`perplexity_tools_prompt_based.py` lines 1054-1083)
  - **Testing**: 4/4 new regression tests passing

### Documentation

- **docs/BUGFIX-gemini-tool-calling.md** - NEW: Comprehensive analysis of both bugs with root causes and fixes
- **docs/PROVIDER-TOOLS-COMPATIBILITY.md** - NEW: Guide explaining how tools work across different providers
- **docs/PROVIDER-ABSTRACTION-REFACTORING.md** - NEW: Detailed refactoring analysis and v1.12.0 recommendations
- **docs/RELEASE-NOTES-v1.11.2.2.md** - NEW: Complete release notes with migration guide

### Testing

- **4 new regression tests** in `tests/test_provider_tools_bugfixes.py`
  - `test_provider_switching_fix_documented()` - Documents Bug #1 fix
  - `test_parse_gemini_nested_json_tool_call()` - Tests Gemini nested JSON parsing
  - `test_parse_tool_call_in_code_block()` - Tests code block tool calls
  - `test_parse_tool_call_simple_no_nested_args()` - Tests simple tool calls
- All 4 tests passing (100%)
- Manual TUI testing confirms both bugs fixed

### Changed

- `ppxai/config.py` - Added `get_default_provider()` and `get_model_pricing(provider)` functions
- `ppxai/commands.py` - Use configurable default provider, tools persistence fix
- `perplexity_tools_prompt_based.py` - Gemini JSON parsing fix, added AIClientWithTools alias
- `.env.example` - Document `DEFAULT_PROVIDER` option

### Impact

- ✅ **Adding new providers now requires ZERO code changes** (config-only)
- ✅ Tools work correctly with all providers (Perplexity, Gemini, OpenAI, OpenRouter, Ollama)
- ✅ Solid foundation for v1.12.0+ features (deprecation warnings, code cleanup)

### Migration Guide

**For Users**: No breaking changes! Everything works as before.
- Optional: Set custom default provider via `DEFAULT_PROVIDER=gemini` in `.env`

**For Developers**: Recommended but not required:
- Use `get_default_provider()` instead of hardcoded "perplexity"
- Use `get_model_pricing(provider)` instead of global `MODEL_PRICING`
- Use `AIClientWithTools` alias for new code (clearer name)

### VSCode Extension Versioning Note

⚠️ **Important**: VSCode extensions only support 3-part semantic versioning (`major.minor.patch`). This is why v1.11.2.1 and v1.11.2.2 were consolidated into v1.11.3. Future releases will use 3-part versions only (e.g., 1.11.3 → 1.11.4 → 1.12.0).

## [1.11.2] - 2025-12-22

### Added - Shell Command Consent Security + Shared Modules Refactoring 🔒

This release introduces two major improvements: a comprehensive shell command consent system for secure AI command execution, and complete shared modules architecture refactoring.

#### Shell Command Consent System

- **Regex-Based Command Classification** - Three-tier security model:
  - **Safe Commands** - Auto-approved read-only operations (ls, cat, grep, pwd, which, whoami, date, uname)
  - **Dangerous Commands** - Require user consent (rm, mv, chmod, sudo, curl | bash, kill, pkill)
  - **Never-Allow Commands** - Always blocked (rm -rf /, dd of=/dev/, fork bombs, mkfs)

- **Session-Scoped Consent** - Flexible approval options:
  - **y (yes, once)** - Approve this command execution
  - **n (no, once)** - Deny this command execution
  - **always** - Auto-approve all matching commands (this session)
  - **never** - Block all matching commands (this session)
  - Consent decisions persist for entire session
  - No persistence to disk (security feature)

- **TUI Consent Interface** - Terminal prompt with command details:
  - Shows command, working directory, risk level
  - Keyboard-friendly y/n/always/never input
  - Clear classification feedback

- **VSCode QuickPick Consent** - Native VSCode consent UI:
  - Keyboard navigation (no mouse required)
  - Four clear options: "Yes, Once", "Yes, Always", "No, Once", "No, Never"
  - Command context and risk level display
  - Dismissible (ESC to cancel)

- **Configuration System** - Customizable patterns in ppxai-config.json:
  - `tools.shell.allowed_commands` - Safe command patterns
  - `tools.shell.dangerous_commands` - Require consent patterns
  - `tools.shell.never_allow` - Forbidden command patterns
  - Uses Python regex with negative lookaheads for security

- **Critical Security Fix** - Commands with redirections now require consent:
  - `cat > file.txt` classified as dangerous (not safe)
  - `echo data > file.txt` classified as dangerous (not safe)
  - Uses `(?!.*[><])` negative lookahead in patterns

#### Shared Modules Architecture Refactoring

- **ppxai/common/ Directory** - Centralized shared code (55KB total):
  - `consent.py` (21KB) - Unified consent system for file editing and shell commands
  - `logger.py` (8KB) - Shared logging system replacing TUI-specific logger
  - `event_handler.py` (9KB) - Common event processing for both TUI and VSCode
  - `commands.py` (14KB) - Shared command handlers

- **TUI Adapter** - TUI now uses shared modules:
  - Migrated from `tui_logger.py` to `ppxai.common.logger`
  - Uses shared consent manager
  - Event handler integration
  - Eliminates duplicate code

- **HTTP Server Adapter** - VSCode backend uses shared modules:
  - Shared logger for consistent logging
  - Shared consent manager
  - Event processing via shared handler
  - Unified architecture with TUI

- **Backward Compatibility** - No breaking changes:
  - Existing ppxai-config.json files work unchanged
  - API remains compatible
  - All existing tests pass

#### Files Changed

**Shell Consent:**
- `ppxai/engine/client.py` - Added request_shell_consent() and command classification
- `ppxai/engine/session.py` - Shell consent state tracking (shell_consent_mode, allowed_shell_patterns, denied_shell_patterns)
- `ppxai/engine/tools/builtin/shell.py` - Integrated consent system into execute_shell_command
- `ppxai/server/http.py` - Added POST /shell-consent endpoint for VSCode
- `ppxai/commands.py` - TUI shell consent handler
- `vscode-extension/src/chatPanel.ts` - QuickPick consent UI implementation
- `ppxai-config.json` - Added tools.shell configuration section
- `docs/SHELL_CONSENT_GUIDE.md` - NEW: Comprehensive 642-line security guide
- `docs/RELEASE-NOTES-v1.11.2.md` - NEW: Detailed release notes

**Shared Modules:**
- `ppxai/common/__init__.py` - NEW: Public exports for shared modules
- `ppxai/common/consent.py` - NEW: Unified consent system
- `ppxai/common/logger.py` - NEW: Shared logging (replaces tui_logger.py)
- `ppxai/common/event_handler.py` - NEW: Common event processing
- `ppxai/common/commands.py` - NEW: Shared command handlers
- `ppxai/main.py` - Integrated shared modules into TUI
- `ppxai/server/http.py` - Integrated shared logger into HTTP server
- `tests/test_consent.py` - Updated for file_mode/shell_mode keys
- `tests/test_common_*.py` - NEW: Comprehensive tests for shared modules

#### Testing
- **308/308 tests passing (100%)** - All tests green
- Shell consent integration tests with edge cases
- Shared modules comprehensive test coverage
- Pattern matching validation (safe/dangerous/never)
- TUI and VSCode consent flow end-to-end tested

#### Documentation
- [docs/SHELL_CONSENT_GUIDE.md](docs/SHELL_CONSENT_GUIDE.md) - Complete security guide
- [docs/RELEASE-NOTES-v1.11.2.md](docs/RELEASE-NOTES-v1.11.2.md) - Full release notes
- Updated README.md with shell consent features
- Updated CLAUDE.md with v1.11.2 summary

### Changed
- Version bumped to 1.11.2 in all package files (pyproject.toml, vscode-extension/package.json)
- TUI and HTTP server now share common modules (no duplicate code)
- Architecture unified between all clients (TUI, VSCode, future web UI)

## [1.11.1] - 2025-12-22

### Fixed - Critical TUI Regression ⚠️

This release fixes a critical regression in v1.11.0 where the TUI failed to display AI responses when tools were enabled.

#### Root Cause
- v1.11.0 switched TUI to use `EngineClient.chat_sync()` to enable file editing tools
- However, `chat_sync()` returns a plain string without rendering (pure function)
- Legacy `AIClient.chat()` had built-in console printing (side effect)
- Result: Response was set but never displayed to user

#### Solution
- **Unified Architecture:** Refactored TUI to use async event stream (like VSCode extension)
- **Event Handling:** TUI now properly handles all event types:
  - `STREAM_CHUNK` - Streaming response chunks
  - `TOOL_CALL` - Tool execution notifications
  - `TOOL_RESULT` - Tool results
  - `CONSENT_REQUEST` - File edit consent prompts
  - `ERROR` - Error messages
- **Real-time UX:** TUI now shows streaming chunks, tool calls, and consent prompts in real-time
- **Code Quality:** Eliminates architectural divergence between TUI and VSCode extension

#### Performance
- **No regression:** EngineClient is actually **16.5% faster** than legacy (2446ms vs 2929ms total time)
- TTFT: 1453ms, Total: 2446ms, Throughput: 64.0 tok/s
- Benchmarked against v1.10.5 baseline

#### Files Changed
- `ppxai/main.py` - Added event-based streaming loop (lines 268-325)
- `pyproject.toml` - Version 1.11.0 → 1.11.1
- `vscode-extension/package.json` - Version 1.11.0 → 1.11.1
- `README.md` - Updated version references and installation instructions
- `vscode-extension/README.md` - Updated version references
- `docs/README.md` - Updated version references
- `CLAUDE.md` - Documented v1.11.1 changes

#### Additional Fixes
- **Conversation History Sync:** Fixed 400 error when using tools with conversation history
  - Engine client and legacy client now properly sync conversation history
  - Fixes message alternation errors ("user or tool message(s) should alternate with assistant message(s)")
  - Syncs history when enabling tools and after each response
- **Inline Markdown in Tables:** File names and inline code now render properly in markdown tables
  - Added `parse_inline_markdown()` to handle backticks, bold, italic in table cells
  - Inline code (`` `text` ``) renders with cyan monospace on grey background (GitHub-like)
  - Bold (`**text**`) and italic (`*text*`) also supported
  - Files: `ppxai/markdown_tables.py` (lines 16-64, 135)

#### New Features
- **Verbose Tool Logging:** Added `/tools set verbose` command to inspect tool inputs/outputs
  - `/tools set verbose on` - Show tool arguments and results during execution
  - `/tools set verbose off` - Hide detailed tool information (default)
  - Useful for debugging and understanding AI tool calls
  - Files: `ppxai/commands.py` (lines 134, 495, 665-698), `ppxai/main.py` (lines 295-302)

#### Testing
- **296/301 tests passing** (same as v1.11.0)
- 5 failures are pre-existing custom endpoint config issues (unrelated)
- Syntax validated, imports verified
- Manually tested: verbose mode, conversation history sync, inline code rendering

### Changed
- Version bumped to 1.11.1 in all package files
- Updated all installation instructions to reference v1.11.1
- Updated documentation to reflect unified event-based architecture
- Enhanced markdown table rendering with inline formatting support

## [1.11.0] - 2025-12-21

### Added - File Editing Tools with User Consent 🎯

This release introduces **autonomous file editing** capabilities with a comprehensive consent system, transforming ppxai into the first phase of an agentic developer assistant.

#### Core Features
- **4 File Editing Tools** - AI can now modify files with user permission:
  - `apply_patch` - Apply unified diff patches (git-style)
  - `replace_block` - Search and replace exact text blocks
  - `insert_text` - Insert text at specific line numbers
  - `delete_lines` - Delete line ranges from files

- **Per-File Session Consent System** - Safety-first approach:
  - **y (yes)** - Allow editing this file (this session)
  - **n (no)** - Deny this edit
  - **always** - Auto-approve all files (this session)
  - **never** - Block all edits (this session)
  - Consent persists only for current session
  - Separate consent tracking per file path

- **TUI Consent Prompts** - Interactive validation using prompt_toolkit:
  - Clear file path display
  - Validated input (only y/n/always/never accepted)
  - Persistent consent state tracking

- **VSCode Consent Dialogs** - Event-driven SSE integration:
  - Modal dialogs with 4 consent options
  - Server-Sent Events for real-time communication
  - Non-blocking async consent flow

- **Atomic File Operations** - Robust and safe:
  - Write-to-temp + rename pattern
  - Automatic rollback on failure
  - File existence validation
  - Permission checks before edit

- **In-App Help System** - `/tools help editing` command:
  - Comprehensive markdown guide
  - Practical examples with chat flows
  - Consent system explanation
  - Troubleshooting tips
  - Available in both TUI and VSCode extension

#### Documentation
- **NEW:** [docs/FILE_EDITING_GUIDE.md](docs/FILE_EDITING_GUIDE.md) - 400+ lines comprehensive user guide
- **NEW:** [vscode-extension/TESTING.md](vscode-extension/TESTING.md) - Testing documentation for VSCode extension
- **Updated:** README.md with File Editing Tools section
- **Updated:** CLAUDE.md with v1.11.0 feature summary and version alignment

#### Testing
- **NEW:** 36 comprehensive tests for file editing features:
  - 25 tests for file editing tools ([tests/test_file_editing_tools.py](tests/test_file_editing_tools.py))
  - 11 tests for help commands and UI ([tests/test_ui.py](tests/test_ui.py), [tests/test_commands.py](tests/test_commands.py))
- **Total:** 273/278 tests passing (98.2%)
- 5 pre-existing custom endpoint integration test failures (unrelated)

#### Technical Implementation
- `ppxai/engine/tools/builtin/editor.py` - NEW, implements all 4 file editing tools
- `ppxai/engine/client.py` - Added `request_file_edit_consent()` async method
- `ppxai/engine/session.py` - Added consent state (`allowed_files`, `edit_consent_mode`)
- `ppxai/commands.py` - TUI consent handler with prompt_toolkit validation + `/tools help editing`
- `ppxai/ui.py` - Added `display_file_editing_help()` function and updated welcome message
- `vscode-extension/src/chatPanel.ts` - Added `getFileEditingHelp()` + help command handler

### Changed
- Version bumped to 1.11.0 in `pyproject.toml` and `vscode-extension/package.json`
- Updated ROADMAP.md to reflect Phase 1 completion
- Updated all version references throughout documentation

### Fixed
- VSCode extension `/tools help editing` command now displays formatted help content

---

## [1.10.8] - 2025-12-21

### Added
- Unified `/save` and `/export` commands across TUI and VSCode extension
- New `/export [filename]` command exports last answer to markdown (`~/.ppxai/exports/`)
- Clear separation between session persistence (JSON) and answer export (markdown)

### Changed
- `/save` now saves session to JSON (`~/.ppxai/sessions/`) for persistence
- VSCode extension "Save Answer" button now saves to exports folder with auto-generated filenames

### Improved
- VSCode extension interrupt UX - orange pulsing "⏹ Streaming..." badge in header
- Streaming interrupt no longer shows red error message on user-initiated stop

---

## [1.10.7] - 2025-12-20

### Fixed
- Perplexity API compatibility - removed deprecated `sonar-reasoning` model
- Model documentation updated to reflect current Perplexity API

### Changed
- Supported Perplexity models: sonar, sonar-pro, sonar-reasoning-pro, sonar-deep-research

---

## [1.10.6] - 2025-12-20

### Added
- Gemini 3 Flash Preview - Speed-optimized with frontier intelligence and 1M context
- Gemini 3 Pro Preview - Most powerful agentic model with code execution and search grounding
- Enhanced model descriptions with detailed capabilities
- Preview pricing estimates for Gemini 3 models

---

## [1.10.5] - 2025-12-20

### Added
- Status bar showing provider, model, and tools status
- VSCode extension interrupt support via Esc key and Command Palette
- TUI Ctrl-C double-press pattern (2s timeout) - first press warns, second exits
- 7 new interrupt handling tests

### Fixed
- Ctrl-C during streaming no longer causes message alternation errors
- Conversation history cleanup on interrupt maintains LLM message alternation
- Gemini tools None content handling
- FastAPI deprecation warnings (migrated to lifespan pattern)

### Testing
- 235/241 tests passing

---

## [1.10.4] - 2025-12-19

### Fixed
- Markdown tables now render properly in TUI (no more raw `|:---|:---|` syntax)
- Tables support left/center/right alignment (`:---`, `:---:`, `---:`)
- `/show` command renders markdown files with formatted tables
- All AI responses render tables correctly

### Added
- 27 new regression tests for table rendering

---

## [1.10.3] - 2025-12-18

### Added
- Standalone `ppxai-server` executables for all platforms (no Python required)
- Automated GitHub Actions CI/CD for multi-platform builds:
  - macOS ARM64 & Intel
  - Linux AMD64
  - Windows

---

## Earlier Versions

See [ROADMAP.md](ROADMAP.md) for historical release information.

---

## Versioning

ppxai follows [Semantic Versioning](https://semver.org/):
- **MAJOR** version for incompatible API changes
- **MINOR** version for new functionality in a backwards compatible manner
- **PATCH** version for backwards compatible bug fixes

## Release Process

1. Update version in `pyproject.toml` and `vscode-extension/package.json`
2. Update CHANGELOG.md with release notes
3. Update ROADMAP.md to move release from "Next" to "Current"
4. Create git tag: `git tag -a v1.x.x -m "Release v1.x.x"`
5. Push tag: `git push origin v1.x.x`
6. GitHub Actions automatically builds and creates release

[1.12.2]: https://github.com/rcconsult/ppxai/releases/tag/v1.12.2
[1.12.1]: https://github.com/rcconsult/ppxai/releases/tag/v1.12.1
[1.12.0]: https://github.com/rcconsult/ppxai/releases/tag/v1.12.0
[1.11.9]: https://github.com/rcconsult/ppxai/releases/tag/v1.11.9
[1.11.8]: https://github.com/rcconsult/ppxai/releases/tag/v1.11.8
[1.11.7]: https://github.com/rcconsult/ppxai/releases/tag/v1.11.7
[1.11.6]: https://github.com/rcconsult/ppxai/releases/tag/v1.11.6
[1.11.5]: https://github.com/rcconsult/ppxai/releases/tag/v1.11.5
[1.11.4]: https://github.com/rcconsult/ppxai/releases/tag/v1.11.4
[1.11.3]: https://github.com/rcconsult/ppxai/releases/tag/v1.11.3
[1.11.2]: https://github.com/rcconsult/ppxai/releases/tag/v1.11.2
[1.11.1]: https://github.com/rcconsult/ppxai/releases/tag/v1.11.1
[1.11.0]: https://github.com/rcconsult/ppxai/releases/tag/v1.11.0
[1.10.8]: https://github.com/rcconsult/ppxai/releases/tag/v1.10.8
[1.10.7]: https://github.com/rcconsult/ppxai/releases/tag/v1.10.7
[1.10.6]: https://github.com/rcconsult/ppxai/releases/tag/v1.10.6
[1.10.5]: https://github.com/rcconsult/ppxai/releases/tag/v1.10.5
[1.10.4]: https://github.com/rcconsult/ppxai/releases/tag/v1.10.4
[1.10.3]: https://github.com/rcconsult/ppxai/releases/tag/v1.10.3
