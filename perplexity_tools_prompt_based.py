"""
AI Client with Prompt-Based Tool Support

Since some providers don't support OpenAI function calling, this uses
prompt engineering to enable tool usage:
1. Tools described in system prompt
2. Model responds with structured tool calls in text
3. We parse and execute the calls
4. Results fed back to the conversation
"""

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Optional, List, Dict, Any
import httpx
from openai import OpenAI
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from datetime import datetime

from tool_manager import ToolManager
from ppxai.config import EXPORTS_DIR, SESSIONS_DIR

console = Console()


class PerplexityClientPromptTools:
    """
    AI client with prompt-based tool support.
    Works around lack of native function calling.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.perplexity.ai",
        session_name: Optional[str] = None,
        enable_tools: bool = False,
        provider: str = None
    ):
        """Initialize the client with optional tool support."""
        # Check if SSL verification should be disabled
        # Use SSL_VERIFY environment variable (applies to all HTTPS connections)
        ssl_verify = os.getenv("SSL_VERIFY", "true").lower() != "false"

        if not ssl_verify:
            # Create custom httpx client with SSL verification disabled
            http_client = httpx.Client(verify=False)
            self.client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                http_client=http_client
            )
        else:
            self.client = OpenAI(
                api_key=api_key,
                base_url=base_url
            )
        self.base_url = base_url
        self.provider = provider or "perplexity"
        self.conversation_history = []
        self.session_name = session_name or f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.enable_tools = enable_tools
        self.tool_manager = ToolManager() if enable_tools else None
        # Add session metadata and usage tracking for compatibility with AIClient
        self.session_metadata = {
            "created_at": datetime.now().isoformat(),
            "model": None,
            "provider": self.provider,
            "message_count": 0
        }
        self.current_session_usage = {
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "estimated_cost": 0.0
        }
        self.auto_route = True
        # Tool configuration
        self.tool_max_iterations = 15  # Default max tool calls per query

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

        # Register built-in tools (pass provider to conditionally register web tools)
        self._register_builtin_tools()

        console.print(f"[green]Tools initialized:[/green] {len(self.tool_manager.tools)} tools available")
        for tool_info in self.tool_manager.list_tools():
            console.print(f"  * {tool_info['name']}: {tool_info['description']}")

        # Note about Perplexity's built-in search
        if self.provider == "perplexity":
            console.print(f"[dim]Note: Perplexity has built-in web search - just ask questions directly![/dim]")
        console.print()

    def _register_builtin_tools(self):
        """Register built-in tools based on provider capabilities."""
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
        def read_file(filepath: str, max_lines: int = 500) -> str:
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
                    "max_lines": {"type": "integer", "description": "Max lines (default: 500)"}
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

        # =====================================================================
        # Date/Time tool with timezone support
        # =====================================================================
        def get_datetime(timezone: str = "UTC") -> str:
            """Get current date and time with timezone support."""
            from datetime import datetime
            try:
                import zoneinfo
                tz = zoneinfo.ZoneInfo(timezone)
            except Exception:
                # Fallback for older Python or invalid timezone
                try:
                    import pytz
                    tz = pytz.timezone(timezone)
                except Exception:
                    return f"Error: Invalid timezone '{timezone}'. Use IANA format like 'Europe/Zurich', 'America/New_York', 'UTC'"

            now = datetime.now(tz)
            return (
                f"Current date and time in {timezone}:\n"
                f"  Date: {now.strftime('%A, %B %d, %Y')}\n"
                f"  Time: {now.strftime('%H:%M:%S')}\n"
                f"  ISO format: {now.isoformat()}\n"
                f"  Unix timestamp: {int(now.timestamp())}"
            )

        self.tool_manager.register_builtin_tool(
            name="get_datetime",
            description="Get the current date and time with timezone support. Use IANA timezone names like 'Europe/Zurich', 'America/New_York', 'Asia/Tokyo', 'UTC'",
            parameters={
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": "IANA timezone name (default: 'UTC'). Examples: 'Europe/Zurich', 'America/New_York', 'Asia/Tokyo'"
                    }
                },
                "required": []
            },
            handler=get_datetime
        )

        # =====================================================================
        # Shell command execution tool (universal - available to all providers)
        # =====================================================================
        def execute_shell_command(command: str, working_dir: str = None) -> str:
            """Execute a shell command and return the output.

            Args:
                command: The shell command to execute
                working_dir: Optional working directory for the command

            Returns:
                str: Command output (stdout + stderr) or error message
            """
            try:
                import platform
                import os
                import subprocess

                # List of interactive commands that require user input
                interactive_commands = [
                    'nano', 'vim', 'vi', 'emacs', 'pico', 'joe',  # Text editors
                    'less', 'more',  # Pagers
                    'top', 'htop', 'btop',  # System monitors
                    'python', 'python3', 'ipython', 'node', 'irb', 'ruby',  # REPLs (without args)
                    'ssh', 'telnet', 'ftp', 'sftp',  # Remote connections
                    'mysql', 'psql', 'mongo', 'redis-cli',  # Database CLIs
                    'bash', 'zsh', 'sh', 'fish', 'csh', 'tcsh',  # Shells (without args)
                ]

                # Extract the base command (first word)
                cmd_parts = command.strip().split()
                if cmd_parts:
                    base_cmd = os.path.basename(cmd_parts[0].lower())

                    # Check if it's an interactive command
                    if base_cmd in interactive_commands:
                        # Some commands are only interactive without arguments
                        repl_commands = ['python', 'python3', 'ipython', 'node', 'irb', 'ruby', 'bash', 'zsh', 'sh', 'fish', 'csh', 'tcsh']
                        if base_cmd in repl_commands and len(cmd_parts) > 1:
                            # Has arguments, likely not interactive (e.g., 'python script.py')
                            pass
                        else:
                            return (
                                f"Error: '{base_cmd}' is an interactive command that requires user input.\n\n"
                                f"Interactive commands like text editors (nano, vim), REPLs (python, node), "
                                f"and pagers (less, more) cannot be run through this tool because they "
                                f"require keyboard input and have a 30-second timeout.\n\n"
                                f"Alternatives:\n"
                                f"- To view file contents: use 'cat <file>' or the read_file tool\n"
                                f"- To edit files: describe the changes you want and I'll help modify the file\n"
                                f"- To run scripts: use 'python script.py' or 'node script.js' with arguments"
                            )

                # Determine shell based on platform
                is_windows = platform.system() == "Windows"

                # Change to working directory if specified
                original_dir = None
                if working_dir:
                    original_dir = os.getcwd()
                    if not os.path.isdir(working_dir):
                        return f"Error: Working directory does not exist: {working_dir}"
                    os.chdir(working_dir)

                try:
                    # Execute command with shell
                    result = subprocess.run(
                        command,
                        shell=True,
                        capture_output=True,
                        text=True,
                        timeout=30,  # 30 second timeout
                        encoding='utf-8' if not is_windows else None,
                        errors='replace'  # Replace encoding errors
                    )

                    # Combine stdout and stderr
                    output = ""
                    if result.stdout:
                        output += result.stdout
                    if result.stderr:
                        if output:
                            output += "\n--- stderr ---\n"
                        output += result.stderr

                    # Add return code if non-zero
                    if result.returncode != 0:
                        output += f"\n\nCommand exited with code: {result.returncode}"

                    return output if output else f"Command completed successfully (exit code: {result.returncode})"

                finally:
                    # Restore original directory
                    if original_dir:
                        os.chdir(original_dir)

            except subprocess.TimeoutExpired:
                return "Error: Command timed out after 30 seconds"
            except Exception as e:
                return f"Error executing command: {str(e)}"

        self.tool_manager.register_builtin_tool(
            name="execute_shell_command",
            description="Execute a shell command in the system. Supports Windows (cmd/PowerShell) and Unix (bash) commands. Use for system operations like creating directories, file operations, running scripts, etc. Commands run with a 30-second timeout. Note: Interactive commands (nano, vim, less, python REPL, etc.) are not supported - use non-interactive alternatives.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute (e.g., 'mkdir new_folder', 'dir', 'ls -la', 'git status')"
                    },
                    "working_dir": {
                        "type": "string",
                        "description": "Optional working directory path where the command should be executed"
                    }
                },
                "required": ["command"]
            },
            handler=execute_shell_command
        )

        # =====================================================================
        # Web-enabled tools (registered based on provider capabilities)
        # Only register tools for capabilities the provider doesn't have natively
        # =====================================================================
        self._register_web_tools()

    def _register_web_tools(self):
        """Register web-enabled tools based on provider capabilities.

        Only registers tools for capabilities the provider doesn't have natively.
        This is configured in ppxai/config.py under each provider's 'capabilities' dict.
        """
        # Import capability checker from config
        try:
            from ppxai.config import provider_needs_tool, get_provider_capabilities
        except ImportError:
            # Fallback for standalone usage
            def provider_needs_tool(provider, category):
                return provider != "perplexity"
            def get_provider_capabilities(provider):
                return {}

        capabilities = get_provider_capabilities(self.provider)

        # Show which capabilities this provider has natively
        native_caps = [k for k, v in capabilities.items() if v]
        if native_caps:
            console.print(f"[dim]Provider has native: {', '.join(native_caps)}[/dim]")

        # =====================================================================
        # Weather forecast tool using wttr.in (free, no API key required)
        # Only register if provider doesn't have native weather capability
        # =====================================================================
        if provider_needs_tool(self.provider, "weather"):
            self._register_weather_tool()

        # =====================================================================
        # Web search tool using DuckDuckGo (no API key required)
        # Only register if provider doesn't have native web search
        # =====================================================================
        if provider_needs_tool(self.provider, "web_search"):
            self._register_web_search_tool()

        # =====================================================================
        # URL fetch tool to read web pages
        # Only register if provider doesn't have native web fetch
        # =====================================================================
        if provider_needs_tool(self.provider, "web_fetch"):
            self._register_fetch_url_tool()

    def _register_weather_tool(self):
        """Register weather forecast tool using wttr.in."""
        def get_weather(location: str, format: str = "short") -> str:
            """Get weather forecast for a location using wttr.in."""
            import urllib.request
            import urllib.error
            import ssl

            # Create SSL context that doesn't verify (for corporate proxies)
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            try:
                # wttr.in format options:
                # ?format=3 - short one-line (City: condition temp)
                # ?format=4 - one-line with more info
                # ?0 - current weather only (no forecast)
                # ?1 - current + 1 day forecast
                # ?2 - current + 2 day forecast (default)
                if format == "short":
                    url = f"https://wttr.in/{urllib.parse.quote(location)}?format=4"
                elif format == "detailed":
                    url = f"https://wttr.in/{urllib.parse.quote(location)}?0&m"  # metric, current only
                else:
                    url = f"https://wttr.in/{urllib.parse.quote(location)}?2&m"  # 2-day forecast, metric

                # Set a reasonable timeout and user agent
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "curl/7.68.0"}  # wttr.in prefers curl-like UA
                )

                with urllib.request.urlopen(req, timeout=10, context=ssl_context) as response:
                    result = response.read().decode('utf-8')

                # Clean up ANSI codes if present
                import re
                result = re.sub(r'\x1b\[[0-9;]*m', '', result)

                return f"Weather for {location}:\n{result}"

            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return f"Error: Location '{location}' not found. Try a different city name or format like 'Geneva,Switzerland'"
                return f"Error fetching weather: HTTP {e.code}"
            except urllib.error.URLError as e:
                return f"Error: Could not connect to weather service. {str(e.reason)}"
            except Exception as e:
                return f"Error getting weather: {str(e)}"

        self.tool_manager.register_builtin_tool(
            name="get_weather",
            description="Get current weather and forecast for a location. Uses wttr.in service (no API key needed)",
            parameters={
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "City name, optionally with country (e.g., 'Geneva', 'Geneva,Switzerland', 'New York', 'Tokyo')"
                    },
                    "format": {
                        "type": "string",
                        "description": "Output format: 'short' (one line), 'detailed' (current only), 'forecast' (2-day forecast)",
                        "enum": ["short", "detailed", "forecast"]
                    }
                },
                "required": ["location"]
            },
            handler=get_weather
        )

    def _register_web_search_tool(self):
        """Register web search tool using DuckDuckGo."""
        def web_search(query: str, num_results: int = 5) -> str:
            """Search the web using DuckDuckGo."""
            import urllib.request
            import urllib.parse
            import urllib.error
            import ssl
            import re

            # Create SSL context
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            try:
                # Use DuckDuckGo HTML search (more reliable than API)
                encoded_query = urllib.parse.quote_plus(query)
                url = f"https://html.duckduckgo.com/html/?q={encoded_query}"

                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    }
                )

                with urllib.request.urlopen(req, timeout=15, context=ssl_context) as response:
                    html = response.read().decode('utf-8')

                # Parse results from HTML
                results = []

                # Find result blocks
                result_pattern = r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>([^<]*)</a>'
                snippet_pattern = r'<a[^>]*class="result__snippet"[^>]*>([^<]*(?:<[^>]*>[^<]*)*)</a>'

                links = re.findall(result_pattern, html)
                snippets = re.findall(snippet_pattern, html)

                for i, (link, title) in enumerate(links[:num_results]):
                    # Clean up the redirect URL
                    if 'uddg=' in link:
                        # Extract actual URL from DuckDuckGo redirect
                        match = re.search(r'uddg=([^&]*)', link)
                        if match:
                            link = urllib.parse.unquote(match.group(1))

                    # Get snippet if available
                    snippet = ""
                    if i < len(snippets):
                        snippet = re.sub(r'<[^>]*>', '', snippets[i])  # Remove HTML tags
                        snippet = snippet.strip()[:200]

                    results.append(f"{i+1}. {title}\n   URL: {link}\n   {snippet}\n")

                if not results:
                    return f"No results found for '{query}'"

                return f"Search results for '{query}':\n\n" + "\n".join(results)

            except urllib.error.URLError as e:
                return f"Error: Could not connect to search service. {str(e.reason)}"
            except Exception as e:
                return f"Error searching: {str(e)}"

        self.tool_manager.register_builtin_tool(
            name="web_search",
            description="Search the web using DuckDuckGo. Returns titles, URLs, and snippets of top results",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (e.g., 'Python tutorials', 'weather API documentation')"
                    },
                    "num_results": {
                        "type": "integer",
                        "description": "Number of results to return (default: 5, max: 10)"
                    }
                },
                "required": ["query"]
            },
            handler=web_search
        )

    def _register_fetch_url_tool(self):
        """Register URL fetch tool to read web pages."""
        def fetch_url(url: str, max_length: int = 5000) -> str:
            """Fetch and extract text content from a URL."""
            import urllib.request
            import urllib.error
            import ssl
            import re

            # Create SSL context
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    }
                )

                with urllib.request.urlopen(req, timeout=15, context=ssl_context) as response:
                    content_type = response.headers.get('Content-Type', '')
                    if 'text/html' not in content_type and 'text/plain' not in content_type:
                        return f"Error: URL returns non-text content ({content_type})"

                    html = response.read().decode('utf-8', errors='ignore')

                # Extract title
                title_match = re.search(r'<title[^>]*>([^<]*)</title>', html, re.IGNORECASE)
                title = title_match.group(1).strip() if title_match else "No title"

                # Remove script and style elements
                html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
                html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
                html = re.sub(r'<nav[^>]*>.*?</nav>', '', html, flags=re.DOTALL | re.IGNORECASE)
                html = re.sub(r'<footer[^>]*>.*?</footer>', '', html, flags=re.DOTALL | re.IGNORECASE)

                # Remove HTML tags
                text = re.sub(r'<[^>]+>', ' ', html)

                # Clean up whitespace
                text = re.sub(r'\s+', ' ', text).strip()

                # Truncate if too long
                if len(text) > max_length:
                    text = text[:max_length] + "... [truncated]"

                return f"Title: {title}\nURL: {url}\n\nContent:\n{text}"

            except urllib.error.HTTPError as e:
                return f"Error: HTTP {e.code} - {e.reason}"
            except urllib.error.URLError as e:
                return f"Error: Could not connect to URL. {str(e.reason)}"
            except Exception as e:
                return f"Error fetching URL: {str(e)}"

        self.tool_manager.register_builtin_tool(
            name="fetch_url",
            description="Fetch and read the text content of a web page URL",
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Full URL to fetch (e.g., 'https://example.com/page')"
                    },
                    "max_length": {
                        "type": "integer",
                        "description": "Maximum characters to return (default: 5000)"
                    }
                },
                "required": ["url"]
            },
            handler=fetch_url
        )

    def _get_tools_prompt(self) -> str:
        """Generate a system prompt describing available tools."""
        if not self.tool_manager or not self.tool_manager.tools:
            return ""

        tools_desc = "# IMPORTANT: You Have Access to Tools\n\n"
        tools_desc += "You MUST use these tools when the user asks for information you don't have access to natively.\n"
        tools_desc += "You are an AI assistant with tool capabilities. When you need real-time information (like current time, weather, web pages), you MUST call the appropriate tool.\n\n"
        tools_desc += "## How to Call a Tool\n\n"
        tools_desc += "To use a tool, respond ONLY with a JSON code block in this exact format:\n\n"
        tools_desc += "```json\n{\n  \"tool\": \"tool_name\",\n  \"arguments\": {\"param\": \"value\"}\n}\n```\n\n"
        tools_desc += "## Available Tools:\n\n"

        for name, tool_def in self.tool_manager.tools.items():
            tools_desc += f"### {name}\n"
            tools_desc += f"{tool_def.description}\n"
            if tool_def.parameters.get("properties"):
                tools_desc += "Parameters:\n"
                for param, info in tool_def.parameters["properties"].items():
                    required = "required" if param in tool_def.parameters.get("required", []) else "optional"
                    tools_desc += f"  - `{param}` ({required}): {info.get('description', '')}\n"
            tools_desc += "\n"

        tools_desc += "## CRITICAL INSTRUCTIONS:\n\n"
        tools_desc += "1. **For date/time questions**: ALWAYS use the `get_datetime` tool. Do NOT say you don't have access.\n"
        tools_desc += "2. **For weather questions**: ALWAYS use the `get_weather` tool. Do NOT say you can't access weather.\n"
        tools_desc += "3. **For web searches**: Use the `web_search` tool to find current information.\n"
        tools_desc += "4. **For reading web pages**: Use the `fetch_url` tool to read URL contents.\n"
        tools_desc += "5. **For system operations**: Use the `execute_shell_command` tool to run commands, create directories, file operations, etc.\n"
        tools_desc += "6. When calling a tool, output ONLY the JSON block, nothing else.\n"
        tools_desc += "7. After receiving tool results, provide a helpful response based on that data.\n"
        tools_desc += "8. NEVER say 'I don't have access to real-time data' or 'I can't execute commands' - you DO have access via these tools!\n"

        return tools_desc

    def _suggest_tools_for_query(self, query: str) -> List[str]:
        """Suggest which tools might be useful for a given query.

        Returns a list of tool names that could help answer the query.
        """
        if not self.tool_manager:
            return []

        query_lower = query.lower()
        suggestions = []

        # Keywords that suggest date/time tool
        datetime_keywords = ['time', 'date', 'today', 'now', 'current time', 'what day', 'timezone', 'clock']
        if any(kw in query_lower for kw in datetime_keywords):
            if 'get_datetime' in self.tool_manager.tools:
                suggestions.append('get_datetime')

        # Keywords that suggest weather tool
        weather_keywords = ['weather', 'forecast', 'temperature', 'rain', 'sunny', 'cloudy', 'snow', 'humidity', 'wind']
        if any(kw in query_lower for kw in weather_keywords):
            if 'get_weather' in self.tool_manager.tools:
                suggestions.append('get_weather')

        # Keywords that suggest web search
        search_keywords = ['search', 'find', 'look up', 'google', 'latest', 'news', 'current events', 'recent']
        if any(kw in query_lower for kw in search_keywords):
            if 'web_search' in self.tool_manager.tools:
                suggestions.append('web_search')

        # Keywords that suggest URL fetch
        url_keywords = ['url', 'website', 'webpage', 'http', 'https', 'link', 'page content', 'read this']
        if any(kw in query_lower for kw in url_keywords):
            if 'fetch_url' in self.tool_manager.tools:
                suggestions.append('fetch_url')

        # Keywords that suggest file operations
        file_keywords = ['file', 'read', 'open', 'contents of', 'show me']
        if any(kw in query_lower for kw in file_keywords):
            if 'read_file' in self.tool_manager.tools:
                suggestions.append('read_file')

        # Keywords that suggest calculator
        calc_keywords = ['calculate', 'math', 'compute', 'multiply', 'divide', 'add', 'subtract', 'sum', 'plus', 'minus', 'times']
        if any(kw in query_lower for kw in calc_keywords):
            if 'calculator' in self.tool_manager.tools:
                suggestions.append('calculator')

        # Keywords that suggest directory listing
        dir_keywords = ['list files', 'directory', 'folder', 'ls', 'dir', 'what files']
        if any(kw in query_lower for kw in dir_keywords):
            if 'list_directory' in self.tool_manager.tools:
                suggestions.append('list_directory')

        # Keywords that suggest file search
        search_file_keywords = ['find files', 'search files', 'locate', '*.py', '*.txt', 'glob']
        if any(kw in query_lower for kw in search_file_keywords):
            if 'search_files' in self.tool_manager.tools:
                suggestions.append('search_files')

        # Keywords that suggest shell command execution
        shell_keywords = ['mkdir', 'create directory', 'delete', 'remove', 'move', 'copy', 'rename',
                         'execute', 'run', 'command', 'shell', 'bash', 'cmd', 'powershell',
                         'git', 'npm', 'pip', 'install', 'build', 'compile', 'make']
        if any(kw in query_lower for kw in shell_keywords):
            if 'execute_shell_command' in self.tool_manager.tools:
                suggestions.append('execute_shell_command')

        return suggestions

    async def chat_with_tools(
        self,
        message: str,
        model: str,
        max_iterations: int = None
    ) -> Optional[str]:
        """
        Chat with prompt-based tool support.

        Args:
            message: User's message
            model: Model ID
            max_iterations: Max tool call iterations (uses self.tool_max_iterations if None)

        Returns:
            Final assistant response
        """
        import time
        start_time = time.time()

        if not self.enable_tools or not self.tool_manager:
            return await self._chat_without_tools(message, model)

        # Use instance default if not specified
        if max_iterations is None:
            max_iterations = self.tool_max_iterations

        # Show suggested tools for this query
        suggested_tools = self._suggest_tools_for_query(message)
        if suggested_tools:
            tools_str = ", ".join(suggested_tools)
            console.print(f"[dim]💡 Relevant tools for this query: {tools_str}[/dim]")

        # Add user message with tool hint if relevant tools detected
        user_content = message
        if suggested_tools:
            # Add a hint to the model about which tool to use
            tool_hint = f"\n\n[System hint: Use the {suggested_tools[0]} tool to answer this question. Respond with the JSON tool call.]"
            user_content = message + tool_hint

        self.conversation_history.append({
            "role": "user",
            "content": user_content
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

                        # Add assistant's tool call attempt to history
                        self.conversation_history.append({
                            "role": "assistant",
                            "content": f"[Tool Call: {tool_name}]\n```json\n{json.dumps(tool_call, indent=2)}\n```"
                        })

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

                    # Show response time
                    elapsed = time.time() - start_time
                    console.print(f"[dim]({elapsed:.1f}s)[/dim]\n")

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
        # Ensure history ends with assistant message to maintain alternation
        if self.conversation_history and self.conversation_history[-1]["role"] == "user":
            self.conversation_history.append({
                "role": "assistant",
                "content": "[Tool iterations limit reached. Please try again with a simpler query or increase max_iterations with '/tools config max_iterations <number>'.]"
            })
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

        Looks for JSON in code blocks or raw JSON with tool/arguments keys.
        Also handles cases where model puts parameters at top level instead of in 'arguments'.
        """
        def normalize_tool_call(data: dict) -> Optional[dict]:
            """Normalize tool call to expected format with 'tool' and 'arguments' keys."""
            if "tool" not in data:
                return None
            tool_name = data["tool"]
            if tool_name not in self.tool_manager.tools:
                return None

            # Already has arguments key - return as-is
            if "arguments" in data:
                return data

            # Model put parameters at top level - extract them into 'arguments'
            # Get expected parameters for this tool
            tool_def = self.tool_manager.tools[tool_name]
            expected_params = set(tool_def.parameters.get("properties", {}).keys())

            # Extract parameters from top level
            arguments = {}
            for key, value in data.items():
                if key != "tool" and key in expected_params:
                    arguments[key] = value

            # If we found any expected parameters, normalize the format
            if arguments:
                return {"tool": tool_name, "arguments": arguments}

            return None

        # First, try to find JSON in code blocks (```json ... ```)
        json_pattern = r'```(?:json)?\s*(\{.*?\})\s*```'
        matches = re.findall(json_pattern, text, re.DOTALL)

        for match in matches:
            try:
                data = json.loads(match)
                normalized = normalize_tool_call(data)
                if normalized:
                    return normalized
            except json.JSONDecodeError:
                continue

        # If no code block found, try to find raw JSON object with tool key
        # This handles models that output JSON without markdown formatting
        raw_json_pattern = r'\{\s*"tool"\s*:\s*"[^"]+"\s*[^}]*\}'
        raw_matches = re.findall(raw_json_pattern, text, re.DOTALL)

        for match in raw_matches:
            try:
                data = json.loads(match)
                normalized = normalize_tool_call(data)
                if normalized:
                    return normalized
            except json.JSONDecodeError:
                continue

        # Last resort: try to parse the entire response as JSON
        text_stripped = text.strip()
        if text_stripped.startswith('{') and text_stripped.endswith('}'):
            try:
                data = json.loads(text_stripped)
                normalized = normalize_tool_call(data)
                if normalized:
                    return normalized
            except json.JSONDecodeError:
                pass

        return None

    async def _chat_without_tools(self, message: str, model: str) -> Optional[str]:
        """Chat without tools."""
        import time
        start_time = time.time()

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

            # Show response time
            elapsed = time.time() - start_time
            console.print(f"[dim]({elapsed:.1f}s)[/dim]\n")

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

    def get_usage_summary(self) -> Dict:
        """Get current session usage summary."""
        return self.current_session_usage.copy()

    def export_conversation(self, filename: Optional[str] = None) -> Path:
        """Export conversation to a markdown file."""
        if not filename:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"conversation_{timestamp}.md"

        filepath = EXPORTS_DIR / filename

        # Build markdown content
        content = f"# Conversation Export\n\n"
        content += f"**Exported:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        content += f"**Session:** {self.session_name}\n"
        if self.session_metadata.get("model"):
            content += f"**Model:** {self.session_metadata['model']}\n"
        content += f"**Messages:** {len(self.conversation_history)}\n\n"

        # Add usage stats
        usage = self.get_usage_summary()
        content += f"## Usage Statistics\n\n"
        content += f"- Total Tokens: {usage['total_tokens']:,}\n"
        content += f"- Prompt Tokens: {usage['prompt_tokens']:,}\n"
        content += f"- Completion Tokens: {usage['completion_tokens']:,}\n"
        content += f"- Estimated Cost: ${usage['estimated_cost']:.4f}\n\n"

        content += "---\n\n"

        # Add conversation
        content += "## Conversation\n\n"
        for msg in self.conversation_history:
            role = msg['role'].capitalize()
            content_text = msg['content']
            content += f"### {role}\n\n{content_text}\n\n"

        # Write to file
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

        return filepath

    def save_session(self) -> Path:
        """Save current session to a JSON file."""
        filepath = SESSIONS_DIR / f"{self.session_name}.json"

        session_data = {
            "session_name": self.session_name,
            "metadata": self.session_metadata,
            "conversation_history": self.conversation_history,
            "usage": self.current_session_usage,
            "saved_at": datetime.now().isoformat()
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(session_data, f, indent=2)

        return filepath

    def chat(self, message: str, model: str, stream: bool = True):
        """
        Synchronous chat method for compatibility with AIClient.

        When tools are enabled, this uses the async chat_with_tools internally.
        Otherwise, it performs a simple chat request.

        Args:
            message: The user's message
            model: The model ID to use
            stream: Whether to stream the response (used only when tools disabled)

        Returns:
            The assistant's response
        """
        if self.enable_tools and self.tool_manager:
            # Use async tool-enabled chat
            return asyncio.run(self.chat_with_tools(message, model))
        else:
            # Simple non-tool chat
            self.conversation_history.append({
                "role": "user",
                "content": message
            })

            try:
                if stream:
                    return self._stream_response(model)
                else:
                    return self._simple_response(model)
            except Exception as e:
                console.print(f"[red]Error: {str(e)}[/red]")
                self.conversation_history.pop()
                return None

    def _stream_response(self, model: str):
        """Stream the response from the API."""
        response_chunks = []

        response_stream = self.client.chat.completions.create(
            model=model,
            messages=self.conversation_history,
            stream=True
        )

        console.print("\n[bold cyan]Assistant:[/bold cyan] [dim](streaming...)[/dim]")
        for chunk in response_stream:
            if chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                response_chunks.append(content)
                console.print(".", end="", style="dim")

        console.print("\n")
        full_response = "".join(response_chunks)

        if full_response.strip():
            console.print(Markdown(full_response))

        self.conversation_history.append({
            "role": "assistant",
            "content": full_response
        })

        return full_response

    def _simple_response(self, model: str):
        """Get a non-streaming response from the API."""
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
