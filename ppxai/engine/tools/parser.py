"""
Tool call parser for the ppxai engine.

This is a LEAF MODULE - no ppxai imports allowed (except types).
Parses model responses to extract tool calls in various formats.

Aligns with the future Tool Factory pattern by using a simple callable
for tool lookup rather than depending on ToolManager directly.
"""

import json
import re
from typing import Any, Callable, Dict, List, Optional, Protocol


class ToolLike(Protocol):
    """Protocol for tool lookup results - used for type checking only."""
    @property
    def parameters(self) -> Dict[str, Any]: ...


# Type alias for tool lookup function
ToolLookupFunc = Callable[[str], Optional[ToolLike]]


# Tool inference rules for models that output raw JSON without 'tool' key.
# Each rule defines how to detect and normalize a tool call.
# Format: {
#   "tool": tool name,
#   "required": keys that MUST be present (any one from list),
#   "allowed": all keys that can be present (superset check),
#   "aliases": {canonical_param: [alias1, alias2, ...]} for normalization
# }
TOOL_INFERENCE_RULES: List[Dict[str, Any]] = [
    {
        "tool": "web_search",
        "required": ["query"],
        "allowed": {"query", "num_results", "top_n", "count", "limit", "max_results", "recency_days"},
        "aliases": {
            "num_results": ["top_n", "count", "limit", "max_results"],
        }
    },
    {
        "tool": "read_file",
        "required": ["path", "filepath"],  # Either one satisfies
        "allowed": {"path", "filepath", "line_start", "line_end", "max_lines"},
        "aliases": {
            "filepath": ["path"],  # Normalize path -> filepath
        }
    },
    {
        "tool": "list_directory",
        "required": [],  # No required keys, but must have at least one allowed key
        "allowed": {"path", "format"},
        "aliases": {}
    },
    {
        "tool": "execute_shell_command",
        "required": ["command"],
        "allowed": {"command", "working_dir"},
        "aliases": {}
    },
    {
        "tool": "fetch_url",
        "required": ["url"],
        "allowed": {"url", "max_length"},
        "aliases": {}
    },
    {
        "tool": "get_weather",
        "required": ["location"],
        "allowed": {"location", "format"},
        "aliases": {}
    },
    {
        "tool": "calculator",
        "required": ["expression"],
        "allowed": {"expression"},
        "aliases": {}
    },
]


def _try_parse_json(json_str: str) -> Optional[Dict[str, Any]]:
    """Try to parse JSON, including handling single quotes.

    Args:
        json_str: JSON string to parse

    Returns:
        Parsed dict or None if parsing fails
    """
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        # Try converting single quotes to double quotes (Python dict style)
        # This handles cases where models output {'tool': 'name'} instead of {"tool": "name"}
        try:
            fixed = json_str.replace("'", '"')
            return json.loads(fixed)
        except json.JSONDecodeError:
            return None


def _normalize_tool_call(
    data: Dict[str, Any],
    get_tool: ToolLookupFunc
) -> Optional[Dict[str, Any]]:
    """Normalize a parsed tool call dict to standard format.

    Args:
        data: Parsed JSON data containing tool call
        get_tool: Function to look up tool by name

    Returns:
        Normalized dict with 'tool' and 'arguments' keys, or None
    """
    # Support both "tool" and "name" keys (some models use OpenAI function format)
    tool_name = data.get("tool") or data.get("name")
    if not tool_name:
        return None

    tool = get_tool(tool_name)
    if not tool:
        return None

    if "arguments" in data:
        args = data["arguments"]
        # Handle nested tool call structure from some models (e.g., GPT-OSS 120B via vLLM)
        # Model sometimes outputs: {"tool": "apply_patch", "arguments": {"tool": "apply_patch", "arguments": {...}}}
        # Unwrap the nested structure to get the actual arguments
        if isinstance(args, dict) and "tool" in args and "arguments" in args:
            # Nested tool call - unwrap it
            args = args["arguments"]
        return {"tool": tool_name, "arguments": args}

    # Model put parameters at top level
    expected_params = set(tool.parameters.get("properties", {}).keys())
    arguments = {}
    for key, value in data.items():
        if key != "tool" and key in expected_params:
            arguments[key] = value

    # Handle tools with no required arguments (e.g., get_working_directory)
    required_params = tool.parameters.get("required", [])
    if arguments or not required_params:
        return {"tool": tool_name, "arguments": arguments}

    return None


def _find_json_objects(text: str) -> List[Dict[str, Any]]:
    """Find all JSON objects in text using brace-counting.

    Handles nested braces, escaped characters, and string literals correctly.
    This is more robust than regex for tool calls containing code diffs
    (apply_patch) where nested braces in the diff content break regex matching.

    Ported from benchmarks/llm-eval/engine_runner.py (v1.15.6, P2).

    Args:
        text: Text potentially containing JSON objects

    Returns:
        List of parsed dict objects found in the text
    """
    objects: List[Dict[str, Any]] = []
    i = 0
    while i < len(text):
        if text[i] == '{':
            depth = 0
            in_string = False
            escape = False
            start = i
            for j in range(i, len(text)):
                c = text[j]
                if escape:
                    escape = False
                    continue
                if c == '\\' and in_string:
                    escape = True
                    continue
                if c == '"' and not escape:
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        candidate = text[start:j + 1]
                        try:
                            obj = json.loads(candidate)
                            if isinstance(obj, dict):
                                objects.append(obj)
                        except json.JSONDecodeError:
                            pass
                        i = j + 1
                        break
            else:
                i += 1
        else:
            i += 1
    return objects


def _infer_tool_from_arguments(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Infer which tool based on argument patterns when 'tool' key is missing.

    This handles models (like vLLM-served models) that output raw JSON arguments
    without the required 'tool' wrapper.

    Uses a configuration-driven dispatcher pattern for maintainability.

    Args:
        data: JSON data without explicit tool key

    Returns:
        Normalized tool call dict or None
    """
    if "tool" in data or "name" in data:
        return None  # Already has tool/name key, use _normalize_tool_call instead

    keys = set(data.keys())

    def match_rule(rule: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Check if data matches a tool rule and return normalized arguments."""
        tool_name = rule["tool"]
        required = rule["required"]
        allowed = rule["allowed"]
        aliases = rule["aliases"]

        # Check required keys (any one from list must be present)
        if required:
            if not any(req in keys for req in required):
                return None
        elif not keys:
            # No required keys defined, but data must have at least one allowed key
            return None

        # Check that all keys are in allowed set
        if not keys <= allowed:
            return None

        # Normalize arguments using aliases
        args = {}
        for key, value in data.items():
            # Check if this key should be mapped to a canonical name
            canonical = key
            for canon, alias_list in aliases.items():
                if key in alias_list:
                    canonical = canon
                    break
            args[canonical] = value

        return {"tool": tool_name, "arguments": args}

    # Try each rule in order (first match wins)
    for rule in TOOL_INFERENCE_RULES:
        result = match_rule(rule)
        if result:
            return result

    return None


def parse_tool_call(
    text: str,
    get_tool: ToolLookupFunc
) -> Optional[Dict[str, Any]]:
    """Parse a tool call from model response text.

    Tries multiple parsing strategies:
    1. Entire response as JSON (fast path for clean tool calls)
    2. Brace-counting extraction of all JSON objects from text
       (handles code blocks, inline JSON, nested braces in diffs)

    Strategy 2 uses _find_json_objects() which correctly handles nested
    braces inside string literals (e.g., apply_patch diffs containing
    '{' and '}' in code). This replaced the previous regex-based approach
    that broke on such content (v1.15.6, P2 backlog).

    Args:
        text: Model response text
        get_tool: Function to look up tool by name (returns tool or None)

    Returns:
        Tool call dict with 'tool' and 'arguments' keys, or None if not found
    """
    if not text:
        return None
    # Strategy 1: Try entire response as JSON (most common case for tool calls)
    text_stripped = text.strip()
    if text_stripped.startswith('{') and text_stripped.endswith('}'):
        data = _try_parse_json(text_stripped)
        if data:
            normalized = _normalize_tool_call(data, get_tool)
            if normalized:
                return normalized
            # Fallback: try to infer tool from arguments (for models like vLLM)
            inferred = _infer_tool_from_arguments(data)
            if inferred:
                return inferred

    # Strategy 2: Find all JSON objects using brace-counting parser.
    # This handles: markdown code blocks, inline JSON, "I'll use X tool" + JSON,
    # and nested braces in apply_patch diffs that break regex extraction.
    json_objects = _find_json_objects(text)
    for data in json_objects:
        # Try normalizing with explicit tool/name key first
        normalized = _normalize_tool_call(data, get_tool)
        if normalized:
            return normalized
        # Fallback: try to infer tool from argument patterns
        inferred = _infer_tool_from_arguments(data)
        if inferred:
            return inferred

    return None


def strip_tool_json_from_text(text: str) -> str:
    """Strip tool call JSON objects from response text.

    v1.15.6, Gap 4: When models output native tool_calls AND duplicate the
    tool call JSON in the response content text, this function removes the
    JSON blocks to prevent user confusion and context waste.

    Only strips JSON objects that look like tool calls (contain "tool" or
    "name" key with "arguments" key). Preserves any surrounding text.

    Args:
        text: Response text potentially containing embedded tool call JSON

    Returns:
        Text with tool call JSON blocks removed, whitespace cleaned up
    """
    if not text or '{' not in text:
        return text

    # Find all JSON object spans using brace-counting
    spans_to_remove: List[tuple] = []
    i = 0
    while i < len(text):
        if text[i] == '{':
            depth = 0
            in_string = False
            escape = False
            start = i
            for j in range(i, len(text)):
                c = text[j]
                if escape:
                    escape = False
                    continue
                if c == '\\' and in_string:
                    escape = True
                    continue
                if c == '"' and not escape:
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        candidate = text[start:j + 1]
                        try:
                            obj = json.loads(candidate)
                            if isinstance(obj, dict):
                                # Only strip objects that look like tool calls
                                has_tool_key = "tool" in obj or "name" in obj
                                has_args = "arguments" in obj
                                if has_tool_key and has_args:
                                    spans_to_remove.append((start, j + 1))
                        except json.JSONDecodeError:
                            pass
                        i = j + 1
                        break
            else:
                i += 1
        else:
            i += 1

    if not spans_to_remove:
        return text

    # Remove spans in reverse order to preserve indices
    result = text
    for start, end in reversed(spans_to_remove):
        # Also strip surrounding markdown code block fences if present
        pre = result[:start].rstrip()
        post = result[end:].lstrip()
        # Check for ```json or ``` before the JSON
        if pre.endswith('```json') or pre.endswith('```'):
            fence_start = pre.rfind('```')
            pre = pre[:fence_start].rstrip()
        # Check for ``` after the JSON
        if post.startswith('```'):
            post = post[3:].lstrip()
        result = pre + '\n' + post

    # Clean up excessive whitespace
    while '\n\n\n' in result:
        result = result.replace('\n\n\n', '\n\n')

    return result.strip()


def detect_truncated_tool_call(text: str) -> Optional[Dict[str, Any]]:
    """Detect if a response contains a truncated/incomplete tool call attempt.

    v1.15.2: GPT-OSS and other models sometimes output "I'll use X tool" followed
    by JSON that gets truncated due to token limits. This function detects such
    patterns to enable targeted retry feedback.

    Args:
        text: Model response text

    Returns:
        Dict with 'tool' (detected tool name) and 'reason' (why it's truncated),
        or None if no truncated tool call detected
    """
    if not text:
        return None
    # Pattern 1: "I'll use the X tool" followed by incomplete JSON
    intent_patterns = [
        r"I'll use (?:the )?(\w+(?:_\w+)*) tool",
        r"I will use (?:the )?(\w+(?:_\w+)*) tool",
        r"Let me use (?:the )?(\w+(?:_\w+)*) tool",
        r"Using (?:the )?(\w+(?:_\w+)*) tool",
    ]

    tool_name = None
    for pattern in intent_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            tool_name = match.group(1)
            break

    if not tool_name:
        return None

    # Check for incomplete JSON after the tool mention
    # Look for opening brace without matching close
    json_start = text.find('{')
    if json_start == -1:
        # No JSON started - model just said it would use tool but didn't output JSON
        return {
            "tool": tool_name,
            "reason": "no_json",
            "message": f"Model stated intent to use '{tool_name}' but did not output tool call JSON"
        }

    # Count braces to detect incomplete JSON
    open_braces = 0
    in_string = False
    escape_next = False

    for char in text[json_start:]:
        if escape_next:
            escape_next = False
            continue
        if char == '\\':
            escape_next = True
            continue
        if char == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == '{':
            open_braces += 1
        elif char == '}':
            open_braces -= 1

    if open_braces > 0:
        # Unclosed braces - JSON is truncated
        return {
            "tool": tool_name,
            "reason": "truncated_json",
            "message": f"Model attempted to call '{tool_name}' but JSON was truncated (unclosed braces: {open_braces})"
        }

    # JSON looks complete but parse_tool_call failed - might be malformed
    # Check for common truncation indicators
    truncation_indicators = [
        text.rstrip().endswith('...'),
        text.rstrip().endswith('"'),  # String cut mid-value
        text.rstrip().endswith(','),  # Cut after a comma
        '```json' in text and text.count('```') % 2 != 0,  # Unclosed code block
    ]

    if any(truncation_indicators):
        return {
            "tool": tool_name,
            "reason": "likely_truncated",
            "message": f"Model attempted to call '{tool_name}' but response appears truncated"
        }

    return None
