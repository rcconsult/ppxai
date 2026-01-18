# ppxai Development Roadmap

> **Current Version**: v1.13.10 (January 2026)
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
- **`@filename` autocomplete fix** - Web App and VSCode now show real file suggestions via `/files/search`
- **E2E Playwright tests** - 55 browser tests for data viewer components

### Session Persistence & Windows Fixes ✅ (v1.13.9)
- **Session auto-save** - Sessions saved after each chat exchange with crash recovery
- **Command history persistence** - User input history saved per session
- **Working directory persistence** - `cd` command changes remembered across restarts
- **Auto-restore on startup** - Configurable: `"always"`, `"prompt"`, `"never"`
- **Tool parameter aliasing** - Handle model variations (`filepath` vs `file_path`)
- **Context overflow prevention** - Friendly error when `@file` exceeds 128K limit
- **Empty responses after tools** - Prompt model for summary when response is empty
- **Reasoning model support** - Handle `reasoning_content` field from DeepSeek R1
- **`/context` command** - Show context usage vs model limit, injected files list (TUI, Web, VSCode)
- **`/context clear`** - Remove all injected @file/@git/@tree content from current session
- **Context badge** - TUI status line and VSCode header show context usage percentage
- **Hash-based deduplication** - Prevents duplicate @git/@tree injections (MD5 content hash)
- **Per-model context limits** - Configure `context_limit` per model (Gemini: 1M tokens)

### Stabilization & Architecture ✅ (v1.13.10)
- **Tool loop detection** - Configurable `max_same_tool_calls` prevents infinite loops with Ollama models
- **Image/PDF preview** - Web app `/show` command supports image and PDF preview
- **VSCode chatPanel.ts refactoring** - Reduced 5,123 to 2,773 lines with EventBus + State Machine architecture
- **EventBus pub/sub** - Decoupled stream handlers, consent handlers, and UI updates
- **Agent state machine** - Explicit state transitions replace implicit local variables
- **handlers/ module** - 1,658 lines of extracted handler code with IoC pattern
- **client.py refactoring** - 36% reduction (2,037→1,311 lines) via 5-phase extraction
- **Technical debt cleared** - All 16 critical/high priority items addressed

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

### v1.14.2 - `/context` Commands for Bootstrap

**Note:** v1.13.9 implemented `/context` and `/context clear` for **injected context** (@file/@git/@tree).
v1.14.2 extends `/context` to also manage **bootstrap context** (AGENTS.md/CLAUDE.md).

| Feature | Description | Status |
|---------|-------------|--------|
| **`/context show`** | Display AGENTS.md sources (extends existing `/context`) | Planned |
| **`/context reload`** | Refresh AGENTS.md from disk | Planned |
| **`/context edit`** | Open AGENTS.md in editor | Planned |
| **Integration** | Unified view of bootstrap + injected context | Planned |

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

### Multi-Model Orchestration (Research)

**Reference:** [docs/2512.15943v1.pdf](docs/2512.15943v1.pdf) - "Small Language Models for Efficient Agentic Tool Calling" (AWS, Dec 2025)

**Paper Summary:**
- Fine-tuned `facebook/opt-350m` (350M params) on ToolBench dataset (187,542 examples, 16,000+ APIs)
- Single epoch training with SFT (Supervised Fine-Tuning) using HuggingFace TRL
- Hyperparameters: lr=5×10⁻⁵, batch=32, gradient clipping=0.3, FP16, AdamW

**Benchmark Results (ToolBench - 1,100 test queries across 6 categories):**

| Model | Params | Pass Rate | Gap |
|-------|--------|-----------|-----|
| **Fine-tuned SLM** | **350M** | **77.55%** | – |
| ToolLLaMA-DFS | 7B | 30.18% | -47% |
| ChatGPT-CoT | 175B | 26.00% | -52% |
| ToolLLaMA-CoT | 7B | 16.27% | -61% |
| Claude-CoT | 52B | 2.73% | -75% |

**Why Small Models Win at Tool Calling:**
1. **Parameter efficiency** - All capacity focused on tool patterns, not general language
2. **Behavioral focus** - Learns structured Thought-Action-Observation patterns
3. **No overgeneralization** - Precise API calls vs verbose explanations

**Implication for ppxai:** Specialized small models can dramatically outperform general-purpose LLMs at specific tasks like tool selection. A 350M router could achieve 77% accuracy while ChatGPT achieves only 26%.

**Proposed Architecture - Dual Model Orchestration:**

```
User Query → Tool Router (small, fast) → Decision
                                            ↓
                            [tool_needed?] ─┬─ Yes → Execute Tool → Response Generator (larger)
                                            └─ No  → Response Generator (larger)
```

| Component | Model Size | Role | Latency |
|-----------|------------|------|---------|
| Tool Router | 350M-1.3B | Decide if/which tool to call | <50ms |
| Response Generator | 3B-7B | Generate code, explanations | ~60 tok/s |

**Benefits:**
- Faster tool decisions (small model = instant routing)
- Better tool selection accuracy (specialized > general)
- Reduced load on main model (only generates, doesn't decide)
- Fits 6GB VRAM: router (500MB) + generator (1.9GB-4.7GB)

**Implementation Path:**

| Phase | Task | Effort |
|-------|------|--------|
| 1 | Add tool-calling benchmark to test suite | Low |
| 2 | Test existing small models (Qwen2.5-0.5B, DeepSeek-Coder 1.3B) on ppxai tools | Medium |
| 3 | Config option: `tool_router_model` separate from `default_model` | Medium |
| 4 | Fine-tune ppxai-specific tool router on our schema (follow paper's SFT approach) | High |

**Ollama Multi-Model Setup:**
```bash
# Router model (stays loaded, instant)
ollama pull qwen2.5-coder:0.5b  # 398MB

# Generator model (loaded on demand)
ollama pull qwen2.5-coder:3b    # 1.9GB

# Run both with OLLAMA_NUM_PARALLEL=2
OLLAMA_NUM_PARALLEL=2 ollama serve
```

**Config example:**
```json
{
  "ollama": {
    "tool_router_model": "qwen2.5-coder:0.5b",
    "default_model": "qwen2.5-coder:3b",
    "orchestration": "router_generator"
  }
}
```

**Paper Limitations to Consider:**
- Model optimized for ToolBench format - may not generalize to ppxai's tool schema
- 350M limit may struggle with complex contextual nuances
- Requires retraining as tools evolve

**Status:** Research phase. PDF saved to `docs/`. Next: benchmark existing small models on ppxai tool schema before implementation.

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
| ~~**`@filename` injection broken**~~ | ~~Web app file injection via `@filename` stopped working after agent context fix.~~ | ✅ Fixed in v1.13.8 |

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

**Last Updated**: January 18, 2026
