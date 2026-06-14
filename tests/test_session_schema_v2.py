"""ADR 0006 Step 4 (v1.18.6) — session schema_version: 2 round-trip tests.

Pins the on-disk shape of v2 sessions and the dual-path deserialize:

1. **Round-trip — v2 saves and loads correctly.** A session with
   image attachments saved by current code carries
   `schema_version: 2` at the top level and an `attachments` array
   per message, each entry round-trippable through
   ArtifactRegistry.deserialize.

2. **Forward-compat — unknown kinds are skipped.** A v2 session with
   an artifact kind unknown to this build loads cleanly with the
   unknown ref dropped (forward-compat property required by
   ADR 0003 — agent runs may carry newer kinds).

3. **Backward-compat — v1 sessions load via legacy fallback.** A
   session JSON with no top-level schema_version (or schema_version: 1)
   and no `attachments` field per message still produces correct
   `Message.attachments` by walking the in-block name+file_id keys,
   matching the pre-v1.18.6 behavior. Legacy v1 loader migration with
   multimodal-drop arrives in Step 5.

4. **Empty attachments stay clean.** Text-only messages do NOT emit
   an empty `attachments: []` field — the JSON stays compact.

Sentinel: schema_version is the load-bearing contract for ADR 0003
agent platform persistence (state.json + events.jsonl will reuse the
same SCHEMA_VERSION discipline). Drift here breaks v1.19.x.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ppxai.engine.artifact_registry import ArtifactRegistry
from ppxai.engine.session import SESSION_SCHEMA_VERSION, SessionManager
from ppxai.engine.session_store import SessionFileStore
from ppxai.engine.types import (
    ImageAttachmentRef,
    Message,
    PdfAttachmentRef,
    TextAttachmentRef,
)


# 1×1 transparent PNG (smallest valid image bytes).
_PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c63f8cf00000003000080010100ce4d4d780000000049454e44ae426082"
)


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
    """SessionManager wired to a real file_store so attachments path-resolve."""
    sess = SessionManager(
        sessions_dir=temp_sessions_dir, exports_dir=temp_exports_dir
    )
    # Wire a fresh SessionFileStore — same shape as runtime wiring in
    # EngineClient.__init__.
    sess.file_store = SessionFileStore(base_dir=tmp_path / "staging")
    return sess


# =============================================================================
# 1. v2 round-trip
# =============================================================================


class TestV2RoundTrip:
    """save() emits schema_version: 2 + attachments array; load() reconstructs."""

    def test_top_level_schema_version_emitted(
        self, session_with_store, temp_sessions_dir
    ):
        """save() writes schema_version=SESSION_SCHEMA_VERSION at top level."""
        # User+assistant pair so validate_and_fix_alternation doesn't strip
        # the trailing-user message during save.
        session_with_store.add_message(Message(role="user", content="hello"))
        session_with_store.add_message(Message(role="assistant", content="hi"))
        session_with_store.save("v2-marker")

        # Either flat or directory format — find the JSON file.
        flat = temp_sessions_dir / "v2-marker.json"
        nested = temp_sessions_dir / "v2-marker" / "session.json"
        path = flat if flat.exists() else nested

        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        assert data["schema_version"] == SESSION_SCHEMA_VERSION
        assert SESSION_SCHEMA_VERSION == 2  # contract pinned

    def test_image_attachment_round_trips_via_registry(
        self, session_with_store, temp_sessions_dir
    ):
        """A Message with an ImageAttachmentRef serializes to a v2 attachments
        array, and load() reconstructs an equivalent ImageAttachmentRef."""
        # Persist the image bytes via the store so file_id resolves.
        meta = session_with_store.file_store.save("shot.png", _PNG_BYTES, media_type="image/png")
        ref = ImageAttachmentRef(
            block_index=1,
            name=meta.name,
            file_id=meta.file_id,
            media_type="image/png",
        )
        msg = Message(
            role="user",
            content=[
                {"type": "text", "text": "look at this"},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{_PNG_BYTES.hex()}"
                    },
                    "name": meta.name,
                    "file_id": meta.file_id,
                },
            ],
            attachments=[ref],
        )
        session_with_store.add_message(msg)
        session_with_store.add_message(Message(role="assistant", content="I see it"))
        session_with_store.save("v2-image")

        # Verify the on-disk shape carries the attachments array.
        nested = temp_sessions_dir / "v2-image" / "session.json"
        flat = temp_sessions_dir / "v2-image.json"
        path = nested if nested.exists() else flat
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        assert data["schema_version"] == 2
        msg_dict = data["messages"][0]
        assert "attachments" in msg_dict
        assert len(msg_dict["attachments"]) == 1
        assert msg_dict["attachments"][0]["kind"] == "image"
        assert msg_dict["attachments"][0]["_schema_version"] == 1
        assert msg_dict["attachments"][0]["block_index"] == 1
        assert msg_dict["attachments"][0]["name"] == meta.name
        assert msg_dict["attachments"][0]["file_id"] == meta.file_id

        # Now load into a fresh SessionManager and verify attachments restored.
        loaded = SessionManager(
            sessions_dir=temp_sessions_dir, exports_dir=session_with_store.exports_dir
        )
        loaded.file_store = session_with_store.file_store
        assert loaded.load("v2-image") is True
        assert len(loaded.messages) == 2
        loaded_msg = loaded.messages[0]
        assert len(loaded_msg.attachments) == 1
        loaded_ref = loaded_msg.attachments[0]
        assert isinstance(loaded_ref, ImageAttachmentRef)
        assert loaded_ref.block_index == 1
        assert loaded_ref.name == meta.name
        assert loaded_ref.file_id == meta.file_id
        assert loaded_ref.media_type == "image/png"

    def test_multiple_kinds_round_trip_via_registry(
        self, session_with_store, temp_sessions_dir
    ):
        """v2 attachments array preserves heterogeneous kinds — Image, Pdf,
        Text in one message all reconstruct via ArtifactRegistry dispatch."""
        msg = Message(
            role="user",
            content=[
                {"type": "text", "text": "mixed bag"},
                {"type": "image_url", "image_url": {"url": "file://x"}},
                {"type": "uploaded_file", "name": "doc.pdf", "file_id": "abc"},
                {"type": "text", "text": "[notes.md]\n# title"},
            ],
            attachments=[
                ImageAttachmentRef(block_index=1, name="x.png", file_id="img1"),
                PdfAttachmentRef(block_index=2, name="doc.pdf", file_id="abc", page_count=3),
                TextAttachmentRef(
                    block_index=3, name="notes.md", file_id="md1",
                    media_type="text/markdown", char_count=8,
                ),
            ],
        )
        session_with_store.add_message(msg)
        session_with_store.add_message(Message(role="assistant", content="received"))
        session_with_store.save("v2-mixed")

        loaded = SessionManager(
            sessions_dir=temp_sessions_dir, exports_dir=session_with_store.exports_dir
        )
        loaded.file_store = session_with_store.file_store
        assert loaded.load("v2-mixed") is True
        kinds = [type(a).__name__ for a in loaded.messages[0].attachments]
        assert kinds == ["ImageAttachmentRef", "PdfAttachmentRef", "TextAttachmentRef"]
        # Per-kind specifics survive
        pdf = loaded.messages[0].attachments[1]
        assert isinstance(pdf, PdfAttachmentRef)
        assert pdf.page_count == 3
        text = loaded.messages[0].attachments[2]
        assert isinstance(text, TextAttachmentRef)
        assert text.media_type == "text/markdown"
        assert text.char_count == 8

    def test_text_only_message_omits_attachments_key(
        self, session_with_store, temp_sessions_dir
    ):
        """Empty attachments list is dropped from the JSON to keep
        text-only messages compact (no `"attachments": []` noise)."""
        session_with_store.add_message(Message(role="user", content="just text"))
        session_with_store.add_message(Message(role="assistant", content="ok"))
        session_with_store.save("v2-text-only")

        flat = temp_sessions_dir / "v2-text-only.json"
        nested = temp_sessions_dir / "v2-text-only" / "session.json"
        path = flat if flat.exists() else nested
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        assert "attachments" not in data["messages"][0]


# =============================================================================
# 2. Forward-compat — unknown kinds skipped
# =============================================================================


class TestForwardCompatUnknownKinds:
    """Unknown future kinds in v2 sessions don't crash load — they're dropped
    with a warning. Required property per ADR 0003 (agent runs may carry
    newer-version artifact kinds an older ppxai doesn't recognize)."""

    def test_unknown_kind_dropped_silently_during_load(
        self, session_with_store, temp_sessions_dir
    ):
        """Hand-craft a v2 session JSON containing an unknown kind +
        a known kind, verify load picks up the known + drops the unknown."""
        session_dir = temp_sessions_dir / "future-kind"
        session_dir.mkdir()
        session_data = {
            "schema_version": 2,
            "session_name": "future-kind",
            "metadata": {},
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "hi"}],
                    "attachments": [
                        {
                            "kind": "image",
                            "_schema_version": 1,
                            "block_index": 0,
                            "name": "x.png",
                            "file_id": "id1",
                            "media_type": "image/png",
                        },
                        {
                            # ← unknown to this build — registry returns None
                            "kind": "subagent_plan",
                            "_schema_version": 1,
                            "block_index": 99,
                            "plan_id": "v1.19.x_future",
                        },
                    ],
                },
                {"role": "assistant", "content": "ack"},
            ],
            "usage": {"total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0,
                      "estimated_cost": 0.0},
            "saved_at": "2026-05-14T12:00:00",
            "command_history": [],
            "working_dir": ".",
            "tools_enabled": False,
        }
        with open(session_dir / "session.json", "w", encoding="utf-8") as f:
            json.dump(session_data, f, indent=2)

        loaded = SessionManager(
            sessions_dir=temp_sessions_dir, exports_dir=session_with_store.exports_dir
        )
        loaded.file_store = session_with_store.file_store
        assert loaded.load("future-kind") is True
        attachments = loaded.messages[0].attachments
        # Unknown skipped; known survives.
        assert len(attachments) == 1
        assert isinstance(attachments[0], ImageAttachmentRef)
        assert attachments[0].name == "x.png"
        # Sanity: the registry really doesn't know this kind yet.
        assert not ArtifactRegistry.has_kind("subagent_plan")


# =============================================================================
# 3. Backward-compat — v1 sessions still load via legacy fallback
# =============================================================================


class TestV1LegacyLoad:
    """v1 sessions (no schema_version, no attachments field) load via
    extract_attachment_refs walking in-block name+file_id keys.

    This is the transitional fallback that keeps ppxai <= 1.18.5 sessions
    loadable in 1.18.6 builds without explicit migration. Step 5 will add
    the explicit migrate-to-v2 path with multimodal-drop policy."""

    def test_v1_session_no_schema_field_triggers_migration(
        self, session_with_store, temp_sessions_dir
    ):
        """Hand-craft a v1-shape session JSON (no schema_version, no
        attachments key, in-block name+file_id) and verify load
        triggers the Step 5 v1 → v2 migration: image dropped + replaced
        with text placeholder, backup file created.

        (Pre-Step-5 behavior — preserve the ImageAttachmentRef via legacy
        extraction — is no longer reachable. Once Step 5 ships, the
        migration always wins for multimodal v1 sessions. The deserialize
        fallback is still exercised internally as the load step that
        feeds into migration; the post-load observable state is the
        migrated v2 shape.)"""
        # Real v1 sessions stored images INLINE as data: URIs (file_id
        # references + uploads/ are a v2 concept). Using an inline image here
        # keeps the test independent of the file store — which load() now
        # resets on every load (session-security finding #2), so a flat
        # session can no longer borrow a previously-staged file_id.
        flat_path = temp_sessions_dir / "v1-legacy.json"
        v1_data = {
            # NB: NO schema_version field — pure v1 shape.
            "session_name": "v1-legacy",
            "metadata": {},
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "look"},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{_PNG_BYTES.hex()}"
                            },
                        },
                    ],
                    # NB: no "attachments" key
                },
                {"role": "assistant", "content": "I see it"},
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

        loaded = SessionManager(
            sessions_dir=temp_sessions_dir, exports_dir=session_with_store.exports_dir
        )
        loaded.file_store = session_with_store.file_store
        assert loaded.load("v1-legacy") is True
        assert len(loaded.messages) == 2
        # Step 5 migration: image dropped, attachments cleared,
        # block replaced with a text placeholder.
        first = loaded.messages[0]
        assert first.attachments == []
        assert isinstance(first.content, list)
        assert first.content[0]["type"] == "text"
        assert first.content[0]["text"] == "look"
        assert first.content[1]["type"] == "text"
        assert "v1 migration" in first.content[1]["text"]
        assert "dropped" in first.content[1]["text"]
        # Backup file preserved (flat-format because we wrote a flat session).
        assert (temp_sessions_dir / "v1-legacy.v1.backup.json").is_file()

    def test_v1_text_only_message_yields_empty_attachments(
        self, session_with_store, temp_sessions_dir
    ):
        """v1 text-only messages have no in-block keys to extract → empty list."""
        flat_path = temp_sessions_dir / "v1-textonly.json"
        v1_data = {
            "session_name": "v1-textonly",
            "metadata": {},
            "messages": [
                {"role": "user", "content": "just text"},
                {"role": "assistant", "content": "ok"},
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

        loaded = SessionManager(
            sessions_dir=temp_sessions_dir, exports_dir=session_with_store.exports_dir
        )
        loaded.file_store = session_with_store.file_store
        assert loaded.load("v1-textonly") is True
        assert len(loaded.messages) == 2
        for m in loaded.messages:
            assert m.attachments == []


# =============================================================================
# 4. SCHEMA_VERSION constant pinning
# =============================================================================


class TestSchemaVersionConstant:
    """The session-level SCHEMA_VERSION is the load-bearing contract that
    will extend to ADR 0003 agent runs (state.json + events.jsonl). Pin
    it so a value-change is a deliberate, reviewed action — not a typo."""

    def test_constant_is_two(self):
        assert SESSION_SCHEMA_VERSION == 2

    def test_explicit_v1_matches_no_schema_field(
        self, session_with_store, temp_sessions_dir
    ):
        """A session JSON with explicit schema_version: 1 behaves identically
        to a session JSON with no schema_version field — both route through
        the Step 5 v1 → v2 migration when multimodal content is present."""
        flat_path = temp_sessions_dir / "v1-explicit.json"
        # Inline data: URI — real v1 shape, independent of the file store
        # (load() now resets it on every load; see finding #2).
        v1_data = {
            "schema_version": 1,
            "session_name": "v1-explicit",
            "metadata": {},
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "x"},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{_PNG_BYTES.hex()}"},
                        },
                    ],
                },
                {"role": "assistant", "content": "ack"},
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

        loaded = SessionManager(
            sessions_dir=temp_sessions_dir, exports_dir=session_with_store.exports_dir
        )
        loaded.file_store = session_with_store.file_store
        assert loaded.load("v1-explicit") is True
        # Step 5 migration fired (same as schema_version-absent case):
        # image dropped, attachments cleared, backup preserved.
        assert loaded.messages[0].attachments == []
        assert "v1 migration" in loaded.messages[0].content[1]["text"]
        assert (temp_sessions_dir / "v1-explicit.v1.backup.json").is_file()
