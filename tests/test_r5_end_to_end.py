"""R5 Stage 4 end-to-end — new producers + consumers + provider flatten.

Verifies the full pipeline with a flipped producer:

  1. Producer (`_preprocess_pdf`) emits a structured `uploaded_file`
     content block (not a text marker).
  2. The block lands in `Message.content` and flows through
     `session.add_message` → `on_messages_changed` callback →
     `refresh_context_attachments` → `AppState.context_attachments`
     field. The badge surfaces for every client.
  3. `/attach remove <file_id>` drops the block from session history.
  4. When the message heads to the provider,
     `flatten_uploaded_file_blocks` rewrites the block to the legacy
     text marker — byte-identical to what pre-R5 producers emitted.
     The LLM sees the same string it has always seen.

If any of those links breaks, user-visible attachments silently
vanish or double-emit. The Stage 1–3 unit tests cover each link in
isolation; this module pins the chain.
"""


import pytest

from ppxai.engine.client import EngineClient
from ppxai.engine.file_preprocessing import preprocess_file
from ppxai.engine.types import Message
from ppxai.engine.uploaded_file import (
    UPLOADED_FILE_BLOCK_TYPE,
    format_uploaded_file_reference,
)


@pytest.fixture
def engine(tmp_path):
    """EngineClient with its SessionFileStore pointed at a temp dir."""
    eng = EngineClient()
    # SessionFileStore.staging_dir is initialized to ~/.ppxai/... by
    # default; for tests we don't want to touch user dirs.
    eng.file_store.staging_dir = tmp_path / "staging"
    eng.file_store.staging_dir.mkdir(parents=True, exist_ok=True)
    return eng


def _fake_pdf_bytes() -> bytes:
    # Minimal PDF-like stub — preprocess_pdf persists it and emits a
    # reference block whether or not pypdf is installed. Size > 0
    # for the size_kb field to be meaningful.
    return b"%PDF-1.4\n%fake\n" + b"\x00" * 256


class TestProducerEmitsStructuredBlock:
    """Stage 4 flip: preprocess_file for PDF/Office/large-CSV emits the
    new content type.
    """

    def test_pdf_preprocess_emits_structured_block(self, engine):
        result = preprocess_file(
            "report.pdf",
            _fake_pdf_bytes(),
            media_type="application/pdf",
            file_store=engine.file_store,
        )
        assert result.ok is True
        assert len(result.parts) == 1
        block = result.parts[0]
        assert block["type"] == UPLOADED_FILE_BLOCK_TYPE
        assert block["name"] == "report.pdf"
        assert block["media_type"] == "application/pdf"
        assert block["file_id"] == result.file_id
        assert "read_pdf" in block["summary"]


class TestStructuredBlockSurfacesInContextAttachments:
    """A structured block added via add_message lands in
    `AppState.context_attachments` as a PDF-kind badge.
    """

    def test_pdf_attachment_becomes_badge(self, engine):
        result = preprocess_file(
            "report.pdf",
            _fake_pdf_bytes(),
            media_type="application/pdf",
            file_store=engine.file_store,
        )
        engine.session.add_message(Message(
            role="user",
            content=[{"type": "text", "text": "Summarize"}, result.parts[0]],
        ))
        attachments = engine.get_context_attachments()
        assert len(attachments) == 1
        assert attachments[0]["name"] == "report.pdf"
        assert attachments[0]["kind"] == "pdf"
        assert attachments[0]["file_id"] == result.file_id


class TestAttachRemoveEvictsStructuredBlock:
    """`/attach remove <file_id>` drops the new block type from history."""

    def test_remove_by_file_id_clears_badge(self, engine):
        result = preprocess_file(
            "report.pdf",
            _fake_pdf_bytes(),
            media_type="application/pdf",
            file_store=engine.file_store,
        )
        engine.session.add_message(Message(
            role="user", content=[result.parts[0]],
        ))
        engine.session.add_message(Message(role="assistant", content="ok"))
        assert len(engine.get_context_attachments()) == 1

        removed = engine.remove_context_attachment(result.file_id)
        assert removed >= 1
        assert engine.get_context_attachments() == []


class TestLLMStringInvariantAcrossRollout:
    """The LLM must see byte-identical strings whether the producer
    emitted a pre-R5 text marker or a post-R5 structured block.

    This is the key safety property of the staged rollout: model
    behavior and token counts can't drift just because the wire format
    changed.
    """

    def test_flatten_produces_legacy_marker_from_new_block(self, engine):
        from ppxai.engine.uploaded_file import flatten_uploaded_file_blocks

        result = preprocess_file(
            "report.pdf",
            _fake_pdf_bytes(),
            media_type="application/pdf",
            file_store=engine.file_store,
        )
        block = result.parts[0]

        # Reconstruct what a pre-R5 producer would have emitted inline.
        legacy_text = format_uploaded_file_reference(
            name=block["name"],
            media_type=block["media_type"],
            file_id=block["file_id"],
            body=block["summary"],
            extra_attrs=block.get("extra"),
        )

        # The flatten (called by every provider adapter) must produce
        # exactly that text in a text block.
        flattened = flatten_uploaded_file_blocks([block])
        assert flattened == [{"type": "text", "text": legacy_text}]
