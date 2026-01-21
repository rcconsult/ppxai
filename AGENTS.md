---
provider_hints:
  local:
    - "Complete tasks fully without stopping on empty responses."
    - "Use tools proactively - don't ask permission for read-only operations."
    - "When editing files, make all changes in a single edit_file call."
  ollama:
    - "Keep responses concise - Ollama has limited context."
    - "Prefer smaller, focused tool calls over complex multi-step operations."
  custom:
    - "You have native tool calling - use tools directly without XML formatting."
    - "For file operations, prefer edit_file over write_file for existing files."
  perplexity:
    - "Use your native web search for current information - don't use web_search tool."
    - "Cite sources as markdown links inline."
  gemini:
    - "Use Google Search grounding for current information when available."
    - "You have a 1M token context - feel free to include full file contents."
model_hints:
  "deepseek-r1*":
    - "Show your reasoning process before taking actions."
    - "Think step-by-step for complex problems."
  "qwen2.5-coder*":
    - "Focus on code quality and correctness."
    - "Use edit_file for surgical changes, write_file only for new files."
  "gpt-oss*":
    - "You are a coding specialist - prioritize working code over explanations."
    - "Execute tools immediately rather than describing what you would do."
  "sonar*":
    - "You have real-time web access - use it for current information."
    - "Always cite sources with markdown links."
---

## Project: ppxai

ppxai is a terminal-based UI application for interacting with multiple AI providers (Perplexity AI, OpenAI, Gemini, OpenRouter, local models via Ollama/vLLM).

### Code Style

- Python 3.10+ with type hints
- Use dataclasses for data structures
- Async/await for I/O operations
- pytest for testing

### Architecture

- `ppxai/engine/` - Core business logic (no UI dependencies)
- `ppxai/server/` - HTTP/SSE server for IDE integration
- `ppxai/commands/` - Slash command handlers
- `ppxai/config/` - Configuration system
- `vscode-extension/` - TypeScript VSCode extension

### Testing

Run tests with:
```bash
uv run pytest tests/ -v
```

Integration tests (require custom endpoint):
```bash
PPXAI_CONFIG_FILE="$HOME/.ppxai/ppxai-config.json" uv run pytest tests/test_custom_endpoint_integration.py -v
```

### Important Files

- `CLAUDE.md` - Detailed project instructions for Claude Code
- `ROADMAP.md` - Feature roadmap and version planning
- `docs/RELEASE-PLAN-v1.14.x.md` - Current release series plan

### Current Development (v1.14.1)

**Stage 1 Complete:** VSCode `/edit` command and `/context reload`

- `/edit filepath[:line[:col]]` - Opens file in VSCode editor with position
- `/context reload` - Reloads AGENTS.md from disk without server restart
- `POST /files/write` - Server endpoint for file writes with path validation
- `POST /context/reload` - Server endpoint for bootstrap context reload
- Full test coverage in `tests/test_http_server.py`

**Next:** Stage 2 (Web App CodeMirror 6 editor) or Stage 3 (TUI)
