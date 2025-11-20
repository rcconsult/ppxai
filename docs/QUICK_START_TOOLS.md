# Quick Start: Tools for ppxai

## ⚡ 60-Second Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the working demo
python demo_tools_working.py
```

That's it! The demo uses **prompt-based tools** that work with Perplexity right now.

## 🎯 What You Get

**4 Built-in Tools:**
- `search_files` - Find files by pattern
- `read_file` - Read file contents
- `list_directory` - Show directory contents
- `calculator` - Evaluate math expressions

**Example:**
```
You: Use the search_files tool to find all Python files

AI: I'll search for Python files.

```json
{
  "tool": "search_files",
  "arguments": {"pattern": "*.py"}
}
```

[Tool executes...]

AI: I found 3 Python files: ppxai.py, tool_manager.py, and demo_tools.py
```

## 📚 Files Overview

| File | Purpose | Use When |
|------|---------|----------|
| `perplexity_tools_prompt_based.py` | **Prompt-based tools** | ✅ Use with Perplexity (works now!) |
| `perplexity_with_tools.py` | Native function calling | Use with OpenAI/Claude |
| `tool_manager.py` | Core tool management | Used by both |
| `demo_tools_working.py` | **Working demo** | Test it out! |

## 🚀 Integration Options

### Option 1: Add `/tools` Command

Quick way to test tools in ppxai:

```python
# Add to ppxai.py
from perplexity_tools_prompt_based import PerplexityClientPromptTools

elif command == "/tools":
    # Enable tools for this session
    tool_client = PerplexityClientPromptTools(
        api_key=api_key,
        session_name=client.session_name,
        enable_tools=True
    )
    asyncio.run(tool_client.initialize_tools())
    client = tool_client
    console.print("[green]Tools enabled![/green]\n")
```

### Option 2: Always Enable (Default)

Make tools available by default:

```python
# In main()
client = PerplexityClientPromptTools(
    api_key=api_key,
    enable_tools=True
)
asyncio.run(client.initialize_tools())
```

## 🤔 Why Two Approaches?

We discovered that **Perplexity doesn't support OpenAI function calling** (yet).

So we provide:
1. **Prompt-based** - Works with Perplexity NOW ✅
2. **Native function calling** - For when Perplexity adds support (future)

See `TOOL_APPROACHES.md` for detailed comparison.

## 📖 Documentation

- **START HERE**: `TOOL_APPROACHES.md` - Which approach to use
- **DETAILED**: `TOOLS_README.md` - Complete architecture and examples
- **INTEGRATION**: `TOOL_INTEGRATION.md` - Step-by-step ppxai.py integration
- **CONCEPTS**: `INTEGRATION_SUMMARY.md` - How MCP + OpenAI work together

## 🔧 Troubleshooting

### "Tool calling is not supported"
✅ **Fixed!** Use `perplexity_tools_prompt_based.py` instead

### "MCP server won't start"
ℹ️ **Optional** - MCP servers are optional. Built-in tools work without MCP.

### "Model isn't using tools"
💡 **Tip**: Be explicit - "Use the search_files tool to..."

## ✨ Key Insight

**You don't need MCP servers** to get started!

The built-in Python tools work great:
- ✅ No Node.js required
- ✅ No external dependencies
- ✅ Simple to understand and modify
- ✅ Works with Perplexity right now

**MCP is optional** for advanced use cases (file systems, databases, web search, etc.)

## 🎮 Try It

```bash
# Basic demo (built-in tools only)
python demo_tools_working.py

# Example queries to try:
# - "Use the search_files tool to find all Python files"
# - "Use the calculator tool to compute 123 * 456"
# - "Use list_directory to show me what's here"
```

## Next Steps

1. ✅ Run `python demo_tools_working.py`
2. ✅ Add `/tools` command to ppxai.py (Option 1 above)
3. ✅ Test with real queries
4. 📝 Read `TOOL_APPROACHES.md` for deeper understanding
5. 🎨 Customize built-in tools for your needs

---

**Questions?** Check `TOOL_APPROACHES.md` for detailed comparison of both approaches!
