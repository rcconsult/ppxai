"""
Example Built-in Tool for ppxai

This demonstrates how to create a custom tool that can be used by the AI.
This example creates a "code analyzer" tool that analyzes Python files.
"""


def analyze_python_file(filepath: str) -> str:
    """
    Analyze a Python file and provide statistics.

    This tool counts lines, functions, classes, imports, and identifies
    potential issues in Python files.

    Args:
        filepath: Path to the Python file to analyze

    Returns:
        Analysis summary as a formatted string
    """
    import ast
    from pathlib import Path

    try:
        # Read the file
        path = Path(filepath).expanduser().resolve()

        if not path.exists():
            return f"Error: File not found: {filepath}"

        if not path.is_file():
            return f"Error: Not a file: {filepath}"

        if not filepath.endswith('.py'):
            return f"Error: Not a Python file: {filepath}"

        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Parse AST
        try:
            tree = ast.parse(content)
        except SyntaxError as e:
            return f"Syntax Error in {filepath}: {e}"

        # Analyze
        lines = content.split('\n')
        total_lines = len(lines)
        blank_lines = sum(1 for line in lines if not line.strip())
        code_lines = total_lines - blank_lines

        functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
        classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]

        # Check for TODOs and FIXMEs
        todos = [i+1 for i, line in enumerate(lines) if 'TODO' in line.upper()]
        fixmes = [i+1 for i, line in enumerate(lines) if 'FIXME' in line.upper()]

        # Build report
        report = f"Analysis of {path.name}:\n\n"
        report += f"📊 Lines:\n"
        report += f"  Total: {total_lines}\n"
        report += f"  Code: {code_lines}\n"
        report += f"  Blank: {blank_lines}\n\n"

        report += f"🏗️  Structure:\n"
        report += f"  Functions: {len(functions)}\n"
        report += f"  Classes: {len(classes)}\n"
        report += f"  Imports: {len(imports)}\n\n"

        if functions:
            report += f"📝 Functions:\n"
            for func in functions[:10]:  # Show first 10
                report += f"  - {func.name}()\n"
            if len(functions) > 10:
                report += f"  ... and {len(functions) - 10} more\n"
            report += "\n"

        if classes:
            report += f"🎨 Classes:\n"
            for cls in classes[:10]:  # Show first 10
                methods = [node.name for node in cls.body if isinstance(node, ast.FunctionDef)]
                report += f"  - {cls.name} ({len(methods)} methods)\n"
            if len(classes) > 10:
                report += f"  ... and {len(classes) - 10} more\n"
            report += "\n"

        if todos or fixmes:
            report += f"⚠️  Notes:\n"
            if todos:
                report += f"  TODO comments on lines: {', '.join(map(str, todos[:5]))}\n"
            if fixmes:
                report += f"  FIXME comments on lines: {', '.join(map(str, fixmes[:5]))}\n"
            report += "\n"

        report += f"✅ File appears valid Python code"

        return report

    except Exception as e:
        return f"Error analyzing file: {str(e)}"


def format_json(json_string: str) -> str:
    """
    Format and validate JSON string.

    Args:
        json_string: JSON string to format

    Returns:
        Formatted JSON or error message
    """
    import json

    try:
        # Parse JSON
        data = json.loads(json_string)

        # Format with indentation
        formatted = json.dumps(data, indent=2, sort_keys=True)

        return f"Formatted JSON:\n```json\n{formatted}\n```"

    except json.JSONDecodeError as e:
        return f"Invalid JSON: {e}"
    except Exception as e:
        return f"Error formatting JSON: {e}"


def calculate_sha256(text: str) -> str:
    """
    Calculate SHA256 hash of text.

    Args:
        text: Text to hash

    Returns:
        SHA256 hash in hexadecimal
    """
    import hashlib

    try:
        hash_obj = hashlib.sha256(text.encode('utf-8'))
        hash_hex = hash_obj.hexdigest()

        return f"SHA256: {hash_hex}"

    except Exception as e:
        return f"Error calculating hash: {e}"


# ============================================================================
# REGISTRATION INSTRUCTIONS
# ============================================================================
#
# To use these tools in ppxai, add this code to perplexity_tools_prompt_based.py
# in the _register_builtin_tools method:
#
# from demo.example_builtin_tool import analyze_python_file, format_json, calculate_sha256
#
# self.tool_manager.register_builtin_tool(
#     name="analyze_python",
#     description="Analyze a Python file and provide statistics including line count, functions, classes, and potential issues",
#     parameters={
#         "type": "object",
#         "properties": {
#             "filepath": {
#                 "type": "string",
#                 "description": "Path to the Python file to analyze"
#             }
#         },
#         "required": ["filepath"]
#     },
#     handler=analyze_python_file
# )
#
# self.tool_manager.register_builtin_tool(
#     name="format_json",
#     description="Format and validate a JSON string with proper indentation",
#     parameters={
#         "type": "object",
#         "properties": {
#             "json_string": {
#                 "type": "string",
#                 "description": "JSON string to format"
#             }
#         },
#         "required": ["json_string"]
#     },
#     handler=format_json
# )
#
# self.tool_manager.register_builtin_tool(
#     name="calculate_sha256",
#     description="Calculate SHA256 hash of text",
#     parameters={
#         "type": "object",
#         "properties": {
#             "text": {
#                 "type": "string",
#                 "description": "Text to hash"
#             }
#         },
#         "required": ["text"]
#     },
#     handler=calculate_sha256
# )
# ============================================================================


# Test the tools independently
if __name__ == "__main__":
    import sys

    print("=" * 70)
    print("Testing Example Built-in Tools")
    print("=" * 70)

    # Test 1: Analyze this file
    print("\n1. Testing analyze_python_file on itself:")
    result = analyze_python_file(__file__)
    print(result)

    # Test 2: Format JSON
    print("\n2. Testing format_json:")
    test_json = '{"name":"ppxai","version":"1.0","features":["chat","tools"]}'
    result = format_json(test_json)
    print(result)

    # Test 3: Calculate hash
    print("\n3. Testing calculate_sha256:")
    result = calculate_sha256("Hello, World!")
    print(result)

    print("\n" + "=" * 70)
    print("All tests completed!")
    print("=" * 70)
