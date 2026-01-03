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

---

## In Development: v1.12.5 - Native Gemini Provider

**Theme**: Enhanced Gemini with Google Search Grounding

| Feature | Description | Status |
|---------|-------------|--------|
| **Native Gemini SDK** | Direct integration with `google-genai` package | ✅ Done |
| **Google Search Grounding** | Real-time web search with citations | ✅ Done |
| **Streaming support** | Full async streaming like Perplexity | ✅ Done |
| **Usage tracking** | Token counts from Gemini API | ✅ Done |
| **Fallback to OpenAI-compat** | Works without `google-genai` installed | ✅ Done |

**Install**: `pip install ppxai[gemini]` for enhanced Gemini support.

**Branch**: `feature/gemini-native-provider`

---

## v1.13.0 - Session Bootstrap

**Theme**: Reproducible starting point for every session

| Feature | Description | Priority |
|---------|-------------|----------|
| **AGENTS.md support** | Load project context on startup | High |
| **File precedence** | Global (`~/.ppxai/`) → Project → Subdirectory | High |
| **`/agents` commands** | `/agents show`, `/agents reload`, `/agents edit` | Medium |
| **CLAUDE.md fallback** | Support both AGENTS.md and CLAUDE.md standards | Medium |

**User value**: Teams share project context. Consistent starting point every session.

---

## v1.14.0+ - Enhanced Recovery & Context

**Theme**: Power user features

| Feature | Description | Priority |
|---------|-------------|----------|
| **`/rewind` browser** | Interactive checkpoint history viewer | Medium |
| **`/agent --dry-run`** | Preview changes without applying | Medium |
| **@url context** | Fetch and inject web content | Low |
| **@clipboard context** | Inject clipboard contents | Low |
| **Token count display** | Show context size before sending | Low |

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
