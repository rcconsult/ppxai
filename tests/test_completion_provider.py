"""Tests for engine-level CompletionProvider (Task #11, v1.17.4).

Exercises the `complete()` function that all four clients delegate to —
directly for Rich/Textual, via POST /complete for Web/VSCode.

Scope:
    - Slash command completion from CommandFactory
    - Alias resolution + annotation
    - Builtin specials (/quit, /exit)
    - Path argument completion per command
    - @file reference completion
    - Empty / unknown input → empty results
"""

from __future__ import annotations

import pytest

# Trigger side-effect registrations so CommandFactory is populated
import ppxai.commands.handler  # noqa: F401

from ppxai.engine.completion import complete


@pytest.fixture
def populated_dir(tmp_path):
    """A tmp dir with predictable files and dirs."""
    (tmp_path / "alpha.txt").write_text("a")
    (tmp_path / "beta.py").write_text("b")
    sub = tmp_path / "subdir"
    sub.mkdir()
    (sub / "deep.md").write_text("d")
    (tmp_path / ".hidden").write_text("h")
    return tmp_path


class TestCommandCompletion:
    def test_slash_a_includes_attach(self):
        items = complete("/a")
        texts = [i["text"] for i in items]
        assert "/attach" in texts
        assert "/agent" in texts

    def test_slash_att_includes_alias(self):
        items = complete("/att")
        texts = [i["text"] for i in items]
        assert "/att" in texts
        assert "/attach" in texts

    def test_alias_has_annotation(self):
        items = complete("/att")
        att = next(i for i in items if i["text"] == "/att")
        assert "alias" in att["description"].lower()
        assert "/attach" in att["description"]
        assert att["kind"] == "alias"

    def test_slash_q_includes_quit(self):
        items = complete("/q")
        texts = [i["text"] for i in items]
        assert "/quit" in texts

    def test_slash_doctor_found(self):
        items = complete("/doc")
        texts = [i["text"] for i in items]
        assert "/doctor" in texts

    def test_empty_slash_returns_all(self):
        items = complete("/")
        # Should return all registered + aliased + builtin commands
        assert len(items) > 30

    def test_unknown_prefix_returns_empty(self):
        items = complete("/zzznonexistent")
        assert items == []

    def test_items_sorted_alphabetically(self):
        items = complete("/")
        texts = [i["text"] for i in items]
        assert texts == sorted(texts)

    def test_replace_start_covers_typed_prefix(self):
        items = complete("/att")
        for item in items:
            assert item["replace_start"] == -4  # len("/att") = 4


class TestPathCompletion:
    def test_attach_lists_dir_contents(self, populated_dir):
        items = complete("/attach ", working_dir=str(populated_dir))
        texts = [i["text"] for i in items]
        assert "alpha.txt" in texts
        assert "subdir/" in texts
        # Hidden files excluded by default
        assert ".hidden" not in texts

    def test_cd_shows_only_dirs(self, populated_dir):
        items = complete("/cd ", working_dir=str(populated_dir))
        texts = [i["text"] for i in items]
        assert "subdir/" in texts
        assert "alpha.txt" not in texts

    def test_path_prefix_filters(self, populated_dir):
        items = complete("/attach al", working_dir=str(populated_dir))
        texts = [i["text"] for i in items]
        assert texts == ["alpha.txt"]

    def test_trailing_slash_navigates(self, populated_dir):
        items = complete("/attach subdir/", working_dir=str(populated_dir))
        texts = [i["text"] for i in items]
        assert "deep.md" in texts

    def test_alias_resolves(self, populated_dir):
        # /att is alias for /attach — path completion should work
        items = complete("/att ", working_dir=str(populated_dir))
        texts = [i["text"] for i in items]
        assert "alpha.txt" in texts

    def test_hidden_files_on_dot_prefix(self, populated_dir):
        items = complete("/attach .", working_dir=str(populated_dir))
        texts = [i["text"] for i in items]
        assert ".hidden" in texts


class TestFileRefCompletion:
    def test_at_sign_triggers_file_refs(self, populated_dir):
        items = complete("look at @al", working_dir=str(populated_dir))
        texts = [i["text"] for i in items]
        assert "@alpha.txt" in texts
        assert all(i["kind"] == "file_ref" for i in items)

    def test_at_sign_fuzzy_matches(self, populated_dir):
        items = complete("@deep", working_dir=str(populated_dir))
        texts = [i["text"] for i in items]
        assert "@deep.md" in texts

    def test_at_sign_no_match(self, populated_dir):
        items = complete("@zzzznonexistent", working_dir=str(populated_dir))
        assert items == []


class TestEdgeCases:
    def test_empty_buffer(self):
        assert complete("") == []

    def test_plain_text_no_completions(self):
        assert complete("hello world") == []

    def test_cursor_mid_buffer(self):
        # Cursor at position 4 in "/att ach" → completing "/att"
        items = complete("/att ach", cursor=4)
        texts = [i["text"] for i in items]
        assert "/attach" in texts
        assert "/att" in texts
