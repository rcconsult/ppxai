# ppxai Development Roadmap

> **Current Version**: v1.13.3 (January 2026)
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
- Google Gemini (2.0 Flash, 2.5 Pro)
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
- Custom provider tool calling tests (8 new tests)
- Documentation updates: test counts, Gemini capabilities, deprecated models
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

---

## Infrastructure

### CI/CD ✅
- GitHub Actions workflow for releases (`.github/workflows/release.yml`)
- Automated builds for Linux, Windows, macOS (ARM + Intel)
- VSCode extension VSIX packaging
- PyPI publishing via CI

**Note:** CI/CD exists but wasn't visible to external code reviewers due to tree depth limits.

---

## v1.14.x Series - Session Bootstrap

**Theme**: Reproducible starting point for every session

**User value**: Teams share project context. Consistent AI behavior across sessions.

### Architecture (Researched)

The implementation follows a separation of concerns pattern:

1. **Discovery** - `ContextInjector.find_bootstrap_files()` in `ppxai/engine/context.py`
   - Locates AGENTS.md or CLAUDE.md in the directory hierarchy
   - AGENTS.md takes priority over CLAUDE.md when both exist

2. **Caching** - `EngineClient._bootstrap_context` in `ppxai/engine/client.py`
   - Loads once on startup, caches until explicit reload
   - Tracks sources via `_bootstrap_sources: List[str]`

3. **Injection** - `EngineClient._build_system_messages()`
   - Prepends bootstrap context to system prompt
   - Integrates with existing tool prompt logic

4. **Status API** - `EngineClient.get_bootstrap_status()`
   - Returns `{loaded: bool, sources: List[str], char_count: int}`
   - Used by `/context show` (TUI) and `GET /context` (HTTP)

### v1.14.0 - AGENTS.md Support

| Feature | Description | Status |
|---------|-------------|--------|
| **AGENTS.md loading** | Load project instructions from AGENTS.md on startup | Planned |
| **CLAUDE.md fallback** | Support CLAUDE.md as alternative filename | Planned |
| **System prompt injection** | Append project context to system prompt | Planned |
| **TUI + VSCode support** | Both interfaces load context via EngineClient | Planned |

**Files to modify:**
- `ppxai/engine/context.py` - Add `find_bootstrap_files()` method
- `ppxai/engine/client.py` - Add bootstrap context loading and injection
- `tests/test_bootstrap_context.py` - New test file

**Test cases:**
```python
test_finds_agents_md_in_working_dir()
test_finds_claude_md_as_fallback()
test_agents_md_takes_priority_over_claude_md()
test_context_injected_into_system_prompt()
test_context_cached_between_chat_calls()
```

### v1.14.1 - File Precedence

| Feature | Description | Status |
|---------|-------------|--------|
| **Global context** | Load from `~/.ppxai/AGENTS.md` | Planned |
| **Project context** | Load from project root AGENTS.md | Planned |
| **Subdirectory context** | Load from current working directory | Planned |
| **Merge strategy** | Global → Project → Subdir (concatenate) | Planned |

**Precedence order:**
1. `~/.ppxai/AGENTS.md` (global defaults)
2. `{project_root}/AGENTS.md` (project-specific)
3. `{cwd}/AGENTS.md` (subdirectory overrides)

**Merge behavior:** Concatenate all found files with `\n\n---\n\n` separator.

### v1.14.2 - `/context` Commands

| Feature | Description | Status |
|---------|-------------|--------|
| **`/context show`** | Display loaded context sources | Planned |
| **`/context reload`** | Refresh context from disk | Planned |
| **`/context edit`** | Open context file in editor | Planned |
| **`/context clear`** | Temporarily disable context | Planned |
| **Tab autocomplete** | Autocomplete for subcommands | Planned |

**Note:** Using `/context` instead of `/agents` - clearer naming, avoids confusion with agent mode.

**Files to modify:**
- `ppxai/commands.py` - Add `/context` command handler
- `ppxai/common/commands.py` - Add to COMMANDS list for autocomplete
- `ppxai/server/http.py` - Add `GET /context`, `POST /context/reload`
- `vscode-extension/src/httpClient.ts` - Add context API calls

### v1.14.3 - Context Enhancements

| Feature | Description | Status |
|---------|-------------|--------|
| **Context size display** | Show token count in status bar | Planned |
| **Conditional sections** | `<!-- if provider:gemini -->` blocks | Planned |
| **Include directive** | `<!-- include: ./docs/style.md -->` | Planned |
| **HTTP endpoint** | `GET /context` for VSCode | Planned |

**Conditional syntax example:**
```markdown
<!-- if provider:gemini -->
Use Google Search Grounding for real-time information.
<!-- endif -->

<!-- if provider:perplexity -->
Cite sources using [1], [2] notation.
<!-- endif -->
```

---

## v1.14.x Series - Enhanced Context Providers

**Theme**: More ways to inject context

### v1.14.0 - @url Context

| Feature | Description | Priority |
|---------|-------------|----------|
| **`@url` provider** | Fetch and inject web content | High |
| **HTML→Markdown** | Convert fetched HTML to markdown | High |
| **Caching** | Cache fetched URLs for session | Medium |
| **Rate limiting** | Prevent abuse of web fetching | Medium |

### v1.14.1 - @clipboard Context

| Feature | Description | Priority |
|---------|-------------|----------|
| **`@clipboard`** | Inject clipboard contents | Medium |
| **Image support** | Handle clipboard images (base64) | Low |
| **TUI + VSCode** | Both interfaces support clipboard | Medium |

### v1.14.2 - Recovery Features

| Feature | Description | Priority |
|---------|-------------|----------|
| **`/rewind` browser** | Interactive checkpoint history viewer | Medium |
| **`/agent --dry-run`** | Preview changes without applying | Medium |
| **Diff preview** | Show what would change before commit | Medium |

---

## Future Considerations

These are tracked but not prioritized:

- **Textual TUI migration** - Only if current TUI becomes limiting (~20-40 hrs)
- **libghostty SDK** - Watch for stable C API (expected 2026)
- **Per-provider tool config** - Enable/disable tools per provider
- **Custom tools** - User-defined tools in `~/.ppxai/tools/`
- ~~**Provider-aware tool guidance**~~ - ✅ Implemented in v1.13.3
- **Cost display in `/usage`** - Show estimated $ cost alongside token counts (feedback from AI code review)
- **Per-provider cost rates** - Configure pricing per model in JSON config
- **Standardized error handling** - Apply detailed traceback logging pattern from Gemini provider to `openai_compat.py` and `perplexity.py` for consistent debugging (feedback from AI code review)

### Jupyter Kernel Tool (Data Science Workflow)

Enable AI to execute cells in a running JupyterLab kernel with real-time output streaming:

| Package | Purpose |
|---------|---------|
| `jupyter_client` | Connect to running kernels via connection file |
| `nbclient` | Higher-level cell execution with callbacks |
| `websockets` | Real-time output streaming via Jupyter wire protocol |
| `nbformat` | Read/write .ipynb files |

**Use case:** Data developer asks AI to "run this notebook cell by cell" and watches output appear in JupyterLab UI in real-time.

**Implementation sketch:**
```python
class JupyterKernelTool(BaseTool):
    name = "execute_notebook_cell"

    async def execute(self, notebook_path: str, cell_index: int):
        # Connect to kernel, execute cell, stream outputs as SSE events
```

### Image Preview in Chat Panel

Current `/show` command opens files in VSCode text editor. Need image preview for:
- **Formats:** PNG, JPG, JPEG, GIF, SVG, WebP
- **Display:** Inline in chat panel or split pane preview
- **Use case:** AI generates chart (e.g., matplotlib), user wants to see it without leaving chat

**Implementation options:**
1. **Inline base64** - Embed `<img src="data:image/png;base64,...">` in chat
2. **VSCode webview** - Use `vscode.Uri.file()` with webview resource mapping
3. **Side panel** - Dedicated image preview panel alongside chat

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
uv run pytest tests/ -v       # Run tests (525 passing)
uv run ppxai-server           # Start server for VSCode dev
```

---

## Historical Notes

For detailed release history, see [CHANGELOG.md](CHANGELOG.md).

For archived planning documents:
- [docs/archive/](docs/archive/) - Legacy documentation
- [docs/v1.11.0-agentic-workflow-plan.md](docs/v1.11.0-agentic-workflow-plan.md) - Agentic workflow design

---

**Last Updated**: January 7, 2026
