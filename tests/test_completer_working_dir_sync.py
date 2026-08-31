"""Autocomplete must follow the working directory.

Replaces `test_cd_sync.py` and `test_ai_tool_cd_sync.py`, which were near-identical
`print()` scripts with zero test functions -- pytest collected 0 items from both, so
they asserted nothing while looking like coverage. They also read `Path.cwd()` and
required a real `docs/` directory, the same host-state dependence that made the
server smoke test flaky.

Both paths that move the working directory converge here:
  * user types `/cd docs`            -> app calls completer.update_working_dir()
  * AI calls the set_working_dir tool -> engine emits WORKING_DIR_CHANGED
                                      -> app._on_working_dir_changed()
                                      -> completer.update_working_dir()
They differ only in what triggers the call, so one set of assertions covers both.
"""


import pytest

from ppxai.tui.completer import TextualCompleter


@pytest.fixture
def workspace(tmp_path):
    """Two sibling dirs with distinct, unmistakable contents."""
    root = tmp_path / "root"
    sub = root / "docs"
    sub.mkdir(parents=True)
    (root / "root_marker.py").write_text("# root\n", encoding="utf-8")
    (root / "another_root_file.py").write_text("# root\n", encoding="utf-8")
    (sub / "docs_marker.md").write_text("# docs\n", encoding="utf-8")
    return root, sub


def _names(completer, text="/show "):
    return [replacement for replacement, _desc in completer.get_completions(text)]


class TestCompleterFollowsWorkingDir:
    def test_completes_against_initial_dir(self, workspace):
        root, _ = workspace
        completer = TextualCompleter(working_dir=root)
        joined = " ".join(_names(completer))
        assert "root_marker.py" in joined
        assert "docs_marker.md" not in joined

    def test_update_switches_the_completion_source(self, workspace):
        """The behavior the old scripts printed but never asserted."""
        root, sub = workspace
        completer = TextualCompleter(working_dir=root)
        completer.update_working_dir(sub)
        joined = " ".join(_names(completer))
        assert "docs_marker.md" in joined
        assert "root_marker.py" not in joined, (
            "completer still offers the old directory's files after a cd"
        )

    def test_update_is_reversible(self, workspace):
        root, sub = workspace
        completer = TextualCompleter(working_dir=root)
        completer.update_working_dir(sub)
        completer.update_working_dir(root)
        assert completer.working_dir == root
        assert "root_marker.py" in " ".join(_names(completer))

    def test_working_dir_attribute_tracks_updates(self, workspace):
        root, sub = workspace
        completer = TextualCompleter(working_dir=root)
        assert completer.working_dir == root
        completer.update_working_dir(sub)
        assert completer.working_dir == sub

    def test_missing_directory_degrades_instead_of_crashing(self, workspace, tmp_path):
        """A cd into a since-deleted dir must degrade, not crash the TUI."""
        root, _ = workspace
        completer = TextualCompleter(working_dir=root)
        completer.update_working_dir(tmp_path / "gone")
        result = completer.get_completions("/show ")
        assert isinstance(result, list)
        assert "root_marker.py" not in " ".join(r for r, _ in result), (
            "stale completions from the previous directory survived the cd"
        )
