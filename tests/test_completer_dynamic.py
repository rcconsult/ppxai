"""Integration tests for PPXAICompleter — the Rich TUI adapter over
engine.completion.

Since v1.17.x, PPXAICompleter is a thin glue layer that delegates ALL
autocomplete logic to `ppxai.engine.completion.complete()`. Command-name
discovery, alias resolution, hidden-command filtering, and cache
invalidation are now tested directly against the engine in
`tests/test_completion_provider.py`. The tests in this file exercise
the glue layer itself: that `get_completions()` wires `document` +
`complete_event` to the engine and yields prompt_toolkit `Completion`
objects with the right `start_position` / `display` / `display_meta`.
"""

from __future__ import annotations

import pytest
from prompt_toolkit.document import Document

# Triggers all side-effect registrations in commands/*.py
import ppxai.commands.handler  # noqa: F401
from ppxai.commands.factory import CommandFactory
from ppxai.rich.main import PPXAICompleter


@pytest.fixture
def completer() -> PPXAICompleter:
    return PPXAICompleter()


class TestCompletionIntegration:
    """End-to-end: drive get_completions() the way prompt_toolkit does."""

    def _completions_for(self, completer: PPXAICompleter, text: str) -> list[str]:
        doc = Document(text=text, cursor_position=len(text))
        return [c.text for c in completer.get_completions(doc, complete_event=None)]

    def test_attach_prefix_completes(self, completer):
        results = self._completions_for(completer, "/att")
        # Both the alias /att and the canonical /attach start with /att.
        assert "/att" in results
        assert "/attach" in results

    def test_a_prefix_includes_attach_and_agent(self, completer):
        results = self._completions_for(completer, "/a")
        assert "/attach" in results
        assert "/auto" in results
        assert "/att" in results

    def test_quit_prefix_completes_builtin(self, completer):
        results = self._completions_for(completer, "/q")
        assert "/quit" in results

    def test_unknown_prefix_returns_nothing(self, completer):
        results = self._completions_for(completer, "/zzzz")
        assert results == []

    def test_file_completion_takes_precedence_over_commands(self, completer):
        # When there's an @ anywhere in the buffer, file completion runs and
        # slash-command completion is suppressed entirely.
        doc = Document(text="look at @", cursor_position=len("look at @"))
        completions = list(completer.get_completions(doc, complete_event=None))
        # Should be file completions (starting with @) or empty — but never
        # contain slash commands.
        for c in completions:
            assert not c.text.startswith("/")


class TestPathArgumentCompletion:
    """Shell-style path completion for /attach, /cd, /ls, /tree, /show, /preview.

    Uses a throwaway tmp_path tree so these tests don't depend on the actual
    project layout. Every case we care about:
      - empty arg (list working dir)
      - leaf prefix (filter by name)
      - trailing slash (navigate into subdir)
      - nested partial (sub-path + leaf)
      - file vs directory discrimination per command
      - alias resolution (/att, /cat)
      - multi-token commands only complete the last token
      - hidden files skipped unless explicitly requested
    """

    @pytest.fixture
    def completer_in(self, tmp_path):
        """PPXAICompleter rooted at a controlled tmp_path tree."""
        # Build a small deterministic tree:
        #   tmp/
        #     apple.png
        #     banana.txt
        #     .hidden
        #     docs/
        #       guide.md
        #       readme.md
        #     src/
        #       main.py
        #       lib/
        #         helper.py
        (tmp_path / "apple.png").write_bytes(b"")
        (tmp_path / "banana.txt").write_text("", encoding="utf-8")
        (tmp_path / ".hidden").write_text("", encoding="utf-8")
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "guide.md").write_text("", encoding="utf-8")
        (tmp_path / "docs" / "readme.md").write_text("", encoding="utf-8")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("", encoding="utf-8")
        (tmp_path / "src" / "lib").mkdir()
        (tmp_path / "src" / "lib" / "helper.py").write_text("", encoding="utf-8")

        class _FakeEngine:
            def __init__(self, root):
                self._root = str(root)

            def get_working_dir(self):
                return self._root

        class _FakeHandler:
            def __init__(self, root):
                self.engine_client = _FakeEngine(root)

        return PPXAICompleter(command_handler=_FakeHandler(tmp_path))

    def _completions(self, completer, text):
        doc = Document(text=text, cursor_position=len(text))
        return list(completer.get_completions(doc, complete_event=None))

    # -------------------- /attach (files + dirs) --------------------

    def test_attach_empty_arg_lists_working_dir(self, completer_in):
        results = self._completions(completer_in, "/attach ")
        texts = [c.text for c in results]
        # Directories first with trailing slash, then files.
        assert "docs/" in texts
        assert "src/" in texts
        assert "apple.png" in texts
        assert "banana.txt" in texts
        # Hidden files not shown.
        assert ".hidden" not in texts

    def test_attach_directories_appear_before_files(self, completer_in):
        results = self._completions(completer_in, "/attach ")
        # Find the indices of first file and last directory.
        texts = [c.text for c in results]
        dir_indices = [i for i, t in enumerate(texts) if t.endswith("/")]
        file_indices = [i for i, t in enumerate(texts) if not t.endswith("/")]
        assert dir_indices, "expected at least one directory"
        assert file_indices, "expected at least one file"
        assert max(dir_indices) < min(file_indices), (
            "directories must sort before files"
        )

    def test_attach_leaf_prefix_filters(self, completer_in):
        results = self._completions(completer_in, "/attach ap")
        texts = [c.text for c in results]
        assert texts == ["apple.png"]
        # start_position replaces only the leaf, not the full arg region.
        assert results[0].start_position == -2

    def test_attach_trailing_slash_navigates_into_dir(self, completer_in):
        results = self._completions(completer_in, "/attach docs/")
        texts = [c.text for c in results]
        assert "guide.md" in texts
        assert "readme.md" in texts
        # start_position is 0 because the leaf is empty.
        for c in results:
            assert c.start_position == 0

    def test_attach_sub_path_filter(self, completer_in):
        results = self._completions(completer_in, "/attach docs/gu")
        texts = [c.text for c in results]
        assert texts == ["guide.md"]
        # Replace only the 2-char leaf "gu", not the whole "docs/gu".
        assert results[0].start_position == -2

    def test_attach_nested_sub_path(self, completer_in):
        results = self._completions(completer_in, "/attach src/lib/")
        texts = [c.text for c in results]
        assert "helper.py" in texts

    def test_attach_multi_token_only_completes_last(self, completer_in):
        # First arg already present, user is typing a second path.
        results = self._completions(completer_in, "/attach apple.png ba")
        texts = [c.text for c in results]
        assert texts == ["banana.txt"]
        # Replacement scoped to the last token only.
        assert results[0].start_position == -2

    def test_attach_hidden_shown_when_dot_typed(self, completer_in):
        results = self._completions(completer_in, "/attach .")
        texts = [c.text for c in results]
        assert ".hidden" in texts

    # -------------------- /cd (dirs only) --------------------

    def test_cd_lists_only_directories(self, completer_in):
        results = self._completions(completer_in, "/cd ")
        texts = [c.text for c in results]
        # Only directories, with trailing slash.
        assert all(t.endswith("/") for t in texts), f"non-dir entries: {texts}"
        assert "docs/" in texts
        assert "src/" in texts
        # Files must not appear.
        assert "apple.png" not in texts

    def test_cd_sub_path_filters_dirs(self, completer_in):
        results = self._completions(completer_in, "/cd src/")
        texts = [c.text for c in results]
        assert "lib/" in texts
        # src/main.py is a file — must not appear under /cd.
        assert "main.py" not in texts

    def test_tree_lists_only_directories(self, completer_in):
        results = self._completions(completer_in, "/tree ")
        texts = [c.text for c in results]
        assert all(t.endswith("/") for t in texts)
        assert "apple.png" not in texts

    # -------------------- /show, /preview (files + dirs for traversal) --------------------

    def test_show_includes_files_and_dirs(self, completer_in):
        results = self._completions(completer_in, "/show ")
        texts = [c.text for c in results]
        assert "apple.png" in texts
        assert "docs/" in texts  # dir offered for traversal

    def test_preview_includes_files(self, completer_in):
        results = self._completions(completer_in, "/preview docs/gu")
        texts = [c.text for c in results]
        assert "guide.md" in texts

    # -------------------- Alias resolution --------------------

    def test_att_alias_completes_paths(self, completer_in):
        # /att is the alias for /attach — must behave identically.
        results = self._completions(completer_in, "/att ap")
        texts = [c.text for c in results]
        assert "apple.png" in texts

    def test_cat_alias_completes_paths(self, completer_in):
        # /cat is the alias for /show — same path semantics.
        results = self._completions(completer_in, "/cat ap")
        texts = [c.text for c in results]
        assert "apple.png" in texts

    # -------------------- Non-path commands don't trigger path completion --------------------

    def test_help_does_not_trigger_path_completion(self, completer_in):
        # /help takes no path — it should fall through to generic command
        # name completion (which won't match anything starting with "docs/").
        results = self._completions(completer_in, "/help docs/")
        texts = [c.text for c in results]
        # No path entries; generic command loop also yields nothing for this prefix.
        assert "guide.md" not in texts
        assert "readme.md" not in texts

    def test_nonexistent_path_returns_nothing(self, completer_in):
        results = self._completions(completer_in, "/attach nonexistent/deep/path/")
        assert results == []
