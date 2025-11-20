# Example MCP Server

This is an example MCP (Model Context Protocol) server that provides text manipulation tools.

## What It Does

Provides 4 tools for text manipulation:
- `reverse_text` - Reverse characters in text
- `count_words` - Count words, characters, and lines
- `to_uppercase` - Convert to uppercase
- `to_lowercase` - Convert to lowercase

## Setup

1. **Install dependencies:**
   ```bash
   cd demo/example_mcp_server
   npm install
   ```

2. **Test the server:**
   ```bash
   node index.js
   ```
   (Server will wait for input - press Ctrl+C to exit)

## Usage with ppxai

### Option 1: Configure in tools.config.json

Create or edit `~/.ppxai/tools.config.json`:

```json
{
  "enabled": true,
  "mcp_servers": [
    {
      "name": "example-text-tools",
      "command": "node",
      "args": ["/full/path/to/ppxai/demo/example_mcp_server/index.js"]
    }
  ]
}
```

Replace `/full/path/to/ppxai` with the actual path to your ppxai directory.

### Option 2: Run directly (for testing)

```python
import asyncio
from perplexity_tools_prompt_based import PerplexityClientPromptTools

async def test():
    client = PerplexityClientPromptTools(
        api_key="your_key",
        enable_tools=True
    )

    # Initialize with this MCP server
    await client.initialize_tools(mcp_servers=[
        {
            "name": "example",
            "command": "node",
            "args": ["/full/path/to/demo/example_mcp_server/index.js"]
        }
    ])

    # Use the tools
    await client.chat_with_tools(
        "Use the reverse_text tool to reverse 'Hello World'",
        model="sonar-pro"
    )

asyncio.run(test())
```

## Modifying the Server

To add your own tools:

1. **Add tool definition** in `tools/list` handler:
   ```javascript
   {
     name: "my_tool",
     description: "What it does",
     inputSchema: {
       type: "object",
       properties: {
         param: {
           type: "string",
           description: "Parameter description"
         }
       },
       required: ["param"]
     }
   }
   ```

2. **Add tool handler** in `tools/call` handler:
   ```javascript
   case "my_tool":
     result = `Processed: ${args.param}`;
     break;
   ```

3. **Test:**
   ```bash
   node index.js
   ```

## File Structure

```
example_mcp_server/
├── index.js       # Main server code
├── package.json   # Node.js dependencies
└── README.md      # This file
```

## Troubleshooting

### "Cannot find module"
```bash
npm install
```

### "Permission denied"
```bash
chmod +x index.js
```

### Server won't start
Check Node.js version:
```bash
node --version  # Need v16 or higher
```

### Testing without ppxai

You can test the server manually using `@modelcontextprotocol/inspector`:

```bash
npx @modelcontextprotocol/inspector node index.js
```

This will open a web interface where you can test the tools interactively.

## Learn More

- [MCP Documentation](https://modelcontextprotocol.io)
- [MCP SDK](https://github.com/modelcontextprotocol/sdk)
- [More MCP Servers](https://github.com/modelcontextprotocol/servers)
