# ppxai Documentation

## Quick Start

**New to ppxai?** Start here:
1. [File Editing Guide](FILE_EDITING_GUIDE.md) - AI-powered file editing with consent
2. [Shell Consent Guide](SHELL_CONSENT_GUIDE.md) - Secure shell command execution

## Documentation Index

### User Guides

| Document | Description |
|----------|-------------|
| [File Editing Guide](FILE_EDITING_GUIDE.md) | AI-powered file editing with user consent |
| [Shell Consent Guide](SHELL_CONSENT_GUIDE.md) | Shell command security with consent system |
| [Context Injection Guide](CONTEXT-INJECTION.md) | `@file`, `@git`, `@tree` context providers |
| [Provider Setup Guide](PROVIDER_SETUP.md) | Configure AI providers (OpenAI, Gemini, Perplexity) |
| [Autorouter Config](AUTOROUTER-CONFIG.md) | Automatic model routing for coding tasks |
| [Custom Tool Development](CUSTOM_TOOL_DEVELOPMENT_GUIDE.md) | Create your own tools for ppxai |

### Technical Reference

| Document | Description |
|----------|-------------|
| [Agentic Workflow Plan](v1.11.0-agentic-workflow-plan.md) | Technical implementation of agentic features |
| [Architecture Refactoring](architecture-refactoring.md) | EngineClient architecture design |

### Archived Documentation

Legacy documentation is preserved in `archive/` for historical reference:
- `archive/legacy-tools-docs/` - Legacy tool system docs (pre-EngineClient)
- `archive/bug-reports/` - Historical bug reports

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
| `get_weather` | Get weather information |
| `calculator` | Perform calculations |

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

The TUI supports tab-completion for tools:

| Input | Tab Shows |
|-------|-----------|
| `/tools <tab>` | enable, disable, list, status, help |
| `/tools help <tab>` | All available tool names |
| `/tools help calc<tab>` | Completes to `calculator` |

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
engine.set_model("gemini-2.0-flash")

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

**Current Version**: v1.13.2
**Last Updated**: 2026-01-05
