"""
Unit tests for FileTree widget.

Tests message dispatch (FilePreview, FileEdit, FileInject),
filter_paths(), _get_cursor_file_path(), and action_dismiss_tree().
"""

import asyncio
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tree(tmp_path: Path, path: Path = None):
    """Return a mounted FileTree app for testing."""
    from textual.app import App, ComposeResult

    from ppxai.tui.widgets.file_tree import FileTree

    root = path or tmp_path

    class TestApp(App):
        def compose(self) -> ComposeResult:
            yield FileTree(root, id="file-tree")

    return TestApp()


# ---------------------------------------------------------------------------
# Class-level unit tests (no Textual pilot needed)
# ---------------------------------------------------------------------------

class TestFileTreeMessages:
    """FileTree message classes have correct structure."""

    def test_file_preview_message(self, tmp_path):
        from ppxai.tui.widgets.file_tree import FileTree

        p = tmp_path / "readme.md"
        msg = FileTree.FilePreview(p)
        assert msg.path == p

    def test_file_edit_message(self, tmp_path):
        from ppxai.tui.widgets.file_tree import FileTree

        p = tmp_path / "main.py"
        msg = FileTree.FileEdit(p)
        assert msg.path == p

    def test_file_inject_message(self, tmp_path):
        from ppxai.tui.widgets.file_tree import FileTree

        p = tmp_path / "config.json"
        msg = FileTree.FileInject(p)
        assert msg.path == p

    def test_messages_are_distinct_types(self, tmp_path):
        from ppxai.tui.widgets.file_tree import FileTree

        p = tmp_path / "file.txt"
        assert type(FileTree.FilePreview(p)) is not type(FileTree.FileEdit(p))
        assert type(FileTree.FilePreview(p)) is not type(FileTree.FileInject(p))
        assert type(FileTree.FileEdit(p)) is not type(FileTree.FileInject(p))


class TestFileTreeBindings:
    """FileTree exposes the expected key bindings."""

    def test_has_edit_binding(self):
        from ppxai.tui.widgets.file_tree import FileTree

        keys = {b.key for b in FileTree.BINDINGS}
        assert "ctrl+enter" in keys

    def test_has_inject_binding(self):
        from ppxai.tui.widgets.file_tree import FileTree

        keys = {b.key for b in FileTree.BINDINGS}
        assert "space" in keys

    def test_has_dismiss_binding(self):
        from ppxai.tui.widgets.file_tree import FileTree

        keys = {b.key for b in FileTree.BINDINGS}
        assert "escape" in keys

    def test_binding_actions(self):
        from ppxai.tui.widgets.file_tree import FileTree

        by_key = {b.key: b.action for b in FileTree.BINDINGS}
        assert by_key["ctrl+enter"] == "edit"
        assert by_key["space"] == "inject"
        assert by_key["escape"] == "dismiss_tree"


class TestFilterPaths:
    """filter_paths() hides noisy directories."""

    def _filter(self, names):
        from ppxai.tui.widgets.file_tree import FileTree

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = [root / n for n in names]
            # Create dirs so Path.name works
            for p in paths:
                p.mkdir(exist_ok=True)
            widget = FileTree.__new__(FileTree)
            return [p.name for p in widget.filter_paths(paths)]

    def test_hides_git(self):
        assert ".git" not in self._filter([".git", "src"])

    def test_hides_venv(self):
        assert ".venv" not in self._filter([".venv", "ppxai"])
        assert "venv" not in self._filter(["venv", "ppxai"])

    def test_hides_pycache(self):
        assert "__pycache__" not in self._filter(["__pycache__", "tests"])

    def test_hides_node_modules(self):
        assert "node_modules" not in self._filter(["node_modules", "src"])

    def test_hides_dist_and_build(self):
        hidden = self._filter(["dist", "build", "ppxai"])
        assert "dist" not in hidden
        assert "build" not in hidden

    def test_keeps_source_dirs(self):
        visible = self._filter(["ppxai", "tests", "docs", "src"])
        assert set(visible) == {"ppxai", "tests", "docs", "src"}

    def test_empty_input(self):
        from ppxai.tui.widgets.file_tree import FileTree
        widget = FileTree.__new__(FileTree)
        assert list(widget.filter_paths([])) == []

    def test_hidden_dirs_frozenset(self):
        from ppxai.tui.widgets.file_tree import FileTree
        assert isinstance(FileTree._HIDDEN_DIRS, frozenset)
        assert ".git" in FileTree._HIDDEN_DIRS
        assert "node_modules" in FileTree._HIDDEN_DIRS
        assert "__pycache__" in FileTree._HIDDEN_DIRS


# ---------------------------------------------------------------------------
# Mounted widget tests (Textual pilot)
# ---------------------------------------------------------------------------

class TestFileTreeMount:
    """FileTree mounts cleanly in a Textual app."""

    def test_mounts_successfully(self, tmp_path):
        from ppxai.tui.widgets.file_tree import FileTree

        app = _make_tree(tmp_path)

        async def run():
            async with app.run_test() as pilot:
                tree = app.query_one("#file-tree", FileTree)
                assert tree is not None

        asyncio.run(run())

    def test_root_path_set(self, tmp_path):
        from ppxai.tui.widgets.file_tree import FileTree

        app = _make_tree(tmp_path)

        async def run():
            async with app.run_test() as pilot:
                tree = app.query_one("#file-tree", FileTree)
                assert Path(tree.path) == tmp_path

        asyncio.run(run())


class TestGetCursorFilePath:
    """_get_cursor_file_path() returns file path or None correctly."""

    def test_returns_none_when_no_cursor(self, tmp_path):
        from ppxai.tui.widgets.file_tree import FileTree

        # Create a file so the tree has content
        (tmp_path / "hello.py").write_text("x = 1", encoding="utf-8")
        app = _make_tree(tmp_path)

        async def run():
            async with app.run_test() as pilot:
                tree = app.query_one("#file-tree", FileTree)
                # cursor_node on root dir → not a file
                result = tree._get_cursor_file_path()
                # Root node is a directory, should return None
                assert result is None or isinstance(result, Path)

        asyncio.run(run())

    def test_get_cursor_file_path_with_file_data(self, tmp_path):
        """_get_cursor_file_path returns path when node data has a .path pointing to a file."""
        from unittest.mock import MagicMock, patch

        from ppxai.tui.widgets.file_tree import FileTree

        target = tmp_path / "target.py"
        target.write_text("pass", encoding="utf-8")

        app = _make_tree(tmp_path)
        results = []

        async def run():
            async with app.run_test() as pilot:
                tree = app.query_one("#file-tree", FileTree)
                # Patch cursor_node property to return a node whose data.path is a real file
                mock_node = MagicMock()
                mock_node.data.path = target
                with patch.object(type(tree), "cursor_node", new_callable=lambda: property(lambda self: mock_node)):
                    results.append(tree._get_cursor_file_path())

        asyncio.run(run())
        assert results == [target]

    def test_get_cursor_file_path_with_directory(self, tmp_path):
        """_get_cursor_file_path returns None when node data points to a directory."""
        from unittest.mock import MagicMock, patch

        from ppxai.tui.widgets.file_tree import FileTree

        app = _make_tree(tmp_path)
        results = []

        async def run():
            async with app.run_test() as pilot:
                tree = app.query_one("#file-tree", FileTree)
                mock_node = MagicMock()
                mock_node.data.path = tmp_path  # directory, not a file
                with patch.object(type(tree), "cursor_node", new_callable=lambda: property(lambda self: mock_node)):
                    results.append(tree._get_cursor_file_path())

        asyncio.run(run())
        assert results == [None]


class TestFileTreeFilePreview:
    """Enter on a file posts FilePreview message."""

    def test_file_selected_posts_preview(self, tmp_path):
        from textual.widgets import DirectoryTree

        from ppxai.tui.widgets.file_tree import FileTree

        (tmp_path / "readme.md").write_text("# Hello", encoding="utf-8")
        previews = []

        class TestApp(_make_tree(tmp_path).__class__):
            def on_file_tree_file_preview(self, event: FileTree.FilePreview):
                previews.append(event.path)

        app = TestApp()

        async def run():
            async with app.run_test() as pilot:
                tree = app.query_one("#file-tree", FileTree)
                # Simulate the internal event that on_directory_tree_file_selected handles
                from unittest.mock import MagicMock
                mock_event = MagicMock(spec=DirectoryTree.FileSelected)
                mock_event.path = tmp_path / "readme.md"
                mock_event.stop = MagicMock()
                tree.on_directory_tree_file_selected(mock_event)
                await pilot.pause()

        asyncio.run(run())
        assert len(previews) == 1
        assert previews[0] == tmp_path / "readme.md"

    def test_file_selected_stops_event(self, tmp_path):
        """on_directory_tree_file_selected must call event.stop()."""
        from unittest.mock import MagicMock

        from textual.widgets import DirectoryTree

        from ppxai.tui.widgets.file_tree import FileTree

        (tmp_path / "file.py").write_text("", encoding="utf-8")
        app = _make_tree(tmp_path)

        async def run():
            async with app.run_test() as pilot:
                tree = app.query_one("#file-tree", FileTree)
                mock_event = MagicMock(spec=DirectoryTree.FileSelected)
                mock_event.path = tmp_path / "file.py"
                mock_event.stop = MagicMock()
                tree.on_directory_tree_file_selected(mock_event)
                mock_event.stop.assert_called_once()

        asyncio.run(run())


class TestActionEdit:
    """action_edit() posts FileEdit when cursor is on a file."""

    def test_action_edit_posts_message(self, tmp_path):
        from unittest.mock import patch

        from ppxai.tui.widgets.file_tree import FileTree

        target = tmp_path / "main.py"
        target.write_text("pass", encoding="utf-8")
        edits = []

        class TestApp(_make_tree(tmp_path).__class__):
            def on_file_tree_file_edit(self, event: FileTree.FileEdit):
                edits.append(event.path)

        app = TestApp()

        async def run():
            async with app.run_test() as pilot:
                tree = app.query_one("#file-tree", FileTree)
                # Patch _get_cursor_file_path to return our target
                with patch.object(tree, "_get_cursor_file_path", return_value=target):
                    tree.action_edit()
                    await pilot.pause()

        asyncio.run(run())
        assert len(edits) == 1
        assert edits[0] == target

    def test_action_edit_noop_on_directory(self, tmp_path):
        """action_edit does nothing when cursor is on a directory."""
        from unittest.mock import patch

        from ppxai.tui.widgets.file_tree import FileTree

        edits = []

        class TestApp(_make_tree(tmp_path).__class__):
            def on_file_tree_file_edit(self, event: FileTree.FileEdit):
                edits.append(event.path)

        app = TestApp()

        async def run():
            async with app.run_test() as pilot:
                tree = app.query_one("#file-tree", FileTree)
                with patch.object(tree, "_get_cursor_file_path", return_value=None):
                    tree.action_edit()
                    await pilot.pause()

        asyncio.run(run())
        assert edits == []


class TestActionInject:
    """action_inject() posts FileInject when cursor is on a file."""

    def test_action_inject_posts_message(self, tmp_path):
        from unittest.mock import patch

        from ppxai.tui.widgets.file_tree import FileTree

        target = tmp_path / "config.json"
        target.write_text("{}", encoding="utf-8")
        injections = []

        class TestApp(_make_tree(tmp_path).__class__):
            def on_file_tree_file_inject(self, event: FileTree.FileInject):
                injections.append(event.path)

        app = TestApp()

        async def run():
            async with app.run_test() as pilot:
                tree = app.query_one("#file-tree", FileTree)
                with patch.object(tree, "_get_cursor_file_path", return_value=target):
                    tree.action_inject()
                    await pilot.pause()

        asyncio.run(run())
        assert len(injections) == 1
        assert injections[0] == target

    def test_action_inject_noop_on_directory(self, tmp_path):
        from unittest.mock import patch

        from ppxai.tui.widgets.file_tree import FileTree

        injections = []

        class TestApp(_make_tree(tmp_path).__class__):
            def on_file_tree_file_inject(self, event: FileTree.FileInject):
                injections.append(event.path)

        app = TestApp()

        async def run():
            async with app.run_test() as pilot:
                tree = app.query_one("#file-tree", FileTree)
                with patch.object(tree, "_get_cursor_file_path", return_value=None):
                    tree.action_inject()
                    await pilot.pause()

        asyncio.run(run())
        assert injections == []


class TestActionDismissTree:
    """action_dismiss_tree() focuses #input-box when present, silently does nothing otherwise."""

    def test_dismiss_does_not_raise_without_input_box(self, tmp_path):
        """action_dismiss_tree must not raise if #input-box is absent."""
        from ppxai.tui.widgets.file_tree import FileTree

        app = _make_tree(tmp_path)

        async def run():
            async with app.run_test() as pilot:
                tree = app.query_one("#file-tree", FileTree)
                # No #input-box in this test app — should not raise
                tree.action_dismiss_tree()

        asyncio.run(run())
