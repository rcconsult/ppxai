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
from .parser import _find_json_objects

logger = get_logger("validator")


class ValidationResult(Enum):
    """Result of validating a model response."""
    VALID = "valid"
    CLAIM_WITHOUT_ACTION = "claim_without_action"
    CLAIM_CONTRADICTS_RESULT = "claim_contradicts_result"
    TOOL_JSON_IN_TEXT = "tool_json_in_text"
    FABRICATED_OUTPUT = "fabricated_output"
    SESSION_POLLUTION = "session_pollution"


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

    # Keyword-set approach for success-claim detection (replaces regex alternation).
    # Claim = SUCCESS_VERB found within PROXIMITY_WINDOW chars of a CLAIM_SIGNAL.
    # This avoids false positives like "I can create files" (present tense capability).
    SUCCESS_VERBS = frozenset({
        'created', 'written', 'saved', 'modified', 'updated', 'completed',
        'generated', 'deleted', 'wrote', 'made', 'fixed', 'opened', 'applied',
        'see', 'view',  # for "you can now see/view" display claims
    })
    # CLAIM_SIGNALS: phrases that introduce a past-action claim.
    # "i " catches "I created/wrote/saved" while NOT matching "I can create"
    # because SUCCESS_VERBS only contains past-tense forms.
    CLAIM_SIGNALS = frozenset({
        "i've", "i have", "i ", "successfully", "has been", "have been",
        "was ", "were ", "is now", "are now", "you can now", "you can see",
    })
    CLAIM_PROXIMITY = 60  # chars to scan around each signal

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

    # (Tool JSON detection now uses _find_json_objects from parser.py — see _check_tool_json_in_text)

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

        # Check for file creation/modification claims without tool calls
        file_warning = self._check_file_claims_without_tools(response_text)
        if file_warning:
            warnings.append(file_warning)

        # Check for display claims without display_file
        display_warning = self._check_display_claims_without_tools(response_text)
        if display_warning:
            warnings.append(display_warning)

        # Check for read/review claims without read_file calls
        read_warning = self._check_read_claims_without_tools(response_text)
        if read_warning:
            warnings.append(read_warning)

        # Check for fabricated shell output
        fabricated_warning = self._check_fabricated_output(response_text)
        if fabricated_warning:
            warnings.append(fabricated_warning)

        return warnings

    def _check_tool_json_in_text(self, response: str) -> Optional[ValidationWarning]:
        """Check if response contains tool call JSON that should have been a tool call.

        Uses the brace-counting JSON parser from parser.py to correctly handle nested
        arguments (e.g. apply_patch diffs with {}) that would defeat a regex approach.
        """
        for obj in _find_json_objects(response):
            if isinstance(obj.get("tool"), str):
                tool_name = obj["tool"]
                return ValidationWarning(
                    result=ValidationResult.TOOL_JSON_IN_TEXT,
                    severity="warning",
                    message=f"Tool call JSON for '{tool_name}' appeared in text instead of being executed",
                    details=f"The model output JSON for the {tool_name} tool instead of calling it",
                    suggested_action=f"Call the {tool_name} tool directly instead of outputting JSON"
                )
        return None

    def _claims_success(self, text: str) -> bool:
        """Return True if text contains a success claim.

        Uses keyword-set + proximity window rather than regex alternation to
        avoid false positives like "I can create files" (capability statements).
        """
        lower = text.lower()
        for signal in self.CLAIM_SIGNALS:
            pos = lower.find(signal)
            while pos != -1:
                window_start = max(0, pos - self.CLAIM_PROXIMITY)
                window_end = min(len(lower), pos + len(signal) + self.CLAIM_PROXIMITY)
                window = lower[window_start:window_end]
                if any(verb in window for verb in self.SUCCESS_VERBS):
                    return True
                pos = lower.find(signal, pos + 1)
        return False

    def _check_success_after_failure(self, response: str) -> Optional[ValidationWarning]:
        """Check if model claims success but a tool failed."""
        # Check if response claims success
        claims_success = self._claims_success(response)

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

    # Filename pattern that handles:
    #   - dotfiles:           .env, .gitignore
    #   - multi-dot names:    config.backup.json, styles.min.css
    #   - long extensions:    README.backup (>5 chars)
    # Pattern: optional leading dot, name chars, then one-or-more .ext segments.
    _FILENAME_PAT = r'(?:\.[\w\-]+|[^\s`"\']*\w(?:\.\w+)+)'

    def _check_file_claims_without_tools(self, response: str) -> Optional[ValidationWarning]:
        """Check if model claims to have created/written/patched a file without using appropriate tools."""
        fp = self._FILENAME_PAT
        file_modification_patterns = [
            # Creation claims: "created styles.css", "written the file `app.js`"
            rf"(?:created|written|saved|generated)\s+(?:the\s+)?(?:file\s+)?[`\"']?({fp})[`\"']?",
            rf"[`\"']({fp})[`\"']?\s+(?:has been|is now|was)\s+(?:created|written|saved)",
            rf"saved (?:to|as|in) [`\"']?({fp})[`\"']?",
            # Patch/update claims: "Applied patches to index.html", "updated `script.js`"
            rf"(?:applied|patched|updated|modified|changed|fixed)\s+(?:patches?\s+to\s+)?(?:both\s+)?[`\"']?({fp})[`\"']?",
            rf"I (?:have |'ve )?(?:applied|patched|updated|modified|changed|fixed)\s+[`\"']?({fp})[`\"']?",
            rf"[`\"']({fp})[`\"']?\s+(?:has been|is now|was)\s+(?:updated|patched|modified|fixed|changed)",
        ]

        for pattern in file_modification_patterns:
            match = re.search(pattern, response, re.IGNORECASE)
            if match:
                claimed_file = match.group(1)

                # Skip false positives from common non-file words
                if claimed_file.lower() in ('the', 'a', 'an', 'to', 'in', 'on', 'is', 'it'):
                    continue

                # Check if any write tool was called for this file
                if not self._was_file_written(claimed_file):
                    # Check if ANY write tool was called at all
                    write_tools_called = [
                        r.tool_name for r in self._tool_calls
                        if r.tool_name in self.FILE_WRITE_TOOLS
                    ]

                    if write_tools_called:
                        # Write tools were used, but not for this specific file
                        return ValidationWarning(
                            result=ValidationResult.CLAIM_WITHOUT_ACTION,
                            severity="warning",
                            message=f"Model claims to have modified '{claimed_file}' but no write tool targeted it",
                            details="Write tools were used for other files",
                            suggested_action="Verify the claimed file was actually modified"
                        )
                    else:
                        return ValidationWarning(
                            result=ValidationResult.CLAIM_WITHOUT_ACTION,
                            severity="warning",
                            message=f"Model claims to have modified '{claimed_file}' but no write tool was called",
                            details="No file write operations (write_file, apply_patch) were performed",
                            suggested_action="Use write_file or apply_patch to actually modify the file"
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

    # Patterns indicating the model claims to have read/reviewed files
    READ_CLAIM_PATTERNS = [
        r"I (?:have |'ve )?(?:read|reviewed|re-read|verified|confirmed|checked|examined|inspected) (?:each|all|every|the) (?:\d+ )?files?",
        r"(?:read|reviewed|re-read|verified|confirmed|checked|examined|inspected) (?:each|all|every) (?:of the )?(?:\d+ )?files?",
        r"re-read each file",
        r"verified (?:that )?(?:the )?(?:files?|contents?) match",
        r"I (?:have |'ve )?(?:gone through|looked at|analyzed) (?:each|all|every) (?:of the )?files?",
        r"ALL \d+ FILES? (?:RE-)?READ",
    ]

    def _check_read_claims_without_tools(self, response: str) -> Optional[ValidationWarning]:
        """Check if model claims to have read/reviewed files without any read_file calls."""
        claims_read = any(
            re.search(pattern, response, re.IGNORECASE)
            for pattern in self.READ_CLAIM_PATTERNS
        )

        if not claims_read:
            return None

        # Count actual read_file calls
        read_calls = [r for r in self._tool_calls if r.tool_name in self.FILE_READ_TOOLS]

        if not read_calls:
            return ValidationWarning(
                result=ValidationResult.CLAIM_WITHOUT_ACTION,
                severity="error",
                message="Model claims to have read/reviewed files but no read_file calls were made",
                details=f"Tool calls: {[r.tool_name for r in self._tool_calls] or 'none'}",
                suggested_action="Use read_file to actually read files before claiming to have reviewed them"
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


def check_session_pollution(
    response_text: str,
    recent_assistant_messages: List[str],
    threshold: float = 0.9,
) -> Optional[ValidationWarning]:
    """Detect session pollution after model switch (B7).

    Compares the new model's response against recent assistant messages.
    If similarity exceeds threshold, the new model may be parroting cached
    context from the previous model instead of generating fresh output.

    Args:
        response_text: Current model's response
        recent_assistant_messages: Last N assistant messages from session
        threshold: Similarity threshold (0.0-1.0), default 0.9

    Returns:
        ValidationWarning if pollution detected, None otherwise
    """
    if not response_text or not recent_assistant_messages:
        return None

    response_clean = response_text.strip().lower()
    if len(response_clean) < 50:
        return None  # Too short to meaningfully compare

    for prev_msg in recent_assistant_messages:
        prev_clean = prev_msg.strip().lower()
        if len(prev_clean) < 50:
            continue

        similarity = _text_similarity(response_clean, prev_clean)
        if similarity >= threshold:
            return ValidationWarning(
                result=ValidationResult.SESSION_POLLUTION,
                severity="warning",
                message=f"Response is {similarity:.0%} similar to a previous model's output — possible session pollution",
                details=f"New response ({len(response_text)} chars) closely matches prior assistant message ({len(prev_msg)} chars)",
                suggested_action="Try /model <name> again or use /clear to start fresh",
            )

    return None


def _text_similarity(a: str, b: str) -> float:
    """Compute normalized text similarity using character-level overlap.

    Uses a simple ratio of shared content to total content, optimized for
    speed over precision. Good enough to detect near-identical responses.
    """
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0

    # Use set-based bigram overlap (fast approximation of edit similarity)
    def bigrams(s):
        return set(s[i:i+2] for i in range(len(s) - 1))

    a_bi = bigrams(a)
    b_bi = bigrams(b)

    if not a_bi or not b_bi:
        return 0.0

    intersection = len(a_bi & b_bi)
    union = len(a_bi | b_bi)
    return intersection / union if union > 0 else 0.0
