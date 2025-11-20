"""
Perplexity Client with Prompt-Based Tool Support

Since Perplexity doesn't support OpenAI function calling, this uses
prompt engineering to enable tool usage:
1. Tools described in system prompt
2. Model responds with structured tool calls in text
3. We parse and execute the calls
4. Results fed back to the conversation
"""

import asyncio
import json
import re
from typing import Optional, List, Dict, Any
from openai import OpenAI
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from datetime import datetime

from tool_manager import ToolManager

console = Console()


class PerplexityClientPromptTools:
    """
    Perplexity client with prompt-based tool support.
    Works around lack of native function calling.
    """

    def __init__(
        self,
        api_key: str,
        session_name: Optional[str] = None,
        enable_tools: bool = False
    ):
        """Initialize the client with optional tool support."""
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://api.perplexity.ai"
        )
        self.conversation_history = []
        self.session_name = session_name or f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.enable_tools = enable_tools
        self.tool_manager = ToolManager() if enable_tools else None

    async def initialize_tools(self, mcp_servers: List[Dict[str, Any]] = None):
        """Initialize the tool system."""
        if not self.enable_tools or not self.tool_manager:
            return

        # Initialize MCP servers if provided (optional)
        if mcp_servers:
            try:
                await self.tool_manager.initialize_mcp_servers(mcp_servers)
            except Exception as e:
                console.print(f"[yellow]Note: MCP servers skipped: {e}[/yellow]")

        # Register built-in tools
        self._register_builtin_tools()

        console.print(f"[green]Tools initialized:[/green] {len(self.tool_manager.tools)} tools available")
        for tool_info in self.tool_manager.list_tools():
            console.print(f"  • {tool_info['name']}: {tool_info['description']}")
        console.print()

    def _register_builtin_tools(self):
        """Register built-in tools."""
        import os
        import subprocess
        from pathlib import Path
        import glob

        # File search tool
        def search_files(pattern: str, directory: str = ".") -> str:
            """Search for files matching a pattern."""
            try:
                results = glob.glob(f"{directory}/**/{pattern}", recursive=True)
                if not results:
                    return f"No files found matching '{pattern}'"
                return "\n".join(results[:20])
            except Exception as e:
                return f"Error: {str(e)}"

        self.tool_manager.register_builtin_tool(
            name="search_files",
            description="Search for files matching a glob pattern in a directory",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern (e.g., '*.py')"},
                    "directory": {"type": "string", "description": "Directory to search (default: '.')"}
                },
                "required": ["pattern"]
            },
            handler=search_files
        )

        # Read file tool
        def read_file(filepath: str, max_lines: int = 100) -> str:
            """Read contents of a file."""
            try:
                path = Path(filepath).expanduser().resolve()
                if not path.exists():
                    return f"Error: File not found: {filepath}"
                if not path.is_file():
                    return f"Error: Not a file: {filepath}"

                with open(path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()[:max_lines]
                    content = ''.join(lines)

                if len(lines) == max_lines:
                    content += f"\n... (truncated to {max_lines} lines)"

                return content
            except Exception as e:
                return f"Error reading file: {str(e)}"

        self.tool_manager.register_builtin_tool(
            name="read_file",
            description="Read the contents of a text file",
            parameters={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path to the file"},
                    "max_lines": {"type": "integer", "description": "Max lines (default: 100)"}
                },
                "required": ["filepath"]
            },
            handler=read_file
        )

        # Calculator tool
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

        self.tool_manager.register_builtin_tool(
            name="calculator",
            description="Evaluate a mathematical expression",
            parameters={
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "Math expression (e.g., '2 + 2')"}
                },
                "required": ["expression"]
            },
            handler=calculate
        )

        # List directory tool
        def list_directory(path: str = ".", format: str = "simple") -> str:
            """List files and directories with optional long format."""
            import stat
            from datetime import datetime

            try:
                dir_path = Path(path).expanduser().resolve()
                if not dir_path.exists():
                    return f"Error: Directory not found: {path}"
                if not dir_path.is_dir():
                    return f"Error: Not a directory: {path}"

                items = []

                if format == "long":
                    # Long format like 'ls -la'
                    for item in sorted(dir_path.iterdir()):
                        try:
                            stats = item.stat()

                            # File type and permissions
                            mode = stats.st_mode
                            perms = stat.filemode(mode)

                            # Number of links
                            nlink = stats.st_nlink

                            # Owner (simplified - just show user)
                            try:
                                import pwd
                                owner = pwd.getpwuid(stats.st_uid).pw_name
                            except:
                                owner = str(stats.st_uid)

                            # Group (simplified)
                            try:
                                import grp
                                group = grp.getgrgid(stats.st_gid).gr_name
                            except:
                                group = str(stats.st_gid)

                            # Size
                            size = stats.st_size

                            # Modified time
                            mtime = datetime.fromtimestamp(stats.st_mtime)
                            mtime_str = mtime.strftime("%b %d %H:%M")

                            # Format the line
                            line = f"{perms} {nlink:3} {owner:8} {group:8} {size:8} {mtime_str} {item.name}"
                            items.append(line)
                        except Exception as e:
                            items.append(f"? {item.name} (error: {e})")
                else:
                    # Simple format
                    for item in sorted(dir_path.iterdir()):
                        item_type = "DIR " if item.is_dir() else "FILE"
                        items.append(f"{item_type} {item.name}")

                result = "\n".join(items[:50])
                if len(items) > 50:
                    result += f"\n... ({len(items) - 50} more items)"

                return result
            except Exception as e:
                return f"Error: {str(e)}"

        self.tool_manager.register_builtin_tool(
            name="list_directory",
            description="List files and directories in a path. Supports simple and long format (like 'ls -la')",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path (default: '.')"
                    },
                    "format": {
                        "type": "string",
                        "description": "Output format: 'simple' (default) or 'long' (detailed like 'ls -la')",
                        "enum": ["simple", "long"]
                    }
                },
                "required": []
            },
            handler=list_directory
        )

    def _get_tools_prompt(self) -> str:
        """Generate a system prompt describing available tools."""
        if not self.tool_manager or not self.tool_manager.tools:
            return ""

        tools_desc = "# Available Tools\n\n"
        tools_desc += "You have access to the following tools. To use a tool, respond with a JSON code block:\n\n"
        tools_desc += "```json\n{\n  \"tool\": \"tool_name\",\n  \"arguments\": {\"param\": \"value\"}\n}\n```\n\n"
        tools_desc += "## Tools:\n\n"

        for name, tool_def in self.tool_manager.tools.items():
            tools_desc += f"**{name}**: {tool_def.description}\n"
            if tool_def.parameters.get("properties"):
                tools_desc += "  Parameters:\n"
                for param, info in tool_def.parameters["properties"].items():
                    required = "required" if param in tool_def.parameters.get("required", []) else "optional"
                    tools_desc += f"  - `{param}` ({required}): {info.get('description', '')}\n"
            tools_desc += "\n"

        tools_desc += "\nIMPORTANT:\n"
        tools_desc += "- Only use tools when explicitly asked or when necessary to answer the question\n"
        tools_desc += "- After using a tool, you'll receive the result and can continue with your response\n"
        tools_desc += "- If you don't need a tool, just respond normally\n"

        return tools_desc

    async def chat_with_tools(
        self,
        message: str,
        model: str,
        max_iterations: int = 5
    ) -> Optional[str]:
        """
        Chat with prompt-based tool support.

        Args:
            message: User's message
            model: Model ID
            max_iterations: Max tool call iterations

        Returns:
            Final assistant response
        """
        if not self.enable_tools or not self.tool_manager:
            return await self._chat_without_tools(message, model)

        # Add user message
        self.conversation_history.append({
            "role": "user",
            "content": message
        })

        iteration = 0
        while iteration < max_iterations:
            iteration += 1

            try:
                # Build messages with tool instructions
                messages = self._build_messages_with_tools()

                # Call API
                response = self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    stream=False
                )

                assistant_message = response.choices[0].message.content

                # Check if the response contains a tool call
                tool_call = self._parse_tool_call(assistant_message)

                if tool_call:
                    # Model wants to use a tool
                    tool_name = tool_call["tool"]
                    tool_args = tool_call["arguments"]

                    console.print(f"\n[cyan]Calling tool:[/cyan] {tool_name}({tool_args})")

                    # Execute the tool
                    try:
                        result = await self.tool_manager.execute_tool(tool_name, tool_args)
                        result_str = str(result)
                        console.print(f"[green]Tool result:[/green] {result_str[:200]}" + ("..." if len(result_str) > 200 else ""))

                        # Add assistant's tool call and result to history
                        self.conversation_history.append({
                            "role": "assistant",
                            "content": f"[Tool Call: {tool_name}]\n```json\n{json.dumps(tool_call, indent=2)}\n```"
                        })

                        self.conversation_history.append({
                            "role": "user",
                            "content": f"[Tool Result for {tool_name}]\n```\n{result_str}\n```\n\nNow provide your final answer based on this result."
                        })

                    except Exception as e:
                        error_msg = f"Error executing tool: {str(e)}"
                        console.print(f"[red]{error_msg}[/red]")

                        self.conversation_history.append({
                            "role": "user",
                            "content": f"[Tool Error]\n{error_msg}\n\nPlease provide an answer without using that tool."
                        })

                    # Continue loop to get response after tool execution
                    continue

                else:
                    # No tool call, this is the final response
                    console.print("\n[bold cyan]Assistant:[/bold cyan]")
                    if assistant_message.strip():
                        console.print(Markdown(assistant_message))
                    console.print()

                    self.conversation_history.append({
                        "role": "assistant",
                        "content": assistant_message
                    })

                    return assistant_message

            except Exception as e:
                console.print(f"[red]Error: {str(e)}[/red]")
                if self.conversation_history and self.conversation_history[-1]["role"] == "user":
                    self.conversation_history.pop()
                return None

        console.print("[yellow]Warning: Maximum tool iterations reached[/yellow]")
        return None

    def _build_messages_with_tools(self) -> List[Dict[str, str]]:
        """Build message list with tool instructions."""
        messages = []

        # Add tool instructions as system message
        tools_prompt = self._get_tools_prompt()
        if tools_prompt:
            messages.append({
                "role": "system",
                "content": tools_prompt
            })

        # Add conversation history
        messages.extend(self.conversation_history)

        return messages

    def _parse_tool_call(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Parse a tool call from model response.

        Looks for JSON code blocks with tool calls.
        """
        # Look for JSON code blocks
        json_pattern = r'```json\s*(\{.*?\})\s*```'
        matches = re.findall(json_pattern, text, re.DOTALL)

        for match in matches:
            try:
                data = json.loads(match)
                if "tool" in data and "arguments" in data:
                    # Valid tool call
                    if data["tool"] in self.tool_manager.tools:
                        return data
            except json.JSONDecodeError:
                continue

        return None

    async def _chat_without_tools(self, message: str, model: str) -> Optional[str]:
        """Chat without tools."""
        self.conversation_history.append({
            "role": "user",
            "content": message
        })

        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=self.conversation_history,
                stream=False
            )

            assistant_message = response.choices[0].message.content

            console.print("\n[bold cyan]Assistant:[/bold cyan]")
            if assistant_message.strip():
                console.print(Markdown(assistant_message))
            console.print()

            self.conversation_history.append({
                "role": "assistant",
                "content": assistant_message
            })

            return assistant_message

        except Exception as e:
            console.print(f"[red]Error: {str(e)}[/red]")
            self.conversation_history.pop()
            return None

    def clear_history(self):
        """Clear conversation history."""
        self.conversation_history = []

    async def cleanup(self):
        """Clean up resources."""
        if self.tool_manager:
            await self.tool_manager.cleanup()


# Example usage
async def example():
    """Example of prompt-based tool usage."""
    import os
    from dotenv import load_dotenv

    load_dotenv()
    api_key = os.getenv("PERPLEXITY_API_KEY")

    client = PerplexityClientPromptTools(
        api_key=api_key,
        enable_tools=True
    )

    await client.initialize_tools()

    console.print(Panel("Testing prompt-based tools", border_style="cyan"))

    # Test 1: File search
    await client.chat_with_tools(
        "Please use the search_files tool to find all Python files in the current directory.",
        model="sonar-pro"
    )

    # Test 2: Calculator
    await client.chat_with_tools(
        "What is 1234 times 5678? Use the calculator tool.",
        model="sonar-pro"
    )

    await client.cleanup()


if __name__ == "__main__":
    asyncio.run(example())
