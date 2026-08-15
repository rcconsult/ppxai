# Custom Tool Development Guide

> **Imports are top-of-file, DAG style — no `if TYPE_CHECKING:`, no lazy
> imports.** Circular imports are broken with a `Protocol` defined in a leaf
> module instead, which is why tools annotate `manager: ToolManagerProtocol`
> and `engine: ToolEngineProtocol` and import them normally. See
> [patterns/protocol-dependency-inversion.md](patterns/protocol-dependency-inversion.md).
> Earlier revisions of this guide taught the guarded-import idiom; the
> examples below have been corrected.

Complete guide to creating, testing, and integrating custom tools. Custom tools work with both **ppxai** (Rich TUI) and **ppxaide** (Textual TUI), as well as the VSCode extension.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Tool Architecture Overview](#tool-architecture-overview)
3. [Creating Your First Tool](#creating-your-first-tool)
4. [Tool Arguments (JSON Schema)](#tool-arguments-json-schema)
5. [Testing Your Tool](#testing-your-tool)
6. [Integrating Into Runtime](#integrating-into-runtime)
7. [Logging and Verbosity](#logging-and-verbosity)
8. [Tool Help and Documentation](#tool-help-and-documentation)
9. [Advanced Patterns](#advanced-patterns)
10. [Security Best Practices](#security-best-practices)
11. [Examples](#examples)
12. [Troubleshooting](#troubleshooting)

---

## Quick Start

Create a working tool in 5 minutes:

### Step 1: Create the Tool File

Create `ppxai/engine/tools/builtin/my_tool.py`:

```python
"""
My custom tool for ppxai.
"""
from ...types import ToolManagerProtocol


def greet_user(name: str, formal: bool = False) -> str:
    """Generate a greeting for a user.

    Args:
        name: The user's name
        formal: Whether to use formal greeting

    Returns:
        A greeting string
    """
    if formal:
        return f"Good day, {name}. How may I assist you?"
    return f"Hey {name}! What's up?"


def register_tools(manager: ToolManagerProtocol):
    """Register custom tools with the manager."""
    manager.register_function(
        name="greet_user",
        description="Generate a personalized greeting for a user",
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The user's name"
                },
                "formal": {
                    "type": "boolean",
                    "description": "Use formal greeting style (default: false)"
                }
            },
            "required": ["name"]
        },
        handler=greet_user
    )
```

### Step 2: Register in `__init__.py`

Edit `ppxai/engine/tools/builtin/__init__.py`:

```python
def register_all_builtin_tools(manager: ToolManagerProtocol, provider: str = None, engine: Optional[ToolEngineProtocol] = None):
    from . import filesystem, calculator, datetime_tool, web, my_tool  # Add import

    # ... existing registrations ...
    my_tool.register_tools(manager)  # Add registration
```

> If your tool needs engine services (working dir, consent, session), its
> `register_tools` takes `engine` too — declare it as
> `register_tools(manager: ToolManagerProtocol, engine: ToolEngineProtocol)`
> and register with `my_tool.register_tools(manager, engine)`. Dropping the
> argument here is the most common cause of a tool that imports cleanly and
> then fails at call time.

### Step 3: Test It

```bash
# Start ppxai
uv run ppxai

# Enable tools and test
/tools enable
/tools list   # Should show greet_user, with its description

# Ask AI to use it
You: Greet John formally
AI: [Calls greet_user with name="John", formal=true]
Good day, John. How may I assist you?
```

---

## Tool Architecture Overview

### Core Components

```
ppxai/engine/tools/
├── base.py           # BaseTool and FunctionTool classes
├── manager.py        # ToolManager (registration, execution, filtering)
└── builtin/          # Built-in tools
    ├── __init__.py   # Auto-registration entry point
    ├── calculator.py # Simple tool example
    ├── shell.py      # Consent-based tool example
    └── your_tool.py  # Your custom tool
```

### BaseTool vs FunctionTool

ppxai provides two ways to create tools:

#### Option 1: FunctionTool (Simpler)

Use `manager.register_function()` to wrap a plain Python function:

```python
def my_function(arg1: str) -> str:
    return f"Result: {arg1}"

manager.register_function(
    name="my_tool",
    description="Tool description",
    parameters={...},
    handler=my_function
)
```

**Best for:** Simple tools, quick prototypes, stateless operations.

#### Option 2: BaseTool Subclass (More Control)

Subclass `BaseTool` for complex tools:

```python
from ppxai.engine.tools.base import BaseTool

class MyTool(BaseTool):
    name = "my_tool"
    description = "Tool description"
    parameters = {
        "type": "object",
        "properties": {...},
        "required": [...]
    }

    async def execute(self, **kwargs) -> str:
        # Your logic here
        return "Result"

# Register
manager.register_tool(MyTool())
```

**Best for:** Stateful tools, tools needing engine access, consent-based tools.

### ToolManager

The `ToolManager` handles:

- **Registration**: `register_tool()`, `register_function()`
- **Provider filtering**: Tools can be provider-specific or excluded
- **Execution**: `execute_tool(name, **kwargs)`
- **Prompt generation**: Creates system prompts describing available tools

---

## Creating Your First Tool

### Function-Based Approach

This is the simplest way to create a tool:

```python
"""
ppxai/engine/tools/builtin/stock_price.py

Stock price lookup tool.
"""
import os
from ...types import ToolManagerProtocol


def get_stock_price(symbol: str) -> str:
    """Get the current stock price for a symbol.

    Args:
        symbol: Stock ticker symbol (e.g., 'AAPL', 'GOOGL')

    Returns:
        Current stock price or error message
    """
    try:
        # Your API logic here
        api_key = os.getenv("STOCK_API_KEY")
        if not api_key:
            return "Error: STOCK_API_KEY not configured"

        # Example: call stock API
        # response = requests.get(f"https://api.example.com/stock/{symbol}")
        # price = response.json()["price"]

        price = 150.25  # Placeholder
        return f"{symbol}: ${price:.2f}"

    except Exception as e:
        return f"Error fetching stock price: {str(e)}"


def register_tools(manager: ToolManagerProtocol):
    """Register stock tools with the manager."""
    manager.register_function(
        name="get_stock_price",
        description="Get current stock price for a ticker symbol (e.g., AAPL, GOOGL, MSFT)",
        parameters={
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Stock ticker symbol (e.g., 'AAPL', 'GOOGL')"
                }
            },
            "required": ["symbol"]
        },
        handler=get_stock_price
    )
```

### Class-Based Approach

For tools that need state or engine access:

```python
"""
ppxai/engine/tools/builtin/database_query.py

Database query tool with connection pooling.
"""
from ..base import BaseTool

from ...types import ToolEngineProtocol, ToolManagerProtocol


class DatabaseQueryTool(BaseTool):
    """Execute read-only database queries."""

    name = "database_query"
    description = "Execute a read-only SQL query against the configured database"
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "SQL SELECT query to execute"
            },
            "limit": {
                "type": "integer",
                "description": "Maximum rows to return (default: 100)"
            }
        },
        "required": ["query"]
    }

    def __init__(self, connection_string: str):
        """Initialize with database connection.

        Args:
            connection_string: Database connection string
        """
        self.connection_string = connection_string
        self._connection = None

    async def execute(self, query: str, limit: int = 100) -> str:
        """Execute the query.

        Args:
            query: SQL query to execute
            limit: Maximum rows to return

        Returns:
            Query results as formatted string
        """
        # Validate query is read-only
        query_upper = query.strip().upper()
        if not query_upper.startswith("SELECT"):
            return "Error: Only SELECT queries are allowed"

        try:
            # Your database logic here
            # results = await self._execute_query(query, limit)
            results = [{"id": 1, "name": "Example"}]  # Placeholder

            return f"Query returned {len(results)} rows:\n{results}"

        except Exception as e:
            return f"Database error: {str(e)}"


def register_tools(manager: ToolManagerProtocol):
    """Register database tools."""
    import os
    conn_string = os.getenv("DATABASE_URL")
    if conn_string:
        manager.register_tool(DatabaseQueryTool(conn_string))
```

---

## Tool Arguments (JSON Schema)

Tools use [JSON Schema](https://json-schema.org/) to define their parameters.

### Basic Types

```python
parameters = {
    "type": "object",
    "properties": {
        # String
        "name": {
            "type": "string",
            "description": "User's full name"
        },

        # Number (float)
        "temperature": {
            "type": "number",
            "description": "Temperature in Celsius"
        },

        # Integer
        "count": {
            "type": "integer",
            "description": "Number of items"
        },

        # Boolean
        "verbose": {
            "type": "boolean",
            "description": "Enable verbose output"
        }
    },
    "required": ["name"]  # Only name is required
}
```

### Enum (Choice from List)

```python
"format": {
    "type": "string",
    "description": "Output format",
    "enum": ["json", "csv", "xml", "text"]
}
```

### Array

```python
"tags": {
    "type": "array",
    "description": "List of tags to apply",
    "items": {"type": "string"}
}
```

### Nested Object

```python
"config": {
    "type": "object",
    "description": "Configuration options",
    "properties": {
        "timeout": {"type": "integer"},
        "retries": {"type": "integer"}
    }
}
```

### Complete Example

```python
parameters = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Search query text"
        },
        "max_results": {
            "type": "integer",
            "description": "Maximum results to return (default: 10)"
        },
        "filters": {
            "type": "object",
            "description": "Optional filters",
            "properties": {
                "date_from": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                "date_to": {"type": "string", "description": "End date (YYYY-MM-DD)"},
                "categories": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Categories to include"
                }
            }
        },
        "sort_by": {
            "type": "string",
            "enum": ["relevance", "date", "popularity"],
            "description": "Sort order (default: relevance)"
        }
    },
    "required": ["query"]
}
```

---

## Testing Your Tool

### Unit Testing with pytest

Create `tests/test_my_tool.py`:

```python
"""Tests for my custom tool."""
import pytest
from ppxai.engine.tools.builtin.my_tool import greet_user


class TestGreetUser:
    """Unit tests for greet_user function."""

    def test_informal_greeting(self):
        """Test informal greeting."""
        result = greet_user("Alice")
        assert "Alice" in result
        assert "Hey" in result

    def test_formal_greeting(self):
        """Test formal greeting."""
        result = greet_user("Bob", formal=True)
        assert "Bob" in result
        assert "Good day" in result

    def test_empty_name(self):
        """Test with empty name."""
        result = greet_user("")
        assert result  # Should still return something


class TestGreetUserRegistration:
    """Test tool registration."""

    def test_tool_registers(self):
        """Test that tool registers with manager."""
        from ppxai.engine.tools.manager import ToolManager
        from ppxai.engine.tools.builtin.my_tool import register_tools

        manager = ToolManager()
        register_tools(manager)

        tool = manager.get_tool("greet_user")
        assert tool is not None
        assert tool.name == "greet_user"
        assert "greeting" in tool.description.lower()

    def test_tool_parameters(self):
        """Test parameter schema is correct."""
        from ppxai.engine.tools.manager import ToolManager
        from ppxai.engine.tools.builtin.my_tool import register_tools

        manager = ToolManager()
        register_tools(manager)

        tool = manager.get_tool("greet_user")
        assert "name" in tool.parameters["properties"]
        assert "name" in tool.parameters["required"]
```

### Integration Testing with EngineClient

```python
"""Integration tests for tool execution."""
import pytest
import asyncio
from ppxai.engine import EngineClient, EventType


class TestToolIntegration:
    """Integration tests using EngineClient."""

    @pytest.fixture
    def engine(self):
        """Create engine with tools enabled."""
        engine = EngineClient()
        engine.set_provider("gemini")  # Or your preferred provider
        engine.set_model("gemini-2.5-flash")
        engine.enable_tools()
        return engine

    def test_tool_appears_in_list(self, engine):
        """Test tool is in available tools list."""
        tools = engine.list_tools()
        tool_names = [t["name"] for t in tools]
        assert "greet_user" in tool_names

    @pytest.mark.asyncio
    async def test_tool_execution(self, engine):
        """Test direct tool execution."""
        result = await engine.tool_manager.execute_tool(
            "greet_user",
            name="Test User",
            formal=True
        )
        assert "Test User" in result
        assert "Good day" in result


class TestToolWithMocking:
    """Test tools that call external APIs."""

    @pytest.fixture
    def mock_api(self, mocker):
        """Mock external API calls."""
        return mocker.patch("requests.get")

    def test_api_tool_success(self, mock_api):
        """Test API tool with mocked response."""
        mock_api.return_value.json.return_value = {"price": 150.25}
        mock_api.return_value.status_code = 200

        from ppxai.engine.tools.builtin.stock_price import get_stock_price
        result = get_stock_price("AAPL")

        assert "AAPL" in result
        assert "150.25" in result

    def test_api_tool_error(self, mock_api):
        """Test API tool error handling."""
        mock_api.side_effect = Exception("Network error")

        from ppxai.engine.tools.builtin.stock_price import get_stock_price
        result = get_stock_price("AAPL")

        assert "Error" in result
```

### Running Tests

```bash
# Run all tests
uv run pytest tests/ -v

# Run specific test file
uv run pytest tests/test_my_tool.py -v

# Run with coverage
uv run pytest tests/test_my_tool.py --cov=ppxai.engine.tools.builtin.my_tool
```

---

## Integrating Into Runtime

### Step 1: Add Your Tool Module

Place your tool file in `ppxai/engine/tools/builtin/`:

```
ppxai/engine/tools/builtin/
├── __init__.py
├── calculator.py
├── datetime_tool.py
├── filesystem.py
├── shell.py
├── editor.py
├── web.py
└── my_tool.py  # Your new tool
```

### Step 2: Register in `__init__.py`

Edit `ppxai/engine/tools/builtin/__init__.py`:

```python
def register_all_builtin_tools(manager: ToolManagerProtocol, provider: str = None, engine: Optional[ToolEngineProtocol] = None):
    """Register all built-in tools with the manager."""
    from . import filesystem, calculator, datetime_tool, web
    from . import my_tool  # Add your import

    # Register tools from each module
    filesystem.register_tools(manager)
    calculator.register_tools(manager)
    datetime_tool.register_tools(manager)
    web.register_tools(manager, provider)
    my_tool.register_tools(manager)  # Add your registration

    # ... rest of function
```

### Step 3: Verify Registration

```bash
# Start ppxai
uv run ppxai

# Check tools
/tools enable
/tools list

# You should see your tool:
# ┌──────────────┬─────────────────────────────────────┬────────┐
# │ Tool         │ Description                         │
# ├──────────────┼─────────────────────────────────────┼────────┤
# │ greet_user   │ Generate a personalized greeting... │ engine │
# └──────────────┴─────────────────────────────────────┴────────┘
```

### Hot Reload During Development

For faster iteration, test your tool function directly:

```python
# test_dev.py
from ppxai.engine.tools.builtin.my_tool import greet_user

# Test changes immediately
print(greet_user("Developer", formal=True))
```

```bash
# Run directly without restarting ppxai
uv run python test_dev.py
```

---

## Logging and Verbosity

### Using Verbose Mode

ppxai has a built-in verbose mode for tool debugging:

```bash
# In TUI
/tools set verbose on

# Now tool calls show detailed information:
# [Tool Call: greet_user]
# Arguments: {"name": "Alice", "formal": true}
# [Tool Result: Good day, Alice. How may I assist you?]
```

### Adding Logging to Your Tool

Use Python's standard logging:

```python
"""Tool with logging."""
import logging
from ...types import ToolManagerProtocol

# Create logger for this module
logger = logging.getLogger(__name__)


def my_tool_function(param: str) -> str:
    """Tool with debug logging."""
    logger.debug(f"my_tool_function called with param={param}")

    try:
        result = do_something(param)
        logger.info(f"my_tool_function succeeded: {result[:50]}...")
        return result
    except Exception as e:
        logger.error(f"my_tool_function failed: {e}", exc_info=True)
        return f"Error: {str(e)}"
```

### Viewing Logs

ppxai logs to `~/.ppxai/logs/`. To see debug output:

```bash
# Enable debug logging (boolean: 1/true/yes/on)
export PPXAI_DEBUG=1

# Run ppxai
uv run ppxai

# Or view logs directly (TUI writes here; the server writes server-debug.log)
tail -f ~/.ppxai/logs/tui-debug.log
```

### Log Levels

| Level | Use For |
|-------|---------|
| `DEBUG` | Detailed diagnostic info (arguments, intermediate steps) |
| `INFO` | General operational info (tool started, completed) |
| `WARNING` | Unexpected but handled situations |
| `ERROR` | Failures that return error messages |

---

## Tool Help and Documentation

### Writing Good Descriptions

The AI reads your tool's description to decide when to use it. Write clear, specific descriptions:

**Bad:**
```python
description = "Does stuff with data"
```

**Good:**
```python
description = "Convert temperature between Celsius, Fahrenheit, and Kelvin. Supports decimal precision and returns the converted value with unit label."
```

### Parameter Descriptions

Each parameter should explain:
1. What it is
2. Valid values/format
3. Default if optional

```python
parameters = {
    "type": "object",
    "properties": {
        "temperature": {
            "type": "number",
            "description": "Temperature value to convert (e.g., 32, 100.5, -40)"
        },
        "from_unit": {
            "type": "string",
            "enum": ["celsius", "fahrenheit", "kelvin"],
            "description": "Source temperature unit"
        },
        "to_unit": {
            "type": "string",
            "enum": ["celsius", "fahrenheit", "kelvin"],
            "description": "Target temperature unit"
        },
        "precision": {
            "type": "integer",
            "description": "Decimal places in result (default: 2, range: 0-6)"
        }
    },
    "required": ["temperature", "from_unit", "to_unit"]
}
```

### Using `/tools list`

`/tools` has no per-tool `help` subcommand — the accepted subcommands are
`on`/`enable`, `off`/`disable`, `list`, `status`, `config`, `set`, `auto`
(`ppxai/commands/tools.py`). `/tools list` shows every registered tool with
its description in one table:

```bash
/tools list

# Output:
# ┌──────────────┬───────────────────────────────────────┬────────┐
# │ Tool         │ Description                            │
# ├──────────────┼───────────────────────────────────────┼────────┤
# │ greet_user   │ Generate a personalized greeting for a │ engine │
# │              │ user                                    │        │
# └──────────────┴───────────────────────────────────────┴────────┘
```

### Autocomplete Support

The TUI provides autocomplete for `/tools` subcommands:

| Input | Tab Shows |
|-------|-----------|
| `/tools <tab>` | on, off, list, status, config, set, auto |

**Tips:**
- Autocomplete works even before tools are enabled (shows the fixed subcommand list)
- `/tools list` shows actual registered tools from `ToolManager`, one row per tool with its description

---

## Advanced Patterns

### Provider-Specific Tools

Make a tool available only for certain providers:

```python
manager.register_function(
    name="gemini_only_tool",
    description="Tool that only works with Gemini",
    parameters={...},
    handler=my_function,
    provider_specific=["gemini"]  # Only available when using Gemini
)
```

### Provider-Excluded Tools

Exclude a tool from providers that have native capability:

```python
manager.register_function(
    name="web_search",
    description="Search the web",
    parameters={...},
    handler=search_function,
    provider_excluded=["perplexity"]  # Perplexity has native search
)
```

### Consent-Based Tools

`EngineClient` has no generic `request_consent()` API — only two concrete
methods, both async and both returning a plain `bool` (see
`ppxai/engine/client.py`):

- `request_file_edit_consent(file_path: str) -> bool` — for tools that
  create/edit/delete a file (this is what `apply_patch`, `write_file`,
  `replace_block`, etc. call)
- `request_shell_consent(command: str, working_dir: str = ".") -> bool` —
  for tools that run a shell command

For tools that modify files, implement consent with the real method:

```python
from ..base import BaseTool

class MyDangerousTool(BaseTool):
    """Tool that requires user consent."""

    name = "dangerous_operation"
    description = "Performs an operation that requires user approval"
    parameters = {...}

    def __init__(self, engine: ToolEngineProtocol):
        self.engine = engine

    async def execute(self, target: str, **kwargs) -> str:
        # Request consent before proceeding (target is a file path here)
        if not await self.engine.request_file_edit_consent(target):
            return f"Error: User denied permission to edit {target}"

        # Proceed with operation
        return do_dangerous_thing(target)
```

If your tool shells out instead of touching a file, call
`request_shell_consent(command, working_dir)` in the same way. There is no
consent hook for other kinds of operations — model tools that need approval
as either a file edit or a shell command.

### Async Operations

Tools can be async for I/O-bound operations:

```python
import aiohttp

async def fetch_data(url: str) -> str:
    """Async tool that fetches data from URL."""
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.text()
                return f"Fetched {len(data)} bytes from {url}"
            return f"Error: HTTP {response.status}"

# register_function handles both sync and async handlers
manager.register_function(
    name="fetch_data",
    description="Fetch data from a URL",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"}
        },
        "required": ["url"]
    },
    handler=fetch_data  # Async function works directly
)
```

---

## Security Best Practices

### Input Validation

Always validate inputs, especially for file paths and commands:

```python
import os
import re

def safe_read_file(filepath: str) -> str:
    """Read file with path validation."""
    # Prevent path traversal
    if ".." in filepath:
        return "Error: Path traversal not allowed"

    # Resolve to absolute path
    abs_path = os.path.abspath(filepath)

    # Check against allowed directory
    allowed_base = os.path.abspath("/allowed/directory")
    if not abs_path.startswith(allowed_base):
        return "Error: Access denied"

    # Read file
    with open(abs_path) as f:
        return f.read()
```

### Environment Variables for Secrets

Never hardcode API keys:

```python
def my_api_tool(query: str) -> str:
    """Tool that uses external API."""
    api_key = os.getenv("MY_API_KEY")
    if not api_key:
        return "Error: MY_API_KEY environment variable not set"

    # Use api_key...
```

### Timeout Operations

Prevent hanging on slow operations:

```python
import asyncio

async def slow_operation(param: str) -> str:
    """Tool with timeout protection."""
    try:
        result = await asyncio.wait_for(
            do_slow_thing(param),
            timeout=30.0  # 30 second timeout
        )
        return result
    except asyncio.TimeoutError:
        return "Error: Operation timed out after 30 seconds"
```

### Error Handling

Always catch exceptions and return user-friendly errors:

```python
def robust_tool(param: str) -> str:
    """Tool with comprehensive error handling."""
    try:
        result = do_something(param)
        return result
    except ValueError as e:
        return f"Invalid input: {str(e)}"
    except ConnectionError as e:
        return f"Network error: {str(e)}"
    except Exception as e:
        # Log the full error for debugging
        logger.error(f"Unexpected error in robust_tool: {e}", exc_info=True)
        # Return safe message to user
        return f"Error: An unexpected error occurred. Check logs for details."
```

---

## Examples

### Example 1: Simple Calculator (Reference)

See `ppxai/engine/tools/builtin/calculator.py`:

```python
"""Calculator tool for mathematical expressions."""
from ...types import ToolManagerProtocol


def calculate(expression: str) -> str:
    """Safely evaluate a mathematical expression."""
    try:
        allowed_chars = set('0123456789+-*/(). ')
        if not all(c in allowed_chars for c in expression):
            return "Error: Invalid characters in expression"
        result = eval(expression, {"__builtins__": {}}, {})
        return str(result)
    except Exception as e:
        return f"Error calculating: {str(e)}"


def register_tools(manager: ToolManagerProtocol):
    manager.register_function(
        name="calculator",
        description="Evaluate a mathematical expression",
        parameters={
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Math expression (e.g., '2 + 2')"
                }
            },
            "required": ["expression"]
        },
        handler=calculate
    )
```

### Example 2: Shell Command (Consent-Based)

See `ppxai/engine/tools/builtin/shell.py` for a complete consent-based tool.

### Example 3: Web Tool (Provider-Excluded)

See `ppxai/engine/tools/builtin/web.py` for provider filtering.

---

## Troubleshooting

### Tool Not Appearing in List

**Symptoms:** `/tools list` doesn't show your tool.

**Checklist:**
1. ✅ File is in `ppxai/engine/tools/builtin/`
2. ✅ File has `register_tools(manager)` function
3. ✅ `register_tools` is called in `builtin/__init__.py`
4. ✅ No import errors (check with `python -c "from ppxai.engine.tools.builtin.my_tool import register_tools"`)
5. ✅ Tools are enabled (`/tools enable`)

**Debug:**
```python
# Check registration
from ppxai.engine.tools.manager import ToolManager
from ppxai.engine.tools.builtin import register_all_builtin_tools

manager = ToolManager()
register_all_builtin_tools(manager)
print([t.name for t in manager.get_available_tools()])
```

### AI Not Calling My Tool

**Symptoms:** AI describes what it would do instead of calling the tool.

**Fixes:**
1. Make description more specific and action-oriented
2. Explicitly tell AI to use the tool: "Use the get_stock_price tool to check AAPL"
3. Check parameter descriptions are clear
4. Ensure tools are enabled (`/tools status`)

### Argument Parsing Errors

**Symptoms:** Tool receives wrong types or missing arguments.

**Fixes:**
1. Verify JSON Schema matches expected types
2. Add default values for optional parameters
3. Handle missing arguments gracefully:

```python
def my_tool(required_param: str, optional_param: str = None) -> str:
    if optional_param is None:
        optional_param = "default_value"
    # ...
```

### Tool Returns Error

**Symptoms:** Tool returns "Error: ..." message.

**Debug:**
1. Enable verbose mode: `/tools set verbose on`
2. Check logs: `tail -f ~/.ppxai/logs/tui-debug.log` (or `server-debug.log` for `ppxai-server`)
3. Test function directly:

```python
from ppxai.engine.tools.builtin.my_tool import my_function
result = my_function("test_input")
print(result)
```

---

## See Also

- [File Editing Guide](file-editing-guide.md) - Built-in file editing tools
- [Shell Consent Guide](shell-consent-guide.md) - Shell command consent system
- [Architecture Refactoring](archive/v1.15.2-completed/architecture-refactoring.md) - EngineClient design
- [Agentic Workflow Plan](archive/v1.15.1-completed/v1.11.0-agentic-workflow-plan.md) - Tool system internals

---

**Version:** v1.13.0+
**Last Updated:** 2026-01-03
**License:** MIT


## Network access: declaring egress

A tool that reaches the network is only usable inside a sandboxed `/task`
run if the operator can allowlist the hosts it needs. Two keys govern that,
and neither is set by the tool's own code:

- **`tools.<tool>.egress`** — the operator-declared host baseline merged
  into any run that *grants* your tool. Without it, a run whose allowlist
  doesn't happen to name your hosts denies the call. This supersedes the
  old `web_search`-only `task_default_allow` (still dual-read).
- **`execution.egress_ceiling`** — a deployment-wide cap intersected with
  every run's allowlist. It can only narrow; a run that needs a host the
  ceiling strips fails **before starting**, naming the stripped hosts.

Design implication: enumerate a *fixed* set of hosts. A tool that derives
its target from model-supplied input cannot be allowlisted, which is why
`get_weather` was made https-only — a scheme fallback put an always-denied
entry into its egress superset and made the whole tool un-allowlistable
under the all-or-nothing rule.
