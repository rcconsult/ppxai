"""Tests for `_compute_tool_success` — the per-tool-call success
classification that feeds the validator's `claim_contradicts_result`
warning and the agent zombie-loop circuit-breaker.

v1.18.7 fix: shell tool results were being misclassified as failed when
LibreOffice (and other tools) wrote benign 'failed' / 'error' strings
to stderr that the shell wrapper captured into its output. The new
implementation reads the authoritative exit code from the wrapper's
'[cwd: X, exit: N]' header instead of substring-matching the body.
"""

from __future__ import annotations

import pytest

from ppxai.engine.chat import _compute_tool_success


# ---------------------------------------------------------------------------
# Shell tools — header-based exit-code parsing (v1.18.7 fix)
# ---------------------------------------------------------------------------


class TestShellToolSuccess:
    def test_clean_success_no_exit_suffix(self):
        # Shell wrapper emits "[cwd: X]\n..." with no ", exit: N" on
        # exit=0.
        result = "[cwd: /workspace]\nhello world\n"
        assert _compute_tool_success("execute_shell_command", result) is True

    def test_explicit_exit_one_fails(self):
        result = "[cwd: /workspace, exit: 1]\nsomething went wrong"
        assert _compute_tool_success("execute_shell_command", result) is False

    def test_explicit_exit_127_fails(self):
        result = "[cwd: /workspace, exit: 127]\ncommand not found: foo"
        assert _compute_tool_success("execute_shell_command", result) is False

    def test_libreoffice_javaldx_warning_is_success(self):
        # THE bug this fix targets. LibreOffice on exit=0 still writes
        # this warning to stderr, the shell wrapper merges it into the
        # output, and the OLD heuristic flagged it as failure because
        # the body contains 'failed'.
        result = (
            "[cwd: /workspace/pydemo]\n"
            "Warning: failed to read path from javaldx\n"
            "convert /workspace/pydemo/deck.pptx -> "
            "/workspace/pydemo/deck.pdf using filter : impress_pdf_Export\n"
        )
        assert _compute_tool_success("execute_shell_command", result) is True

    def test_body_failed_with_nonzero_exit_fails(self):
        # If the command DID fail AND the body mentions 'failed', we
        # still classify as failure — exit code is the signal.
        result = "[cwd: /workspace, exit: 2]\nlibreoffice: failed to open file"
        assert _compute_tool_success("execute_shell_command", result) is False

    def test_body_error_with_zero_exit_is_success(self):
        # tool says "no errors" with exit 0 — body has 'error:' but exit
        # code says success.
        result = (
            "[cwd: /workspace]\n"
            "Compile check: no errors detected (0 error: instances)\n"
        )
        assert _compute_tool_success("execute_shell_command", result) is True

    def test_no_wrapper_falls_back_to_substring_check(self):
        # Custom shell that doesn't emit the [cwd: ...] header — fall
        # back to substring matching so the heuristic still classifies
        # known failure modes correctly.
        result = "Error: command not found\n"
        assert _compute_tool_success("execute_shell_command", result) is False

    def test_no_wrapper_clean_is_success(self):
        result = "hello world\n"
        assert _compute_tool_success("execute_shell_command", result) is True

    def test_execute_command_alias_uses_same_path(self):
        # The wrapper framework uses 'execute_command' as an alias —
        # same heuristic should apply.
        result = "[cwd: /workspace, exit: 1]\nfail"
        assert _compute_tool_success("execute_command", result) is False
        ok = "[cwd: /workspace]\nok"
        assert _compute_tool_success("execute_command", ok) is True


# ---------------------------------------------------------------------------
# Read-only tools — only "Error:" prefix counts as failure
# ---------------------------------------------------------------------------


class TestReadOnlyToolSuccess:
    def test_read_file_with_error_in_body_is_success(self):
        # read_file returns the file's content. Source code that
        # mentions 'error:' or 'failed' is not a tool failure.
        result = (
            "import logging\n"
            "logger.error('something failed: %s', e)\n"
            "raise ValueError('not found')\n"
        )
        assert _compute_tool_success("read_file", result) is True

    def test_read_file_with_error_prefix_is_failure(self):
        result = "Error: file not found"
        assert _compute_tool_success("read_file", result) is False

    @pytest.mark.parametrize("tool", [
        'read_file', 'display_file', 'list_directory',
        'search_files', 'get_working_directory',
    ])
    def test_all_read_only_tools_use_same_rule(self, tool):
        assert _compute_tool_success(tool, "Error: nope") is False
        assert _compute_tool_success(tool, "some clean content") is True


# ---------------------------------------------------------------------------
# Other tools — substring-match fallback (unchanged behavior)
# ---------------------------------------------------------------------------


class TestOtherToolSuccess:
    def test_write_file_success(self):
        assert _compute_tool_success("write_file", "✓ wrote test.py") is True

    def test_write_file_failure(self):
        assert _compute_tool_success(
            "write_file", "Error: permission denied"
        ) is False

    def test_native_pptx_tool_success_text(self):
        # list_pptx_slides returns markdown — substring 'error' must
        # not appear in the success message format.
        ok = "# deck.pptx — 3 slide(s)\n\n## Slide 1\n- Shapes: 2×TEXT\n"
        assert _compute_tool_success("list_pptx_slides", ok) is True

    def test_native_tool_failure_with_error_prefix(self):
        bad = "Error: 'deck.pptx' is not a PowerPoint file"
        assert _compute_tool_success("list_pptx_slides", bad) is False
