"""Integration tests for SessionFileStore ↔ SessionManager ↔ EngineClient.

Phase 2.1a (v1.17.4). Exercises the full pipeline from engine ownership
through message serialization, session save/load with the directory
format, AppState context_attachments refresh with file_id fields, and
backward-compat with Phase-1 legacy sessions that predate the store.

Scope:
    - EngineClient creates and wires a SessionFileStore automatically
    - Session with multimodal content saves in directory format
    - Session with only text content saves in flat format
    - Serialize rewrites inline data URIs → file_id references
    - Deserialize expands file_id references → data URIs
    - Full save/load round trip preserves message content exactly
    - File bytes survive save → fresh load with a new EngineClient
    - context_attachments entries include file_id field
    - Legacy Phase-1 sessions (inline base64 in JSON) still load
    - list_sessions finds both formats
    - delete_session handles both formats
    - Format transition: text-only session gains first attachment mid-conversation
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from ppxai.engine.client import EngineClient
from ppxai.engine.session import SessionManager
from ppxai.engine.session_store import SessionFileStore
from ppxai.engine.types import Message


# A 1x1 red PNG (real bytes, decodable by PIL if needed downstream).
_RED_PIXEL_PNG = base64.b64decode(
    b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8DwHwAFAQH/c4"
    b"X0gAAAAABJRU5ErkJggg=="
)
_RED_DATA_URI = f"data:image/png;base64,{base64.b64encode(_RED_PIXEL_PNG).decode('ascii')}"

_BLUE_PIXEL_PNG = _RED_PIXEL_PNG[:-4] + b"\x01\x02\x03\x04"  # different bytes
_BLUE_DATA_URI = f"data:image/png;base64,{base64.b64encode(_BLUE_PIXEL_PNG).decode('ascii')}"


@pytest.fixture
def isolated_dirs(tmp_path, monkeypatch):
    """Redirect both SessionFileStore staging and session dir into tmp_path.

    Patches the module-level `_DEFAULT_STAGING_DIR` used when EngineClient
    constructs its file store with no explicit base_dir, and provides a
    throwaway sessions directory for SessionManager.
    """
    import ppxai.engine.session_store as store_mod

    staging = tmp_path / "staging"
    staging.mkdir()
    monkeypatch.setattr(store_mod, "_DEFAULT_STAGING_DIR", staging)

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()

    return {
        "staging": staging,
        "sessions_dir": sessions_dir,
        "tmp_path": tmp_path,
    }


@pytest.fixture
def engine(isolated_dirs) -> EngineClient:
    """Fresh EngineClient with its session dir redirected into tmp_path."""
    client = EngineClient()
    # Point session manager at the isolated dir. The file store is
    # already pointing at the redirected staging dir thanks to the
    # monkeypatch in isolated_dirs.
    client.session.sessions_dir = isolated_dirs["sessions_dir"]
    return client


# -----------------------------------------------------------------------------
# Engine wiring
# -----------------------------------------------------------------------------


class TestEngineWiring:
    def test_engine_creates_file_store(self, engine):
        assert isinstance(engine.file_store, SessionFileStore)

    def test_engine_wires_store_into_session(self, engine):
        # SessionManager gains a reference so serialize/deserialize can
        # rewrite content blocks without going through the engine.
        assert engine.session.file_store is engine.file_store

    def test_standalone_session_manager_has_no_store(self, tmp_path):
        # SessionManager without an engine still works — file_store stays None
        # and serialize/deserialize behave like Phase 1 (inline base64).
        session = SessionManager(sessions_dir=tmp_path)
        assert session.file_store is None


# -----------------------------------------------------------------------------
# Content rewriting — serialize → file_id, deserialize → data URI
# -----------------------------------------------------------------------------


class TestContentRewriting:
    def test_serialize_rewrites_inline_data_uri_to_file_id(self, engine):
        msg = Message(
            role="user",
            content=[
                {"type": "text", "text": "describe this"},
                {
                    "type": "image_url",
                    "name": "chart.png",
                    "image_url": {"url": _RED_DATA_URI},
                },
            ],
        )
        serialized = engine.session._serialize_message(msg)

        # Text part unchanged.
        assert serialized["content"][0] == {"type": "text", "text": "describe this"}
        # ADR 0006 Step 7c (v1.18.6): image_url blocks carry only
        # {type, image_url}; file_id + name encoded in the URL.
        img_block = serialized["content"][1]
        assert img_block["type"] == "image_url"
        assert set(img_block.keys()) == {"type", "image_url"}
        url = img_block["image_url"]["url"]
        assert url.startswith("file://uploads/")
        assert "chart.png" in url
        # file_id parses out of the URL (file://uploads/<file_id>/<name>).
        file_id = url[len("file://uploads/"):].split("/", 1)[0]
        assert file_id  # non-empty
        # Bytes are on disk in the store.
        path = engine.file_store.get(file_id)
        assert path is not None
        assert path.read_bytes() == _RED_PIXEL_PNG

    def test_serialize_already_referenced_url_passes_through(self, engine):
        """ADR 0006 Step 7c (v1.18.6): a block whose URL is already a
        `file://uploads/<file_id>/<name>` reference (e.g. on second save
        of a session) passes through unchanged — same file_id, same URL.
        Previously this test pre-populated an in-block `file_id` key,
        which is no longer the round-trip contract."""
        meta = engine.file_store.save("preset.png", _RED_PIXEL_PNG, media_type="image/png")
        msg = Message(
            role="user",
            content=[{
                "type": "image_url",
                "image_url": {"url": f"file://uploads/{meta.file_id}/{meta.name}"},
            }],
        )
        serialized = engine.session._serialize_message(msg)
        img_block = serialized["content"][0]
        # Pass-through: same URL, no extra keys, content-addressed id
        # preserved without re-hashing.
        assert img_block == msg.content[0]

    def test_deserialize_expands_file_id_to_data_uri(self, engine):
        # Round-trip a block: serialize to file_id, then deserialize and
        # check the data URI reappears identically.
        msg = Message(
            role="user",
            content=[{
                "type": "image_url",
                "name": "chart.png",
                "image_url": {"url": _RED_DATA_URI},
            }],
        )
        serialized = engine.session._serialize_message(msg)
        restored = engine.session._deserialize_message(serialized)
        img_block = restored.content[0]
        # Provider adapters see a data URI identical to the original.
        assert img_block["image_url"]["url"] == _RED_DATA_URI
        # ADR 0006 Step 7c (v1.18.6): in-block name+file_id keys are
        # gone. The block is spec-clean. Downstream consumers
        # (context_attachments) read metadata from
        # Message.attachments which _deserialize_message populates
        # via extract_attachment_refs synthesis from the v1 blocks
        # the test serialized.
        assert set(img_block.keys()) == {"type", "image_url"}

    def test_deserialize_missing_file_replaces_with_placeholder(self, engine):
        # Simulate a manually-deleted attachment between save and load.
        msg = Message(
            role="user",
            content=[{
                "type": "image_url",
                "name": "chart.png",
                "image_url": {"url": _RED_DATA_URI},
            }],
        )
        serialized = engine.session._serialize_message(msg)
        # ADR 0006 Step 7c: file_id encoded in the URL, not as a
        # separate key. Parse it out.
        url = serialized["content"][0]["image_url"]["url"]
        file_id = url[len("file://uploads/"):].split("/", 1)[0]
        # Wipe the on-disk bytes out from under the store.
        path = engine.file_store.get(file_id)
        path.unlink()

        restored = engine.session._deserialize_message(serialized)
        # Missing file becomes a text placeholder — load doesn't crash.
        assert restored.content[0]["type"] == "text"
        assert "missing" in restored.content[0]["text"].lower()
        assert "chart.png" in restored.content[0]["text"]

    def test_serialize_passes_through_legacy_string_content(self, engine):
        # Text-only messages are untouched regardless of file_store.
        msg = Message(role="user", content="plain text")
        serialized = engine.session._serialize_message(msg)
        assert serialized == {"role": "user", "content": "plain text"}

    def test_serialize_passes_through_text_parts(self, engine):
        msg = Message(role="user", content=[{"type": "text", "text": "hello"}])
        serialized = engine.session._serialize_message(msg)
        assert serialized["content"] == [{"type": "text", "text": "hello"}]


# -----------------------------------------------------------------------------
# Session save/load round trip with attachments
# -----------------------------------------------------------------------------


class TestSessionRoundTrip:
    def test_save_with_attachments_uses_directory_format(self, engine, isolated_dirs):
        engine.session.add_message(Message(
            role="user",
            content=[
                {"type": "text", "text": "look"},
                {"type": "image_url", "name": "x.png",
                 "image_url": {"url": _RED_DATA_URI}},
            ],
        ))
        engine.session.add_message(Message(role="assistant", content="ok"))
        engine.session.save("multimodal_test")

        sessions = isolated_dirs["sessions_dir"]
        # Directory layout: sessions/multimodal_test/session.json + uploads/
        assert (sessions / "multimodal_test").is_dir()
        assert (sessions / "multimodal_test" / "session.json").is_file()
        assert (sessions / "multimodal_test" / "uploads").is_dir()
        # The old flat-file location does NOT exist.
        assert not (sessions / "multimodal_test.json").exists()

    def test_save_without_attachments_uses_flat_format(self, engine, isolated_dirs):
        engine.session.add_message(Message(role="user", content="hello"))
        engine.session.add_message(Message(role="assistant", content="hi"))
        engine.session.save("text_only")

        sessions = isolated_dirs["sessions_dir"]
        # Flat format: sessions/text_only.json (no directory).
        assert (sessions / "text_only.json").is_file()
        assert not (sessions / "text_only").exists()

    def test_session_json_has_file_id_not_base64(self, engine, isolated_dirs):
        engine.session.add_message(Message(
            role="user",
            content=[{
                "type": "image_url", "name": "chart.png",
                "image_url": {"url": _RED_DATA_URI},
            }],
        ))
        # Real conversations have an assistant reply before save; without
        # one, validate_and_fix_alternation pops the trailing user turn.
        engine.session.add_message(Message(role="assistant", content="ok"))
        engine.session.save("compact")

        session_json = isolated_dirs["sessions_dir"] / "compact" / "session.json"
        with open(session_json, encoding="utf-8") as f:
            data = json.load(f)

        # The image_url URL in the saved JSON is a file:// reference,
        # not a data URI. This is the whole point of Phase 2.1a.
        # ADR 0006 Step 7c: file_id encoded in the URL, no in-block key.
        img_block = data["messages"][0]["content"][0]
        url = img_block["image_url"]["url"]
        assert url.startswith("file://uploads/")
        assert "data:image" not in url
        # file_id parses from the URL itself
        file_id = url[len("file://uploads/"):].split("/", 1)[0]
        assert file_id

    def test_full_round_trip_with_fresh_engine(self, engine, isolated_dirs):
        # Save a session with an image, then load it from a completely
        # fresh EngineClient (simulating process restart) and verify the
        # image survives end-to-end.
        engine.session.add_message(Message(
            role="user",
            content=[
                {"type": "text", "text": "describe"},
                {"type": "image_url", "name": "chart.png",
                 "image_url": {"url": _RED_DATA_URI}},
            ],
        ))
        engine.session.add_message(Message(role="assistant", content="A red dot."))
        engine.session.save("roundtrip_test")

        fresh = EngineClient()
        fresh.session.sessions_dir = isolated_dirs["sessions_dir"]

        assert fresh.session.load("roundtrip_test")
        assert len(fresh.session.messages) == 2  # user + assistant
        user_msg = fresh.session.messages[0]
        assert user_msg.role == "user"
        # In-memory message has the expanded data URI — provider adapters
        # see exactly what they saw before the save.
        assert user_msg.content[1]["image_url"]["url"] == _RED_DATA_URI
        # ADR 0006 Step 7c: file_id lives on Message.attachments, not
        # in the block. extract_attachment_refs synthesizes the
        # ImageAttachmentRef from the legacy save's in-block name
        # (the test wrote it before Step 7c, so the v1-shaped pre-save
        # block had a name). Post-Step-7c saves write spec-clean blocks
        # but the load-side reconstructs attachments from session JSON's
        # `attachments` field instead. Either way, the bytes are on disk.
        # Find the file_id from the v2 attachments side.
        assert user_msg.attachments
        restored_file_id = user_msg.attachments[0].file_id
        assert restored_file_id
        restored_path = fresh.file_store.get(restored_file_id)
        assert restored_path is not None
        assert restored_path.read_bytes() == _RED_PIXEL_PNG

    def test_round_trip_preserves_file_id_across_engines(
        self, engine, isolated_dirs
    ):
        # file_id is content-addressed — the same bytes get the same id
        # across two EngineClient instances. We verify this by loading
        # the session from a fresh engine and checking the restored
        # file_id matches what the original engine wrote to disk
        # (read straight from session.json), plus the bytes resolve
        # through the fresh store to the original content.
        engine.session.add_message(Message(
            role="user",
            content=[{
                "type": "image_url", "name": "x.png",
                "image_url": {"url": _RED_DATA_URI},
            }],
        ))
        engine.session.add_message(Message(role="assistant", content="ok"))
        engine.session.save("id_stability")

        # Read the file_id from the persisted JSON.
        # ADR 0006 Step 7c: file_id lives in the URL
        # (file://uploads/<file_id>/<name>), not as a separate in-block key.
        # ADR 0006 Step 4: also surfaces in `attachments` array.
        session_json = (
            isolated_dirs["sessions_dir"] / "id_stability" / "session.json"
        )
        with open(session_json, encoding="utf-8") as f:
            data = json.load(f)
        # Either source is canonical; check both.
        url = data["messages"][0]["content"][0]["image_url"]["url"]
        original_id_from_url = url[len("file://uploads/"):].split("/", 1)[0]
        original_id_from_attachments = data["messages"][0]["attachments"][0]["file_id"]
        assert original_id_from_url == original_id_from_attachments
        original_id = original_id_from_url
        assert original_id  # non-empty

        fresh = EngineClient()
        fresh.session.sessions_dir = isolated_dirs["sessions_dir"]
        fresh.session.load("id_stability")
        loaded_id = fresh.session.messages[0].attachments[0].file_id
        # Same content-addressed id in both engines.
        assert loaded_id == original_id
        # And the restored bytes resolve through the fresh store.
        assert fresh.file_store.get(loaded_id).read_bytes() == _RED_PIXEL_PNG

    def test_multiple_attachments_round_trip(self, engine, isolated_dirs):
        engine.session.add_message(Message(
            role="user",
            content=[
                {"type": "image_url", "name": "red.png",
                 "image_url": {"url": _RED_DATA_URI}},
                {"type": "image_url", "name": "blue.png",
                 "image_url": {"url": _BLUE_DATA_URI}},
            ],
        ))
        engine.session.add_message(Message(role="assistant", content="Two dots."))
        engine.session.save("two_images")

        fresh = EngineClient()
        fresh.session.sessions_dir = isolated_dirs["sessions_dir"]
        fresh.session.load("two_images")

        # Both images reconstructed correctly.
        blocks = fresh.session.messages[0].content
        assert len(blocks) == 2
        assert blocks[0]["image_url"]["url"] == _RED_DATA_URI
        assert blocks[1]["image_url"]["url"] == _BLUE_DATA_URI
        # ADR 0006 Step 7c: file_ids live on Message.attachments, not
        # in-block. Each block has its own ImageAttachmentRef.
        attachments = fresh.session.messages[0].attachments
        assert len(attachments) == 2
        # Different file_ids for different bytes.
        assert attachments[0].file_id != attachments[1].file_id


# -----------------------------------------------------------------------------
# context_attachments AppState integration with file_id
# -----------------------------------------------------------------------------


class TestContextAttachmentsWithFileId:
    def test_entry_has_file_id_field(self, engine):
        # Pre-register via file store so the block comes with a file_id
        # populated — matches the post-Phase-2.1a /attach flow.
        meta = engine.file_store.save(
            "chart.png", _RED_PIXEL_PNG, media_type="image/png"
        )
        engine.session.add_message(Message(
            role="user",
            content=[{
                "type": "image_url",
                "name": "chart.png",
                "file_id": meta.file_id,
                "image_url": {"url": _RED_DATA_URI},
            }],
        ))
        attachments = engine.get_context_attachments()
        assert len(attachments) == 1
        entry = attachments[0]
        # New schema includes file_id.
        assert "file_id" in entry
        assert entry["file_id"] == meta.file_id
        assert entry["name"] == "chart.png"
        assert entry["media_type"] == "image/png"

    def test_legacy_block_without_file_id_has_empty_file_id(self, engine):
        # A Phase-1 style block with no file_id still produces a valid
        # entry — file_id defaults to empty string, media_type parsed
        # from the inline data URI.
        engine.session.add_message(Message(
            role="user",
            content=[{
                "type": "image_url",
                "name": "legacy.png",
                "image_url": {"url": _RED_DATA_URI},
            }],
        ))
        attachments = engine.get_context_attachments()
        assert len(attachments) == 1
        assert attachments[0]["file_id"] == ""
        assert attachments[0]["media_type"] == "image/png"

    def test_dedup_by_file_id_across_turns(self, engine):
        # Same content across two turns — should appear once in context,
        # keyed by file_id (not by name, which might legitimately differ).
        meta = engine.file_store.save(
            "same.png", _RED_PIXEL_PNG, media_type="image/png"
        )
        for _ in range(2):
            engine.session.add_message(Message(
                role="user",
                content=[{
                    "type": "image_url",
                    "name": "same.png",
                    "file_id": meta.file_id,
                    "image_url": {"url": _RED_DATA_URI},
                }],
            ))
        attachments = engine.get_context_attachments()
        assert len(attachments) == 1


# -----------------------------------------------------------------------------
# Backward compat: legacy Phase-1 inline-base64 sessions
# -----------------------------------------------------------------------------


class TestLegacySessionCompat:
    def test_load_phase1_session_with_inline_base64(self, engine, isolated_dirs):
        """Simulate a pre-Phase-2.1a session file on disk: flat .json with
        inline base64 data URIs and no file_id field.

        ADR 0006 Step 5 (v1.18.6): on first load by a 1.18.6+ build,
        v1 multimodal sessions auto-migrate to v2. The image_url block
        is dropped + replaced with a text placeholder; the original v1
        bytes are preserved at `<name>.v1.backup.json` for forensic
        recovery. The session is still loadable; the user-visible
        content has shifted from "image + provider can read it" to
        "text placeholder pointing at backup". Documented breaking
        change in v1.18.6 release notes.
        """
        legacy_data = {
            "session_name": "phase1_legacy",
            "metadata": {"created_at": "2026-04-01", "provider": "gemini",
                         "model": "gemini-3-flash-preview", "message_count": 2},
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "what is this"},
                        {
                            "type": "image_url",
                            "name": "legacy.png",
                            "image_url": {"url": _RED_DATA_URI},
                        },
                    ],
                },
                {"role": "assistant", "content": "An image."},
            ],
            "usage": {"total_tokens": 100, "prompt_tokens": 80,
                      "completion_tokens": 20, "estimated_cost": 0.001},
            "saved_at": "2026-04-01",
        }

        legacy_path = isolated_dirs["sessions_dir"] / "phase1_legacy.json"
        with open(legacy_path, "w", encoding="utf-8") as f:
            json.dump(legacy_data, f)

        # Load with the v1.18.6+ engine — load itself must succeed.
        assert engine.session.load("phase1_legacy")
        assert len(engine.session.messages) == 2
        # Step 5 migration fired: image_url replaced with text placeholder.
        first_msg = engine.session.messages[0]
        assert isinstance(first_msg.content, list)
        assert first_msg.content[0]["text"] == "what is this"  # text preserved
        assert first_msg.content[1]["type"] == "text"
        assert "v1 migration" in first_msg.content[1]["text"]
        assert "legacy.png" in first_msg.content[1]["text"]
        # Original v1 file preserved at the backup location.
        assert (isolated_dirs["sessions_dir"] / "phase1_legacy.v1.backup.json").is_file()

    def test_list_sessions_finds_both_formats(self, engine, isolated_dirs):
        # Create one flat session and one directory session side by side.
        engine.session.add_message(Message(role="user", content="flat"))
        engine.session.add_message(Message(role="assistant", content="ok"))
        engine.session.save("flat_session")

        engine.session.clear()
        engine.session.add_message(Message(
            role="user",
            content=[{
                "type": "image_url", "name": "x.png",
                "image_url": {"url": _RED_DATA_URI},
            }],
        ))
        engine.session.add_message(Message(role="assistant", content="ok"))
        engine.session.save("dir_session")

        sessions = engine.session.list_sessions()
        names = {s.name for s in sessions}
        assert "flat_session" in names
        assert "dir_session" in names

    def test_delete_session_removes_directory_format(self, engine, isolated_dirs):
        engine.session.add_message(Message(
            role="user",
            content=[{
                "type": "image_url", "name": "x.png",
                "image_url": {"url": _RED_DATA_URI},
            }],
        ))
        engine.session.add_message(Message(role="assistant", content="ok"))
        engine.session.save("to_delete")

        session_dir = isolated_dirs["sessions_dir"] / "to_delete"
        assert session_dir.is_dir()

        assert engine.session.delete_session("to_delete") is True
        assert not session_dir.exists()

    def test_delete_session_removes_flat_format(self, engine, isolated_dirs):
        engine.session.add_message(Message(role="user", content="text"))
        engine.session.save("flat_delete")

        flat = isolated_dirs["sessions_dir"] / "flat_delete.json"
        assert flat.is_file()

        assert engine.session.delete_session("flat_delete") is True
        assert not flat.exists()


# -----------------------------------------------------------------------------
# Format transition: text-only session gains first attachment mid-conversation
# -----------------------------------------------------------------------------


class TestFormatTransition:
    def test_text_session_migrates_to_directory_on_first_attachment(
        self, engine, isolated_dirs
    ):
        sessions = isolated_dirs["sessions_dir"]

        # Start as a text-only session — saves as flat .json. Pair with
        # an assistant turn so validate_and_fix_alternation doesn't pop
        # the user message.
        engine.session.add_message(Message(role="user", content="hello"))
        engine.session.add_message(Message(role="assistant", content="hi"))
        engine.session.save("migrating")
        assert (sessions / "migrating.json").is_file()
        assert not (sessions / "migrating").exists()

        # Attach an image and save again — must migrate to directory format.
        engine.session.add_message(Message(
            role="user",
            content=[{
                "type": "image_url", "name": "new.png",
                "image_url": {"url": _RED_DATA_URI},
            }],
        ))
        engine.session.add_message(Message(role="assistant", content="seen"))
        engine.session.save("migrating")

        # Directory layout now present, stale flat file removed.
        assert (sessions / "migrating").is_dir()
        assert (sessions / "migrating" / "session.json").is_file()
        assert (sessions / "migrating" / "uploads").is_dir()
        assert not (sessions / "migrating.json").exists()

    def test_migrated_session_loads_cleanly(self, engine, isolated_dirs):
        # Text-only save → attach → save → load from a fresh engine.
        engine.session.add_message(Message(role="user", content="first"))
        engine.session.add_message(Message(role="assistant", content="first reply"))
        engine.session.save("migrated_load")

        engine.session.add_message(Message(
            role="user",
            content=[{
                "type": "image_url", "name": "added.png",
                "image_url": {"url": _RED_DATA_URI},
            }],
        ))
        engine.session.add_message(Message(role="assistant", content="seen"))
        engine.session.save("migrated_load")

        fresh = EngineClient()
        fresh.session.sessions_dir = isolated_dirs["sessions_dir"]
        assert fresh.session.load("migrated_load")
        assert len(fresh.session.messages) == 4
        # First message still plain text.
        assert fresh.session.messages[0].content == "first"
        # Third message has the image data URI reconstructed.
        assert fresh.session.messages[2].content[0]["image_url"]["url"] == _RED_DATA_URI
