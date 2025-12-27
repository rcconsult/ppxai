# ppxai Development Roadmap

> **Current Version**: v1.11.9 (December 2025)
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

## Next Up: v1.12.0 - Polish & Stability

**Goal**: Bug fixes, test coverage, documentation polish

| Task | Priority | Effort |
|------|----------|--------|
| Add agent mode tests (`tests/test_agent_mode.py`) | High | 2 hrs |
| Fix 4 test warnings (unawaited coroutines) | Medium | 1 hr |
| Remove remaining legacy comments in tests | Low | 30 min |
| Update all doc version references | Medium | 30 min |

---

## Future: v1.13.0+ - Enhanced Capabilities

### Better Tool System
- **Per-Provider Tool Config** - Enable/disable tools per provider in config
- **Tool Presets** - `coding`, `research`, `admin` preset bundles
- **Custom Tools** - User-defined tools in `~/.ppxai/tools/`

### Enhanced Context
- **@url** - Fetch and inject web content
- **@clipboard** - Inject clipboard contents
- **Context size display** - Show token count before sending

### VSCode Extension Improvements
- **Inline diff preview** - Show file changes before applying
- **Terminal integration** - Run commands in VSCode terminal
- **Git integration** - Stage, commit from agent mode

### Performance
- **Response caching** - Cache identical queries
- **Streaming improvements** - Lower latency first token

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
