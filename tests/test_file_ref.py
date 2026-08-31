"""Tests for the unified file-reference resolver (engine.file_ref).

v1.18.7: every office tool resolves files through this module. The
resolver accepts EITHER a SessionFileStore file_id OR a workspace
path, with strict working-dir confinement on the path branch.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ppxai.engine.file_ref import FileRef, resolve_file_reference
from ppxai.engine.session_store import SessionFileStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path) -> Path:
    """A simulated workspace directory with one file inside."""
    wd = tmp_path / "workspace"
    wd.mkdir()
    (wd / "report.pdf").write_bytes(b"%PDF-1.4 stub")
    (wd / "subdir").mkdir()
    (wd / "subdir" / "nested.pptx").write_bytes(b"PK stub")
    return wd


@pytest.fixture
def store(tmp_path) -> SessionFileStore:
    return SessionFileStore(base_dir=tmp_path / "uploads")


@pytest.fixture
def engine(workspace, store):
    """Engine stub with both file_store and working_dir."""
    return SimpleNamespace(
        file_store=store,
        get_working_dir=lambda: str(workspace),
    )


@pytest.fixture
def engine_no_wd(store):
    """Engine stub WITHOUT working_dir — file_id path still works, path branch fails."""
    return SimpleNamespace(file_store=store)


# ---------------------------------------------------------------------------
# Validation errors (neither / both)
# ---------------------------------------------------------------------------


class TestArgumentValidation:
    def test_neither_argument_errors(self, engine):
        meta, err = resolve_file_reference(engine)
        assert meta is None
        assert err is not None
        assert "file_id" in err and "path" in err

    def test_both_arguments_errors(self, engine):
        meta, err = resolve_file_reference(engine, file_id="abc", path="report.pdf")
        assert meta is None
        assert err is not None
        assert "not both" in err.lower()

    def test_empty_strings_treated_as_missing(self, engine):
        # Empty strings should fail the "must pass one" check, not be
        # treated as a valid id/path.
        meta, err = resolve_file_reference(engine, file_id="", path="")
        assert meta is None
        assert "Must pass" in err


# ---------------------------------------------------------------------------
# file_id branch (SessionFileStore lookup) — regression coverage
# ---------------------------------------------------------------------------


class TestFileIdBranch:
    def test_file_id_resolves_to_metadata(self, engine, store):
        meta_saved = store.save("hello.txt", b"hello", media_type="text/plain")
        meta, err = resolve_file_reference(engine, file_id=meta_saved.file_id)
        assert err is None
        assert meta is meta_saved  # same FileMetadata instance

    def test_unknown_file_id_errors(self, engine):
        meta, err = resolve_file_reference(engine, file_id="nonexistent_id")
        assert meta is None
        assert "Unknown file_id" in err

    def test_file_store_missing_errors_clearly(self):
        engine_no_store = SimpleNamespace()
        meta, err = resolve_file_reference(engine_no_store, file_id="abc")
        assert meta is None
        assert "SessionFileStore" in err

    def test_on_disk_file_missing_errors(self, engine, store):
        meta_saved = store.save("a.txt", b"data")
        meta_saved.path.unlink()  # simulate disk-side disappearance
        meta, err = resolve_file_reference(engine, file_id=meta_saved.file_id)
        assert meta is None
        assert "missing on disk" in err


# ---------------------------------------------------------------------------
# path branch (workspace lookup) — new in v1.18.7
# ---------------------------------------------------------------------------


class TestPathBranch:
    def test_relative_path_resolves(self, engine, workspace):
        meta, err = resolve_file_reference(engine, path="report.pdf")
        assert err is None
        assert isinstance(meta, FileRef)
        assert meta.path == workspace / "report.pdf"
        assert meta.name == "report.pdf"
        assert meta.media_type == "application/pdf"

    def test_relative_path_with_subdir(self, engine, workspace):
        meta, err = resolve_file_reference(engine, path="subdir/nested.pptx")
        assert err is None
        assert meta.path == workspace / "subdir" / "nested.pptx"
        assert meta.media_type.endswith("presentationml.presentation")

    def test_absolute_path_inside_workspace_resolves(self, engine, workspace):
        abs_path = str(workspace / "report.pdf")
        meta, err = resolve_file_reference(engine, path=abs_path)
        assert err is None
        assert meta.path == workspace / "report.pdf"

    def test_absolute_path_outside_workspace_rejected(self, engine, tmp_path):
        outside = tmp_path / "outside.pdf"
        outside.write_bytes(b"%PDF stub")
        meta, err = resolve_file_reference(engine, path=str(outside))
        assert meta is None
        assert "outside the working directory" in err

    def test_relative_path_escape_rejected(self, engine, tmp_path):
        # ../outside.pdf when working_dir is tmp_path/workspace should
        # resolve to tmp_path/outside.pdf — outside the workspace.
        outside = tmp_path / "escape.pdf"
        outside.write_bytes(b"%PDF stub")
        meta, err = resolve_file_reference(engine, path="../escape.pdf")
        assert meta is None
        assert "outside the working directory" in err

    def test_nonexistent_path_errors(self, engine):
        meta, err = resolve_file_reference(engine, path="missing.pdf")
        assert meta is None
        assert "does not exist" in err

    def test_path_pointing_at_directory_rejected(self, engine, workspace):
        meta, err = resolve_file_reference(engine, path="subdir")
        assert meta is None
        assert "not a regular file" in err

    def test_relative_path_without_working_dir_errors(self, engine_no_wd):
        meta, err = resolve_file_reference(engine_no_wd, path="anything.pdf")
        assert meta is None
        assert "working_dir" in err

    def test_absolute_path_without_working_dir_resolves(self, engine_no_wd, tmp_path):
        # When engine has no working_dir, absolute paths pass through
        # without confinement. This is the desktop / TUI case where the
        # CLI is just running locally.
        f = tmp_path / "freestanding.pdf"
        f.write_bytes(b"%PDF stub")
        meta, err = resolve_file_reference(engine_no_wd, path=str(f))
        assert err is None
        assert meta.path == f.resolve()


# ---------------------------------------------------------------------------
# Media type guessing
# ---------------------------------------------------------------------------


class TestMediaTypeGuess:
    @pytest.mark.parametrize("filename,expected_mt", [
        ("report.pdf", "application/pdf"),
        ("deck.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
        ("data.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ("doc.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("table.csv", "text/csv"),
        ("legacy.ppt", "application/vnd.ms-powerpoint"),
        ("legacy.xls", "application/vnd.ms-excel"),
        ("legacy.doc", "application/msword"),
    ])
    def test_office_extensions_map_correctly(
        self, engine, workspace, filename, expected_mt
    ):
        (workspace / filename).write_bytes(b"stub")
        meta, err = resolve_file_reference(engine, path=filename)
        assert err is None
        assert meta.media_type == expected_mt

    def test_unknown_extension_falls_through(self, engine, workspace):
        (workspace / "weird.xyz").write_bytes(b"stub")
        meta, err = resolve_file_reference(engine, path="weird.xyz")
        assert err is None
        # Either "application/octet-stream" or whatever mimetypes guesses.
        # Just confirm it's a string and resolution didn't fail.
        assert isinstance(meta.media_type, str)


# ---------------------------------------------------------------------------
# FileRef stub structural compatibility with FileMetadata
# ---------------------------------------------------------------------------


class TestFileRefShape:
    """FileRef and FileMetadata must expose the same attributes that
    office tools depend on, so the tools don't have to branch on type."""

    def test_file_ref_has_required_attrs(self, engine, workspace):
        meta, _ = resolve_file_reference(engine, path="report.pdf")
        # Same attributes that all _is_*() helpers read.
        assert hasattr(meta, "name")
        assert hasattr(meta, "media_type")
        assert hasattr(meta, "path")
        assert isinstance(meta.path, Path)

    def test_metadata_and_ref_are_attribute_compatible(
        self, engine, workspace, store
    ):
        # Both resolvers should return things with the same trio of
        # attributes — so an office tool calling _is_pptx(meta) etc.
        # doesn't need to know which branch fired.
        store_meta = store.save("file.pdf", b"%PDF stub", media_type="application/pdf")
        path_meta, _ = resolve_file_reference(engine, path="report.pdf")
        for attr in ("name", "media_type", "path"):
            assert hasattr(store_meta, attr)
            assert hasattr(path_meta, attr)
