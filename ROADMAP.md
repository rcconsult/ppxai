# ppxai Development Roadmap

> **Current Version**: v1.12.5 (January 2026)
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

## v1.13.x Series - Session Bootstrap

**Theme**: Reproducible starting point for every session

**User value**: Teams share project context. Consistent AI behavior across sessions.

### v1.13.0 - AGENTS.md Support

| Feature | Description | Status |
|---------|-------------|--------|
| **AGENTS.md loading** | Load project instructions from AGENTS.md on startup | Planned |
| **CLAUDE.md fallback** | Support CLAUDE.md as alternative filename | Planned |
| **System prompt injection** | Append project context to system prompt | Planned |
| **TUI + VSCode support** | Both interfaces load context | Planned |

**Implementation notes:**
- Parse markdown, extract text content
- Inject as system message prefix (append, not replace)
- Show loaded context in `/status` output

### v1.13.1 - File Precedence

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

### v1.13.2 - `/context` Commands

| Feature | Description | Status |
|---------|-------------|--------|
| **`/context show`** | Display loaded context sources | Planned |
| **`/context reload`** | Refresh context from disk | Planned |
| **`/context edit`** | Open context file in editor | Planned |
| **`/context clear`** | Temporarily disable context | Planned |
| **Tab autocomplete** | Autocomplete for subcommands | Planned |

**Note:** Using `/context` instead of `/agents` - clearer naming, avoids confusion with agent mode.

### v1.13.3 - Context Enhancements

| Feature | Description | Status |
|---------|-------------|--------|
| **Context size display** | Show token count in status bar | Planned |
| **Conditional sections** | `<!-- if provider:gemini -->` blocks | Planned |
| **Include directive** | `<!-- include: ./docs/style.md -->` | Planned |
| **HTTP endpoint** | `GET /context` for VSCode | Planned |

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
uv run pytest tests/ -v       # Run tests (406 passing)
uv run ppxai-server           # Start server for VSCode dev
```

---

## Historical Notes

For detailed release history, see [CHANGELOG.md](CHANGELOG.md).

For archived planning documents:
- [docs/archive/](docs/archive/) - Legacy documentation
- [docs/v1.11.0-agentic-workflow-plan.md](docs/v1.11.0-agentic-workflow-plan.md) - Agentic workflow design

---

**Last Updated**: January 3, 2026
