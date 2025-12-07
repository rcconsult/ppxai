"""
Calculator tool for mathematical expressions.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..manager import ToolManager


def calculate(expression: str) -> str:
    """Safely evaluate a mathematical expression.

    Args:
        expression: Math expression (e.g., '2 + 2')

    Returns:
        Result or error message
    """
    try:
        allowed_chars = set('0123456789+-*/(). ')
        if not all(c in allowed_chars for c in expression):
            return "Error: Invalid characters in expression"
        result = eval(expression, {"__builtins__": {}}, {})
        return str(result)
    except Exception as e:
        return f"Error calculating: {str(e)}"


def register_tools(manager: 'ToolManager'):
    """Register calculator tools with the manager."""

    manager.register_function(
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
