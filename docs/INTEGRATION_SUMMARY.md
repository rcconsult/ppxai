# How MCP + OpenAI Function Calling Work Together

## Quick Summary

**MCP (Option 1)** + **OpenAI Function Calling (Option 2)** = Complete Tool System

```
┌──────────────────────────────────────────────────────────┐
│                  Integration Flow                         │
└──────────────────────────────────────────────────────────┘

1. MCP Servers provide tools
   ├─ @modelcontextprotocol/server-filesystem (file ops)
   ├─ @modelcontextprotocol/server-brave-search (web search)
   ├─ @modelcontextprotocol/server-git (git operations)
   └─ Custom user-provided MCP servers

2. Tool Manager discovers and converts
   ├─ MCP tool format → OpenAI function format
   ├─ Registers built-in Python tools
   └─ Creates unified tool registry

3. Perplexity API receives OpenAI format
   ├─ Tools passed as `tools` parameter
   ├─ Model decides which tools to call
   └─ Returns tool_calls in response

4. Execution routed back through MCP
   ├─ MCP tools → Execute via MCP server
   ├─ Built-in tools → Execute Python function
   └─ Results added to conversation

5. Loop continues until model responds without tools
```

## Why This Combination?

### MCP Provides:
- **Discovery**: Find tools from multiple sources
- **Standardization**: Common protocol for tool definitions
- **Ecosystem**: Reuse existing MCP servers
- **Extensibility**: Easy to add new tool sources
- **Isolation**: Tools run in separate processes

### OpenAI Function Calling Provides:
- **Intelligence**: Model decides when/how to use tools
- **Natural flow**: Tools integrated into conversation
- **API compatibility**: Works with Perplexity's OpenAI-compatible API
- **Structured params**: JSON schema for tool parameters
- **Multi-step**: Chain multiple tool calls together

## Integration Points

### 1. Tool Discovery (MCP → Unified Format)

```python
# MCP provides tools in its format
mcp_tool = {
    "name": "read_file",
    "description": "Read contents of a file",
    "inputSchema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"}
        }
    }
}

# Tool Manager converts to unified format
tool_def = ToolDefinition(
    name="read_file",
    description="Read contents of a file",
    parameters={...},  # Same as inputSchema
    source='mcp',
    mcp_server='filesystem'
)
```

### 2. API Call (Unified → OpenAI Format)

```python
# Tool Manager converts to OpenAI format
openai_tools = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read contents of a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"}
                }
            }
        }
    }
]

# Sent to Perplexity API
response = client.chat.completions.create(
    model="sonar-pro",
    messages=[...],
    tools=openai_tools,
    tool_choice="auto"
)
```

### 3. Execution (OpenAI Response → MCP/Built-in)

```python
# Model responds with tool call
tool_call = response.choices[0].message.tool_calls[0]
# {
#     "id": "call_abc123",
#     "type": "function",
#     "function": {
#         "name": "read_file",
#         "arguments": '{"path": "config.json"}'
#     }
# }

# Route to appropriate handler
if tool_def.source == 'mcp':
    result = await mcp_session.call_tool(name, args)
elif tool_def.source == 'builtin':
    result = await builtin_handler(**args)
```

## Benefits of Integration

1. **Best of Both Worlds**
   - MCP's tool ecosystem + Model's intelligence

2. **Flexibility**
   - MCP tools: Node.js servers (community ecosystem)
   - Built-in tools: Python functions (custom logic)
   - API tools: OpenAI format (model compatibility)

3. **Separation of Concerns**
   - MCP: Tool definition & execution
   - OpenAI: Model intelligence & decision-making
   - Tool Manager: Bridge between them

4. **Scalability**
   - Add new MCP servers without code changes
   - Add built-in tools with Python functions
   - Model automatically learns new tools

## Example Flow

```
User: "Read the README.md file and count the lines"

1. Message sent to Perplexity with tools list

2. Model response:
   tool_calls: [
     {name: "read_file", args: {"filepath": "README.md"}}
   ]

3. Tool Manager routes to MCP filesystem server

4. MCP executes: read_file("README.md")
   Returns: "# Project\n\nDescription..."

5. Result added to conversation

6. Model called again with result

7. Model response:
   tool_calls: [
     {name: "calculator", args: {"expression": "50"}}
   ]

8. Tool Manager routes to built-in Python function

9. Built-in executes: calculate("50")
   Returns: "50"

10. Result added to conversation

11. Model called again

12. Model final response:
    content: "The README.md file has 50 lines."

13. User sees final answer
```

## Adding User Tools

### Option 1: Create MCP Server (Node.js)

```javascript
// my-tool-server/index.js
import { Server } from "@modelcontextprotocol/sdk/server/index.js";

const server = new Server({
  name: "my-tools",
  version: "1.0.0"
});

server.setRequestHandler("tools/list", async () => ({
  tools: [
    {
      name: "my_custom_tool",
      description: "Does something custom",
      inputSchema: {
        type: "object",
        properties: {
          param: { type: "string" }
        }
      }
    }
  ]
}));

server.setRequestHandler("tools/call", async (request) => {
  if (request.params.name === "my_custom_tool") {
    // Execute tool logic
    return {
      content: [{ type: "text", text: "Result" }]
    };
  }
});
```

Add to `tools.config.json`:
```json
{
  "mcp_servers": [
    {
      "name": "my-tools",
      "command": "node",
      "args": ["./my-tool-server/index.js"]
    }
  ]
}
```

### Option 2: Create Built-in Tool (Python)

```python
# In perplexity_with_tools.py, add to _register_builtin_tools():

def my_custom_tool(param: str) -> str:
    """My custom tool logic."""
    # Your implementation
    return f"Processed: {param}"

self.tool_manager.register_builtin_tool(
    name="my_custom_tool",
    description="Does something custom",
    parameters={
        "type": "object",
        "properties": {
            "param": {
                "type": "string",
                "description": "Input parameter"
            }
        },
        "required": ["param"]
    },
    handler=my_custom_tool
)
```

## Available MCP Servers

From https://github.com/modelcontextprotocol/servers:

- **@modelcontextprotocol/server-filesystem** - File operations
- **@modelcontextprotocol/server-brave-search** - Web search
- **@modelcontextprotocol/server-git** - Git operations
- **@modelcontextprotocol/server-sqlite** - Database queries
- **@modelcontextprotocol/server-github** - GitHub API
- **@modelcontextprotocol/server-google-maps** - Maps API
- **@modelcontextprotocol/server-slack** - Slack integration
- **@modelcontextprotocol/server-puppeteer** - Web automation

## Security Considerations

1. **MCP Servers**
   - Run in separate processes (isolation)
   - Can restrict filesystem access
   - Review server code before use

2. **Built-in Tools**
   - `run_shell_command` disabled by default
   - Input validation required
   - Avoid executing arbitrary code

3. **Tool Configuration**
   - Keep sensitive configs in `.gitignore`
   - Use environment variables for API keys
   - Audit tool permissions

## Troubleshooting

### Tools not working?

1. Check MCP installation: `pip list | grep mcp`
2. Check Node.js: `node --version` (need v16+)
3. Enable debug logging in tool_manager.py
4. Check tool config: `cat ~/.ppxai/tools.config.json`

### Model not calling tools?

1. Check model support (some models don't support function calling)
2. Verify `tool_choice="auto"` is set
3. Make tool descriptions clear and specific
4. Check parameter schemas are valid JSON Schema

### MCP server fails?

1. Test server directly: `npx @modelcontextprotocol/server-filesystem .`
2. Check server logs
3. Verify command and args in config
4. Ensure environment variables are set

## Next Steps

1. **Try the examples**: Run `python perplexity_with_tools.py`
2. **Add to ppxai**: Follow integration guide
3. **Test with simple tools**: Start with built-in tools
4. **Add MCP servers**: Try filesystem server first
5. **Create custom tools**: Build your own MCP server or built-in tool

## Resources

- **MCP Docs**: https://modelcontextprotocol.io
- **MCP Servers**: https://github.com/modelcontextprotocol/servers
- **OpenAI Function Calling**: https://platform.openai.com/docs/guides/function-calling
- **Perplexity API**: https://docs.perplexity.ai
