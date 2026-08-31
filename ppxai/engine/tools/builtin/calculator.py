"""
Calculator tool for mathematical expressions.

Uses AST-based parsing for safe evaluation (no eval()).
"""

import ast
import operator
from typing import Union

from ...types import ToolManagerProtocol


# Supported operators for safe evaluation
_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
}

_UNARY_OPERATORS = {
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval(node: ast.AST) -> Union[int, float]:
    """Safely evaluate an AST node.

    Only supports numbers, binary operations, and unary operations.
    Raises ValueError for unsupported constructs.

    Args:
        node: AST node to evaluate

    Returns:
        Numeric result

    Raises:
        ValueError: If expression contains unsupported constructs
    """
    # Handle numeric constants (Python 3.8+ uses ast.Constant)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value

    # Handle legacy ast.Num (Python < 3.8 compatibility)
    if isinstance(node, ast.Num):
        return node.n

    # Handle binary operations (e.g., 2 + 3)
    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _BINARY_OPERATORS:
            raise ValueError(f"Unsupported operator: {op_type.__name__}")
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)
        return _BINARY_OPERATORS[op_type](left, right)

    # Handle unary operations (e.g., -5)
    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _UNARY_OPERATORS:
            raise ValueError(f"Unsupported unary operator: {op_type.__name__}")
        operand = _safe_eval(node.operand)
        return _UNARY_OPERATORS[op_type](operand)

    raise ValueError(f"Unsupported expression type: {type(node).__name__}")


def calculate(expression: str) -> str:
    """Safely evaluate a mathematical expression using AST parsing.

    Supports: +, -, *, /, //, %, ** and parentheses.
    Does NOT use eval() - parses expression into AST and evaluates safely.

    Args:
        expression: Math expression (e.g., '2 + 2', '(3 + 4) * 2')

    Returns:
        Result or error message
    """
    try:
        # Parse expression into AST
        tree = ast.parse(expression, mode='eval')
        # Safely evaluate the AST
        result = _safe_eval(tree.body)
        # Format result (avoid unnecessary decimals for integers)
        if isinstance(result, float) and result.is_integer():
            return str(int(result))
        return str(result)
    except SyntaxError:
        return f"Error: Invalid expression syntax"
    except ZeroDivisionError:
        return "Error: Division by zero"
    except ValueError as e:
        return f"Error: {str(e)}"
    except Exception as e:
        return f"Error calculating: {str(e)}"


def register_tools(manager: ToolManagerProtocol):
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
