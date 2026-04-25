"""Static structural tests for the file-tree → AppState subscriber (v1.18.1).

State-sync determinism Phase C. Pre-v1.18.1 the file-tree refresh
on cwd change was inline in the working_dir_changed SSE handler
(line 2012-2032 of app.js), with a 300ms debounce + a parallel
_fileTreeCurrentPath cache to dedupe session-restore replays. The
folder badge update was duplicated across handleStateSync (line
906-907) and the same SSE handler. Four write paths to cwd:

  - working_dir_changed event (chat-stream replay)
  - state_sync event (REST piggyback / SSE during chat)
  - cd command optimistic update (apiClient.setWorkingDir result)
  - session restore / load result

each had to remember to fire badge + tree refresh. Drift between
them caused the rare misalignment symptom.

Phase C: AppState equality-dedup + a single subscriber consolidate
the four paths. Each just writes `state.workingDir = ...`; the
subscriber fires badge + tree refresh exactly once per real change
(no debounce needed at this layer).

Drift fences:
  - The subscriber is wired in init().
  - _fileTreeCurrentPath and _fileTreeRefreshTimer are gone.
  - The working_dir_changed SSE handler doesn't refresh inline.
  - The handleStateSync working_dir branch doesn't call
    updateFolderBadge inline.
"""

from __future__ import annotations

import re
from pathlib import Path

APP_JS = Path(__file__).resolve().parents[1] / "ppxai" / "web" / "app.js"


def _read() -> str:
    return APP_JS.read_text(encoding="utf-8")


class TestSubscriberWiring:
    def test_subscriber_method_defined(self):
        src = _read()
        assert re.search(r"\b_onWorkingDirChanged\s*\(\s*cwd\s*\)", src), (
            "_onWorkingDirChanged(cwd) method not found"
        )

    def test_subscriber_registered_in_init(self):
        """`state.on('workingDir', ...)` must be wired in init()
        so the first AppState write from the connection sequence
        already fires the listener."""
        src = _read()
        assert re.search(
            r"this\.state\.on\(\s*['\"]workingDir['\"]",
            src,
        ), "state.on('workingDir', ...) not registered in app.js"

    def test_subscriber_calls_badge_and_tree_refresh(self):
        """The subscriber must do both DOM side-effects so the
        four cwd-write paths can't drift."""
        src = _read()
        # Find the _onWorkingDirChanged body
        match = re.search(
            r"_onWorkingDirChanged\s*\(\s*cwd\s*\)\s*\{[\s\S]*?\n    \}",
            src,
        )
        assert match, "could not extract _onWorkingDirChanged body"
        body = match.group(0)
        assert "updateFolderBadge" in body, (
            "_onWorkingDirChanged must call updateFolderBadge"
        )
        assert "_fileTree" in body and "refresh" in body, (
            "_onWorkingDirChanged must refresh the file tree"
        )


class TestStaleStateRemoved:
    """Phase C drops `_fileTreeCurrentPath` and `_fileTreeRefreshTimer`
    — they were a 300ms debounce hack to dedupe session-restore
    replays. AppState.set is now equality-deduplicated, so the
    same value arriving multiple times only fires the subscriber
    once. The cache is no longer needed."""

    def test_no_filetree_current_path(self):
        src = _read()
        assert "_fileTreeCurrentPath" not in src, (
            "_fileTreeCurrentPath should be removed; AppState dedup "
            "now handles same-value replays."
        )

    def test_no_filetree_refresh_timer(self):
        src = _read()
        assert "_fileTreeRefreshTimer" not in src, (
            "_fileTreeRefreshTimer should be removed; the inline "
            "300ms debounce is replaced by AppState equality dedup."
        )

    def test_no_inline_settimeout_for_tree_refresh(self):
        """The old code wrapped `_fileTree.refresh(true)` in a
        setTimeout. After Phase C, the refresh is a direct call from
        the subscriber. A lingering setTimeout around tree refresh
        is a regression."""
        src = _read()
        # Look for setTimeout near _fileTree.refresh
        for m in re.finditer(r"setTimeout\([\s\S]*?\)", src):
            block = m.group(0)
            if "_fileTree" in block and "refresh" in block:
                raise AssertionError(
                    f"Found setTimeout wrapping _fileTree.refresh: "
                    f"{block[:200]}... — Phase C makes this redundant."
                )


class TestEventHandlersDelegateToSubscriber:
    """Both the working_dir_changed SSE handler and the state_sync
    handler now write through AppState and rely on the subscriber.
    Direct calls to updateFolderBadge / _fileTree.refresh from these
    handlers are a regression."""

    def test_working_dir_changed_handler_minimal(self):
        src = _read()
        # Find the working_dir_changed case body
        match = re.search(
            r"case\s+['\"]working_dir_changed['\"]\s*:[\s\S]*?break;",
            src,
        )
        assert match, "could not find working_dir_changed handler"
        body = match.group(0)
        # Should write through state.workingDir
        assert "this.state.workingDir" in body
        # Should NOT call updateFolderBadge or _fileTree.refresh
        assert "updateFolderBadge" not in body, (
            "working_dir_changed handler should not call updateFolderBadge "
            "directly; the AppState subscriber does that."
        )
        assert "_fileTree.refresh" not in body, (
            "working_dir_changed handler should not call _fileTree.refresh "
            "directly; the AppState subscriber does that."
        )

    def test_state_sync_working_dir_branch_does_not_double_call(self):
        """The handleStateSync branch for working_dir must NOT call
        updateFolderBadge — updateFromPython() writes through
        AppState first, which fires the subscriber, which calls
        updateFolderBadge. Calling it again here would just do the
        DOM work twice for the same change."""
        src = _read()
        # Find the handleStateSync method body
        match = re.search(
            r"handleStateSync\s*\(\s*changes\s*\)\s*\{[\s\S]*?\n    \}",
            src,
        )
        assert match, "could not find handleStateSync method"
        body = match.group(0)
        # The working_dir branch should be present (we keep it as
        # a no-op marker for the keyMap completeness) but must
        # not call updateFolderBadge inside.
        wd_branch = re.search(
            r"pyKey\s*===\s*['\"]working_dir['\"][\s\S]*?\}\s*else",
            body,
        )
        if wd_branch:
            # Ensure the branch body is empty / no badge call
            assert "updateFolderBadge" not in wd_branch.group(0), (
                "handleStateSync working_dir branch must not call "
                "updateFolderBadge directly; subscriber handles it."
            )
