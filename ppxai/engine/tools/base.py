"""
Base tool abstract class.

All tools must implement this interface.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List


class BaseTool(ABC):
    """Abstract base class for all tools.

    Tools can be:
    - Universal: Available to all providers
    - Provider-specific: Only for certain providers
    - Provider-excluded: Not for certain providers (they have native capability)
    """

    # Tool metadata (override in subclasses)
    name: str = "base_tool"
    description: str = "Base tool description"
    parameters: Dict[str, Any] = {"type": "object", "properties": {}, "required": []}

    # Provider filtering (None = available to all)
    provider_specific: Optional[List[str]] = None  # Only for these providers
    provider_excluded: Optional[List[str]] = None  # Excluded for these providers

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        """Execute the tool and return result.

        Args:
            **kwargs: Tool-specific arguments

        Returns:
            String result of tool execution
        """
        pass

    def is_available_for(self, provider: str) -> bool:
        """Check if tool is available for a specific provider.

        Args:
            provider: Provider name

        Returns:
            True if tool is available for this provider
        """
        # If provider_specific is set, only those providers can use it
        if self.provider_specific is not None:
            return provider in self.provider_specific

        # If provider_excluded is set, those providers cannot use it
        if self.provider_excluded is not None:
            return provider not in self.provider_excluded

        # Otherwise available to all
        return True

    def get_definition(self) -> Dict[str, Any]:
        """Get tool definition for prompts.

        Returns:
            Dictionary with name, description, and parameters
        """
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters
        }


class FunctionTool(BaseTool):
    """A tool that wraps a simple function.

    Allows creating tools from functions without subclassing.
    """

    def __init__(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        handler: callable,
        provider_specific: Optional[List[str]] = None,
        provider_excluded: Optional[List[str]] = None
    ):
        """Create a tool from a function.

        Args:
            name: Tool name
            description: Tool description
            parameters: JSON Schema for parameters
            handler: Function to execute (can be sync or async)
            provider_specific: Only for these providers
            provider_excluded: Excluded for these providers
        """
        self.name = name
        self.description = description
        self.parameters = parameters
        self._handler = handler
        self.provider_specific = provider_specific
        self.provider_excluded = provider_excluded

    async def execute(self, **kwargs) -> str:
        """Execute the wrapped function.

        Args:
            **kwargs: Arguments to pass to the handler

        Returns:
            String result
        """
        import asyncio
        import inspect

        # Handle both sync and async functions
        if inspect.iscoroutinefunction(self._handler):
            result = await self._handler(**kwargs)
        else:
            result = self._handler(**kwargs)

        return str(result)
