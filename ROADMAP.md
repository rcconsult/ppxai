# ppxai Development Roadmap

> **Current Version**: v1.12.3 (January 2026)
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

## Next Up: v1.12.0 - Safety & Reproducibility

**Theme**: Make agent mode safe and predictable with atomic rollback

| Feature | Description | Priority |
|---------|-------------|----------|
| **Git-based checkpoints** | Auto-commit before `/agent` tasks for atomic rollback | High |
| **`/undo` command** | Revert last agent task (`git revert HEAD`) | High |
| **Agent mode tests** | Add `tests/test_agent_mode.py` | High |
| **Fix test warnings** | 4 unawaited coroutine warnings | Medium |

**User value**: If agent edits go wrong, `/undo` restores all files atomically.

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
uv run pytest tests/ -v       # Run tests (337 passing)
uv run ppxai-server           # Start server for VSCode dev
```

---

## Historical Notes

For detailed release history, see [CHANGELOG.md](CHANGELOG.md).

For archived planning documents:
- [docs/archive/](docs/archive/) - Legacy documentation
- [docs/v1.11.0-agentic-workflow-plan.md](docs/v1.11.0-agentic-workflow-plan.md) - Agentic workflow design

---

**Last Updated**: December 27, 2025
