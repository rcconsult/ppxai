"""
Tool manager for the ppxai engine.

Handles tool registration, filtering by provider, and execution.
"""

from typing import Dict, List, Optional, Any
from .base import BaseTool, FunctionTool
from ..types import Event, EventType, ToolCallInfo


class ToolManager:
    """Manages tool registration and execution.

    Tools are provider-aware and filtered based on current provider's capabilities.
    """

    def __init__(self):
        """Initialize the tool manager."""
        self._tools: Dict[str, BaseTool] = {}
        self._provider: Optional[str] = None
        self.max_iterations: int = 15

    def register_tool(self, tool: BaseTool):
        """Register a tool.

        Args:
            tool: Tool instance to register
        """
        self._tools[tool.name] = tool

    def register_function(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        handler: callable,
        provider_specific: Optional[List[str]] = None,
        provider_excluded: Optional[List[str]] = None
    ):
        """Register a function as a tool.

        Args:
            name: Tool name
            description: Tool description
            parameters: JSON Schema for parameters
            handler: Function to execute
            provider_specific: Only for these providers
            provider_excluded: Excluded for these providers
        """
        tool = FunctionTool(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
            provider_specific=provider_specific,
            provider_excluded=provider_excluded
        )
        self.register_tool(tool)

    def set_provider(self, provider: str):
        """Set current provider (filters available tools).

        Args:
            provider: Provider name
        """
        self._provider = provider

    def get_tool(self, name: str) -> Optional[BaseTool]:
        """Get a specific tool by name.

        Args:
            name: Tool name

        Returns:
            Tool if found and available, None otherwise
        """
        tool = self._tools.get(name)
        if tool is None:
            return None
        if self._provider and not tool.is_available_for(self._provider):
            return None
        return tool

    def get_available_tools(self) -> List[BaseTool]:
        """Get tools available for current provider.

        Returns:
            List of available tools
        """
        if self._provider is None:
            return list(self._tools.values())
        return [t for t in self._tools.values() if t.is_available_for(self._provider)]

    def list_tools(self) -> List[Dict[str, Any]]:
        """List available tools as dictionaries.

        Returns:
            List of tool info dicts with name and description
        """
        return [
            {"name": t.name, "description": t.description}
            for t in self.get_available_tools()
        ]

    async def execute_tool(self, name: str, **kwargs) -> str:
        """Execute a tool by name.

        Args:
            name: Tool name
            **kwargs: Tool arguments

        Returns:
            Tool result as string

        Raises:
            ValueError: If tool not found or not available
        """
        tool = self.get_tool(name)
        if not tool:
            raise ValueError(f"Tool not found or not available: {name}")
        return await tool.execute(**kwargs)

    def get_tools_prompt(self) -> str:
        """Generate system prompt describing available tools.

        Returns:
            System prompt text for tool usage
        """
        tools = self.get_available_tools()
        if not tools:
            return ""

        prompt = "# IMPORTANT: You Have Access to Tools\n\n"
        prompt += "You MUST use these tools when the user asks for information you don't have access to natively.\n"
        prompt += "You are an AI assistant with tool capabilities. When you need real-time information (like current time, weather, web pages), you MUST call the appropriate tool.\n\n"
        prompt += "## How to Call a Tool\n\n"
        prompt += "To use a tool, respond ONLY with a JSON code block in this exact format:\n\n"
        prompt += "```json\n{\n  \"tool\": \"tool_name\",\n  \"arguments\": {\"param\": \"value\"}\n}\n```\n\n"
        prompt += "## Available Tools:\n\n"

        for tool in tools:
            prompt += f"### {tool.name}\n"
            prompt += f"{tool.description}\n"
            if tool.parameters.get("properties"):
                prompt += "Parameters:\n"
                for param, info in tool.parameters["properties"].items():
                    required = "required" if param in tool.parameters.get("required", []) else "optional"
                    prompt += f"  - `{param}` ({required}): {info.get('description', '')}\n"
            prompt += "\n"

        prompt += "## CRITICAL INSTRUCTIONS:\n\n"
        prompt += "1. **For date/time questions**: ALWAYS use the `get_datetime` tool. Do NOT say you don't have access.\n"
        prompt += "2. **For weather questions**: ALWAYS use the `get_weather` tool. Do NOT say you can't access weather.\n"
        prompt += "3. **For web searches**: Use the `web_search` tool to find current information.\n"
        prompt += "4. **For reading web pages**: Use the `fetch_url` tool to read URL contents.\n"
        prompt += "5. **For system operations**: Use the `execute_shell_command` tool to run commands, create directories, file operations, etc.\n"
        prompt += "6. When calling a tool, output ONLY the JSON block, nothing else.\n"
        prompt += "7. After receiving tool results, provide a helpful response based on that data.\n"
        prompt += "8. NEVER say 'I don't have access to real-time data' or 'I can't execute commands' - you DO have access via these tools!\n"

        return prompt

    def clear(self):
        """Remove all registered tools."""
        self._tools.clear()

    async def cleanup(self):
        """Clean up resources (for MCP tools, etc)."""
        # Placeholder for future MCP cleanup
        pass
