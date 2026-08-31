"""
Response Quality Validator for LLM Benchmark

Evaluates response quality beyond just tool correctness,
detecting anti-patterns and measuring response cleanliness.
"""

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class QualityMetrics:
    """Response quality metrics."""
    tool_correctness: bool      # Did the right tool get called?
    tool_success: bool           # Did the tool execute successfully?
    response_quality: float      # Response cleanliness score (0.0-1.0)
    anti_patterns: list[str]     # Detected anti-patterns
    quality_notes: list[str]     # Detailed quality observations

    @property
    def overall_score(self) -> float:
        """
        Calculate overall test score considering all factors.

        Returns 0.0 if tool is incorrect/failed.
        Otherwise returns quality score with anti-pattern penalties.
        """
        if not (self.tool_correctness and self.tool_success):
            return 0.0

        # Each anti-pattern reduces score
        penalty = len(self.anti_patterns) * 0.15  # 15% per anti-pattern
        return max(0.0, self.response_quality - penalty)

    @property
    def passed(self) -> bool:
        """Test passes if score >= 0.7 (70% threshold)."""
        return self.overall_score >= 0.7

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "tool_correctness": self.tool_correctness,
            "tool_success": self.tool_success,
            "response_quality": self.response_quality,
            "anti_patterns": self.anti_patterns,
            "quality_notes": self.quality_notes,
            "overall_score": self.overall_score,
            "passed": self.passed,
        }


def validate_response_quality(
    response: dict[str, Any],
    expected_tool: str = None,
    tool_calling_method: str = "native",
) -> QualityMetrics:
    """
    Validate response quality and detect anti-patterns.

    Args:
        response: LLM response dict with 'content' and 'tool_calls'
        expected_tool: Expected tool name (if checking tool correctness)
        tool_calling_method: How tool calls are made ("native", "prompt_based", "auto").
            In prompt-based mode, tool JSON in content is expected behavior, not an
            anti-pattern — the penalty is skipped.

    Returns:
        QualityMetrics with scores and detected anti-patterns
    """
    content = response.get("content", "")
    tool_calls = response.get("tool_calls", [])
    is_prompt_based = tool_calling_method == "prompt_based"

    anti_patterns = []
    quality_notes = []
    base_quality = 1.0

    # 1. Tool JSON in content (while also making tool calls)
    # In prompt-based mode, tool JSON in content IS the tool call mechanism,
    # so this is expected behavior, not an anti-pattern.
    if tool_calls and _has_tool_json_in_content(content) and not is_prompt_based:
        anti_patterns.append("tool_json_in_content")
        quality_notes.append("Model output tool JSON in response text while also making tool calls")
        base_quality -= 0.3

    # 2. Explanation before/with tool call
    # In prompt-based mode, models commonly explain before outputting JSON —
    # only penalize lightly since we care more about correctness.
    if tool_calls and _has_explanation_with_tool(content):
        if is_prompt_based:
            # Lighter penalty for prompt-based — explanation is common and less harmful
            anti_patterns.append("explained_before_tool")
            quality_notes.append("Model explained before tool call (minor in prompt-based mode)")
            base_quality -= 0.05
        else:
            anti_patterns.append("explained_before_tool")
            quality_notes.append("Model explained what it would do instead of calling tool directly")
            base_quality -= 0.2

    # 3. Code blocks in content when tool call handles it
    if tool_calls and "```python" in content:
        # Check if this is duplication or legitimate explanation
        if len(content) > 200:  # Substantial code in content
            anti_patterns.append("duplicate_code_in_content")
            quality_notes.append("Model output code in response when tool call should handle it")
            base_quality -= 0.15

    # 4. Unnecessary tool calls
    if len(tool_calls) > 1:
        tool_names = [tc.get("function", {}).get("name") for tc in tool_calls]
        # Allow read_file + apply_patch (reasonable pattern)
        if not ("read_file" in tool_names and "apply_patch" in tool_names):
            # Check for truly redundant calls
            if len(set(tool_names)) < len(tool_names):
                anti_patterns.append("duplicate_tool_calls")
                quality_notes.append(f"Model made {len(tool_calls)} tool calls, some may be unnecessary")
                base_quality -= 0.1

    # 5. Hallucinated tool names in content
    if _has_hallucinated_tools(content, tool_calls):
        anti_patterns.append("hallucinated_tools")
        quality_notes.append("Model mentioned tools in content that weren't actually called")
        base_quality -= 0.2

    # 6. Check tool correctness if expected_tool provided
    tool_correctness = True
    tool_success = True

    if expected_tool:
        if not tool_calls:
            tool_correctness = False
            quality_notes.append(f"Expected {expected_tool} but no tool was called")
        elif tool_calls[0].get("function", {}).get("name") != expected_tool:
            tool_correctness = False
            actual_tool = tool_calls[0].get("function", {}).get("name")
            quality_notes.append(f"Expected {expected_tool} but got {actual_tool}")

    # 7. Positive quality indicators
    if tool_calls and not content.strip():
        quality_notes.append("Clean tool-only response (no unnecessary text)")
        base_quality = min(1.0, base_quality + 0.1)  # Bonus for clean response

    if not anti_patterns:
        quality_notes.append("No anti-patterns detected")

    return QualityMetrics(
        tool_correctness=tool_correctness,
        tool_success=tool_success,
        response_quality=max(0.0, min(1.0, base_quality)),
        anti_patterns=anti_patterns,
        quality_notes=quality_notes,
    )


def _has_tool_json_in_content(content: str) -> bool:
    """Check if content contains tool call JSON."""
    json_patterns = [
        r'\{\s*"tool"\s*:',
        r'\{\s*"name"\s*:\s*"(read_file|write_file|apply_patch|run_command|search_code)"',
        r'\{\s*"function"\s*:',
        r'```json\s*\{\s*"tool"',
        r'```json\s*\{\s*"name"',
    ]

    for pattern in json_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            return True
    return False


def _has_explanation_with_tool(content: str) -> bool:
    """Check if model explained before/with tool call."""
    explanation_phrases = [
        r"i'?ll\s+use",
        r"i\s+will\s+use",
        r"let\s+me\s+use",
        r"using\s+the\s+\w+\s+tool",
        r"i'm\s+going\s+to\s+use",
        r"first\s+i'?ll",
        r"i\s+need\s+to\s+use",
    ]

    # Only flag if explanation is substantial (not just brief context)
    if len(content) < 30:
        return False

    for phrase in explanation_phrases:
        if re.search(phrase, content, re.IGNORECASE):
            return True
    return False


def _has_hallucinated_tools(content: str, tool_calls: list[dict]) -> bool:
    """Check if model claims to use tools that weren't actually called."""
    if not content or not tool_calls:
        return False

    # Get actual tool names called
    actual_tools = {tc.get("function", {}).get("name") for tc in tool_calls}

    # Check for mentions of other tools
    all_tools = {"read_file", "write_file", "apply_patch", "run_command", "search_code", "get_diagnostics"}
    mentioned_tools = set()

    for tool in all_tools:
        if tool in content.lower():
            mentioned_tools.add(tool)

    # Hallucination if model mentions tools it didn't call
    hallucinated = mentioned_tools - actual_tools
    return len(hallucinated) > 0


def format_quality_report(metrics: QualityMetrics) -> str:
    """Format quality metrics for human-readable output."""
    lines = []
    lines.append(f"Overall Score: {metrics.overall_score:.1%}")
    lines.append(f"Pass/Fail: {'PASS' if metrics.passed else 'FAIL'}")
    lines.append(f"Tool Correctness: {'✓' if metrics.tool_correctness else '✗'}")
    lines.append(f"Tool Success: {'✓' if metrics.tool_success else '✗'}")
    lines.append(f"Response Quality: {metrics.response_quality:.1%}")

    if metrics.anti_patterns:
        lines.append(f"\nAnti-patterns detected ({len(metrics.anti_patterns)}):")
        for pattern in metrics.anti_patterns:
            lines.append(f"  - {pattern}")

    if metrics.quality_notes:
        lines.append("\nQuality notes:")
        for note in metrics.quality_notes:
            lines.append(f"  - {note}")

    return "\n".join(lines)
