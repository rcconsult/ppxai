# Tool System Integration Guide

This guide explains how MCP (Model Context Protocol) and OpenAI Function Calling work together in ppxai.

## Architecture Overview

### How It Works

```
User Message → Perplexity API (with tools) → Model Response
                      ↓
              Tool calls needed?
                      ↓
              ┌─── Yes ────┐
              ↓             ↓
        MCP Tool      Built-in Tool
              ↓             ↓
         Execute → Return Result → Add to conversation → Loop back
```

### Key Components

1. **MCP (Model Context Protocol)**
   - **Purpose**: Standard protocol for discovering and executing tools
   - **Source**: External MCP servers (Node.js packages)
   - **Examples**: File operations, web search, git operations, databases
   - **Benefit**: Reusable tools from growing ecosystem

2. **OpenAI Function Calling**
   - **Purpose**: Format that LLMs understand for tool invocation
   - **Source**: API specification (works with Perplexity API)
   - **Benefit**: Model decides when/how to use tools intelligently

3. **Tool Manager** (`tool_manager.py`)
   - **Purpose**: Bridge between MCP and OpenAI formats
   - **Functions**:
     - Discovers tools from MCP servers
     - Registers built-in Python tools
     - Converts MCP format → OpenAI format
     - Routes tool execution to correct handler

## Setup Instructions

### 1. Install Dependencies

```bash
# Install MCP client library
pip install mcp

# MCP servers are typically Node.js packages (installed on-demand via npx)
# Make sure you have Node.js installed:
node --version  # Should be v16 or higher
```

### 2. Configure Tools

Copy the example config:
```bash
cp tools.config.json.example tools.config.json
```

Edit `tools.config.json`:
```json
{
  "enabled": true,
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

### 3. Integration into ppxai.py

Here's how to integrate the tool system into your main application:

#### Option A: Add as a new command (Recommended for testing)

```python
# In ppxai.py, add this import at the top
import asyncio
from perplexity_with_tools import PerplexityClientWithTools, load_tool_config

# In the main() function, add a new command:
elif command == "/tools":
    # Enable tool mode for current session
    if not isinstance(client, PerplexityClientWithTools):
        # Upgrade to tool-enabled client
        tool_client = PerplexityClientWithTools(
            api_key=api_key,
            session_name=client.session_name,
            enable_tools=True
        )
        # Copy conversation history
        tool_client.conversation_history = client.conversation_history

        # Initialize tools
        config = load_tool_config(Path.home() / ".ppxai" / "tools.config.json")
        if config.get("enabled"):
            asyncio.run(tool_client.initialize_tools(config.get("mcp_servers", [])))
            client = tool_client
            console.print("[green]Tool mode activated![/green]\n")
        else:
            console.print("[yellow]Tools are disabled in config[/yellow]\n")
    else:
        console.print("[yellow]Tools already enabled[/yellow]\n")
    continue

elif command == "/toollist":
    # List available tools
    if isinstance(client, PerplexityClientWithTools) and client.tool_manager:
        tools = client.tool_manager.list_tools()
        table = Table(title="Available Tools", show_header=True)
        table.add_column("Tool", style="cyan")
        table.add_column("Source", style="green")
        table.add_column("Description", style="white")

        for tool in tools:
            table.add_row(tool['name'], tool['source'], tool['description'])

        console.print(table)
    else:
        console.print("[yellow]Tools not enabled. Use /tools to enable.[/yellow]\n")
    continue
```

#### Option B: Make tools default (Advanced)

Modify the initialization in `main()`:

```python
def main():
    api_key = os.getenv("PERPLEXITY_API_KEY")

    # Load tool configuration
    tool_config_path = Path.home() / ".ppxai" / "tools.config.json"
    tool_config = load_tool_config(tool_config_path)

    # Initialize client with tools if enabled
    if tool_config.get("enabled", False):
        client = PerplexityClientWithTools(
            api_key=api_key,
            enable_tools=True
        )
        asyncio.run(client.initialize_tools(tool_config.get("mcp_servers", [])))
    else:
        client = PerplexityClient(api_key)

    # ... rest of main()
```

### 4. Update Message Handling

For tool-enabled clients, use async chat:

```python
# When sending a message with tools enabled:
if isinstance(client, PerplexityClientWithTools) and client.enable_tools:
    response = asyncio.run(client.chat_with_tools(user_input, current_model))
else:
    response = client.chat(user_input, current_model, stream=True)
```

## Usage Examples

### Example 1: File Operations

```
You: Can you search for all Python files and show me their sizes?

Assistant is using 1 tool(s)...
Calling tool: search_files({'pattern': '*.py', 'directory': '.'})
Tool result: ppxai.py
tool_manager.py
perplexity_with_tools.py
Assistant is using 1 tool(s)...
Calling tool: run_shell_command({'command': 'ls -lh *.py'})
Tool result: -rw-r--r--  1 user  staff  35K  ppxai.py
-rw-r--r--  1 user  staff  8.2K tool_manager.py
-rw-r--r--  1 user  staff  12K  perplexity_with_tools.py