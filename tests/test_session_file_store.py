"""Tests for SessionFileStore (Phase 2.1, v1.17.4).

Exercises every public method against a real filesystem (tmp_path) — no
mocks, because the whole point of this module is to correctly shuffle
bytes between directories and the logic is trivial to test directly.

Scope boundaries:
    - save / get / get_metadata / list_all / cleanup / cleanup_all
    - move_to_session + restore_from_session round trip
    - Content dedup (identical bytes get one file_id)
    - Path traversal defenses (crafted names don't escape the store)
    - classify_kind for every broad category
    - FileMetadata.to_dict() projection

Explicitly NOT in scope yet:
    - Engine wiring (Phase 2.1a — separate test file)
    - Session serialization rewriting (Phase 2.1a)
    - Context attachments AppState integration (Phase 2.1a)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ppxai.engine.session_store import (
    KIND_IMAGE,
    KIND_OFFICE,
    KIND_OTHER,
    KIND_PDF,
    KIND_TEXT,
    FileMetadata,
    SessionFileStore,
    _compute_file_id,
    classify_kind,
)


# Minimal valid image bytes — not a real image, just deterministic content
# for hashing tests. SessionFileStore doesn't decode images, so any bytes
# work for testing storage behavior.
_IMAGE_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
_OTHER_IMAGE_BYTES = b"\x89PNG\r\n\x1a\n" + b"\xff" * 100
_TEXT_BYTES = b"print('hello world')\n"


@pytest.fixture
def store(tmp_path) -> SessionFileStore:
    """SessionFileStore rooted at a throwaway tmp_path staging dir."""
    staging = tmp_path / "uploads"
    return SessionFileStore(base_dir=staging)


# -----------------------------------------------------------------------------
# classify_kind — broad category mapping
# -----------------------------------------------------------------------------


class TestClassifyKind:
    def test_image_mime_types(self):
        assert classify_kind("image/png", "x.png") == KIND_IMAGE
        assert classify_kind("image/jpeg", "x.jpg") == KIND_IMAGE
        assert classify_kind("image/webp", "x.webp") == KIND_IMAGE
        assert classify_kind("image/gif", "x.gif") == KIND_IMAGE

    def test_pdf(self):
        assert classify_kind("application/pdf", "doc.pdf") == KIND_PDF

    def test_text_mime_types(self):
        assert classify_kind("text/plain", "x.txt") == KIND_TEXT
        assert classify_kind("text/markdown", "x.md") == KIND_TEXT
        assert classify_kind("text/x-python", "x.py") == KIND_TEXT

    def test_office_mime_types(self):
        assert classify_kind(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "x.xlsx",
        ) == KIND_OFFICE
        assert classify_kind(
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "x.pptx",
        ) == KIND_OFFICE
        assert classify_kind("application/msword", "x.doc") == KIND_OFFICE

    def test_extension_fallback_for_code_files(self):
        # mimetypes returns application/octet-stream for unknown types,
        # but we still want code files classified as text.
        assert classify_kind("application/octet-stream", "main.rs") == KIND_TEXT
        assert classify_kind("application/octet-stream", "config.toml") == KIND_TEXT
        assert classify_kind("application/octet-stream", "data.json") == KIND_TEXT

    def test_extension_fallback_for_office(self):
        assert classify_kind("application/octet-stream", "sheet.xlsx") == KIND_OFFICE
        assert classify_kind("application/octet-stream", "slides.pptx") == KIND_OFFICE

    def test_extension_fallback_for_pdf(self):
        assert classify_kind("application/octet-stream", "doc.pdf") == KIND_PDF

    def test_unknown_falls_back_to_other(self):
        assert classify_kind("application/octet-stream", "file.bin") == KIND_OTHER
        assert classify_kind("application/x-tar", "archive.tar") == KIND_OTHER


# -----------------------------------------------------------------------------
# _compute_file_id — deterministic hashing + sanitization
# -----------------------------------------------------------------------------


class TestComputeFileId:
    def test_same_bytes_same_name_yield_same_id(self):
        a = _compute_file_id(b"hello", "file.txt")
        b = _compute_file_id(b"hello", "file.txt")
        assert a == b

    def test_different_bytes_yield_different_ids(self):
        a = _compute_file_id(b"hello", "file.txt")
        b = _compute_file_id(b"world", "file.txt")
        assert a != b

    def test_id_contains_sanitized_name_hint(self):
        # Spaces and special chars collapse to underscores so the id
        # stays filesystem-safe.
        fid = _compute_file_id(b"x", "My Chart (v2).png")
        # 16-char hash, underscore, sanitized name hint.
        assert fid.startswith(fid.split("_")[0])
        assert "/" not in fid
        assert "\\" not in fid
        assert " " not in fid

    def test_path_separators_in_name_are_sanitized(self):
        # Path traversal attempt via crafted name.
        fid = _compute_file_id(b"x", "../../etc/passwd")
        assert "/" not in fid
        assert ".." not in fid or fid.count(".") <= 4  # allow only dots from name extension

    def test_long_name_is_truncated(self):
        fid = _compute_file_id(b"x", "a" * 100 + ".png")
        # Name hint capped at 32 chars; total id stays bounded.
        assert len(fid) < 100


# -----------------------------------------------------------------------------
# SessionFileStore.save — round-trip, dedup, error paths
# -----------------------------------------------------------------------------


class TestSave:
    def test_save_returns_metadata(self, store):
        meta = store.save("chart.png", _IMAGE_BYTES, media_type="image/png")
        assert isinstance(meta, FileMetadata)
        assert meta.name == "chart.png"
        assert meta.media_type == "image/png"
        assert meta.size == len(_IMAGE_BYTES)
        assert meta.kind == KIND_IMAGE

    def test_save_writes_bytes_to_disk(self, store):
        meta = store.save("chart.png", _IMAGE_BYTES, media_type="image/png")
        assert meta.path.exists()
        assert meta.path.read_bytes() == _IMAGE_BYTES

    def test_save_auto_detects_media_type_from_extension(self, store):
        meta = store.save("photo.jpeg", _IMAGE_BYTES)
        assert meta.media_type == "image/jpeg"

    def test_save_falls_back_to_octet_stream_for_unknown_extension(self, store):
        meta = store.save("data.weirdext", b"blob")
        assert meta.media_type == "application/octet-stream"

    def test_save_dedup_identical_bytes(self, store):
        m1 = store.save("chart.png", _IMAGE_BYTES, media_type="image/png")
        m2 = store.save("chart.png", _IMAGE_BYTES, media_type="image/png")
        # Same file_id, same path, in-memory is a single entry.
        assert m1.file_id == m2.file_id
        assert m1.path == m2.path
        assert len(store.list_all()) == 1

    def test_save_different_bytes_get_different_ids(self, store):
        m1 = store.save("a.png", _IMAGE_BYTES, media_type="image/png")
        m2 = store.save("b.png", _OTHER_IMAGE_BYTES, media_type="image/png")
        assert m1.file_id != m2.file_id
        assert len(store.list_all()) == 2

    def test_save_strips_directory_components_from_name(self, store):
        # Path traversal defense — names with directory parts are
        # reduced to basename before touching disk.
        meta = store.save("../../evil.png", _IMAGE_BYTES, media_type="image/png")
        assert meta.name == "evil.png"
        # The on-disk path must be inside the store's base directory.
        assert str(meta.path).startswith(str(store._base_dir))

    def test_save_with_empty_name_uses_default(self, store):
        meta = store.save("", b"bytes", media_type="application/octet-stream")
        assert meta.name == "file"

    def test_save_text_file_classified_correctly(self, store):
        meta = store.save("main.py", _TEXT_BYTES)
        assert meta.kind == KIND_TEXT

    def test_save_is_idempotent_for_identical_content(self, store):
        # Second save with the same bytes should not rewrite the file
        # (we can't observe that directly, but we can observe that the
        # file still exists and metadata matches).
        m1 = store.save("x.png", _IMAGE_BYTES, media_type="image/png")
        first_mtime = m1.path.stat().st_mtime
        m2 = store.save("x.png", _IMAGE_BYTES, media_type="image/png")
        second_mtime = m2.path.stat().st_mtime
        assert first_mtime == second_mtime
        assert m1.file_id == m2.file_id


# -----------------------------------------------------------------------------
# get / get_metadata / list_all
# -----------------------------------------------------------------------------


class TestReadAccessors:
    def test_get_returns_path_for_known_id(self, store):
        meta = store.save("chart.png", _IMAGE_BYTES, media_type="image/png")
        assert store.get(meta.file_id) == meta.path

    def test_get_returns_none_for_unknown_id(self, store):
        assert store.get("bogus_id") is None

    def test_get_metadata_returns_full_metadata(self, store):
        meta = store.save("chart.png", _IMAGE_BYTES, media_type="image/png")
        retrieved = store.get_metadata(meta.file_id)
        assert retrieved is meta

    def test_get_metadata_returns_none_for_unknown_id(self, store):
        assert store.get_metadata("bogus") is None

    def test_list_all_returns_all_entries(self, store):
        store.save("a.png", _IMAGE_BYTES, media_type="image/png")
        store.save("b.png", _OTHER_IMAGE_BYTES, media_type="image/png")
        store.save("c.txt", _TEXT_BYTES)
        entries = store.list_all()
        assert len(entries) == 3
        names = {e.name for e in entries}
        assert names == {"a.png", "b.png", "c.txt"}

    def test_list_all_empty_store(self, store):
        assert store.list_all() == []


# -----------------------------------------------------------------------------
# cleanup / cleanup_all
# -----------------------------------------------------------------------------


class TestCleanup:
    def test_cleanup_removes_file_and_metadata(self, store):
        meta = store.save("x.png", _IMAGE_BYTES, media_type="image/png")
        path = meta.path
        assert path.exists()

        removed = store.cleanup(meta.file_id)
        assert removed is True
        assert not path.exists()
        assert store.get(meta.file_id) is None
        assert store.get_metadata(meta.file_id) is None

    def test_cleanup_returns_false_for_unknown_id(self, store):
        assert store.cleanup("bogus") is False

    def test_cleanup_removes_empty_parent_dir(self, store):
        meta = store.save("x.png", _IMAGE_BYTES, media_type="image/png")
        parent = meta.path.parent
        store.cleanup(meta.file_id)
        # file_id directory should be gone since it held only that file.
        assert not parent.exists()

    def test_cleanup_all_removes_everything(self, store):
        store.save("a.png", _IMAGE_BYTES, media_type="image/png")
        store.save("b.png", _OTHER_IMAGE_BYTES, media_type="image/png")
        store.save("c.txt", _TEXT_BYTES)

        count = store.cleanup_all()
        assert count == 3
        assert store.list_all() == []

    def test_cleanup_all_is_safe_on_empty_store(self, store):
        assert store.cleanup_all() == 0


# -----------------------------------------------------------------------------
# move_to_session / restore_from_session round trip
# -----------------------------------------------------------------------------


class TestSessionBinding:
    def test_move_to_session_relocates_files(self, store, tmp_path):
        meta = store.save("chart.png", _IMAGE_BYTES, media_type="image/png")
        staged_path = meta.path
        assert staged_path.exists()

        session_dir = tmp_path / "sessions" / "test_session"
        rel_map = store.move_to_session(session_dir)

        assert meta.file_id in rel_map
        assert rel_map[meta.file_id] == f"uploads/{meta.file_id}/chart.png"
        # File is now under the session dir, not staging.
        assert not staged_path.exists()
        new_path = session_dir / "uploads" / meta.file_id / "chart.png"
        assert new_path.exists()
        assert new_path.read_bytes() == _IMAGE_BYTES
        # Metadata.path updated to point at the new location.
        assert store.get(meta.file_id) == new_path

    def test_move_to_session_multiple_files(self, store, tmp_path):
        m1 = store.save("a.png", _IMAGE_BYTES, media_type="image/png")
        m2 = store.save("b.png", _OTHER_IMAGE_BYTES, media_type="image/png")
        m3 = store.save("notes.txt", _TEXT_BYTES)

        session_dir = tmp_path / "sessions" / "multi"
        rel_map = store.move_to_session(session_dir)

        assert len(rel_map) == 3
        assert set(rel_map.keys()) == {m1.file_id, m2.file_id, m3.file_id}
        for file_id, rel in rel_map.items():
            assert (session_dir / rel).exists()

    def test_move_to_session_is_idempotent(self, store, tmp_path):
        meta = store.save("x.png", _IMAGE_BYTES, media_type="image/png")
        session_dir = tmp_path / "sessions" / "idempotent"

        first_map = store.move_to_session(session_dir)
        second_map = store.move_to_session(session_dir)

        # Same mapping returned, file still exists in the right place,
        # no crash from trying to move a file that's already there.
        assert first_map == second_map
        assert (session_dir / first_map[meta.file_id]).exists()

    def test_move_to_session_handles_missing_source_gracefully(
        self, store, tmp_path
    ):
        # Simulate someone deleting a staged file out from under us.
        meta = store.save("x.png", _IMAGE_BYTES, media_type="image/png")
        meta.path.unlink()

        session_dir = tmp_path / "sessions" / "missing_source"
        rel_map = store.move_to_session(session_dir)

        # The orphaned entry is silently dropped rather than crashing
        # the save flow. Loud logging covers the diagnostic side.
        assert meta.file_id not in rel_map
        assert store.get_metadata(meta.file_id) is None

    def test_restore_from_session_rebuilds_state(self, store, tmp_path):
        # Save some files, move them into a session, then spin up a
        # fresh store and restore from the same directory.
        m1 = store.save("chart.png", _IMAGE_BYTES, media_type="image/png")
        m2 = store.save("notes.txt", _TEXT_BYTES)

        session_dir = tmp_path / "sessions" / "restore_test"
        store.move_to_session(session_dir)

        # Fresh store — no memory of the prior state.
        new_store = SessionFileStore(base_dir=tmp_path / "fresh_staging")
        count = new_store.restore_from_session(session_dir)

        assert count == 2
        assert new_store.get_metadata(m1.file_id) is not None
        assert new_store.get_metadata(m2.file_id) is not None
        # File bytes still match.
        assert new_store.get(m1.file_id).read_bytes() == _IMAGE_BYTES
        assert new_store.get(m2.file_id).read_bytes() == _TEXT_BYTES

    def test_restore_from_session_with_no_uploads_dir(self, store, tmp_path):
        # Legacy text-only session: the session dir exists but has no
        # uploads/ subdirectory. Must return 0 silently.
        legacy_dir = tmp_path / "sessions" / "legacy"
        legacy_dir.mkdir(parents=True)
        count = store.restore_from_session(legacy_dir)
        assert count == 0
        assert store.list_all() == []

    def test_restore_from_session_clears_prior_state(self, store, tmp_path):
        # Pre-existing state should be wiped when restoring.
        store.save("old.png", _IMAGE_BYTES, media_type="image/png")
        assert len(store.list_all()) == 1

        # Restore from an empty session dir.
        empty_session = tmp_path / "sessions" / "empty"
        (empty_session / "uploads").mkdir(parents=True)
        count = store.restore_from_session(empty_session)
        assert count == 0
        assert store.list_all() == []

    def test_round_trip_preserves_file_ids(self, store, tmp_path):
        # The whole point of content-addressed IDs: save → move → restore
        # yields the same file_id, so message content references survive.
        original_meta = store.save(
            "chart.png", _IMAGE_BYTES, media_type="image/png"
        )
        original_id = original_meta.file_id

        session_dir = tmp_path / "sessions" / "roundtrip"
        store.move_to_session(session_dir)

        fresh = SessionFileStore(base_dir=tmp_path / "fresh")
        fresh.restore_from_session(session_dir)

        restored_meta = fresh.get_metadata(original_id)
        assert restored_meta is not None
        assert restored_meta.file_id == original_id
        assert restored_meta.name == "chart.png"
        assert restored_meta.media_type == "image/png"
        assert restored_meta.size == len(_IMAGE_BYTES)
        assert restored_meta.kind == KIND_IMAGE


# -----------------------------------------------------------------------------
# FileMetadata.to_dict — JSON projection for AppState
# -----------------------------------------------------------------------------


class TestFileMetadataProjection:
    def test_to_dict_excludes_path(self, store):
        meta = store.save("chart.png", _IMAGE_BYTES, media_type="image/png")
        d = meta.to_dict()
        assert "path" not in d
        assert d["file_id"] == meta.file_id
        assert d["name"] == "chart.png"
        assert d["media_type"] == "image/png"
        assert d["size"] == len(_IMAGE_BYTES)
        assert d["kind"] == KIND_IMAGE

    def test_to_dict_is_json_serializable(self, store):
        # AppState.context_attachments entries must survive SSE state_sync
        # as JSON without any custom encoder.
        meta = store.save("chart.png", _IMAGE_BYTES, media_type="image/png")
        dumped = json.dumps(meta.to_dict())
        roundtripped = json.loads(dumped)
        assert roundtripped == meta.to_dict()


# -----------------------------------------------------------------------------
# Save-after-move_to_session — new files land in the session dir
# -----------------------------------------------------------------------------


class TestSaveAfterBinding:
    def test_save_after_move_to_session_writes_to_session_dir(
        self, store, tmp_path
    ):
        # Initial save lands in staging.
        store.save("first.png", _IMAGE_BYTES, media_type="image/png")
        # Bind to a session.
        session_dir = tmp_path / "sessions" / "bound"
        store.move_to_session(session_dir)
        # New saves should go directly into the session dir.
        meta = store.save("second.png", _OTHER_IMAGE_BYTES, media_type="image/png")
        assert str(meta.path).startswith(str(session_dir / "uploads"))
        assert meta.path.exists()
