# GPT-OSS Behavior Mitigation Plan

**Version:** 1.0
**Date:** 2026-02-03
**Target Release:** v1.15.2

> **Note:** These mitigations apply to ALL LLM models, not just GPT-OSS. Any model can exhibit
> hallucination, tool avoidance, or error denial behaviors. The fixes ensure ppxai remains
> reliable regardless of which model is used.

## Overview

This document outlines fixes to mitigate GPT-OSS 120B model behavior issues observed during agentic workflows. The goal is to detect and handle cases where the model:
1. Claims success when tools fail
2. Outputs tool call JSON as text instead of making actual calls
3. Avoids using tools when explicitly requested
4. Hallucinates file existence or content

---

## Phase 1: Critical Fixes (v1.15.2)

### 1.1 Enhanced System Prompt for Tool Result Validation

**File:** `ppxai/engine/tools/manager.py` (tools prompt injection)

**Change:** Add explicit instructions to the tools system prompt:

```python
TOOL_RESULT_VALIDATION_PROMPT = """
CRITICAL RULES FOR TOOL USAGE:
1. ALWAYS check tool_result before claiming success
2. If tool_result contains "Error:" or "not found", acknowledge the failure - do NOT claim success
3. NEVER say "I've created/opened/written" unless a tool_result confirms success
4. If you need to create a file, use write_file or apply_patch tool - describing the content is NOT creating it
5. When user asks you to "use tools" or run a command, you MUST make a tool call - do NOT fabricate output
6. After each tool call, verify the result matches your intended action before proceeding
"""
```

**Implementation:**
```python
def get_tools_prompt(self, tools: list[dict]) -> str:
    base_prompt = self._format_tools_for_prompt(tools)
    return f"{TOOL_RESULT_VALIDATION_PROMPT}\n\n{base_prompt}"
```

---

### 1.2 Post-Response Hallucination Detection

**File:** `ppxai/engine/client.py` (new function)

**Change:** Add detection for common hallucination patterns after model response.

```python
import re
from typing import Optional, Tuple

class HallucinationDetector:
    """Detect potential hallucinations in model responses."""

    # Patterns that indicate the model claims to have performed an action
    SUCCESS_CLAIM_PATTERNS = [
        r"I've (created|written|saved|opened|generated|made|updated|fixed)",
        r"The file .* (has been|is now|was) (created|written|saved|opened|generated)",
        r"Successfully (created|written|saved|opened|generated)",
        r"(is|are) now (open|available|ready|created|saved)",
        r"You can (now )?(see|view|open|scroll through)",
    ]

    # Tool results that indicate failure
    FAILURE_PATTERNS = [
        r"Error:",
        r"not found",
        r"No changes applied",
        r"failed",
        r"does not exist",
        r"permission denied",
    ]

    @classmethod
    def check_response(
        cls,
        response_text: str,
        tool_results: list[dict],
        tool_calls_made: list[str]
    ) -> Optional[Tuple[str, str]]:
        """
        Check if response claims success but tool results indicate failure.

        Returns:
            Tuple of (warning_type, details) if hallucination detected, None otherwise
        """
        # Check if response claims success
        claims_success = any(
            re.search(pattern, response_text, re.IGNORECASE)
            for pattern in cls.SUCCESS_CLAIM_PATTERNS
        )

        if not claims_success:
            return None

        # Check if any tool result indicates failure
        for result in tool_results:
            result_text = str(result.get('result', ''))
            if any(re.search(p, result_text, re.IGNORECASE) for p in cls.FAILURE_PATTERNS):
                return (
                    "success_after_failure",
                    f"Model claims success but tool returned: {result_text[:100]}"
                )

        # Check if success claimed but no relevant tool was called
        file_tools = {'write_file', 'apply_patch', 'insert_text', 'replace_block'}
        display_tools = {'display_file', 'read_file'}

        if re.search(r"(created|written|saved)", response_text, re.IGNORECASE):
            if not any(t in tool_calls_made for t in file_tools):
                return (
                    "success_without_tool",
                    "Model claims file creation but no write tool was called"
                )

        if re.search(r"(opened|open in.*viewer)", response_text, re.IGNORECASE):
            if 'display_file' not in tool_calls_made:
                return (
                    "display_without_tool",
                    "Model claims file is open but display_file was not called"
                )

        return None
```

**Integration in `EngineClient._process_response()`:**
```python
# After processing tool calls and getting response
warning = HallucinationDetector.check_response(
    response_text=assistant_message,
    tool_results=collected_tool_results,
    tool_calls_made=[tc['name'] for tc in tool_calls]
)

if warning:
    warning_type, details = warning
    logger.warning(f"Potential hallucination detected: {warning_type} - {details}")

    # Emit warning event to UI
    await self._emit_event(Event(
        type=EventType.WARNING,
        data={
            "type": "hallucination_detected",
            "warning_type": warning_type,
            "details": details
        }
    ))
```

---

### 1.3 Tool JSON in Text Detection Enhancement

**File:** `ppxai/engine/tools/parser.py`

**Change:** Enhance the existing truncated tool call detection to also handle complete tool JSON in text.

```python
def detect_tool_json_in_text(response_text: str) -> Optional[dict]:
    """
    Detect if the response contains tool call JSON that should have been a tool call.

    This handles cases where GPT-OSS outputs:
    ```json
    {"tool": "apply_patch", "arguments": {...}}
    ```
    instead of making an actual tool call.
    """
    # Pattern for tool JSON in markdown code blocks
    json_block_pattern = r'```json\s*\n?\s*\{\s*"tool"\s*:\s*"(\w+)"'

    # Pattern for inline tool JSON
    inline_pattern = r'\{\s*"tool"\s*:\s*"(\w+)"\s*,\s*"arguments"\s*:'

    for pattern in [json_block_pattern, inline_pattern]:
        match = re.search(pattern, response_text)
        if match:
            tool_name = match.group(1)
            return {
                "detected": True,
                "tool_name": tool_name,
                "pattern": "json_in_text"
            }

    return None
```

**Integration:** When detected, add recovery guidance to next request:
```python
if tool_json := detect_tool_json_in_text(response_text):
    # Add guidance for next iteration
    recovery_message = (
        f"You output tool call JSON as text instead of calling the {tool_json['tool_name']} tool. "
        f"Please make an actual tool call using the {tool_json['tool_name']} tool now."
    )
    # Inject into next request or auto-retry with guidance
```

---

## Phase 2: Additional Improvements (v1.15.2)

### 2.1 Tool Result Validation Layer

**New File:** `ppxai/engine/tools/validator.py`

Create a validation layer that checks model claims against actual tool results.

```python
from dataclasses import dataclass
from enum import Enum
from typing import Optional

class ValidationResult(Enum):
    VALID = "valid"
    CLAIM_WITHOUT_ACTION = "claim_without_action"
    CLAIM_CONTRADICTS_RESULT = "claim_contradicts_result"
    FABRICATED_OUTPUT = "fabricated_output"

@dataclass
class ValidationReport:
    result: ValidationResult
    details: str
    severity: str  # "warning", "error"
    suggested_action: Optional[str] = None

class ToolResultValidator:
    """Validates model responses against actual tool results."""

    def __init__(self):
        self.session_tool_calls: list[dict] = []
        self.session_files_created: set[str] = set()
        self.session_files_read: set[str] = set()

    def record_tool_call(self, tool_name: str, args: dict, result: str):
        """Record a tool call and its result."""
        self.session_tool_calls.append({
            "tool": tool_name,
            "args": args,
            "result": result,
            "success": "error" not in result.lower()
        })

        # Track file operations
        if tool_name in ("write_file", "apply_patch", "insert_text"):
            if "success" in result.lower() or "✓" in result:
                path = args.get("file_path") or args.get("filepath", "")
                self.session_files_created.add(path)

    def validate_response(self, response: str, recent_results: list[dict]) -> ValidationReport:
        """Validate model response against recent tool results."""

        # Check for file creation claims
        file_claims = self._extract_file_claims(response)

        for claimed_file in file_claims:
            # Check if file was actually created this session
            if claimed_file not in self.session_files_created:
                # Check if a tool tried to create it but failed
                failed_attempt = self._find_failed_attempt(claimed_file, recent_results)
                if failed_attempt:
                    return ValidationReport(
                        result=ValidationResult.CLAIM_CONTRADICTS_RESULT,
                        details=f"Claimed '{claimed_file}' was created but tool returned: {failed_attempt}",
                        severity="error",
                        suggested_action="Acknowledge the error and retry the operation"
                    )
                else:
                    return ValidationReport(
                        result=ValidationResult.CLAIM_WITHOUT_ACTION,
                        details=f"Claimed '{claimed_file}' was created but no tool was called to create it",
                        severity="warning",
                        suggested_action="Use write_file or apply_patch to actually create the file"
                    )

        return ValidationReport(
            result=ValidationResult.VALID,
            details="No validation issues detected",
            severity="info"
        )

    def _extract_file_claims(self, response: str) -> list[str]:
        """Extract file paths that the model claims to have created/modified."""
        patterns = [
            r"(?:created|written|saved|generated)\s+(?:the\s+)?(?:file\s+)?[`\"]?([^\s`\"]+\.(?:md|py|txt|json|yaml))[`\"]?",
            r"[`\"]([^\s`\"]+\.(?:md|py|txt|json|yaml))[`\"]?\s+(?:has been|is now|was)\s+(?:created|written|saved)",
        ]

        files = []
        for pattern in patterns:
            matches = re.findall(pattern, response, re.IGNORECASE)
            files.extend(matches)

        return list(set(files))

    def _find_failed_attempt(self, filename: str, results: list[dict]) -> Optional[str]:
        """Find if there was a failed attempt to create this file."""
        for result in results:
            if filename in str(result.get("args", {})):
                result_text = result.get("result", "")
                if "error" in result_text.lower() or "not found" in result_text.lower():
                    return result_text[:200]
        return None
```

---

### 2.2 Tool Avoidance Detection

**File:** `ppxai/engine/client.py`

Detect when user explicitly requests tool use but model doesn't comply.

```python
class ToolAvoidanceDetector:
    """Detect when model avoids using tools despite explicit requests."""

    EXPLICIT_TOOL_REQUESTS = [
        r"use (?:the )?(\w+) tool",
        r"run (?:the )?command",
        r"execute",
        r"call (?:the )?(\w+)",
        r"^(ls|dir|cat|grep|find)\s",  # Shell commands
        r"using tools",
        r"with tools",
    ]

    @classmethod
    def check_avoidance(
        cls,
        user_message: str,
        tool_calls_made: list[str],
        response_text: str
    ) -> Optional[str]:
        """
        Check if user requested tool use but model didn't comply.

        Returns warning message if avoidance detected.
        """
        # Check if user explicitly requested tool use
        requested_tool = False
        for pattern in cls.EXPLICIT_TOOL_REQUESTS:
            if re.search(pattern, user_message, re.IGNORECASE):
                requested_tool = True
                break

        if not requested_tool:
            return None

        # Check if any tools were called
        if tool_calls_made:
            return None

        # Check if response contains fabricated output (looks like tool output but isn't)
        fabricated_patterns = [
            r"^-rw",  # ls -l output
            r"^\d+\s+\w+\s+\w+",  # File listing
            r"```\n.*\n```",  # Code blocks that look like output
        ]

        for pattern in fabricated_patterns:
            if re.search(pattern, response_text, re.MULTILINE):
                return (
                    f"User requested tool use but model fabricated output instead. "
                    f"No tools were called despite explicit request."
                )

        return None
```

---

### 2.3 UI Warning Display

**File:** `ppxai/server/http.py` and `vscode-extension/media/webview/app.js`

Add SSE event handling for hallucination warnings.

**Server (SSE event):**
```python
# New event type
class EventType(Enum):
    # ... existing types ...
    WARNING = "warning"
    HALLUCINATION_DETECTED = "hallucination_detected"
```

**Web App (JavaScript):**
```javascript
case 'hallucination_detected':
    showWarningBanner({
        type: data.warning_type,
        message: getHallucinationWarningMessage(data),
        dismissable: true
    });
    break;

function getHallucinationWarningMessage(data) {
    switch (data.warning_type) {
        case 'success_after_failure':
            return '⚠️ Model claimed success but tool reported an error. Verify the result manually.';
        case 'success_without_tool':
            return '⚠️ Model claimed to create a file but no write operation was performed.';
        case 'display_without_tool':
            return '⚠️ Model claimed to open a file but display_file was not called.';
        default:
            return '⚠️ Potential inconsistency detected in model response.';
    }
}
```

---

## Phase 3: Long-Term Improvements

### 3.1 Model-Specific Behavior Profiles

Create configuration profiles for different models that adjust:
- Retry strategies
- Validation strictness
- System prompt additions
- Tool calling format expectations

```yaml
# ppxai-config.json
{
  "model_profiles": {
    "openai/gpt-oss-*": {
      "validation": {
        "hallucination_detection": "strict",
        "tool_result_validation": true,
        "tool_avoidance_detection": true
      },
      "retry": {
        "on_empty_response": true,
        "on_tool_json_in_text": true,
        "max_retries": 3
      },
      "system_prompt_additions": [
        "ALWAYS verify tool results before claiming success",
        "NEVER output tool JSON in text - make actual tool calls"
      ]
    }
  }
}
```

### 3.2 Confidence Scoring

Implement confidence scoring for model claims based on:
- Whether corresponding tools were called
- Whether tool results support the claims
- Historical accuracy of similar claims

### 3.3 User-Facing Audit Log

Provide users with a tool call audit log showing:
- All tools called during the session
- Results of each tool call
- Model claims vs. actual results
- Flagged inconsistencies

---

## Implementation Priority

| Phase | Item | Priority | Effort | Impact |
|-------|------|----------|--------|--------|
| 1.1 | Enhanced system prompt | High | Low | Medium |
| 1.2 | Hallucination detection | High | Medium | High |
| 1.3 | Tool JSON detection enhancement | High | Low | Medium |
| 2.1 | Tool result validation layer | Medium | High | High |
| 2.2 | Tool avoidance detection | Medium | Medium | Medium |
| 2.3 | UI warning display | Medium | Low | Medium |
| 3.1 | Model behavior profiles | Low | High | High |
| 3.2 | Confidence scoring | Low | High | Medium |
| 3.3 | User audit log | Low | Medium | Medium |

---

## Testing Plan

### Unit Tests
- `test_hallucination_detector.py` - Test detection patterns
- `test_tool_result_validator.py` - Test validation logic
- `test_tool_avoidance_detector.py` - Test avoidance detection

### Integration Tests
- Simulate GPT-OSS failure patterns and verify detection
- Test UI warning display in web app
- Test recovery flows after detection

### Manual Testing
- Run real GPT-OSS sessions with monitoring
- Verify warnings appear appropriately
- Confirm false positive rate is acceptable

---

## Success Metrics

1. **Hallucination Detection Rate**: >90% of false success claims detected
2. **False Positive Rate**: <5% of valid responses flagged incorrectly
3. **User Experience**: Users report increased trust in model outputs
4. **Task Completion**: Reduction in tasks requiring manual verification

---

## References

- [GPT-OSS Behavior Issues Analysis](./GPT-OSS-BEHAVIOR-ISSUES-2026-02-03.md)
- [vLLM Harmony Parser Issue #23567](https://github.com/vllm-project/vllm/issues/23567)
- [CLAUDE.md - vLLM/GPT-OSS Tool Calling Reference](../CLAUDE.md)
