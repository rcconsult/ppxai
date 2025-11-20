"""
Fixed Tool Manager - Better MCP error handling and cleanup

This version properly handles MCP server lifecycle and cleanup.
"""

import asyncio
import json
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ToolDefinition:
    """Unified tool definition that bridges MCP and OpenAI formats."""
    name: str
    description: str
    parameters: Dict[str, Any]
    source: str  # 'mcp' or 'builtin'
    mcp_server: Optional[str] = None


class ToolManager:
    """
    Manages tools from multiple sources with improved error handling.
    """

    def __init__(self):
        self.tools: Dict[str, ToolDefinition] = {}
        self.mcp_contexts: Dict[str, Any] = {}  # Store async context managers
        self.mcp_sessions: Dict[str, Any] = {}
        self.builtin_handlers: Dict[str, callable] = {}

    async def initialize_mcp_servers(self, server_configs: List[Dict[str, Any]]):
        """
        Initialize MCP servers with proper error handling.
        """
        if not server_configs:
            return

        # Check if MCP is available
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError:
            print("Warning: MCP not installed. Skipping MCP servers.")
            print("Install with: pip install mcp")
            return

        for config in server_configs:
            server_name = config['name']
            try:
                # Validate Node.js is available for npx commands
                if config['command'] == 'npx':
                    import subprocess
                    try:
                        result = subprocess.run(
                            ['node', '--version'],
                            capture_output=True,
                            text=True,
                            timeout=5
                        )
                        if result.returncode != 0:
                            print(f"Warning: Node.js not available, skipping MCP server '{server_name}'")
                            continue
                    except (FileNotFoundError, subprocess.TimeoutExpired):
                        print(f"Warning: Node.js not found, skipping MCP server '{server_name}'")
                        continue

                print(f"Initializing MCP server: {server_name}...")

                server_params = StdioServerParameters(
                    command=config['command'],
                    args=config.get('args', []),
                    env=config.get('env', None)
                )

                # Create context manager but don't enter yet
                context = stdio_client(server_params)

                # Enter the context
                read, write = await context.__aenter__()

                # Create and initialize session
                session = ClientSession(read, write)
                await session.initialize()

                # Store both context and session for proper cleanup
                self.mcp_contexts[server_name] = context
                self.mcp_sessions[server_name] = session

                # Discover tools
                try:
                    tools_result = await asyncio.wait_for(
                        session.list_tools(),
                        timeout=10.0
                    )

                    # Convert tools to unified format
                    for mcp_tool in tools_result.tools:
                        tool_def = self._convert_mcp_to_unified(mcp_tool, server_name)
                        self.tools[tool_def.name] = tool_def

                    print(f"  ✓ Loaded {len(tools_result.tools)} tools from {server_name}")

                except asyncio.TimeoutError:
                    print(f"  ✗ Timeout loading tools from {server_name}")
                    await self._cleanup_server(server_name)
                except Exception as e:
                    print(f"  ✗ Error loading tools from {server_name}: {e}")
                    await self._cleanup_server(server_name)

            except Exception as e:
                print(f"Warning: Failed to initialize MCP server '{server_name}': {e}")
                # Clean up any partial initialization
                await self._cleanup_server(server_name)

    async def _cleanup_server(self, server_name: str):
        """Clean up a single server's resources."""
        try:
            if server_name in self.mcp_contexts:
                context = self.mcp_contexts[server_name]
                await context.__aexit__(None, None, None)
                del self.mcp_contexts[server_name]
            if server_name in self.mcp_sessions:
                del self.mcp_sessions[server_name]
        except Exception:
            pass  # Ignore cleanup errors

    def _convert_mcp_to_unified(self, mcp_tool: Any, server_name: str) -> ToolDefinition:
        """Convert MCP tool definition to unified format."""
        return ToolDefinition(
            name=mcp_tool.name,
            description=mcp_tool.description or "",
            parameters=mcp_tool.inputSchema if hasattr(mcp_tool, 'inputSchema') else {},
            source='mcp',
            mcp_server=server_name
        )

    def register_builtin_tool(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        handler: callable
    ):
        """Register a built-in Python tool."""
        tool_def = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            source='builtin'
        )
        self.tools[name] = tool_def
        self.builtin_handlers[name] = handler

    def get_openai_tools(self) -> List[Dict[str, Any]]:
        """Convert all tools to OpenAI format."""
        openai_tools = []
        for tool_name, tool_def in self.tools.items():
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool_def.name,
                    "description": tool_def.description,
                    "parameters": tool_def.parameters
                }
            })
        return openai_tools

    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Execute a tool by name."""
        if tool_name not in self.tools:
            raise ValueError(f"Unknown tool: {tool_name}")

        tool_def = self.tools[tool_name]

        if tool_def.source == 'mcp':
            return await self._execute_mcp_tool(tool_def, arguments)
        elif tool_def.source == 'builtin':
            return await self._execute_builtin_tool(tool_def, arguments)
        else:
            raise ValueError(f"Unknown tool source: {tool_def.source}")

    async def _execute_mcp_tool(self, tool_def: ToolDefinition, arguments: Dict[str, Any]) -> Any:
        """Execute a tool via MCP server."""
        if tool_def.mcp_server not in self.mcp_sessions:
            raise RuntimeError(f"MCP server not initialized: {tool_def.mcp_server}")

        session = self.mcp_sessions[tool_def.mcp_server]

        try:
            # Call the tool with timeout
            result = await asyncio.wait_for(
                session.call_tool(tool_def.name, arguments),
                timeout=30.0
            )

            # Extract text content
            if hasattr(result, 'content') and result.content:
                text_content = []
                for item in result.content:
                    if hasattr(item, 'text'):
                        text_content.append(item.text)
                return '\n'.join(text_content)

            return str(result)

        except asyncio.TimeoutError:
            return "Error: Tool execution timed out (30s)"
        except Exception as e:
            return f"Error executing MCP tool: {str(e)}"

    async def _execute_builtin_tool(self, tool_def: ToolDefinition, arguments: Dict[str, Any]) -> Any:
        """Execute a built-in Python tool."""
        handler = self.builtin_handlers.get(tool_def.name)
        if not handler:
            raise ValueError(f"No handler for builtin tool: {tool_def.name}")

        try:
            # Check if async
            if asyncio.iscoroutinefunction(handler):
                return await handler(**arguments)
            else:
                # Run sync in executor
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(None, lambda: handler(**arguments))
        except Exception as e:
            return f"Error executing builtin tool: {str(e)}"

    async def cleanup(self):
        """Clean up all MCP sessions properly."""
        # Close sessions first
        for server_name in list(self.mcp_sessions.keys()):
            try:
                session = self.mcp_sessions[server_name]
                # Sessions don't need explicit cleanup usually
                del self.mcp_sessions[server_name]
            except Exception as e:
                print(f"Warning: Error closing session {server_name}: {e}")

        # Then exit contexts
        for server_name in list(self.mcp_contexts.keys()):
            try:
                context = self.mcp_contexts[server_name]
                # Exit context manager
                await asyncio.wait_for(
                    context.__aexit__(None, None, None),
                    timeout=5.0
                )
                del self.mcp_contexts[server_name]
            except asyncio.TimeoutError:
                print(f"Warning: Timeout cleaning up MCP server {server_name}")
            except Exception as e:
                print(f"Warning: Error cleaning up MCP server {server_name}: {e}")

        self.mcp_sessions.clear()
        self.mcp_contexts.clear()

    def list_tools(self) -> List[Dict[str, str]]:
        """Get a human-readable list of all tools."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "source": tool.source,
                "server": tool.mcp_server if tool.source == 'mcp' else "built-in"
            }
            for tool in self.tools.values()
        ]


# Helper functions
def load_tool_config(config_path: Path) -> Dict[str, Any]:
    """Load tool configuration from JSON file."""
    if not config_path.exists():
        return {"mcp_servers": [], "enabled": False}

    with open(config_path, 'r') as f:
        return json.load(f)


def save_default_config(config_path: Path):
    """Save a default tool configuration file."""
    default_config = {
        "enabled": True,
        "mcp_servers": [
            {
                "name": "filesystem",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
            }
        ]
    }

    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, 'w') as f:
        json.dump(default_config, f, indent=2)
