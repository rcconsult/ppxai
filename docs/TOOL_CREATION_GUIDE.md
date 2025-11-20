# Tool Creation Guide

Step-by-step guide for adding custom tools to ppxai.

## Table of Contents

1. [Quick Decision](#quick-decision)
2. [Option 1: Built-in Python Tool](#option-1-built-in-python-tool-recommended)
3. [Option 2: MCP Server Tool](#option-2-mcp-server-tool-advanced)
4. [Testing Your Tool](#testing-your-tool)
5. [Troubleshooting](#troubleshooting)

---

## Quick Decision

**Choose Built-in Python Tool if:**
- ✅ You can write it in Python in <100 lines
- ✅ You want simplicity and fast execution
- ✅ It's specific to your use case

**Choose MCP Server if:**
- ✅ A community MCP server already exists for your need
- ✅ You want to share the tool across multiple apps
- ✅ You need Node.js-specific functionality

**90% of use cases → Built-in Python Tool**

---

## Option 1: Built-in Python Tool (Recommended)

### Time Required: 10-15 minutes

### Step 1: Create Your Tool File

Create `my_tools.py` in the ppxai directory:

```python
"""
My Custom Tools for ppxai
"""

def my_tool_function(param1: str, param2: int = 10) -> str:
    """
    Brief description of what this tool does.

    Args:
        param1: Description of first parameter
        param2: Description of second parameter (default: 10)

    Returns:
        String description of the result
    """
    try:
        # Your tool logic here
        result = f"Processed {param1} with value {param2}"
        return result

    except Exception as e:
        # Always handle errors gracefully
        return f"Error: {str(e)}"
```

**Example: Weather API Tool**

```python
def get_weather(city: str, units: str = "metric") -> str:
    """
    Get current weather for a city.

    Args:
        city: City name (e.g., "San Francisco")
        units: Temperature units (metric/imperial)

    Returns:
        Weather information string
    """
    import requests
    import os

    try:
        api_key = os.getenv("WEATHER_API_KEY")
        if not api_key:
            return "Error: WEATHER_API_KEY not set in environment"

        url = f"http://api.openweathermap.org/data/2.5/weather"
        params = {
            "q": city,
            "appid": api_key,
            "units": units
        }

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()
        temp = data['main']['temp']
        desc = data['weather'][0]['description']

        return f"Weather in {city}: {temp}°{'C' if units=='metric' else 'F'}, {desc}"

    except requests.exceptions.RequestException as e:
        return f"API error: {str(e)}"
    except KeyError as e:
        return f"Unexpected API response format: {str(e)}"
    except Exception as e:
        return f"Error getting weather: {str(e)}"
```

### Step 2: Register Your Tool

Edit `perplexity_tools_prompt_based.py`, find the `_register_builtin_tools` method (around line 50), and add:

```python
def _register_builtin_tools(self):
    """Register built-in tools."""
    import os
    import subprocess
    from pathlib import Path
    import glob

    # ... existing tools ...

    # ========== ADD YOUR TOOLS HERE ==========

    # Import your tool functions
    from my_tools import my_tool_function, get_weather

    # Register your first tool
    self.tool_manager.register_builtin_tool(
        name="my_tool",  # Name the AI will use
        description="Brief description of what this tool does",
        parameters={
            "type": "object",
            "properties": {
                "param1": {
                    "type": "string",
                    "description": "What param1 is for"
                },
                "param2": {
                    "type": "integer",
                    "description": "What param2 is for (optional, default: 10)"
                }
            },
            "required": ["param1"]  # Only param1 is required
        },
        handler=my_tool_function
    )

    # Register weather tool
    self.tool_manager.register_builtin_tool(
        name="get_weather",
        description="Get current weather information for any city",
        parameters={
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "City name (e.g., 'San Francisco', 'London')"
                },
                "units": {
                    "type": "string",
                    "description": "Temperature units: 'metric' (Celsius) or 'imperial' (Fahrenheit)",
                    "enum": ["metric", "imperial"]
                }
            },
            "required": ["city"]
        },
        handler=get_weather
    )
```

### Step 3: Test Your Tool

Create a test file `test_my_tool.py`:

```python
#!/usr/bin/env python3
import asyncio
import os
from dotenv import load_dotenv
from perplexity_tools_prompt_based import PerplexityClientPromptTools

async def test():
    load_dotenv()

    client = PerplexityClientPromptTools(
        api_key=os.getenv('PERPLEXITY_API_KEY'),
        enable_tools=True
    )

    await client.initialize_tools()

    # Test your tool
    await client.chat_with_tools(
        "Use the get_weather tool to check the weather in San Francisco",
        model='sonar-pro'
    )

    await client.cleanup()

asyncio.run(test())
```

Run it:
```bash
python test_my_tool.py
```

### Step 4: Use in ppxai

After integration (see next section), you can use it:

```
You: What's the weather in London?
AI: I'll check the weather for you.
[Uses get_weather tool]
AI: Weather in London: 12°C, partly cloudy
```

### Built-in Tool Checklist

- [ ] Function has clear docstring
- [ ] Parameters have type hints
- [ ] Errors are handled with try/except
- [ ] Returns string (or can be converted to string)
- [ ] Tested independently before registering
- [ ] Registered with clear description
- [ ] Required parameters marked in schema

---

## Option 2: MCP Server Tool (Advanced)

### Time Required: 1-2 hours

### When to Use

- Using existing MCP servers (GitHub, Slack, etc.)
- Building reusable tool for multiple apps
- Need Node.js functionality

### Step 1: Check for Existing MCP Servers

Browse: https://github.com/modelcontextprotocol/servers

Popular servers:
- `@modelcontextprotocol/server-github` - GitHub API
- `@modelcontextprotocol/server-slack` - Slack
- `@modelcontextprotocol/server-sqlite` - SQLite
- `@modelcontextprotocol/server-postgres` - PostgreSQL
- `@modelcontextprotocol/server-brave-search` - Web search

### Step 2A: Using Existing MCP Server

If a server exists, configure it in `~/.ppxai/tools.config.json`:

```json
{
  "enabled": true,
  "mcp_servers": [
    {
      "name": "github",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_TOKEN": "${GITHUB_TOKEN}"
      }
    }
  ]
}
```

Add to your `.env`:
```bash
GITHUB_TOKEN=ghp_your_token_here
```

That's it! The tools from that server will be available.

### Step 2B: Building Your Own MCP Server

Only if no existing server meets your needs.

**Prerequisites:**
```bash
node --version  # Need v16+
npm install -g @modelcontextprotocol/create-server
```

**Create Server:**

```bash
cd demo/
npx @modelcontextprotocol/create-server my-mcp-server
cd my-mcp-server
```

**Edit `src/index.ts`:**

```typescript
#!/usr/bin/env node
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

const server = new Server(
  {
    name: "my-mcp-server",
    version: "1.0.0",
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

// List available tools
server.setRequestHandler("tools/list", async () => {
  return {
    tools: [
      {
        name: "my_mcp_tool",
        description: "Does something useful",
        inputSchema: {
          type: "object",
          properties: {
            param1: {
              type: "string",
              description: "Description of param1",
            },
          },
          required: ["param1"],
        },
      },
    ],
  };
});

// Handle tool calls
server.setRequestHandler("tools/call", async (request) => {
  const { name, arguments: args } = request.params;

  if (name === "my_mcp_tool") {
    // Your tool logic here
    const result = `Processed: ${args.param1}`;

    return {
      content: [
        {
          type: "text",
          text: result,
        },
      ],
    };
  }

  throw new Error(`Unknown tool: ${name}`);
});

// Start server
const transport = new StdioServerTransport();
await server.connect(transport);
```

**Build:**
```bash
npm run build
```

**Configure in tools.config.json:**
```json
{
  "mcp_servers": [
    {
      "name": "my-server",
      "command": "node",
      "args": ["/full/path/to/my-mcp-server/build/index.js"]
    }
  ]
}
```

### Step 3: Test MCP Server

```bash
# Test if server starts
node build/index.js

# Test with ppxai
python tests/test_mcp.py
```

### MCP Server Checklist

- [ ] Node.js v16+ installed
- [ ] Server builds without errors
- [ ] Server starts manually
- [ ] Configured in tools.config.json
- [ ] Environment variables set
- [ ] Tested with test_mcp.py

---

## Testing Your Tool

### Quick Test

```bash
# Test all tools
python tests/test_all_tools.py

# Test specific tool
python -c "
import asyncio
from my_tools import my_tool_function

result = my_tool_function('test', 42)
print(result)
"
```

### Integration Test

After integrating into ppxai:

```bash
./ppxai.py
/tools enable
You: [Ask AI to use your tool]
```

### Test Checklist

- [ ] Tool function works independently
- [ ] Tool appears in tool list
- [ ] AI can call the tool successfully
- [ ] Tool returns useful results
- [ ] Errors are handled gracefully
- [ ] Tool description is clear for AI

---

## Troubleshooting

### Built-in Tool Issues

**Problem: Tool not appearing**
```bash
# Check if tool is registered
python -c "
from perplexity_tools_prompt_based import PerplexityClientPromptTools
import asyncio

async def check():
    client = PerplexityClientPromptTools('fake', enable_tools=True)
    await client.initialize_tools()
    for tool in client.tool_manager.list_tools():
        print(tool['name'])

asyncio.run(check())
"
```

**Problem: Tool errors when called**
- Test function independently first
- Check all parameters are provided
- Add more error handling
- Check return type is string

**Problem: AI doesn't use the tool**
- Make description more specific
- Explicitly tell AI to use the tool
- Check parameter descriptions are clear

### MCP Server Issues

**Problem: Server won't start**
```bash
# Check Node.js version
node --version  # Need v16+

# Test server directly
node path/to/server/index.js

# Check logs
python tests/test_mcp.py
```

**Problem: Connection timeout**
- Check network connection
- Try pre-installing: `npx -y @modelcontextprotocol/server-name`
- Increase timeout in tool_manager.py

**Problem: MCP async errors on exit**
- This is a known issue with MCP library
- Doesn't affect functionality
- Can be ignored

---

## Best Practices

### For Built-in Tools

1. **Keep it simple** - One tool, one purpose
2. **Handle errors** - Always use try/except
3. **Clear descriptions** - AI needs to understand what it does
4. **Type hints** - Help with debugging
5. **Test independently** - Before registering
6. **Return strings** - Simplest for AI to process

### For MCP Servers

1. **Use existing servers** - Don't reinvent the wheel
2. **Document well** - Others might use your server
3. **Version properly** - Follow semver
4. **Handle errors** - Return error in content
5. **Test thoroughly** - Cross-process bugs are hard to debug

### Security

1. **Validate inputs** - Don't trust parameters blindly
2. **Use environment variables** - Never hardcode secrets
3. **Limit scope** - Tools should do one thing well
4. **Timeout operations** - Don't let tools hang
5. **Sanitize outputs** - Be careful with user data

---

## Examples

See:
- `demo/example_builtin_tool.py` - Complete built-in tool example
- `demo/example_mcp_server/` - Complete MCP server example
- `tests/test_all_tools.py` - Testing examples

---

## Quick Reference

### Built-in Tool Template

```python
def tool_name(param: str) -> str:
    """One-line description."""
    try:
        # Logic here
        return result
    except Exception as e:
        return f"Error: {e}"

# Register in perplexity_tools_prompt_based.py:
self.tool_manager.register_builtin_tool(
    name="tool_name",
    description="Description for AI",
    parameters={
        "type": "object",
        "properties": {
            "param": {"type": "string", "description": "Param description"}
        },
        "required": ["param"]
    },
    handler=tool_name
)
```

### Parameter Types

```python
"properties": {
    "string_param": {"type": "string"},
    "number_param": {"type": "number"},
    "integer_param": {"type": "integer"},
    "boolean_param": {"type": "boolean"},
    "enum_param": {"type": "string", "enum": ["opt1", "opt2"]},
    "array_param": {"type": "array", "items": {"type": "string"}}
}
```

---

## Getting Help

- **Examples**: Check `demo/` directory
- **Tests**: See `tests/` directory  
- **Issues**: Report at GitHub issues
- **Community**: MCP Discord server

---

**Ready to create your first tool?** Start with Option 1 (Built-in) - you can always add MCP servers later!
