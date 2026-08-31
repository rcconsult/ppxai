"""R5 Stage 5 — session round-trip + R10 cache predicate cover new type.

Confirms that a session containing the new `uploaded_file` block type
saves and loads correctly, that the R10 multimodal cache predicate
(`_message_has_multimodal`) treats it as multimodal (so save() picks
directory format, not flat JSON), and that the field values survive
unchanged through JSON round-trip.
"""


from ppxai.engine.session import SessionManager, _message_has_multimodal
from ppxai.engine.types import Message
from ppxai.engine.uploaded_file import make_uploaded_file_block


def _pdf_block(file_id="sha256:abc", name="report.pdf"):
    return make_uploaded_file_block(
        name=name,
        media_type="application/pdf",
        file_id=file_id,
        summary=f"PDF attached: {name}. Use read_pdf.",
        extra={"pages": "12", "size_kb": "520.3"},
    )


class TestR10PredicateRecognizesNewType:
    """The multimodal cache predicate must treat uploaded_file as multimodal.

    R10's cache decides flat-JSON vs. directory-format session layout.
    If uploaded_file doesn't count as multimodal, sessions with PDF
    attachments would land in flat JSON and their uploads/ subtree
    wouldn't be created.
    """

    def test_message_with_uploaded_file_is_multimodal(self):
        msg = Message(role="user", content=[_pdf_block()])
        assert _message_has_multimodal(msg) is True

    def test_message_with_text_and_uploaded_file_is_multimodal(self):
        msg = Message(
            role="user",
            content=[{"type": "text", "text": "Summarize:"}, _pdf_block()],
        )
        assert _message_has_multimodal(msg) is True

    def test_text_only_message_is_not_multimodal(self):
        """Sanity — shared predicate still returns False for plain text."""
        msg = Message(role="user", content=[{"type": "text", "text": "hi"}])
        assert _message_has_multimodal(msg) is False

    def test_string_content_is_not_multimodal(self):
        msg = Message(role="user", content="plain string")
        assert _message_has_multimodal(msg) is False

    def test_cache_flips_to_true_on_uploaded_file_add(self, tmp_path):
        """SessionManager.add_message should eagerly flip
        `_multimodal_cache` to True when the new message contains
        an uploaded_file block — same fast path as image_url.
        """
        session = SessionManager(
            sessions_dir=tmp_path, exports_dir=tmp_path / "exports",
        )
        # Cold start — cache is None
        assert session._multimodal_cache is None

        session.add_message(Message(role="user", content="hi"))
        # After a text-only add the cache is still None (lazy scan).
        # But session decides format on first save; the predicate stays
        # False-or-unscanned until something multimodal lands.
        assert session._multimodal_cache is None or session._multimodal_cache is False

        session.add_message(Message(role="user", content=[_pdf_block()]))
        assert session._multimodal_cache is True


class TestUploadedFileBlockRoundTrip:
    """A session containing the new block type must save and load with
    every field intact.
    """

    def test_structured_block_survives_save_and_load(self, tmp_path):
        session = SessionManager(
            sessions_dir=tmp_path, exports_dir=tmp_path / "exports",
        )
        session.session_name = "round_trip_test"
        original_block = _pdf_block(file_id="sha256:abc", name="report.pdf")
        session.add_message(Message(
            role="user",
            content=[{"type": "text", "text": "check this:"}, original_block],
        ))
        session.add_message(Message(role="assistant", content="ok"))

        saved = session.save("round_trip_test")
        assert saved

        # Fresh SessionManager, load the session back.
        fresh = SessionManager(
            sessions_dir=tmp_path, exports_dir=tmp_path / "exports",
        )
        loaded = fresh.load("round_trip_test")
        assert loaded is True
        assert len(fresh.messages) == 2

        user_msg = fresh.messages[0]
        assert isinstance(user_msg.content, list)
        # The uploaded_file block is still there with every field.
        uploaded = [
            b for b in user_msg.content
            if isinstance(b, dict) and b.get("type") == "uploaded_file"
        ]
        assert len(uploaded) == 1
        block = uploaded[0]
        assert block["name"] == "report.pdf"
        assert block["media_type"] == "application/pdf"
        assert block["file_id"] == "sha256:abc"
        assert "Use read_pdf" in block["summary"]
        assert block["extra"]["pages"] == "12"
        assert block["extra"]["size_kb"] == "520.3"


class TestMixedSessionLoad:
    """A session with BOTH legacy text markers AND new structured blocks
    loads cleanly. Simulates a session saved mid-migration (some turns
    on pre-R5, some post-R5).
    """

    def test_mixed_session_loads_without_error(self, tmp_path):
        from ppxai.engine.uploaded_file import format_uploaded_file_reference

        session = SessionManager(
            sessions_dir=tmp_path, exports_dir=tmp_path / "exports",
        )
        session.session_name = "mixed"
        # Turn 0: pre-R5 shape — text marker embedded in a text block.
        legacy_text = format_uploaded_file_reference(
            name="old.pdf",
            media_type="application/pdf",
            file_id="sha256:legacy",
            body="Old PDF. Use read_pdf.",
        )
        session.add_message(Message(
            role="user",
            content=[{"type": "text", "text": legacy_text}],
        ))
        session.add_message(Message(role="assistant", content="ok"))
        # Turn 2: post-R5 shape — structured block.
        session.add_message(Message(
            role="user",
            content=[_pdf_block(file_id="sha256:new", name="new.pdf")],
        ))
        session.add_message(Message(role="assistant", content="ok"))
        session.save("mixed")

        fresh = SessionManager(
            sessions_dir=tmp_path, exports_dir=tmp_path / "exports",
        )
        assert fresh.load("mixed") is True
        assert len(fresh.messages) == 4
        # Legacy text marker preserved as-is.
        first_turn_content = fresh.messages[0].content
        first_text = first_turn_content[0]["text"]
        assert "<uploaded_file" in first_text
        assert 'name="old.pdf"' in first_text
        # Structured block preserved as-is.
        third_turn_content = fresh.messages[2].content
        assert third_turn_content[0]["type"] == "uploaded_file"
        assert third_turn_content[0]["name"] == "new.pdf"
