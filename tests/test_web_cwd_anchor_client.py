"""Static structural tests for the web-side cwd_anchor wiring (v1.18.1 Phase D).

The server-side 409 contract is exercised by tests/test_files_cwd_anchor.py.
This file pins the client structural contracts:

  - api-client throws structured errors (status, body, expected,
    actual, events) that callers can introspect on 409.
  - file-tree records `workingDirAtLoad` from /files/list responses
    and passes it through click handlers as `cwdAnchor`.
  - app.handleCwdAnchorMismatch consumes events[] from the 409
    body and feeds them through handleStateSync (so AppState
    catches up and the file tree refreshes via the Phase C
    subscriber).
  - All six file-views (CodeEditor, Image, Pdf, Markdown, Data) have
    an `_cwdAnchor` field and pass it to readFile.
  - View error paths catch err.status === 409 and call the recovery
    helper before showing a generic "failed to load" message.

Runtime is exercised by the e2e suite (Step 6).
"""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "ppxai" / "web"


def _read(rel: str) -> str:
    return (WEB / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# api-client structured errors
# ---------------------------------------------------------------------------

class TestApiClientStructuredErrors:
    def test_throws_with_status_attached(self):
        src = _read("shared/api-client.js")
        assert "err.status" in src, (
            "api-client must attach .status to thrown errors so "
            "callers can branch on 409"
        )

    def test_extracts_expected_actual_events(self):
        """The 409 body has {detail, expected, actual, events} —
        api-client must surface them as top-level error fields."""
        src = _read("shared/api-client.js")
        assert "err.expected" in src
        assert "err.actual" in src
        assert "err.events" in src

    def test_message_remains_string_compat(self):
        """Existing callers do `err.message.includes('404')` —
        the rewrite must keep err.message a usable string."""
        src = _read("shared/api-client.js")
        # The new helper builds messageParts[] then joins
        assert "messageParts" in src or "err.message" in src


# ---------------------------------------------------------------------------
# File tree records the anchor + plumbs it through click handlers
# ---------------------------------------------------------------------------

class TestFileTreeAnchor:
    def test_workingDirAtLoad_field(self):
        src = _read("components/file-tree.js")
        assert "workingDirAtLoad" in src

    def test_anchor_recorded_from_files_list_response(self):
        """When /files/list returns `working_dir`, the file tree
        stores it as `workingDirAtLoad` for use as cwd_anchor."""
        src = _read("components/file-tree.js")
        # Look for the assignment pattern
        assert re.search(
            r"this\.workingDirAtLoad\s*=\s*data\.working_dir",
            src,
        ), "workingDirAtLoad must be set from /files/list response"

    def test_click_handlers_pass_anchor(self):
        """onFileClick / onFileEdit must receive the anchor as the
        second arg so the receiving view can pass it to readFile."""
        src = _read("components/file-tree.js")
        # Find the click handler block
        assert re.search(
            r"this\.onFileClick\(\s*path\s*,\s*\w+\s*\)",
            src,
        ), "onFileClick should pass cwdAnchor as second argument"
        assert re.search(
            r"this\.onFileEdit\(\s*path\s*,\s*\w+\s*\)",
            src,
        ), "onFileEdit should pass cwdAnchor as second argument"


# ---------------------------------------------------------------------------
# All views accept and pass the anchor
# ---------------------------------------------------------------------------

class TestViewsAcceptCwdAnchor:
    VIEWS = [
        "components/views/code-editor-view.js",
        "components/views/image-file-view.js",
        "components/views/markdown-file-view.js",
        "components/views/data-file-view.js",
        "components/views/pdf-file-view.js",
    ]

    def test_each_view_stores_cwdAnchor(self):
        """Every view stores _cwdAnchor in its constructor so
        readFile() can pass it on later mounts."""
        for v in self.VIEWS:
            src = _read(v)
            assert "_cwdAnchor" in src, (
                f"{v} missing _cwdAnchor field — needed for Phase D anchor"
            )

    def test_each_view_passes_anchor_to_readfile(self):
        for v in self.VIEWS:
            src = _read(v)
            assert "readFile(this._path, this._cwdAnchor)" in src, (
                f"{v} must pass this._cwdAnchor to apiClient.readFile"
            )


# ---------------------------------------------------------------------------
# Error path: views catch 409 and call the recovery helper
# ---------------------------------------------------------------------------

class TestViewsHandle409:
    VIEWS_WITH_RECOVERY = [
        "components/views/code-editor-view.js",
        "components/views/image-file-view.js",
        "components/views/markdown-file-view.js",
        "components/views/data-file-view.js",
        "components/views/pdf-file-view.js",
    ]

    def test_each_view_calls_recovery_on_409(self):
        for v in self.VIEWS_WITH_RECOVERY:
            src = _read(v)
            assert "handleCwdAnchorMismatch" in src, (
                f"{v} read-error path must call handleCwdAnchorMismatch "
                f"on err.status === 409"
            )


# ---------------------------------------------------------------------------
# app.handleCwdAnchorMismatch
# ---------------------------------------------------------------------------

class TestAppRecoveryHelper:
    def test_helper_defined(self):
        src = _read("app.js")
        assert re.search(
            r"\bhandleCwdAnchorMismatch\s*\(\s*err\s*\)",
            src,
        ), "PpxaiApp.handleCwdAnchorMismatch(err) not found"

    def test_helper_drains_events_through_handlestate_sync(self):
        """The helper must feed events[] from the 409 body through
        the same dispatcher as live SSE state_sync — so AppState
        catches up and the Phase C subscriber refreshes the tree."""
        src = _read("app.js")
        # Find the handler body
        match = re.search(
            r"handleCwdAnchorMismatch\s*\(\s*err\s*\)\s*\{[\s\S]*?\n    \}",
            src,
        )
        assert match, "could not extract handleCwdAnchorMismatch body"
        body = match.group(0)
        assert "handleStateSync" in body or "processSseEvent" in body, (
            "helper must dispatch err.events through the SSE handler"
        )
        # Drift fence: helper guards on err.status === 409 (so it
        # can be called from any catch without false positives)
        assert "409" in body
