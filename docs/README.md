# ppxai Documentation

## Quick Start

**New to tools?** Start here:
1. [Tool Creation Guide](TOOL_CREATION_GUIDE.md) - Step-by-step guide for creating tools ⭐
2. [Quick Start](QUICK_START_TOOLS.md) - 60-second setup

## Documentation Index

### For Users

| Document | Description |
|----------|-------------|
| [Tool Creation Guide](TOOL_CREATION_GUIDE.md) | **START HERE** - Step-by-step guide for both approaches |
| [Quick Start](QUICK_START_TOOLS.md) | Get tools working in 60 seconds |
| [Tool Approaches](TOOL_APPROACHES.md) | Comparison: Prompt-based vs Native function calling |

### Reference

| Document | Description |
|----------|-------------|
| [Tools README](TOOLS_README.md) | Complete technical reference |
| [Integration Summary](INTEGRATION_SUMMARY.md) | How MCP + OpenAI work together |
| [User Tools Guide](USER_TOOLS_GUIDE.md) | Detailed guide for custom tools |

### Troubleshooting

| Document | Description |
|----------|-------------|
| [MCP Fix Guide](MCP_FIX_GUIDE.md) | MCP server troubleshooting |

### Archive

| Document | Description |
|----------|-------------|
| [Tool Integration](TOOL_INTEGRATION.md) | Legacy integration docs |
| [Tool Integration Complete](TOOL_INTEGRATION_COMPLETE.md) | Legacy docs |

## Tool System Overview

ppxai supports two approaches for adding custom tools:

### 1. Built-in Python Tools (Recommended)

**Best for:** Most use cases (90%)

- ✅ Simple Python functions
- ✅ Fast execution (same process)
- ✅ Easy to debug
- ✅ No external dependencies

**Example:** See `demo/example_builtin_tool.py`

**Guide:** [Tool Creation Guide - Option 1](TOOL_CREATION_GUIDE.md#option-1-built-in-python-tool-recommended)

### 2. MCP Server Tools (Advanced)

**Best for:** Standard integrations (GitHub, Slack, etc.)

- ✅ Reusable across apps
- ✅ Community ecosystem
- ⚠️ Requires Node.js
- ⚠️ More complex

**Example:** See `demo/example_mcp_server/`

**Guide:** [Tool Creation Guide - Option 2](TOOL_CREATION_GUIDE.md#option-2-mcp-server-tool-advanced)

## Getting Started with Tools

### Step 1: Enable Tools

In ppxai:
```
/tools enable
```

### Step 2: List Available Tools

```
/tools list
```

### Step 3: Use Tools

Just ask the AI to use them:
```
You: Use the calculator tool to compute 42 * 58
```

The AI will automatically use the appropriate tool!

### Step 4: Create Your Own

Follow the [Tool Creation Guide](TOOL_CREATION_GUIDE.md)

## Examples

### Built-in Tool Examples

See `demo/example_builtin_tool.py`:
- `analyze_python_file` - Analyze Python code
- `format_json` - Format JSON strings
- `calculate_sha256` - Calculate file hashes

### MCP Server Example

See `demo/example_mcp_server/`:
- Complete working MCP server
- 4 text manipulation tools
- Ready to use or modify

## Testing

All tests are in `tests/` directory:

```bash
# Test all tools
python tests/test_all_tools.py

# Test MCP diagnostics
python tests/test_mcp.py

# Test prompt-based approach
python tests/test_prompt_tools.py
```

## Directory Structure

```
ppxai/
├── ppxai.py                              # Main CLI (with /tools commands)
├── tool_manager.py                       # Core tool management
├── perplexity_tools_prompt_based.py      # Prompt-based implementation
├── demo/
│   ├── example_builtin_tool.py           # Built-in tool example
│   ├── example_mcp_server/               # MCP server example
│   └── demo_tools_working.py             # Working demo
├── tests/
│   ├── test_all_tools.py                 # Test all tools
│   ├── test_mcp.py                       # MCP diagnostics
│   └── test_prompt_tools.py              # Quick test
└── docs/
    ├── README.md                          # This file
    ├── TOOL_CREATION_GUIDE.md            # ⭐ Start here
    └── ...                                # Other guides
```

## FAQ

**Q: Do I need MCP servers?**
A: No! Built-in Python tools work great for most use cases.

**Q: Which approach should I use?**
A: Start with built-in Python tools (Option 1). Add MCP only if you need standard integrations like GitHub/Slack.

**Q: How do I add my own tool?**
A: Follow the [Tool Creation Guide](TOOL_CREATION_GUIDE.md) - takes ~15 minutes.

**Q: Do tools work with Perplexity?**
A: Yes! We use prompt-based tool invocation that works with Perplexity.

**Q: Can I use both approaches?**
A: Yes! You can have both built-in and MCP tools simultaneously.

## Support

- **Examples**: Check `demo/` directory
- **Tests**: See `tests/` directory
- **Issues**: GitHub issues
- **MCP Community**: [MCP Discord](https://discord.gg/modelcontextprotocol)

---

**Ready to add tools?** Start with [Tool Creation Guide](TOOL_CREATION_GUIDE.md)!
