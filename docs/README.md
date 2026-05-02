# ppxai Documentation

## Quick Start

**New to ppxai?** Start here:
1. [Bootstrap Context Guide](BOOTSTRAP_CONTEXT_GUIDE.md) - Project-specific instructions via AGENTS.md
2. [File Editing Guide](FILE_EDITING_GUIDE.md) - AI-powered file editing with consent
3. [Shell Consent Guide](SHELL_CONSENT_GUIDE.md) - Secure shell command execution

## Documentation Index

### User Guides

| Document | Description |
|----------|-------------|
| [Bootstrap Context Guide](BOOTSTRAP_CONTEXT_GUIDE.md) | Project-specific instructions via AGENTS.md (v1.14.0+, hierarchical scopes v1.14.2+) |
| [File Editing Guide](FILE_EDITING_GUIDE.md) | AI-powered file editing with user consent |
| [Shell Consent Guide](SHELL_CONSENT_GUIDE.md) | Shell command security with consent system |
| [Context Injection Guide](CONTEXT-INJECTION.md) | `@file`, `@git`, `@tree`, `@clipboard`, `@url` context providers |
| [Provider Setup Guide](PROVIDER_SETUP.md) | Configure AI providers (OpenAI, Gemini, Perplexity) |
| [Autorouter Config](AUTOROUTER-CONFIG.md) | Automatic model routing for coding tasks |
| [Custom Tool Development](CUSTOM_TOOL_DEVELOPMENT_GUIDE.md) | Create your own tools for ppxai |
| [Agent Mode Guide](AGENT_MODE_GUIDE.md) | Autonomous multi-step task execution |
| [Checkpoint Guide](CHECKPOINT_GUIDE.md) | Undo and rollback agent operations |
| [Ollama Limitations](ollama-limitations.md) | Local model constraints and workarounds |
| [Tool Calling](TOOL_CALLING.md) | Native vs prompt-based tool calling (v1.15.3+) |
| [Installation Guide](INSTALLATION.md) | Install ppxai on any platform |
| [Debug Logging](DEBUG-LOGGING.md) | `/debug-log` command, persistence, early-startup diagnostics |

### Technical Reference

| Document | Description |
|----------|-------------|
| [Architecture](ARCHITECTURE.md) | Module hierarchy, import patterns, transactional state |
| [DGX Spark Setup](DGX-SPARK-SETUP.md) | vLLM + Ollama on NVIDIA DGX Spark |
| [vLLM Tool Calling](vllm-tool-calling-guide.md) | Hermes vs Harmony, native vs prompt-based |
| [Prompt-Based Tool Calling](prompt-based-tool-calling.md) | Developer guide for non-native tool calling |
| [Release Notes v1.18.0 (draft)](RELEASE-NOTES-v1.18.0.md) | **In progress** — P0 agent heartbeat primitives (`AGENT_BEAT` / `_RUN_START` / `_RUN_COMPLETE` / `_RUN_ERROR` / `_ZOMBIE`), zombie circuit-breaker, cross-client renderers |
| [Stabilization v1.18.0](STABILIZATION-v1.18.0.md) | **Landed** — five-phase cleanup pass: `GET /state` reconnect endpoint, AppState `last_message_role`, `format_tokens`/`format_usage_badge` cross-language helpers, `AutosaveFailureGuard`, public-API promotion of 8 helpers, removed `has_vision_model` alias |
| [Release Notes v1.17.7](RELEASE-NOTES-v1.17.7.md) | `ppxai-desktop --version` stale-fallback fix |
| [Release Notes v1.17.6](RELEASE-NOTES-v1.17.6.md) | R5 first-class `uploaded_file` content type, R19 multimodal rendering gap |
| [Release Notes v1.17.5](RELEASE-NOTES-v1.17.5.md) | R8–R18 bugfix batch (alternation, CSV streaming, Gemini null-parts, /attach UX) |
| [Release Notes v1.17.4](RELEASE-NOTES-v1.17.4.md) | File upload Phases 0–7, CompletionProvider, schema DTO, EngineClient decomposition |
| [Release Notes v1.17.3](RELEASE-NOTES-v1.17.3.md) | CodeMirror modular split, verbose tools toggle, benchmark infra |
| [Release Notes v1.17.2](RELEASE-NOTES-v1.17.2.md) | SSE state_sync, thread-safe AppState, iTerm2 images, preview venv detect |
| [Release Notes v1.17.1](RELEASE-NOTES-v1.17.1.md) | AppState wiring, EngineClient decomposition, web terminal, preview serve |
| [Release Notes v1.17.0](RELEASE-NOTES-v1.17.0.md) | Server/config modularization, K8s POC, key bindings registry, Textual 8.1.1, protocol-based imports |
| [Release Notes v1.16.2](RELEASE-NOTES-v1.16.2.md) | RightPanelFrame, file tree sidebar, inline images, web refactor, shell config |
| [Release Notes v1.16.1](RELEASE-NOTES-v1.16.1.md) | FileTree widget, CommandFactory server pattern, unified session restore |
| [Release Notes v1.15.6](RELEASE-NOTES-v1.15.6.md) | Native OpenAI provider, model profiles, benchmark analysis |
| [Release Notes v1.15.5](RELEASE-NOTES-v1.15.5.md) | Multi-line input, Escape key fix, build fix |
| [Release Notes v1.15.4](RELEASE-NOTES-v1.15.4.md) | Live preview, SSL fixes, debug logging |
| [Release Plan v1.15.x](archive/RELEASE-PLAN-v1.15.x.md) | Development plan for v1.15.x series (archived) |

### Archived Documentation

Legacy and completed documentation is preserved in `archive/` for historical reference:
- `archive/release-notes/` - Release notes for v1.11.x through v1.14.x
- `archive/benchmarks/` - Model evaluation reports (Gemini, Perplexity, GPT-OSS tuning)
- `archive/design/` - Completed design documents (image handler, side panel, distributed arch)
- `archive/v1.15.1-completed/` - v1.15.1 planning and implementation docs
- `archive/v1.15.2-completed/` - v1.15.2 planning and implementation docs
- `archive/v1.15.3/` - v1.15.3 planning docs
- `archive/v1.15.4/` - v1.15.4 planning docs (preview, SSL bugfix)

## Tool System Overview

ppxai includes built-in tools for AI-powered development:

### Built-in Tools

| Tool | Description |
|------|-------------|
| `list_directory` | List files in directories |
| `read_file` | Read file contents |
| `execute_shell_command` | Run shell commands (with consent) |
| `apply_patch` | Apply unified diff patches |
| `replace_block` | Find and replace text blocks |
| `insert_text` | Insert text at line numbers |
| `delete_lines` | Delete line ranges |
| `web_search` | Search the web (DuckDuckGo) |
| `web_search_premium` | Premium web search (Perplexity/Gemini) |
| `fetch_url` | Fetch URL contents |
| `get_datetime` | Get current date/time |
| `get_weather` | Get weather information (HTTPS/HTTP fallback for corporate proxies) |
| `calculator` | Perform calculations |
| `display_file` | AI proactively shows files after generating them |
| `search_files` | Search for files by pattern |
| `get_working_directory` | Get current working directory |
| `container_list` | List Docker/Podman containers |
| `container_logs` | Get container logs |
| `pod_list` | List Kubernetes pods |
| `kubectl_apply` | Apply Kubernetes manifests |

### Enabling Tools

```bash
# In TUI
/tools enable

# Check status
/tools status

# List available tools
/tools list

# Get help for a specific tool
/tools help calculator
```

### Autocomplete

All four clients (Rich TUI, Textual TUI, Web, VSCode) share the same
autocomplete via `ppxai/engine/completion.py`. Rich + Textual call it
in-process; Web + VSCode call it via `POST /complete`.

| Input | Tab Shows |
|-------|-----------|
| `/tools <tab>` | enable, disable, list, status, help |
| `/tools help <tab>` | All available tool names (live from `tool_manager.list_tools()`) |
| `/tools help calc<tab>` | Completes to `calculator` |
| `/usage show <tab>` | session, provider, model, off |
| `/checkpoint backend <tab>` | git, file, auto, none |
| `/theme <tab>` | All themes + `list`, `emoji` subcommands |
| `/model <tab>` | Models for the active provider (dynamic) |
| `/provider <tab>` | All configured provider IDs |
| `/attach <tab>` | Path completion with file/dir discrimination |
| `@<tab>` | `@git`, `@tree`, `@clipboard`, `@url` + fuzzy file search |

Every item returned by the engine has a stable JSON schema:
`{text, display, description, kind, replace_start}`. Client-side
completers are pure glue — they don't own any subcommand tables.

### Creating Custom Tools

Tools are implemented in `ppxai/engine/tools/builtin/`:

```python
from ppxai.engine.tools.base import BaseTool

class MyTool(BaseTool):
    name = "my_tool"
    description = "Description for the AI"
    parameters = {
        "type": "object",
        "properties": {
            "arg1": {"type": "string", "description": "First argument"}
        },
        "required": ["arg1"]
    }

    async def execute(self, arg1: str) -> str:
        return f"Result: {arg1}"
```

Register in `ppxai/engine/tools/builtin/__init__.py`:

```python
from .my_tool import MyTool

def register_all_builtin_tools(manager, provider_name=None, engine=None):
    # ... existing registrations ...
    manager.register_tool(MyTool())
```

## Using EngineClient

The `EngineClient` is the primary interface for programmatic access:

```python
from ppxai.engine import EngineClient

# Create engine
engine = EngineClient()

# Configure
engine.set_provider("gemini")
engine.set_model("gemini-2.5-flash")

# Enable tools
engine.enable_tools()

# Chat (sync)
response = engine.chat_sync("What time is it?")

# Chat (async with events)
async for event in engine.chat("Explore this project"):
    if event.type == EventType.STREAM_CHUNK:
        print(event.data, end="")
    elif event.type == EventType.TOOL_CALL:
        print(f"Calling: {event.data['tool']}")
```

## Directory Structure

```
ppxai/
├── ppxai/                                # Main package
│   ├── main.py                           # CLI entry point
│   ├── commands.py                       # Slash command handlers
│   └── engine/                           # Core engine
│       ├── client.py                     # EngineClient (primary interface)
│       ├── providers/                    # Provider implementations
│       └── tools/                        # Tool system
│           ├── manager.py                # ToolManager
│           └── builtin/                  # Built-in tools
├── demo/
│   └── demo_tools_working.py             # Working demo
├── tests/
│   ├── test_engine_tool_parsing.py       # Tool parsing tests
│   ├── test_file_editing_tools.py        # File editing tests
│   └── ...                               # Additional tests
└── docs/
    ├── README.md                          # This file
    ├── FILE_EDITING_GUIDE.md             # File editing guide
    └── archive/                           # Archived documentation
```

## FAQ

**Q: What is EngineClient?**
A: The unified client interface for all AI interactions. It replaces the legacy AIClient.

**Q: How do I add a new AI provider?**
A: See [Provider Setup Guide](PROVIDER_SETUP.md) for configuration examples.

**Q: How do tools work?**
A: Tools are registered with `ToolManager` and available to the AI when enabled. The AI can call tools by outputting JSON with the tool name and arguments.

**Q: Is consent required for file editing?**
A: Yes! All file edits require user consent. See [File Editing Guide](FILE_EDITING_GUIDE.md).

**Q: How do I use context injection?**
A: Type `@filename`, `@git`, or `@tree` in your messages. See [Context Injection Guide](CONTEXT-INJECTION.md).

## Support

- **GitHub Issues**: [github.com/rcconsult/ppxai/issues](https://github.com/rcconsult/ppxai/issues)
- **Documentation**: This folder
- **Examples**: `demo/` directory

---

**Current Version**: v1.18.3
**Last Updated**: 2026-05-02
