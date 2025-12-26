# User-Defined Tools Guide

A practical guide for adding your own tools to ppxai.

## 🤔 Which Approach Should I Use?

Use this decision tree:

```
Do you need this tool?
         │
         ├─→ Is it a simple Python function? ──→ YES ──→ Built-in Tool ✅
         │                                                 (See Option 1)
         │
         ├─→ Does a community MCP server exist? ─→ YES ─→ MCP Server ✅
         │   (GitHub, Slack, database, etc.)              (See Option 2)
         │
         ├─→ Do you want to share with other apps? → YES → MCP Server ✅
         │                                                  (See Option 2)
         │
         └─→ Is it complex/stateful? ─────────────→ YES ─→ Built-in Tool ✅
                                                            (Easier to debug)
```

## 📊 Quick Comparison

| Criteria | Built-in Python Tool | MCP Server |
|----------|---------------------|------------|
| **Complexity** | Simple | Complex |
| **Setup Time** | < 5 minutes | 15-30 minutes |
| **Dependencies** | None (just Python) | Node.js required |
| **Debugging** | Easy (native Python) | Harder (cross-process) |
| **Reusability** | ppxai only | Any MCP client |
| **Community Tools** | Build yourself | Use existing servers |
| **Performance** | Fast (same process) | Slower (IPC overhead) |
| **Best For** | Custom logic | Standard integrations |

## 🎯 When to Use Each

### Use Built-in Python Tools When:

✅ **Simple operations**
- File operations specific to your workflow
- Custom calculations or data processing
- API calls to your internal services
- Database queries for your specific DB
- System commands you use frequently

✅ **You value simplicity**
- Quick to implement
- Easy to debug
- No external dependencies
- Fast execution

✅ **Custom business logic**
- Specific to your use case
- Requires Python libraries you already use
- Needs access to local resources

### Use MCP Servers When:

✅ **Standard integrations exist**
- GitHub API (use `@modelcontextprotocol/server-github`)
- Slack (use `@modelcontextprotocol/server-slack`)
- Google Calendar, Gmail, etc.
- Databases (PostgreSQL, SQLite)
- Web search (Brave, DuckDuckGo)

✅ **Tool reusability**
- Want to use same tools in multiple apps
- Building tools for others to use
- Contributing to MCP ecosystem

✅ **Isolation requirements**
- Tool needs separate process
- Want crash isolation
- Need specific Node.js libraries

## 🛠️ Option 1: Built-in Python Tools (Recommended for Most Cases)

### Step 1: Define Your Tool

What do you want to do? Examples:
- Read your company's API
- Query a specific database
- Process files in a certain way
- Run custom scripts
- Call internal services

### Step 2: Write the Function

Create `my_custom_tools.py`:

```python
"""
My Custom Tools for ppxai
"""

def my_api_tool(endpoint: str, method: str = "GET") -> str:
    """
    Call my company's API.

    Args:
        endpoint: API endpoint path (e.g., "/users")
        method: HTTP method (GET, POST, etc.)

    Returns:
        API response as JSON string
    """
    import requests
    import os

    base_url = os.getenv("MY_API_URL", "https://api.mycompany.com")
    api_key = os.getenv("MY_API_KEY")

    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        if method == "GET":
            response = requests.get(f"{base_url}{endpoint}", headers=headers)
        elif method == "POST":
            response = requests.post(f"{base_url}{endpoint}", headers=headers)

        response.raise_for_status()
        return response.json()

    except Exception as e:
        return f"Error calling API: {str(e)}"


def query_customer_db(customer_id: str) -> str:
    """
    Query our customer database.

    Args:
        customer_id: Customer ID to look up

    Returns:
        Customer information
    """
    import sqlite3

    try:
        conn = sqlite3.connect("/path/to/customers.db")
        cursor = conn.cursor()

        cursor.execute(
            "SELECT * FROM customers WHERE id = ?",
            (customer_id,)
        )

        result = cursor.fetchone()
        conn.close()

        if result:
            return f"Customer: {result[1]}, Email: {result[2]}, Status: {result[3]}"
        else:
            return f"Customer {customer_id} not found"

    except Exception as e:
        return f"Database error: {str(e)}"


def run_deployment_script(environment: str) -> str:
    """
    Run deployment script for specified environment.

    Args:
        environment: Target environment (dev, staging, prod)

    Returns:
        Deployment output
    """
    import subprocess

    if environment not in ["dev", "staging", "prod"]:
        return "Error: Invalid environment. Use dev, staging, or prod."

    try:
        result = subprocess.run(
            ["./scripts/deploy.sh", environment],
            capture_output=True,
            text=True,
            timeout=60
        )

        return f"Deployment to {environment}:\n{result.stdout}\n{result.stderr}"

    except subprocess.TimeoutExpired:
        return "Error: Deployment timed out (60s)"
    except Exception as e:
        return f"Deployment error: {str(e)}"
```

### Step 3: Register Your Tools

Edit `perplexity_tools_prompt_based.py`, in the `_register_builtin_tools` method:

```python
def _register_builtin_tools(self):
    """Register built-in tools."""
    # ... existing tools ...

    # Import your custom tools
    from my_custom_tools import my_api_tool, query_customer_db, run_deployment_script

    # Register API tool
    self.tool_manager.register_builtin_tool(
        name="my_api_call",
        description="Call my company's API endpoint",
        parameters={
            "type": "object",
            "properties": {
                "endpoint": {
                    "type": "string",
                    "description": "API endpoint path (e.g., '/users')"
                },
                "method": {
                    "type": "string",
                    "description": "HTTP method (GET or POST)",
                    "enum": ["GET", "POST"]
                }
            },
            "required": ["endpoint"]
        },
        handler=my_api_tool
    )

    # Register database query tool
    self.tool_manager.register_builtin_tool(
        name="query_customer",
        description="Look up customer information from our database",
        parameters={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Customer ID to look up"
                }
            },
            "required": ["customer_id"]
        },
        handler=query_customer_db
    )

    # Register deployment tool
    self.tool_manager.register_builtin_tool(
        name="deploy",
        description="Deploy application to specified environment",
        parameters={
            "type": "object",
            "properties": {
                "environment": {
                    "type": "string",
                    "description": "Target environment",
                    "enum": ["dev", "staging", "prod"]
                }
            },
            "required": ["environment"]
        },
        handler=run_deployment_script
    )
```

### Step 4: Use Your Tools

```bash
python demo_tools_working.py
```

Or in ppxai:
```
You: Use the my_api_call tool to fetch /users endpoint

You: Query customer ID 12345 using the query_customer tool

You: Deploy to staging environment
```

### Built-in Tool Template

Copy this template for new tools:

```python
def my_tool_name(param1: str, param2: int = 10) -> str:
    """
    One-line description of what this tool does.

    Args:
        param1: Description of first parameter
        param2: Description of second parameter (default: 10)

    Returns:
        Description of what is returned
    """
    try:
        # Your tool logic here
        result = do_something(param1, param2)
        return str(result)

    except Exception as e:
        return f"Error: {str(e)}"

# Registration (add to _register_builtin_tools):
self.tool_manager.register_builtin_tool(
    name="my_tool_name",
    description="One-line description for the AI model",
    parameters={
        "type": "object",
        "properties": {
            "param1": {
                "type": "string",
                "description": "What param1 is for"
            },
            "param2": {
                "type": "integer",
                "description": "What param2 is for (default: 10)"
            }
        },
        "required": ["param1"]  # param2 is optional
    },
    handler=my_tool_name
)
```

---

## 🌐 Option 2: MCP Servers (For Standard Integrations)

### When to Choose MCP

✅ **Use existing MCP servers** for standard integrations:
- GitHub API
- Slack messaging
- Google services
- Databases (PostgreSQL, SQLite)
- Web search

✅ **Build your own MCP server** when:
- You want to share tools with other MCP-compatible apps
- You need process isolation
- You're building a reusable integration

### Using Existing MCP Servers

#### Step 1: Find Available Servers

Browse: https://github.com/modelcontextprotocol/servers

Popular servers:
- `@modelcontextprotocol/server-filesystem` - File operations
- `@modelcontextprotocol/server-github` - GitHub API
- `@modelcontextprotocol/server-brave-search` - Web search
- `@modelcontextprotocol/server-sqlite` - SQLite databases
- `@modelcontextprotocol/server-slack` - Slack messaging
- `@modelcontextprotocol/server-postgres` - PostgreSQL databases

#### Step 2: Configure in tools.config.json

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
    },
    {
      "name": "slack",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-slack"],
      "env": {
        "SLACK_BOT_TOKEN": "${SLACK_BOT_TOKEN}"
      }
    },
    {
      "name": "database",
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-sqlite",
        "/path/to/your/database.db"
      ]
    }
  ]
}
```

#### Step 3: Set Environment Variables

```bash
# In your .env file
GITHUB_TOKEN=ghp_yourtoken
SLACK_BOT_TOKEN=xoxb-yourtoken
```

#### Step 4: Initialize with MCP Servers

```python
from perplexity_tools_prompt_based import PerplexityClientPromptTools
from tool_manager import load_tool_config
from pathlib import Path

client = PerplexityClientPromptTools(
    api_key=api_key,
    enable_tools=True
)

# Load config with MCP servers
config = load_tool_config(Path.home() / ".ppxai" / "tools.config.json")
await client.initialize_tools(mcp_servers=config.get("mcp_servers", []))
```

### Building Your Own MCP Server

#### When to Build Your Own

- Want to share integration across multiple apps
- Need complex tool with its own state
- Prefer Node.js/TypeScript ecosystem
- Want tool isolation from main app

#### Quick MCP Server Template

Create `my-mcp-server/index.js`:

```javascript
#!/usr/bin/env node

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

// Create server
const server = new Server(
  {
    name: "my-custom-server",
    version: "1.0.0",
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

// Define available tools
server.setRequestHandler("tools/list", async () => {
  return {
    tools: [
      {
        name: "my_tool",
        description: "Does something useful",
        inputSchema: {
          type: "object",
          properties: {
            input: {
              type: "string",
              description: "Input parameter",
            },
          },
          required: ["input"],
        },
      },
    ],
  };
});

// Handle tool execution
server.setRequestHandler("tools/call", async (request) => {
  const { name, arguments: args } = request.params;

  if (name === "my_tool") {
    const input = args.input;

    // Your tool logic here
    const result = `Processed: ${input}`;

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

#### package.json

```json
{
  "name": "my-mcp-server",
  "version": "1.0.0",
  "type": "module",
  "bin": {
    "my-mcp-server": "./index.js"
  },
  "dependencies": {
    "@modelcontextprotocol/sdk": "^0.5.0"
  }
}
```

#### Use Your MCP Server

```json
{
  "mcp_servers": [
    {
      "name": "my-server",
      "command": "node",
      "args": ["/path/to/my-mcp-server/index.js"]
    }
  ]
}
```

---

## 🎯 Real-World Examples

### Example 1: Code Review Helper (Built-in Tool)

**Use Case:** Check if code follows your team's standards

**Why Built-in:** Custom logic specific to your team

```python
def check_code_standards(file_path: str) -> str:
    """Check if code follows team standards."""
    import re
    from pathlib import Path

    issues = []

    try:
        content = Path(file_path).read_text()

        # Check for TODO comments
        if 'TODO' in content:
            issues.append("Contains TODO comments")

        # Check for console.log (if JavaScript)
        if file_path.endswith('.js') and 'console.log' in content:
            issues.append("Contains console.log statements")

        # Check for long lines
        long_lines = [i+1 for i, line in enumerate(content.split('\n'))
                      if len(line) > 100]
        if long_lines:
            issues.append(f"Long lines (>100 chars): {long_lines[:5]}")

        if issues:
            return "Issues found:\n" + "\n".join(f"- {issue}" for issue in issues)
        else:
            return "✓ Code follows team standards"

    except Exception as e:
        return f"Error: {str(e)}"
```

### Example 2: GitHub Integration (MCP Server)

**Use Case:** Create issues, check PRs, etc.

**Why MCP:** Standard GitHub API, existing server available

```json
{
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

Usage:
```
You: Use GitHub tools to create an issue titled "Bug in login" in repo myorg/myapp
```

### Example 3: Database Query (Built-in Tool)

**Use Case:** Query your specific database with custom logic

**Why Built-in:** Specific queries for your schema

```python
def query_sales_data(start_date: str, end_date: str, region: str = "all") -> str:
    """Query sales data for date range."""
    import psycopg2
    import os

    try:
        conn = psycopg2.connect(os.getenv("DATABASE_URL"))
        cursor = conn.cursor()

        query = """
            SELECT
                DATE(sale_date) as date,
                SUM(amount) as total_sales,
                COUNT(*) as num_transactions
            FROM sales
            WHERE sale_date BETWEEN %s AND %s
        """

        params = [start_date, end_date]

        if region != "all":
            query += " AND region = %s"
            params.append(region)

        query += " GROUP BY DATE(sale_date) ORDER BY date"

        cursor.execute(query, params)
        results = cursor.fetchall()

        conn.close()

        output = f"Sales data from {start_date} to {end_date}:\n"
        for date, total, count in results:
            output += f"  {date}: ${total:,.2f} ({count} transactions)\n"

        return output

    except Exception as e:
        return f"Database error: {str(e)}"
```

---

## 📋 Decision Checklist

Before adding a tool, ask yourself:

- [ ] What does this tool do? (1-sentence description)
- [ ] Is there an existing MCP server for this?
  - ✅ Yes → Use MCP server (Option 2)
  - ❌ No → Continue...
- [ ] Can I write this as a Python function in <50 lines?
  - ✅ Yes → Built-in tool (Option 1)
  - ❌ No → Consider if MCP server is worth the complexity
- [ ] Do I need to share this with other apps?
  - ✅ Yes → MCP server (Option 2)
  - ❌ No → Built-in tool (Option 1)
- [ ] Do I need Node.js-specific libraries?
  - ✅ Yes → MCP server (Option 2)
  - ❌ No → Built-in tool (Option 1)

**Default choice:** Built-in tool (Option 1) - simpler and faster

---

## 🚀 Getting Started

### Quick Start (Built-in Tools)

1. Create `my_custom_tools.py` with your functions
2. Edit `perplexity_tools_prompt_based.py` to register them
3. Test with `python demo_tools_working.py`
4. Use in ppxai!

**Time needed:** 15 minutes

### Advanced (MCP Servers)

1. Find existing MCP server or build your own
2. Create `tools.config.json`
3. Set environment variables
4. Test with `python test_mcp.py`
5. Use in ppxai!

**Time needed:** 1-2 hours

---

## 💡 Recommendations

**For most users:** Start with built-in Python tools (Option 1)
- Simpler
- Faster
- No external dependencies
- Easier to debug
- Perfect for custom logic

**For advanced users:** Mix both approaches
- Built-in tools for custom logic
- MCP servers for standard integrations (GitHub, Slack, etc.)

**Rule of thumb:** If you can write it in Python in <50 lines, make it a built-in tool!

---

## ❓ FAQ

**Q: Can I mix built-in tools and MCP servers?**
A: Yes! That's actually the recommended approach.

**Q: Which is faster?**
A: Built-in tools (same process). MCP has IPC overhead.

**Q: Which is more reliable?**
A: Built-in tools (no external dependencies or network issues).

**Q: Can I convert an MCP server to built-in tool?**
A: Yes! If the MCP server is doing something simple, rewrite it as a Python function.

**Q: Do I need to restart ppxai to add new tools?**
A: Yes, tools are loaded at startup.

**Q: Can tools call other tools?**
A: No, tools can't directly call each other. The AI model orchestrates tool usage.

**Q: How do I debug a tool?**
A: Built-in tools: Use Python debugger. MCP servers: Check server logs.

---

## 📚 Next Steps

1. Read through the examples above
2. Identify 2-3 tools you want to add
3. Start with built-in tools (simpler)
4. Follow the template
5. Test and iterate

**Need help?** Check the templates and examples in this guide!
