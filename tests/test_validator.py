"""
Tests for the ResponseValidator (v1.15.2 - hallucination detection).

These tests verify that the validator correctly detects:
1. Success claims that contradict tool errors
2. File creation claims without corresponding tool calls
3. Display claims without display_file calls
4. Tool JSON appearing in text instead of actual tool calls
5. Fabricated output that looks like shell results
"""

import pytest
from ppxai.engine.tools.validator import (
    ResponseValidator,
    ValidationResult,
    ValidationWarning,
    validate_response,
)


class TestResponseValidator:
    """Tests for ResponseValidator class."""

    def test_init(self):
        """Test validator initializes with empty state."""
        validator = ResponseValidator()
        assert validator._tool_calls == []
        assert validator._files_successfully_written == set()

    def test_reset(self):
        """Test reset clears all state."""
        validator = ResponseValidator()
        validator.record_tool_call("write_file", {"file_path": "test.py"}, "✓ Success", True, 1)
        validator.reset()
        assert validator._tool_calls == []
        assert validator._files_successfully_written == set()

    def test_record_successful_write(self):
        """Test recording a successful file write."""
        validator = ResponseValidator()
        validator.record_tool_call(
            tool_name="write_file",
            arguments={"file_path": "/path/to/file.py"},
            result="✓ Successfully written",
            success=True,
            iteration=1
        )
        assert len(validator._tool_calls) == 1
        assert "/path/to/file.py" in validator._files_successfully_written

    def test_record_failed_write(self):
        """Test recording a failed file write."""
        validator = ResponseValidator()
        validator.record_tool_call(
            tool_name="write_file",
            arguments={"file_path": "/path/to/file.py"},
            result="Error: Permission denied",
            success=False,
            iteration=1
        )
        assert len(validator._tool_calls) == 1
        assert "/path/to/file.py" not in validator._files_successfully_written


class TestSuccessAfterFailure:
    """Tests for detecting success claims after tool failures."""

    def test_detects_success_claim_after_error(self):
        """Model claims success but tool returned error."""
        validator = ResponseValidator()
        validator.record_tool_call(
            tool_name="write_file",
            arguments={"file_path": "test.py"},
            result="Error: File not found",
            success=False,
            iteration=1
        )

        response = "I've successfully created the file test.py with the requested content."
        warnings = validator.validate_response(response)

        assert len(warnings) >= 1
        assert any(w.result == ValidationResult.CLAIM_CONTRADICTS_RESULT for w in warnings)

    def test_no_warning_when_tool_succeeded(self):
        """No warning when tool actually succeeded."""
        validator = ResponseValidator()
        validator.record_tool_call(
            tool_name="write_file",
            arguments={"file_path": "test.py"},
            result="✓ Successfully created test.py",
            success=True,
            iteration=1
        )

        response = "I've successfully created the file test.py with the requested content."
        warnings = validator.validate_response(response)

        # Should not have claim_contradicts_result
        contradiction_warnings = [w for w in warnings if w.result == ValidationResult.CLAIM_CONTRADICTS_RESULT]
        assert len(contradiction_warnings) == 0

    def test_detects_display_claim_after_not_found(self):
        """Model claims file is open but display_file returned error."""
        validator = ResponseValidator()
        validator.record_tool_call(
            tool_name="display_file",
            arguments={"filepath": "output.md"},
            result="Error: File not found: output.md",
            success=False,
            iteration=1
        )

        response = "The file output.md is now open in the viewer pane."
        warnings = validator.validate_response(response)

        assert len(warnings) >= 1
        error_warnings = [w for w in warnings if w.result == ValidationResult.CLAIM_CONTRADICTS_RESULT]
        assert len(error_warnings) >= 1

    def test_no_false_positive_for_read_file_with_error_content(self):
        """No contradiction when read_file returns source code with error-like strings.

        Bug fix: read_file result IS file content. Source code containing
        'Error:', 'not found', etc. in error handling must not be treated
        as a tool failure.
        """
        validator = ResponseValidator()
        # read_file succeeded - content happens to contain error-like strings
        validator.record_tool_call(
            tool_name="read_file",
            arguments={"filepath": "script.js"},
            result='class App {\n    console.error("Could not load:", error);\n    if (notFound) return;\n}',
            success=True,  # With fix, read-only tools use prefix-based success
            iteration=1
        )
        validator.record_tool_call(
            tool_name="apply_patch",
            arguments={"file_path": "script.js"},
            result="✓ Successfully applied patch to script.js",
            success=True,
            iteration=2
        )

        response = "I've fixed the critical errors in script.js."
        warnings = validator.validate_response(response)

        contradiction_warnings = [w for w in warnings if w.result == ValidationResult.CLAIM_CONTRADICTS_RESULT]
        assert len(contradiction_warnings) == 0


class TestFileClaimsWithoutTools:
    """Tests for detecting file creation claims without tool calls."""

    def test_detects_file_creation_claim_without_tool(self):
        """Model claims to have created a file but no write tool was called."""
        validator = ResponseValidator()
        # Record only a read operation, no write
        validator.record_tool_call(
            tool_name="read_file",
            arguments={"filepath": "input.txt"},
            result="file contents here",
            success=True,
            iteration=1
        )

        response = "I've created the file output.py with the implementation you requested."
        warnings = validator.validate_response(response)

        claim_warnings = [w for w in warnings if w.result == ValidationResult.CLAIM_WITHOUT_ACTION]
        assert len(claim_warnings) >= 1

    def test_no_warning_when_file_was_written(self):
        """No warning when the file was actually written."""
        validator = ResponseValidator()
        validator.record_tool_call(
            tool_name="apply_patch",
            arguments={"file_path": "output.py"},
            result="✓ Successfully applied patch",
            success=True,
            iteration=1
        )

        response = "I've created the file output.py with the implementation you requested."
        warnings = validator.validate_response(response)

        claim_warnings = [w for w in warnings if w.result == ValidationResult.CLAIM_WITHOUT_ACTION]
        assert len(claim_warnings) == 0


class TestDisplayClaimsWithoutTools:
    """Tests for detecting display claims without display_file calls."""

    def test_detects_display_claim_without_tool(self):
        """Model claims file is displayed but display_file was not called."""
        validator = ResponseValidator()
        # Only a write operation, no display
        validator.record_tool_call(
            tool_name="write_file",
            arguments={"file_path": "output.md"},
            result="✓ Success",
            success=True,
            iteration=1
        )

        response = "The file is now open in the viewer pane. You can scroll through it."
        warnings = validator.validate_response(response)

        claim_warnings = [w for w in warnings if w.result == ValidationResult.CLAIM_WITHOUT_ACTION]
        assert len(claim_warnings) >= 1

    def test_no_warning_when_display_was_called(self):
        """No warning when display_file was actually called."""
        validator = ResponseValidator()
        validator.record_tool_call(
            tool_name="display_file",
            arguments={"filepath": "output.md"},
            result="Opening output.md in viewer",
            success=True,
            iteration=1
        )

        response = "The file is now open in the viewer pane."
        warnings = validator.validate_response(response)

        display_warnings = [
            w for w in warnings
            if w.result == ValidationResult.CLAIM_WITHOUT_ACTION and "display" in w.message.lower()
        ]
        assert len(display_warnings) == 0


class TestToolJsonInText:
    """Tests for detecting tool call JSON in response text."""

    def test_detects_json_in_markdown_block(self):
        """Detects tool JSON in markdown code block."""
        validator = ResponseValidator()

        response = '''I'll create the file now.

```json
{
  "tool": "write_file",
  "arguments": {
    "file_path": "test.py",
    "content": "print('hello')"
  }
}
```'''

        warnings = validator.validate_response(response)

        json_warnings = [w for w in warnings if w.result == ValidationResult.TOOL_JSON_IN_TEXT]
        assert len(json_warnings) >= 1
        assert "write_file" in json_warnings[0].message

    def test_detects_inline_tool_json(self):
        """Detects inline tool JSON in response."""
        validator = ResponseValidator()

        response = 'Let me use this: {"tool": "apply_patch", "arguments": {"file_path": "x.py"}}'

        warnings = validator.validate_response(response)

        json_warnings = [w for w in warnings if w.result == ValidationResult.TOOL_JSON_IN_TEXT]
        assert len(json_warnings) >= 1

    def test_no_warning_for_regular_json(self):
        """No warning for regular JSON that isn't a tool call."""
        validator = ResponseValidator()

        response = '''Here's an example config:
```json
{
  "name": "test",
  "version": "1.0"
}
```'''

        warnings = validator.validate_response(response)

        json_warnings = [w for w in warnings if w.result == ValidationResult.TOOL_JSON_IN_TEXT]
        assert len(json_warnings) == 0


class TestFabricatedOutput:
    """Tests for detecting fabricated shell output."""

    def test_detects_fabricated_ls_output(self):
        """Detects fabricated ls -l output without shell command."""
        validator = ResponseValidator()
        # No shell command was run

        response = '''Here's the directory listing:
```
-rw-r--r-- 1 user user 1234 Jan 1 12:00 file.txt
drwxr-xr-x 2 user user 4096 Jan 1 12:00 subdir
```'''

        warnings = validator.validate_response(response)

        fab_warnings = [w for w in warnings if w.result == ValidationResult.FABRICATED_OUTPUT]
        assert len(fab_warnings) >= 1

    def test_no_warning_when_shell_was_run(self):
        """No warning when shell command was actually executed."""
        validator = ResponseValidator()
        validator.record_tool_call(
            tool_name="execute_shell_command",
            arguments={"command": "ls -la"},
            result="-rw-r--r-- 1 user user 1234 file.txt",
            success=True,
            iteration=1
        )

        response = '''Here's the directory listing:
```
-rw-r--r-- 1 user user 1234 file.txt
```'''

        warnings = validator.validate_response(response)

        fab_warnings = [w for w in warnings if w.result == ValidationResult.FABRICATED_OUTPUT]
        assert len(fab_warnings) == 0


class TestConvenienceFunction:
    """Tests for the validate_response convenience function."""

    def test_validate_response_function(self):
        """Test the standalone validate_response function."""
        tool_calls = [
            {
                "tool": "write_file",
                "arguments": {"file_path": "test.py"},
                "result": "Error: Permission denied",
                "success": False
            }
        ]

        response = "I've successfully created test.py."
        warnings = validate_response(response, tool_calls)

        assert len(warnings) >= 1
        assert any(w.result == ValidationResult.CLAIM_CONTRADICTS_RESULT for w in warnings)


class TestSuccessClaimPatterns:
    """Tests for various success claim patterns."""

    @pytest.mark.parametrize("response", [
        "I've created the file successfully.",
        "I have written the content to the file.",
        "I created a new configuration file.",
        "The file has been created with the content.",
        "The file is now created and ready.",
        "Successfully created the output file.",
        "You can now see the file in the viewer.",
        "The changes have been saved to disk.",
    ])
    def test_detects_various_success_claims(self, response):
        """Test that various success claim patterns are detected."""
        validator = ResponseValidator()
        # Record a failed tool call
        validator.record_tool_call(
            tool_name="write_file",
            arguments={"file_path": "test.txt"},
            result="Error: Disk full",
            success=False,
            iteration=1
        )

        warnings = validator.validate_response(response)

        # Should detect the contradiction
        contradiction_warnings = [w for w in warnings if w.result == ValidationResult.CLAIM_CONTRADICTS_RESULT]
        assert len(contradiction_warnings) >= 1, f"Failed to detect success claim in: {response}"


class TestReadClaimsWithoutTools:
    """Tests for detecting read/review claims without read_file calls (A1)."""

    def test_detects_read_claim_with_zero_reads(self):
        """Model claims 'I read each file' with 0 read_file calls."""
        validator = ResponseValidator()
        # Only a write call, no reads
        validator.record_tool_call(
            tool_name="write_file",
            arguments={"file_path": "output.md"},
            result="✓ Success",
            success=True,
            iteration=1
        )

        response = "I have read each file and verified the contents are correct."
        warnings = validator.validate_response(response)

        read_warnings = [w for w in warnings if w.result == ValidationResult.CLAIM_WITHOUT_ACTION
                         and "read" in w.message.lower()]
        assert len(read_warnings) >= 1
        assert read_warnings[0].severity == "error"

    def test_detects_reviewed_all_files_with_zero_reads(self):
        """Model claims 'reviewed all files' with no tool calls at all."""
        validator = ResponseValidator()

        response = "I've reviewed all 8 files and everything looks good."
        warnings = validator.validate_response(response)

        read_warnings = [w for w in warnings if w.result == ValidationResult.CLAIM_WITHOUT_ACTION
                         and "read" in w.message.lower()]
        assert len(read_warnings) >= 1

    def test_detects_all_caps_reread_claim(self):
        """Model claims 'ALL 8 FILES RE-READ' (sonar-pro pattern)."""
        validator = ResponseValidator()

        response = "ALL 8 FILES RE-READ and verified against the original specifications."
        warnings = validator.validate_response(response)

        read_warnings = [w for w in warnings if w.result == ValidationResult.CLAIM_WITHOUT_ACTION
                         and "read" in w.message.lower()]
        assert len(read_warnings) >= 1

    def test_no_warning_when_reads_were_made(self):
        """No warning when read_file was actually called."""
        validator = ResponseValidator()
        for i, fname in enumerate(["a.py", "b.py", "c.py"]):
            validator.record_tool_call(
                tool_name="read_file",
                arguments={"filepath": fname},
                result=f"contents of {fname}",
                success=True,
                iteration=i + 1
            )

        response = "I have read each file and here's my analysis."
        warnings = validator.validate_response(response)

        read_warnings = [w for w in warnings if w.result == ValidationResult.CLAIM_WITHOUT_ACTION
                         and "read" in w.message.lower()]
        assert len(read_warnings) == 0

    def test_no_warning_without_read_claim(self):
        """No warning when response doesn't claim to have read files."""
        validator = ResponseValidator()

        response = "Here's a summary of the project structure based on the files you shared."
        warnings = validator.validate_response(response)

        read_warnings = [w for w in warnings if w.result == ValidationResult.CLAIM_WITHOUT_ACTION
                         and "read" in w.message.lower()]
        assert len(read_warnings) == 0


class TestGetSummary:
    """Tests for the debug summary function."""

    def test_empty_summary(self):
        """Test summary with no tool calls."""
        validator = ResponseValidator()
        summary = validator.get_tool_calls_summary()
        assert "No tool calls recorded" in summary

    def test_summary_with_calls(self):
        """Test summary with tool calls."""
        validator = ResponseValidator()
        validator.record_tool_call("read_file", {"filepath": "a.txt"}, "content", True, 1)
        validator.record_tool_call("write_file", {"file_path": "b.txt"}, "Error", False, 2)

        summary = validator.get_tool_calls_summary()

        assert "2 total" in summary
        assert "read_file" in summary
        assert "write_file" in summary
        assert "✓" in summary  # Success indicator
        assert "✗" in summary  # Failure indicator


class TestPatchClaimsWithoutTools:
    """Tests for detecting patch/update claims without tool calls (v1.16.0).

    Reproduces the codex-mini hallucination pattern where the model says
    "Applied patches to index.html and styles.css" without calling apply_patch.
    """

    def test_detects_applied_patches_claim(self):
        """Model claims 'Applied patches to X' but no apply_patch was called."""
        validator = ResponseValidator()
        # Only read operations — no writes
        validator.record_tool_call("read_file", {"filepath": "script.js"}, "content", True, 1)
        validator.record_tool_call("read_file", {"filepath": "index.html"}, "content", True, 2)

        response = "Applied patches to both `index.html` and `styles.css` to support the Matrix animation overlay."
        warnings = validator.validate_response(response)

        claim_warnings = [w for w in warnings if w.result == ValidationResult.CLAIM_WITHOUT_ACTION]
        assert len(claim_warnings) >= 1
        assert "modified" in claim_warnings[0].message.lower() or "write tool" in claim_warnings[0].details.lower()

    def test_detects_updated_file_claim(self):
        """Model claims 'I have updated script.js' but no write tool was called."""
        validator = ResponseValidator()
        validator.record_tool_call("read_file", {"filepath": "script.js"}, "content", True, 1)

        response = "I have updated `script.js` so delete buttons are wired via JavaScript callbacks."
        warnings = validator.validate_response(response)

        claim_warnings = [w for w in warnings if w.result == ValidationResult.CLAIM_WITHOUT_ACTION]
        assert len(claim_warnings) >= 1

    def test_detects_modified_file_claim(self):
        """Model claims to have modified a file without tools."""
        validator = ResponseValidator()

        response = "I've modified `styles.css` to fix the z-index issue."
        warnings = validator.validate_response(response)

        claim_warnings = [w for w in warnings if w.result == ValidationResult.CLAIM_WITHOUT_ACTION]
        assert len(claim_warnings) >= 1

    def test_detects_fixed_file_claim(self):
        """Model claims to have fixed a file without tools."""
        validator = ResponseValidator()

        response = "Fixed `app.js` to handle the toggle correctly."
        warnings = validator.validate_response(response)

        claim_warnings = [w for w in warnings if w.result == ValidationResult.CLAIM_WITHOUT_ACTION]
        assert len(claim_warnings) >= 1

    def test_no_warning_when_apply_patch_was_called(self):
        """No warning when apply_patch was actually called for the file."""
        validator = ResponseValidator()
        validator.record_tool_call(
            "apply_patch",
            {"file_path": "styles.css"},
            "✓ Successfully applied patch to styles.css",
            True,
            iteration=1
        )

        response = "Applied patches to `styles.css` to fix the z-index."
        warnings = validator.validate_response(response)

        claim_warnings = [w for w in warnings if w.result == ValidationResult.CLAIM_WITHOUT_ACTION]
        assert len(claim_warnings) == 0

    def test_no_warning_when_write_file_was_called(self):
        """No warning when write_file was called for the file."""
        validator = ResponseValidator()
        validator.record_tool_call(
            "write_file",
            {"file_path": "index.html"},
            "✓ File written",
            True,
            iteration=1
        )

        response = "I've updated `index.html` with the new toggle button."
        warnings = validator.validate_response(response)

        claim_warnings = [w for w in warnings if w.result == ValidationResult.CLAIM_WITHOUT_ACTION]
        assert len(claim_warnings) == 0

    def test_no_false_positive_on_discussion(self):
        """No warning when model discusses changes without claiming to have made them."""
        validator = ResponseValidator()

        response = "I can update `styles.css` to fix the z-index. Want me to proceed?"
        warnings = validator.validate_response(response)

        claim_warnings = [w for w in warnings if w.result == ValidationResult.CLAIM_WITHOUT_ACTION]
        assert len(claim_warnings) == 0


class TestWrongFileClaimDetection:
    """Tests for detecting claims about a file that wasn't actually modified."""

    def test_warns_when_wrong_file_claimed(self):
        """Warning when model claims to have fixed file X but only wrote to file Y."""
        validator = ResponseValidator()
        validator.record_tool_call(
            tool_name="apply_patch",
            arguments={"file_path": "index.html"},
            result="✓ Successfully applied patch to index.html",
            success=True,
            iteration=1
        )

        response = "I've fixed script.js to resolve the syntax errors."
        warnings = validator.validate_response(response)

        claim_warnings = [w for w in warnings if w.result == ValidationResult.CLAIM_WITHOUT_ACTION]
        assert len(claim_warnings) >= 1
        assert "script.js" in claim_warnings[0].message

    def test_no_warning_when_correct_file_claimed(self):
        """No warning when the claimed file matches the written file."""
        validator = ResponseValidator()
        validator.record_tool_call(
            tool_name="apply_patch",
            arguments={"file_path": "script.js"},
            result="✓ Successfully applied patch to script.js",
            success=True,
            iteration=1
        )

        response = "I've fixed script.js to resolve the syntax errors."
        warnings = validator.validate_response(response)

        claim_warnings = [w for w in warnings if w.result == ValidationResult.CLAIM_WITHOUT_ACTION]
        assert len(claim_warnings) == 0

    def test_no_warning_when_multiple_files_written(self):
        """No warning when the claimed file is among multiple written files."""
        validator = ResponseValidator()
        validator.record_tool_call(
            tool_name="apply_patch",
            arguments={"file_path": "index.html"},
            result="✓ Successfully applied patch to index.html",
            success=True,
            iteration=1
        )
        validator.record_tool_call(
            tool_name="replace_block",
            arguments={"file_path": "script.js"},
            result="✓ Successfully replaced block in script.js",
            success=True,
            iteration=2
        )

        response = "I've updated script.js with the Iron Man theme toggle."
        warnings = validator.validate_response(response)

        claim_warnings = [w for w in warnings if w.result == ValidationResult.CLAIM_WITHOUT_ACTION]
        assert len(claim_warnings) == 0
