# ppxai Development Roadmap

> **Current Version**: v1.13.8 (January 2026)
> **Focus**: Multi-LLM interface for developers—terminal + VSCode, zero vendor lock-in

---

## Core Value Proposition

ppxai provides:
1. **Multi-Provider Support** - Switch between Perplexity, Gemini, OpenAI, OpenRouter, Ollama anytime
2. **Dual Interface** - Same experience in TUI and VSCode extension
3. **Agent Mode** - Iterative tool execution with consent-based safety
4. **Open Source** - Inspect, modify, self-host, no telemetry

---

## Completed (v1.11.x)

### Agentic Workflow ✅
- File editing tools with consent (`apply_patch`, `replace_block`, `insert_text`, `delete_lines`)
- Context injection (`@file`, `@git`, `@tree`)
- `/agent` command for autonomous multi-step execution
- Safety: dangerous command patterns, minimum word validation
- Configurable via `ppxai-config.json`

### Multi-Provider ✅
- Perplexity AI (with citations)
- Google Gemini (2.0 Flash, 2.5 Flash, 2.5 Pro)
- OpenAI (GPT-4o, o1)
- OpenRouter (Claude, 100+ models)
- Local models (Ollama, vLLM)

### Developer Experience ✅
- TUI with Rich markdown, tables, OSC 8 hyperlinks
- VSCode extension with webview chat, context menu commands
- Coding commands (`/generate`, `/test`, `/docs`, `/explain`, `/debug`, `/convert`)
- Session management, token tracking, cost estimation

---

## Completed (v1.12.x)

### Safety & Reproducibility ✅ (v1.12.0)
- Git-based checkpoints: Auto-commit before `/agent` tasks
- `/undo` command: Revert last agent task atomically
- Stale checkpoint detection
- File-based fallback for non-git directories

### TUI Themes ✅ (v1.12.1)
- 4 themes: Standard, Tron Legacy, Matrix, Nord
- Framed status panel with colored badges
- Clickable file links via OSC 8 hyperlinks
- `/theme` command with autocomplete

### Tool Call Parsing ✅ (v1.12.2)
- Fixed single-quote JSON parsing in tool calls
- Improved error handling for malformed tool responses

### Usage Analytics ✅ (v1.12.3)
- Persistent usage storage in `~/.ppxai/usage/usage.json`
- Time-based usage reports: `/usage 24h|week|month|year|all`
- HTTP endpoints: `/usage/report`, `/usage/sessions`
- Auto-save after each chat (VSCode), on quit (TUI)

### Checkpoint Management ✅ (v1.12.4)
- `/checkpoint` command with 6 subcommands
- Status, list, backend switching, clear, info, undo alias
- Tab autocomplete for subcommands and backends
- VSCode extension full support
- HTTP endpoints for remote control

### Native Gemini Provider ✅ (v1.12.5)
- Native `google-genai` SDK integration
- Google Search Grounding with citations (like Perplexity)
- Streaming support with usage tracking
- Graceful fallback to OpenAI-compatible API
- Install: `pip install ppxai[gemini]`

---

## Completed (v1.13.x)

### Premium Web Search ✅ (v1.13.0)
- Premium web search tool for custom providers (vLLM, Ollama)
- Priority fallback: Perplexity Sonar → Gemini Grounding → DuckDuckGo (free)
- SSL_VERIFY environment variable for corporate proxy support
- Custom provider tool calling tests
- Install: `pip install ppxai[gemini]` for Gemini Grounding support

### Desktop Web App ✅ (v1.13.1)
- Standalone `ppxai-desktop` launcher for all platforms
- macOS `.app` bundle with DMG installer
- Full-featured browser-based chat interface
- Feature parity: commands, tools, agent mode, themes
- Working directory context with folder badge

### Bugfix Release ✅ (v1.13.2)
- Fixed markdown rendering (bullet lists, `/usage` tables)
- Updated marked.js to v11.1.1 in Web App
- Desktop Web App: auto-detect server URL, proper favicon
- Shared modules for command/formatter parity
- Windows compatibility fixes (tests, PEP 735 config)

### Gemini Tools + Grounding ✅ (v1.13.3)
- **Gemini system instruction fix** - System messages now passed via `system_instruction` config
- **Tools + grounding together** - Both work simultaneously (not mutually exclusive)
- **Native web search guidance** - Tool prompt tells providers with native search to use it
- **Provider options** - New `options` section in JSON config for provider-specific settings
- **Detailed error tracebacks** - Full stack traces for Gemini API errors
- **UTF-8 BOM handling** - Windows config file compatibility
- **Windows PowerShell installer** - `scripts/install.ps1` for one-line Windows install

### Error Handling & LLM Guidance ✅ (v1.13.4)
- **SSL certificate support** - `SSL_CERT_FILE` environment variable for corporate proxies
- **Windows shell guidance** - Explicit warnings that bash heredocs don't work on Windows
- **Tool parameter emphasis** - Better error messages for missing arguments
- **Actionable error tips** - Suggestions for appropriate tools on file-not-found errors

### Session Isolation ✅ (v1.13.5)
- **Multi-client isolation** - VSCode and Web App get isolated sessions on same server
- **Session ID header** - `X-Session-Id` HTTP header routes requests to per-session EngineClient
- **Per-session state** - Conversation history, working directory, provider/model, consent state
- **Session lifecycle** - Auto-expire after 1 hour, usage saved on cleanup
- **Monitoring endpoint** - `GET /sessions/list` for debugging active sessions

### Release Script Fixes ✅ (v1.13.6)
- **Windows `gh` CLI compatibility** - Release script works on Windows PowerShell
- **UTF-8 encoding** - Release scripts use proper encoding on all platforms

### Config & Status Fixes ✅ (v1.13.7)
- **`/config reload` command** - Hot-reload `ppxai-config.json` without restart
- **`/status` command fixes** - Fixed session methods and working directory display
- **Gemini grounding pricing** - Corrected pricing in example config ($35/1K requests)

### Data Visualization & Container Tools ✅ (v1.13.8)
- **CSV/TSV table viewer** - Rich tables in TUI, interactive DataTableViewer in Web App
- **JSON/YAML/TOML/HCL tree viewer** - Collapsible trees with syntax highlighting
- **Rendered/Source toggle** - Switch between formatted view and raw source (TUI + Web)
- **Container management tools** - 16 tools for Docker, Podman, Kubernetes CLI
- **Format auto-detection** - Extension-based and content sniffing for data files
- **Visualization config** - `max_rows`, `page_size`, `tree_depth`, `csv_delimiter` options
- **Optional dependencies** - `pip install ppxai[data]` for YAML/HCL parsing

---

## Infrastructure

### CI/CD ✅
- GitHub Actions workflow for releases (`.github/workflows/release.yml`)
- Automated builds for Linux, Windows, macOS (ARM + Intel)
- VSCode extension VSIX packaging
- PyPI publishing via CI

---

## v1.14.x Series - Session Bootstrap & Context

**Theme**: Reproducible starting point for every session

**User value**: Teams share project context. Consistent AI behavior across sessions.

**Prerequisite (v1.13.6):** System prompts are already supported via `ppxai-config.json`:
- Global: `system_prompt` at root level
- Per-provider: `providers.<name>.system_prompt`
- Modes: `system_prompt_mode` = "prepend" | "append" | "replace"
- Location: `ppxai/config.py:get_system_prompt()`, `ppxai/engine/client.py:1171-1186`

### v1.14.0 - AGENTS.md Support

| Feature | Description | Status |
|---------|-------------|--------|
| **AGENTS.md loading** | Load project instructions from AGENTS.md on startup | Planned |
| **CLAUDE.md fallback** | Support CLAUDE.md as alternative filename | Planned |
| **Bootstrap context injection** | Inject project context into system prompt (respects existing mode) | Planned |
| **TUI + VSCode support** | Both interfaces load context via EngineClient | Planned |

**Architecture:**
1. **Discovery** - `ContextInjector.find_bootstrap_files()` locates AGENTS.md/CLAUDE.md
2. **Caching** - `EngineClient._bootstrap_context` loads once, caches until reload
3. **Injection** - Modify existing system prompt assembly at `client.py:1171-1186`:
   - Bootstrap context is prepended to existing `system_prompt` (before mode is applied)
   - Order: `[bootstrap_context] + [config system_prompt] + [tool_prompt]` (for prepend mode)
4. **Status API** - `EngineClient.get_bootstrap_status()` returns loaded sources

**No conflicts:** Bootstrap context extends the existing system prompt pipeline, doesn't replace it.

### v1.14.1 - File Precedence & Merge

| Feature | Description | Status |
|---------|-------------|--------|
| **Global context** | Load from `~/.ppxai/AGENTS.md` | Planned |
| **Project context** | Load from project root AGENTS.md | Planned |
| **Subdirectory context** | Load from current working directory | Planned |
| **Merge strategy** | Global → Project → Subdir (concatenate) | Planned |

### v1.14.2 - `/context` Commands

| Feature | Description | Status |
|---------|-------------|--------|
| **`/context show`** | Display loaded context sources | Planned |
| **`/context reload`** | Refresh context from disk | Planned |
| **`/context edit`** | Open context file in editor | Planned |
| **`/context clear`** | Temporarily disable context | Planned |

### v1.14.3 - Enhanced Context Providers

| Feature | Description | Status |
|---------|-------------|--------|
| **`@url` provider** | Fetch and inject web content | Planned |
| **`@clipboard`** | Inject clipboard contents | Planned |
| **Conditional sections** | `<!-- if provider:gemini -->` blocks | Planned |
| **Include directive** | `<!-- include: ./docs/style.md -->` | Planned |

---

## Future Considerations

These are tracked but not prioritized:

- **Textual TUI migration** - Only if current TUI becomes limiting
- **libghostty SDK** - Watch for stable C API (expected 2026)
- **Per-provider tool config** - Enable/disable tools per provider
- **Custom tools** - User-defined tools in `~/.ppxai/tools/`
- ~~**Provider-aware tool guidance**~~ - ✅ Implemented in v1.13.3
- ~~**Cost display in `/usage`**~~ - ✅ Implemented (shows $ cost in session and reports)
- ~~**Per-provider cost rates**~~ - ✅ Implemented in `config.py` (pricing per model)
- ~~**Standardized error handling**~~ - ✅ All providers now have detailed traceback logging
- **`/rewind` browser** - Interactive checkpoint history viewer
- **`/agent --dry-run`** - Preview changes without applying

### Data Visualization Library Upgrade (Web App)

Current: Vanilla JavaScript (`DataTableViewer`, `DataTreeViewer`) - lightweight, no dependencies.

**Alternative libraries to consider if advanced features needed:**

| Library | Size | Use Case |
|---------|------|----------|
| **Tabulator** | ~100KB | Virtual scrolling, column resize, export (10K+ rows) |
| **AG Grid** (Free) | ~500KB | Professional tables, filtering, grouping |
| **json-viewer** | ~10KB | Focused JSON tree visualization |
| **JSONEditor** | ~200KB | Tree + code view with editing |

**Criteria for upgrade:**
- User requests column resizing or virtual scrolling for large files
- Performance issues with current implementation (>5000 rows)
- Need for data export (CSV, Excel) from preview

**Current vanilla JS is sufficient for v1.13.x preview use case.**

### Jupyter Kernel Tool (Data Science Workflow)

Enable AI to execute cells in a running JupyterLab kernel with real-time output streaming:

| Package | Purpose |
|---------|---------|
| `jupyter_client` | Connect to running kernels via connection file |
| `nbclient` | Higher-level cell execution with callbacks |
| `websockets` | Real-time output streaming via Jupyter wire protocol |
| `nbformat` | Read/write .ipynb files |

**Use case:** Data developer asks AI to "run this notebook cell by cell" and watches output appear in JupyterLab UI in real-time.

### Image Preview in Chat Panel

Current `/show` command opens files in VSCode text editor. Need image preview for:
- **Formats:** PNG, JPG, JPEG, GIF, SVG, WebP
- **Display:** Inline in chat panel or split pane preview
- **Use case:** AI generates chart (e.g., matplotlib), user wants to see it without leaving chat

---

## Known Issues

| Issue | Description | Status |
|-------|-------------|--------|
| **`@filename` injection broken** | Web app file injection via `@filename` stopped working after agent context fix. `@git` and `@tree` work correctly. | Deferred to v1.13.9 |

---

## Non-Goals

ppxai is **not** trying to be:
- An autonomous coding agent (it's an interface, not an AI)
- A replacement for Claude Code or Cursor (use those for full autonomy)
- A one-size-fits-all solution (flexibility over magic)

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

```bash
uv run pytest tests/ -v       # Run tests (583 passing)
uv run ppxai-server           # Start server for VSCode dev
```

---

## Historical Notes

For detailed release history, see [CHANGELOG.md](CHANGELOG.md).

For archived planning documents:
- [docs/v1.11.0-agentic-workflow-plan.md](docs/v1.11.0-agentic-workflow-plan.md) - Agentic workflow design
- Legacy archive available at tag [v1.13.3](https://github.com/rcconsult/ppxai/tree/v1.13.3/docs/archive)

---

**Last Updated**: January 11, 2026
