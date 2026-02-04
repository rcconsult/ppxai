"""
Tool result validation and hallucination detection (v1.15.2).

This module provides validation to detect when LLM models:
1. Claim success after tool failures
2. Claim file operations without calling appropriate tools
3. Output tool call JSON as text instead of making actual calls
4. Fabricate output that looks like tool results

These issues can occur with any LLM model, not just GPT-OSS.
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any, Set

from ...common.logger import get_logger

logger = get_logger("validator")


class ValidationResult(Enum):
    """Result of validating a model response."""
    VALID = "valid"
    CLAIM_WITHOUT_ACTION = "claim_without_action"
    CLAIM_CONTRADICTS_RESULT = "claim_contradicts_result"
    TOOL_JSON_IN_TEXT = "tool_json_in_text"
    FABRICATED_OUTPUT = "fabricated_output"


@dataclass
class ValidationWarning:
    """A detected validation issue."""
    result: ValidationResult
    severity: str  # "info", "warning", "error"
    message: str
    details: Optional[str] = None
    suggested_action: Optional[str] = None


@dataclass
class ToolCallRecord:
    """Record of a single tool call."""
    tool_name: str
    arguments: Dict[str, Any]
    result: str
    success: bool
    iteration: int


class ResponseValidator:
    """
    Validates LLM responses against actual tool calls and results.

    Tracks tool calls within a chat turn and validates model claims
    against what actually happened.

    Usage:
        validator = ResponseValidator()

        # During tool execution:
        validator.record_tool_call("write_file", {"path": "..."}, "✓ Success", True, 1)

        # After response:
        warnings = validator.validate_response(response_text)

        # Reset between chat turns:
        validator.reset()
    """

    # Patterns indicating the model claims to have performed an action
    SUCCESS_CLAIM_PATTERNS = [
        r"I'?ve (created|written|saved|opened|generated|made|updated|fixed|modified)",
        r"I have (created|written|saved|opened|generated|made|updated|fixed|modified)",
        r"I (created|wrote|saved|opened|generated|made|updated|fixed|modified)",
        r"The file[s]? (?:has|have) been (created|written|saved|opened|generated)",
        r"The file[s]? (?:is|are) now (created|open|available|ready|saved)",
        r"Successfully (created|written|saved|opened|generated|updated|fixed)",
        r"(?:is|are) now (?:open|available|ready|created|saved) in (?:the )?viewer",
        r"You can (?:now )?(?:see|view|open|scroll through|find)",
        r"has been (?:fully )?(?:created|written|saved|generated|updated|fixed)",
        r"(?:changes|content|data) (?:has|have) been saved",
    ]

    # Tool results that indicate failure
    FAILURE_PATTERNS = [
        r"Error:",
        r"error:",
        r"not found",
        r"No changes applied",
        r"failed",
        r"does not exist",
        r"permission denied",
        r"cannot",
        r"Unable to",
    ]

    # Patterns for tool JSON appearing in text (should have been a tool call)
    TOOL_JSON_PATTERNS = [
        r'```json\s*\n?\s*\{\s*"tool"\s*:\s*"(\w+)"',
        r'\{\s*"tool"\s*:\s*"(\w+)"\s*,\s*"arguments"\s*:',
        r'```\s*\n?\s*\{\s*"tool"\s*:\s*"(\w+)"',
    ]

    # Fabricated output patterns (looks like tool output but no tool was called)
    FABRICATED_OUTPUT_PATTERNS = [
        (r"^-rw", "shell_listing"),  # ls -l output
        (r"^\d+\s+\w+\s+\w+\s+\d+", "file_listing"),  # File listing
        (r"^total\s+\d+", "shell_total"),  # Shell total line
        (r"^drwx", "shell_directory"),  # Directory listing
    ]

    # File operation tools
    FILE_WRITE_TOOLS = {'write_file', 'apply_patch', 'insert_text', 'replace_block', 'delete_lines'}
    FILE_READ_TOOLS = {'read_file', 'display_file'}
    SHELL_TOOLS = {'execute_shell_command', 'execute_command'}

    def __init__(self):
        self._tool_calls: List[ToolCallRecord] = []
        self._files_successfully_written: Set[str] = set()
        self._files_displayed: Set[str] = set()
        self._shell_commands_run: Set[str] = set()

    def reset(self):
        """Reset state for a new chat turn."""
        self._tool_calls.clear()
        self._files_successfully_written.clear()
        self._files_displayed.clear()
        self._shell_commands_run.clear()

    def record_tool_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        result: str,
        success: bool,
        iteration: int
    ):
        """Record a tool call and its result.

        Args:
            tool_name: Name of the tool called
            arguments: Arguments passed to the tool
            result: Result string from the tool
            success: Whether the tool call succeeded
            iteration: Current iteration number
        """
        record = ToolCallRecord(
            tool_name=tool_name,
            arguments=arguments,
            result=result,
            success=success,
            iteration=iteration
        )
        self._tool_calls.append(record)

        # Track successful file operations
        if success:
            if tool_name in self.FILE_WRITE_TOOLS:
                path = arguments.get("file_path") or arguments.get("filepath", "")
                if path:
                    self._files_successfully_written.add(path)
                    # Also track normalized versions
                    self._files_successfully_written.add(path.replace("\\", "/"))
                    self._files_successfully_written.add(path.replace("/", "\\"))

            if tool_name in self.FILE_READ_TOOLS:
                path = arguments.get("filepath") or arguments.get("file_path", "")
                if path:
                    self._files_displayed.add(path)

            if tool_name in self.SHELL_TOOLS:
                cmd = arguments.get("command", "")
                if cmd:
                    self._shell_commands_run.add(cmd)

        logger.debug(
            f"Recorded tool call: {tool_name} success={success} "
            f"files_written={len(self._files_successfully_written)}"
        )

    def validate_response(self, response_text: str) -> List[ValidationWarning]:
        """Validate a model response against recorded tool calls.

        Args:
            response_text: The model's response text

        Returns:
            List of validation warnings (empty if valid)
        """
        warnings = []

        # Check for tool JSON in text
        json_warning = self._check_tool_json_in_text(response_text)
        if json_warning:
            warnings.append(json_warning)

        # Check for success claims that contradict tool results
        contradiction_warning = self._check_success_after_failure(response_text)
        if contradiction_warning:
            warnings.append(contradiction_warning)

        # Check for file creation claims without tool calls
        file_warning = self._check_file_claims_without_tools(response_text)
        if file_warning:
            warnings.append(file_warning)

        # Check for display claims without display_file
        display_warning = self._check_display_claims_without_tools(response_text)
        if display_warning:
            warnings.append(display_warning)

        # Check for fabricated shell output
        fabricated_warning = self._check_fabricated_output(response_text)
        if fabricated_warning:
            warnings.append(fabricated_warning)

        return warnings

    def _check_tool_json_in_text(self, response: str) -> Optional[ValidationWarning]:
        """Check if response contains tool call JSON that should have been a tool call."""
        for pattern in self.TOOL_JSON_PATTERNS:
            match = re.search(pattern, response, re.IGNORECASE | re.MULTILINE)
            if match:
                tool_name = match.group(1)
                return ValidationWarning(
                    result=ValidationResult.TOOL_JSON_IN_TEXT,
                    severity="warning",
                    message=f"Tool call JSON for '{tool_name}' appeared in text instead of being executed",
                    details=f"The model output JSON for the {tool_name} tool instead of calling it",
                    suggested_action=f"Call the {tool_name} tool directly instead of outputting JSON"
                )
        return None

    def _check_success_after_failure(self, response: str) -> Optional[ValidationWarning]:
        """Check if model claims success but a tool failed."""
        # Check if response claims success
        claims_success = any(
            re.search(pattern, response, re.IGNORECASE)
            for pattern in self.SUCCESS_CLAIM_PATTERNS
        )

        if not claims_success:
            return None

        # Check recent tool results for failures
        for record in reversed(self._tool_calls[-5:]):  # Check last 5 calls
            if not record.success:
                # Check if the failure is relevant to what's being claimed
                result_lower = record.result.lower()
                if any(re.search(p, result_lower, re.IGNORECASE) for p in self.FAILURE_PATTERNS):
                    return ValidationWarning(
                        result=ValidationResult.CLAIM_CONTRADICTS_RESULT,
                        severity="error",
                        message=f"Model claims success but {record.tool_name} returned an error",
                        details=f"Tool result: {record.result[:200]}",
                        suggested_action="Acknowledge the error and retry or use a different approach"
                    )

        return None

    def _check_file_claims_without_tools(self, response: str) -> Optional[ValidationWarning]:
        """Check if model claims to have created/written a file without using appropriate tools."""
        # Pattern to detect file creation claims
        file_creation_patterns = [
            r"(?:created|written|saved|generated)\s+(?:the\s+)?(?:file\s+)?[`\"']?([^\s`\"']+\.\w{1,5})[`\"']?",
            r"[`\"']([^\s`\"']+\.\w{1,5})[`\"']?\s+(?:has been|is now|was)\s+(?:created|written|saved)",
            r"saved (?:to|as|in) [`\"']?([^\s`\"']+\.\w{1,5})[`\"']?",
        ]

        for pattern in file_creation_patterns:
            match = re.search(pattern, response, re.IGNORECASE)
            if match:
                claimed_file = match.group(1)

                # Check if any write tool was called for this file
                if not self._was_file_written(claimed_file):
                    # Check if ANY write tool was called at all
                    write_tools_called = [
                        r.tool_name for r in self._tool_calls
                        if r.tool_name in self.FILE_WRITE_TOOLS
                    ]

                    if not write_tools_called:
                        return ValidationWarning(
                            result=ValidationResult.CLAIM_WITHOUT_ACTION,
                            severity="warning",
                            message=f"Model claims to have created '{claimed_file}' but no write tool was called",
                            details="No file write operations were performed",
                            suggested_action="Use write_file or apply_patch to actually create the file"
                        )

        return None

    def _check_display_claims_without_tools(self, response: str) -> Optional[ValidationWarning]:
        """Check if model claims file is open/displayed without calling display_file."""
        display_patterns = [
            r"(?:is now|now)\s+(?:open|displayed|showing)\s+in\s+(?:the\s+)?viewer",
            r"opened?\s+in\s+(?:the\s+)?viewer\s+pane",
            r"can\s+(?:now\s+)?(?:see|view|scroll through)\s+(?:it|the file)\s+in\s+(?:the\s+)?viewer",
        ]

        for pattern in display_patterns:
            if re.search(pattern, response, re.IGNORECASE):
                # Check if display_file was called successfully
                display_calls = [
                    r for r in self._tool_calls
                    if r.tool_name == "display_file" and r.success
                ]

                if not display_calls:
                    # Check if display_file was called but failed
                    failed_display = [
                        r for r in self._tool_calls
                        if r.tool_name == "display_file" and not r.success
                    ]

                    if failed_display:
                        return ValidationWarning(
                            result=ValidationResult.CLAIM_CONTRADICTS_RESULT,
                            severity="error",
                            message="Model claims file is open but display_file failed",
                            details=f"display_file error: {failed_display[-1].result[:200]}",
                            suggested_action="Acknowledge the error - the file could not be displayed"
                        )
                    else:
                        return ValidationWarning(
                            result=ValidationResult.CLAIM_WITHOUT_ACTION,
                            severity="warning",
                            message="Model claims file is displayed but display_file was not called",
                            suggested_action="Call display_file to actually open the file in the viewer"
                        )

        return None

    def _check_fabricated_output(self, response: str) -> Optional[ValidationWarning]:
        """Check for fabricated output that looks like tool results."""
        # Only check if it looks like the model is showing "output" without having run a command
        if not self._shell_commands_run:
            for pattern, output_type in self.FABRICATED_OUTPUT_PATTERNS:
                # Check lines in code blocks
                code_block_match = re.search(r'```[^\n]*\n(.+?)```', response, re.DOTALL)
                if code_block_match:
                    block_content = code_block_match.group(1)
                    for line in block_content.split('\n'):
                        if re.match(pattern, line.strip()):
                            return ValidationWarning(
                                result=ValidationResult.FABRICATED_OUTPUT,
                                severity="warning",
                                message=f"Response contains what looks like shell output ({output_type}) but no command was executed",
                                details="The model may have fabricated this output",
                                suggested_action="Use execute_shell_command to actually run the command"
                            )

        return None

    def _was_file_written(self, filename: str) -> bool:
        """Check if a file was successfully written."""
        # Normalize for comparison
        filename_lower = filename.lower()
        filename_normalized = filename.replace("\\", "/").lower()

        for written_file in self._files_successfully_written:
            written_lower = written_file.lower()
            written_normalized = written_file.replace("\\", "/").lower()

            # Check various matching strategies
            if (filename_lower == written_lower or
                filename_normalized == written_normalized or
                filename_lower in written_lower or
                written_lower.endswith(filename_lower)):
                return True

        return False

    def get_tool_calls_summary(self) -> str:
        """Get a summary of tool calls for debugging."""
        if not self._tool_calls:
            return "No tool calls recorded"

        lines = [f"Tool calls ({len(self._tool_calls)} total):"]
        for i, record in enumerate(self._tool_calls):
            status = "✓" if record.success else "✗"
            lines.append(f"  {i+1}. [{status}] {record.tool_name}")

        lines.append(f"Files written: {list(self._files_successfully_written)}")
        lines.append(f"Files displayed: {list(self._files_displayed)}")

        return "\n".join(lines)


# Convenience function for quick validation
def validate_response(
    response_text: str,
    tool_calls: List[Dict[str, Any]]
) -> List[ValidationWarning]:
    """Quick validation without maintaining state.

    Args:
        response_text: Model response to validate
        tool_calls: List of tool call dicts with keys:
            - tool: tool name
            - arguments: dict of arguments
            - result: result string
            - success: bool

    Returns:
        List of validation warnings
    """
    validator = ResponseValidator()

    for i, tc in enumerate(tool_calls):
        validator.record_tool_call(
            tool_name=tc.get("tool", ""),
            arguments=tc.get("arguments", {}),
            result=tc.get("result", ""),
            success=tc.get("success", True),
            iteration=i + 1
        )

    return validator.validate_response(response_text)
