# ppxai Tool System

> Integrating MCP (Model Context Protocol) with OpenAI Function Calling

## Overview

This tool system combines two powerful standards to give your ppxai CLI access to external tools:

- **MCP** - Protocol for tool discovery and execution
- **OpenAI Function Calling** - LLM-native tool invocation format

## Quick Start

```bash
# 1. Install MCP client
pip install mcp

# 2. Configure tools (optional)
cp tools.config.json.example ~/.ppxai/tools.config.json

# 3. Run the demo
python demo_tools.py
```

## Files Created

### Core Implementation
- **`tool_manager.py`** - Bridge between MCP and OpenAI formats
- **`perplexity_with_tools.py`** - Enhanced Perplexity client with tool support

### Configuration
- **`tools.config.json.example`** - Example configuration for MCP servers and built-in tools
- **`~/.ppxai/tools.config.json`** - Your actual configuration (create from example)

### Documentation
- **`INTEGRATION_SUMMARY.md`** - Complete guide on how MCP and OpenAI Function Calling work together
- **`TOOL_INTEGRATION.md`** - Step-by-step integration instructions for ppxai.py
- **`TOOLS_README.md`** - This file

### Demo
- **`demo_tools.py`** - Interactive demonstration of the tool system

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         ppxai Application                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  User Input: "Search for Python files and count them"         │
│                                                                 │
│  ┌───────────────────────────────────────────────────────┐    │
│  │         PerplexityClientWithTools                     │    │
│  │  ┌─────────────────────────────────────────────┐     │    │
│  │  │          Tool Manager                        │     │    │
│  │  │                                              │     │    │
│  │  │  ┌─────────────┐      ┌──────────────┐     │     │    │
│  │  │  │ MCP Client  │      │ Built-in     │     │    │    │
│  │  │  │             │      │ Tool         │     │    │    │
│  │  │  │ Discovers:  │      │ Registry     │     │    │    │
│  │  │  │  • Files    │      │              │     │    │    │
│  │  │  │  • Git      │      │ Functions:   │     │    │    │
│  │  │  │  • Web      │      │  • search    │     │    │    │
│  │  │  │  • DB       │      │  • calc      │     │    │    │
│  │  │  └─────────────┘      │  • read      │     │    │    │
│  │  │         ↓             └──────────────┘     │    │    │
│  │  │         └────────────┬─────────┘           │    │    │
│  │  │                      ↓                      │    │    │
│  │  │         ┌─────────────────────────┐        │    │    │
│  │  │         │  Unified Tool Catalog   │        │    │    │
│  │  │         │  (Internal Format)       │        │    │    │
│  │  │         └─────────────────────────┘        │    │    │
│  │  │                      ↓                      │    │    │
│  │  │         ┌─────────────────────────┐        │    │    │
│  │  │         │ Convert to OpenAI Format │        │    │    │
│  │  │         │ (Function Definitions)   │        │    │    │
│  │  │         └─────────────────────────┘        │    │    │
│  │  └─────────────────────────────────────────────┘    │    │
│  └───────────────────────────────────────────────────────┘    │
│                           ↓                                   │
│  ┌───────────────────────────────────────────────────────┐   │
│  │         Perplexity API Call                          │   │
│  │                                                       │   │
│  │  POST https://api.perplexity.ai/chat/completions     │   │
│  │  {                                                    │   │
│  │    "model": "sonar-pro",                             │   │
│  │    "messages": [...],                                │   │
│  │    "tools": [                                        │   │
│  │      {                                               │   │
│  │        "type": "function",                           │   │
│  │        "function": {                                 │   │
│  │          "name": "search_files",                     │   │
│  │          "description": "...",                       │   │
│  │          "parameters": {...}                         │   │
│  │        }                                             │   │
│  │      }                                               │   │
│  │    ]                                                 │   │
│  │  }                                                   │   │
│  └───────────────────────────────────────────────────────┘   │
│                           ↓                                   │
│  ┌───────────────────────────────────────────────────────┐   │
│  │         Model Response                               │   │
│  │                                                       │   │
│  │  {                                                    │   │
│  │    "choices": [{                                     │   │
│  │      "message": {                                    │   │
│  │        "tool_calls": [{                              │   │
│  │          "id": "call_123",                           │   │
│  │          "function": {                               │   │
│  │            "name": "search_files",                   │   │
│  │            "arguments": "{\"pattern\": \"*.py\"}"    │   │
│  │          }                                           │   │
│  │        }]                                            │   │
│  │      }                                               │   │
│  │    }]                                                │   │
│  │  }                                                   │   │
│  └───────────────────────────────────────────────────────┘   │
│                           ↓                                   │
│  ┌───────────────────────────────────────────────────────┐   │
│  │         Tool Execution Router                        │   │
│  │                                                       │   │
│  │  Tool: search_files                                  │   │
│  │  Source: builtin                                     │   │
│  │           ↓                                          │   │
│  │  Execute: Python function                            │   │
│  │  Result: ["file1.py", "file2.py"]                    │   │
│  └───────────────────────────────────────────────────────┘   │
│                           ↓                                   │
│  ┌───────────────────────────────────────────────────────┐   │
│  │    Add Result to Conversation & Loop                 │   │
│  │                                                       │   │
│  │  {                                                    │   │
│  │    "role": "tool",                                   │   │
│  │    "tool_call_id": "call_123",                       │   │
│  │    "content": "file1.py\nfile2.py"                   │   │
│  │  }                                                   │   │
│  │                                                       │   │
│  │  → Call API again with tool result                   │   │
│  │  → Model sees result and responds:                   │   │
│  │    "I found 2 Python files"                          │   │
│  └───────────────────────────────────────────────────────┘   │
│                           ↓                                   │
│  Display to User: "I found 2 Python files"                   │
│                                                               │
└─────────────────────────────────────────────────────────────────┘
```

## How It Works

### 1. Tool Discovery

**MCP servers** expose available tools:
```javascript
// MCP filesystem server provides:
{
  "tools": [
    {
      "name": "read_file",
      "description": "Read a file",
      "inputSchema": {...}
    },
    {
      "name": "write_file",
      "description": "Write to a file",
      "inputSchema": {...}
    }
  ]
}
```

**Built-in tools** are registered in Python:
```python
tool_manager.register_builtin_tool(
    name="calculator",
    description="Evaluate math expressions",
    parameters={...},
    handler=calculate_function
)
```

### 2. Format Conversion

Tool Manager converts both sources to OpenAI format:

```python
# Input: MCP tool or built-in tool
# Output: OpenAI function definition
{
    "type": "function",
    "function": {
        "name": "tool_name",
        "description": "What it does",
        "parameters": {
            "type": "object",
            "properties": {...},
            "required": [...]
        }
    }
}
```

### 3. API Integration

Tools sent to Perplexity API:
```python
response = client.chat.completions.create(
    model="sonar-pro",
    messages=conversation_history,
    tools=openai_format_tools,  # ← Our converted tools
    tool_choice="auto"          # ← Model decides
)
```

### 4. Intelligent Execution

Model analyzes the request and decides:
- Which tools to use (if any)
- What parameters to pass
- When to call multiple tools
- When to stop and respond to user

### 5. Result Integration

Tool results flow back into conversation:
```python
# Model calls: search_files(pattern="*.py")
# We execute and return: ["file1.py", "file2.py"]
# Model sees the result and continues...
```

## Available Tools

### Built-in Tools (Python)

Always available, no external dependencies:

- **`search_files`** - Find files by glob pattern
- **`read_file`** - Read file contents
- **`calculator`** - Evaluate mathematical expressions
- **`run_shell_command`** - Execute shell commands (disabled by default for security)

### MCP Server Tools (Node.js)

Require MCP servers configured in `tools.config.json`:

- **Filesystem** - `@modelcontextprotocol/server-filesystem`
  - read_file, write_file, list_directory, etc.

- **Git** - `@modelcontextprotocol/server-git`
  - git_status, git_diff, git_log, etc.

- **Brave Search** - `@modelcontextprotocol/server-brave-search`
  - web_search (requires BRAVE_API_KEY)

- **SQLite** - `@modelcontextprotocol/server-sqlite`
  - query, schema, tables, etc.

- **GitHub** - `@modelcontextprotocol/server-github`
  - create_issue, list_prs, etc. (requires GITHUB_TOKEN)

See full list: https://github.com/modelcontextprotocol/servers

## Example Usage

```python
from perplexity_with_tools import PerplexityClientWithTools

# Create client
client = PerplexityClientWithTools(
    api_key=api_key,
    enable_tools=True
)

# Configure MCP servers
await client.initialize_tools(mcp_servers=[
    {
        "name": "filesystem",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "."]
    }
])

# Chat with tools
await client.chat_with_tools(
    "Find all Python files and show me the biggest one",
    model="sonar-pro"
)

# Model will:
# 1. Call search_files to find Python files
# 2. Call read_file or shell command to check sizes
# 3. Respond with the answer
```

## Configuration

### Basic Config (`~/.ppxai/tools.config.json`)

```json
{
  "enabled": true,
  "max_tool_iterations": 5,
  "mcp_servers": [
    {
      "name": "filesystem",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "."]
    }
  ],
  "builtin_tools": {
    "search_files": true,
    "read_file": true,
    "calculator": true,
    "run_shell_command": false
  }
}
```

### Advanced Config

```json
{
  "enabled": true,
  "max_tool_iterations": 10,
  "mcp_servers": [
    {
      "name": "filesystem",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/workspace"]
    },
    {
      "name": "git",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-git", "."]
    },
    {
      "name": "brave",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-brave-search"],
      "env": {
        "BRAVE_API_KEY": "${BRAVE_API_KEY}"
      }
    }
  ],
  "builtin_tools": {
    "search_files": true,
    "read_file": true,
    "calculator": true,
    "run_shell_command": true
  }
}
```

## Security

⚠️ **Important Security Considerations**:

1. **Shell Commands**: Disabled by default. Only enable if you trust the model.

2. **Filesystem Access**: MCP filesystem server can access any path you specify. Limit scope:
   ```json
   "args": ["-y", "@modelcontextprotocol/server-filesystem", "/safe/directory"]
   ```

3. **API Keys**: Store in environment variables, not in config:
   ```json
   "env": {
     "API_KEY": "${API_KEY}"  // Reads from environment
   }
   ```

4. **Review Tools**: Check what each MCP server can do before enabling it.

## Integration into ppxai.py

See `TOOL_INTEGRATION.md` for complete integration steps. Quick summary:

```python
# Option 1: Add /tools command to enable on-demand
elif command == "/tools":
    # Upgrade client to tool-enabled version
    # Initialize tools
    # Continue session with tools

# Option 2: Enable by default if configured
client = PerplexityClientWithTools(api_key, enable_tools=True)
await client.initialize_tools(mcp_servers=config['mcp_servers'])
```

## Troubleshooting

### "MCP not installed"
```bash
pip install mcp
```

### "Node.js required for MCP servers"
```bash
# Install Node.js v16+
brew install node  # macOS
```

### "Tool not being called"
- Make tool description clear and specific
- Check model supports function calling (sonar-pro works well)
- Try asking explicitly: "use the search_files tool"

### "MCP server won't start"
- Test server directly: `npx @modelcontextprotocol/server-filesystem .`
- Check Node.js version: `node --version`
- Review server logs in terminal

## Next Steps

1. **📖 Read**: `INTEGRATION_SUMMARY.md` for detailed concepts
2. **🎮 Demo**: Run `python demo_tools.py` to see it in action
3. **🔧 Configure**: Copy and edit `tools.config.json`
4. **🚀 Integrate**: Follow `TOOL_INTEGRATION.md` to add to ppxai
5. **🛠️ Build**: Create your own MCP server or built-in tool

## Resources

- **MCP Specification**: https://modelcontextprotocol.io
- **MCP Servers**: https://github.com/modelcontextprotocol/servers
- **OpenAI Function Calling**: https://platform.openai.com/docs/guides/function-calling
- **Perplexity API Docs**: https://docs.perplexity.ai

---

**Questions?** Check the integration guides or open an issue!
