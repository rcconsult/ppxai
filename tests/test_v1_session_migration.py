"""ADR 0006 Step 5 (v1.18.6) — v1 → v2 session migration on first load.

Pins the user-facing migration contract:

1. **Multimodal v1 sessions trigger migration** — image_url +
   uploaded_file blocks dropped + replaced with text placeholders
   pointing at preserved v1 backup folder. Text content + tool_calls
   + metadata preserved verbatim.

2. **Pure-text v1 sessions skip migration** — no backup folder
   created (no multimodal data to lose), but the next save() writes
   schema_version: 2 naturally.

3. **v2 sessions skip migration** — idempotent, no double-backup.

4. **Backup folder excluded from list_sessions** — `*.v1.backup/`
   directories and `*.v1.backup.json` flat files don't surface as
   active sessions in the user's session list.

5. **Backup-name load is read-only** — directly loading
   `<name>.v1.backup` doesn't trigger a re-migration loop
   (`<x>.v1.backup.v1.backup/` nesting prevention).

6. **Permanent regression fixture** — `tests/fixtures/sessions/v1_with_image/`
   ships in the repo. Real-world-ish v1.18.x session shape (text + image
   attachment + multi-turn). Migration over this fixture asserts the
   exact post-migration message shape so future refactors can't drift.

Sentinel: this is the user-facing contract for the v1.18.6 breaking
change. Any change to migration semantics MUST update this file.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from ppxai.engine.session import SESSION_SCHEMA_VERSION, SessionManager
from ppxai.engine.session_store import SessionFileStore
from ppxai.engine.types import Message

_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "sessions"


@pytest.fixture
def temp_sessions_dir(tmp_path: Path) -> Path:
    d = tmp_path / "sessions"
    d.mkdir()
    return d


@pytest.fixture
def temp_exports_dir(tmp_path: Path) -> Path:
    d = tmp_path / "exports"
    d.mkdir()
    return d


@pytest.fixture
def session_with_store(
    temp_sessions_dir: Path, temp_exports_dir: Path, tmp_path: Path
) -> SessionManager:
    """SessionManager wired to a real file_store so multimodal blocks
    can round-trip the file_id resolution path."""
    sess = SessionManager(
        sessions_dir=temp_sessions_dir, exports_dir=temp_exports_dir
    )
    sess.file_store = SessionFileStore(base_dir=tmp_path / "staging")
    return sess


def _copy_fixture_into(dest_sessions_dir: Path, fixture_name: str) -> None:
    """Copy a v1 fixture into the test's temp sessions dir so each test
    runs against a fresh, mutable copy. The fixture under tests/fixtures/
    is read-only (committed to git)."""
    src = _FIXTURE_ROOT / fixture_name
    dst = dest_sessions_dir / fixture_name
    shutil.copytree(src, dst)


# =============================================================================
# 1. Multimodal v1 → v2 migration (the load-bearing case)
# =============================================================================


class TestMultimodalV1Migration:
    """v1 sessions with image_url / uploaded_file blocks get migrated on
    first load. Text + tool_calls + metadata preserved; multimodal
    blocks become text placeholders pointing at the preserved backup."""

    def test_fixture_load_triggers_migration(
        self, session_with_store, temp_sessions_dir
    ):
        """The committed v1_with_image fixture loads, migration runs,
        v2 JSON written, v1 backup preserved alongside."""
        _copy_fixture_into(temp_sessions_dir, "v1_with_image")
        assert session_with_store.load("v1_with_image") is True

        # In-memory: 4 messages preserved, multimodal blocks → text
        # placeholder.
        assert len(session_with_store.messages) == 4
        first = session_with_store.messages[0]
        assert isinstance(first.content, list)
        assert len(first.content) == 2  # original 2 blocks preserved
        assert first.content[0]["type"] == "text"
        assert first.content[0]["text"] == "What's in this screenshot?"
        # Image block → text placeholder
        assert first.content[1]["type"] == "text"
        assert "v1 migration" in first.content[1]["text"]
        assert "image_url" in first.content[1]["text"]
        assert "screenshot.png" in first.content[1]["text"]
        assert "v1_with_image.v1.backup/" in first.content[1]["text"]
        # Attachments cleared (no longer reference the dropped block)
        assert first.attachments == []

        # Plain-text messages preserved verbatim
        assert session_with_store.messages[1].role == "assistant"
        assert "dashboard" in session_with_store.messages[1].content
        assert session_with_store.messages[2].content == "Can you focus on the bottom panel?"

    def test_v1_backup_folder_created_alongside(
        self, session_with_store, temp_sessions_dir
    ):
        """After migration, `<name>.v1.backup/` exists with the original
        session.json (still showing v1 shape) and uploads/ subtree."""
        _copy_fixture_into(temp_sessions_dir, "v1_with_image")
        session_with_store.load("v1_with_image")

        backup = temp_sessions_dir / "v1_with_image.v1.backup"
        assert backup.is_dir()
        assert (backup / "session.json").is_file()
        # Original uploads/ subtree preserved (the screenshot bytes are
        # still there for forensic inspection by the user).
        assert (backup / "uploads").is_dir()
        assert (backup / "uploads" / "abc123def456_screenshot.png" / "screenshot.png").is_file()

        # Backup session.json still shows v1 shape (no schema_version field,
        # in-block name+file_id keys preserved). It's a snapshot — never
        # rewritten.
        with open(backup / "session.json", encoding="utf-8") as f:
            backup_data = json.load(f)
        assert "schema_version" not in backup_data
        # Image block still has its in-block name+file_id (untouched).
        first_msg = backup_data["messages"][0]
        image_block = first_msg["content"][1]
        assert image_block["type"] == "image_url"
        assert image_block["name"] == "screenshot.png"
        assert image_block["file_id"] == "abc123def456_screenshot.png"

    def test_v2_session_json_written_after_migration(
        self, session_with_store, temp_sessions_dir
    ):
        """save() (called by the migration) replaces session.json with
        the v2 shape: schema_version: 2 + per-message attachments
        (empty in this case because images were dropped)."""
        _copy_fixture_into(temp_sessions_dir, "v1_with_image")
        session_with_store.load("v1_with_image")

        post = temp_sessions_dir / "v1_with_image" / "session.json"
        with open(post, encoding="utf-8") as f:
            v2_data = json.load(f)

        assert v2_data["schema_version"] == SESSION_SCHEMA_VERSION
        # Multimodal blocks were rewritten to text placeholders, so
        # save() doesn't see "multimodal" anymore — but message count
        # + roles preserved.
        assert len(v2_data["messages"]) == 4
        assert all(
            "attachments" not in msg or msg["attachments"] == []
            for msg in v2_data["messages"]
        )
        # Persistence fields preserved through the migration round-trip.
        assert v2_data["working_dir"] == "/home/user/projects/ops"
        assert v2_data["command_history"] == [
            "/attach screenshot.png",
            "What's in this screenshot?",
            "Can you focus on the bottom panel?",
        ]

    def test_idempotent_second_load_does_not_re_migrate(
        self, session_with_store, temp_sessions_dir, temp_exports_dir
    ):
        """Loading the migrated session a second time sees v2 shape and
        skips migration entirely. No nested `.v1.backup.v1.backup/`."""
        _copy_fixture_into(temp_sessions_dir, "v1_with_image")
        session_with_store.load("v1_with_image")  # migrate

        # Fresh SessionManager (simulating next launch)
        loaded2 = SessionManager(
            sessions_dir=temp_sessions_dir, exports_dir=temp_exports_dir
        )
        loaded2.file_store = session_with_store.file_store
        loaded2.load("v1_with_image")

        # Backup folder is unchanged — no nested re-backup.
        nested_double = temp_sessions_dir / "v1_with_image.v1.backup.v1.backup"
        assert not nested_double.exists()
        # Only one backup directory total
        backup_dirs = [
            p for p in temp_sessions_dir.iterdir()
            if p.is_dir() and p.name.endswith(".v1.backup")
        ]
        assert len(backup_dirs) == 1


# =============================================================================
# 2. Pure-text v1 → v2 (no backup needed)
# =============================================================================


class TestPureTextV1Migration:
    """v1 sessions WITHOUT multimodal content don't need a backup —
    nothing's being dropped. They still get re-saved as v2 on the
    next normal save() cycle (handled implicitly by the v2-writing
    save() that we don't trigger here)."""

    def test_text_only_v1_no_backup_created(
        self, session_with_store, temp_sessions_dir
    ):
        """Hand-build a v1 text-only session, load it, verify NO backup
        folder is created (text content has no multimodal data to lose)."""
        flat_path = temp_sessions_dir / "v1-textonly.json"
        v1_data = {
            "session_name": "v1-textonly",
            "metadata": {},
            "messages": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi back"},
            ],
            "usage": {"total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0,
                      "estimated_cost": 0.0},
            "saved_at": "2026-04-01T00:00:00",
            "command_history": [],
            "working_dir": ".",
            "tools_enabled": False,
        }
        with open(flat_path, "w", encoding="utf-8") as f:
            json.dump(v1_data, f, indent=2)

        assert session_with_store.load("v1-textonly") is True
        # No backup file created
        assert not (temp_sessions_dir / "v1-textonly.v1.backup.json").exists()
        assert not (temp_sessions_dir / "v1-textonly.v1.backup").exists()
        # Original v1 file still in place — load doesn't rewrite text-only
        # sessions immediately; they migrate naturally on next save().
        assert flat_path.is_file()


# =============================================================================
# 3. v2 sessions skip migration entirely
# =============================================================================


class TestV2SessionSkipsMigration:
    """A session already at schema_version: 2 doesn't trigger migration
    — no backup, no rewrite. Idempotence guarantee."""

    def test_v2_session_load_no_backup_created(
        self, session_with_store, temp_sessions_dir
    ):
        """Save a session natively (writes v2), reload it, verify no
        backup spuriously created."""
        session_with_store.add_message(Message(role="user", content="hello"))
        session_with_store.add_message(Message(role="assistant", content="hi"))
        session_with_store.save("native-v2")

        # Fresh SessionManager simulating next launch
        from ppxai.engine.session import SessionManager
        loaded = SessionManager(
            sessions_dir=temp_sessions_dir,
            exports_dir=session_with_store.exports_dir,
        )
        loaded.file_store = session_with_store.file_store
        loaded.load("native-v2")

        backup = temp_sessions_dir / "native-v2.v1.backup"
        backup_flat = temp_sessions_dir / "native-v2.v1.backup.json"
        assert not backup.exists()
        assert not backup_flat.exists()


# =============================================================================
# 4. Backup folders hidden from list_sessions
# =============================================================================


class TestBackupHiddenFromList:
    """Migration creates `<name>.v1.backup/` siblings — those must NOT
    appear in the user's session list. Otherwise loading a session that
    was migrated yesterday would show TWO entries: the migrated v2 and
    the backup v1, confusing users and causing /resume ambiguity."""

    def test_v1_backup_directory_excluded(
        self, session_with_store, temp_sessions_dir
    ):
        _copy_fixture_into(temp_sessions_dir, "v1_with_image")
        session_with_store.load("v1_with_image")  # creates backup

        # Verify backup exists on disk
        assert (temp_sessions_dir / "v1_with_image.v1.backup").is_dir()

        # But list_sessions returns only the active session
        names = [s.name for s in session_with_store.list_sessions()]
        assert "v1_with_image" in names
        assert "v1_with_image.v1.backup" not in names

    def test_v1_backup_flat_file_excluded(
        self, session_with_store, temp_sessions_dir
    ):
        """Flat-format backups (`<name>.v1.backup.json`) similarly hidden."""
        # Synthesize a leftover backup file
        leftover = temp_sessions_dir / "old-session.v1.backup.json"
        leftover.write_text(
            json.dumps({"session_name": "old-session.v1.backup", "messages": []}),
            encoding="utf-8",
        )
        # Plus a normal session so list_sessions doesn't return empty
        session_with_store.add_message(Message(role="user", content="hi"))
        session_with_store.add_message(Message(role="assistant", content="hello"))
        session_with_store.save("normal")

        names = [s.name for s in session_with_store.list_sessions()]
        assert "normal" in names
        assert "old-session.v1.backup" not in names


# =============================================================================
# 5. Backup-name explicit load is read-only (no re-migration)
# =============================================================================


class TestBackupExplicitLoadReadOnly:
    """If a user explicitly loads `<name>.v1.backup` (e.g. for forensic
    inspection of a migrated session), the migration MUST NOT re-fire —
    otherwise we'd nest `<x>.v1.backup.v1.backup/` indefinitely."""

    def test_explicit_backup_load_does_not_re_migrate(
        self, session_with_store, temp_sessions_dir
    ):
        _copy_fixture_into(temp_sessions_dir, "v1_with_image")
        session_with_store.load("v1_with_image")  # creates the backup

        # User now loads the backup directly by name
        from ppxai.engine.session import SessionManager
        loaded = SessionManager(
            sessions_dir=temp_sessions_dir,
            exports_dir=session_with_store.exports_dir,
        )
        loaded.file_store = session_with_store.file_store
        # The backup folder name is what's on disk — load it directly.
        assert loaded.load("v1_with_image.v1.backup") is True

        # Critically: NO nested `.v1.backup.v1.backup/` created.
        nested = temp_sessions_dir / "v1_with_image.v1.backup.v1.backup"
        assert not nested.exists()
