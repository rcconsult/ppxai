"""R5 Stage 3 — consumers accept both structured and legacy text-marker shapes.

During the R5 rollout `multimodal_ops.refresh_context_attachments` and
`multimodal_ops.remove_context_attachment` must handle BOTH:
  - the new `{"type": "uploaded_file", ...}` block (Stage 4 producers)
  - the legacy `<uploaded_file>` XML marker inside a text block (pre-v1.17.6
    sessions loaded from disk)

This is the backward-compat net that lets a session saved by v1.17.5
open correctly under v1.17.6 without migration. A new producer emits
the structured type; an old session keeps its text markers. Both
surface as context_attachment badges and both are removable via
`/attach remove`.
"""

import pytest

from ppxai.engine.client import EngineClient
from ppxai.engine.types import Message
from ppxai.engine.uploaded_file import (
    format_uploaded_file_reference,
    make_uploaded_file_block,
)


@pytest.fixture
def engine():
    return EngineClient()


def _pdf_block(file_id="sha256:abc", name="report.pdf"):
    return make_uploaded_file_block(
        name=name,
        media_type="application/pdf",
        file_id=file_id,
        summary=f"PDF attached: {name}. Use read_pdf.",
        extra={"pages": "12"},
    )


def _pdf_marker_text(file_id="sha256:abc", name="report.pdf"):
    """Legacy text-marker form — what pre-R5 producers emitted."""
    return format_uploaded_file_reference(
        name=name,
        media_type="application/pdf",
        file_id=file_id,
        body=f"PDF attached: {name}. Use read_pdf.",
        extra_attrs={"pages": "12"},
    )


class TestRefreshContextAttachmentsStructured:
    """New-shape path: structured uploaded_file block produces a badge."""

    def test_structured_pdf_block_surfaces_as_badge(self, engine):
        engine.session.add_message(Message(
            role="user",
            content=[{"type": "text", "text": "Summarize:"}, _pdf_block()],
        ))
        attachments = engine.get_context_attachments()
        assert len(attachments) == 1
        entry = attachments[0]
        assert entry["name"] == "report.pdf"
        assert entry["kind"] == "pdf"
        assert entry["media_type"] == "application/pdf"
        assert entry["file_id"] == "sha256:abc"
        assert entry["turn_index"] == 0

    def test_structured_non_pdf_block_kind_is_file(self, engine):
        engine.session.add_message(Message(
            role="user",
            content=[make_uploaded_file_block(
                name="data.xlsx",
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                file_id="sha256:xl",
                summary="Excel attached.",
            )],
        ))
        attachments = engine.get_context_attachments()
        assert len(attachments) == 1
        assert attachments[0]["kind"] == "file"

    def test_structured_blocks_deduped_by_file_id(self, engine):
        """Content-addressed dedup must work on the new shape too (R7 invariant)."""
        for _ in range(2):
            engine.session.add_message(Message(
                role="user",
                content=[_pdf_block(file_id="sha256:same")],
            ))
            engine.session.add_message(Message(role="assistant", content="ok"))
        attachments = engine.get_context_attachments()
        assert len(attachments) == 1


class TestRefreshContextAttachmentsLegacy:
    """Legacy text-marker path: pre-v1.17.6 sessions still produce badges."""

    def test_legacy_text_marker_still_parsed(self, engine):
        engine.session.add_message(Message(
            role="user",
            content=[{"type": "text", "text": _pdf_marker_text()}],
        ))
        attachments = engine.get_context_attachments()
        assert len(attachments) == 1
        entry = attachments[0]
        assert entry["name"] == "report.pdf"
        assert entry["kind"] == "pdf"
        assert entry["file_id"] == "sha256:abc"


class TestRefreshContextAttachmentsMixed:
    """Mixed sessions (some turns legacy, some new) — both shapes coexist."""

    def test_structured_and_legacy_in_same_session(self, engine):
        # Turn 0: legacy text marker
        engine.session.add_message(Message(
            role="user",
            content=[{"type": "text", "text": _pdf_marker_text(
                file_id="sha256:legacy", name="old.pdf",
            )}],
        ))
        engine.session.add_message(Message(role="assistant", content="ok"))
        # Turn 2: structured block
        engine.session.add_message(Message(
            role="user",
            content=[_pdf_block(file_id="sha256:new", name="new.pdf")],
        ))
        attachments = engine.get_context_attachments()
        assert len(attachments) == 2
        names = [a["name"] for a in attachments]
        assert names == ["old.pdf", "new.pdf"]
        assert {a["file_id"] for a in attachments} == {"sha256:legacy", "sha256:new"}

    def test_same_file_id_in_both_shapes_deduped(self, engine):
        """A session that has the same file_id under both shapes (unusual,
        but possible during a mid-migration save) should dedup across both.
        """
        engine.session.add_message(Message(
            role="user",
            content=[_pdf_block(file_id="sha256:shared")],
        ))
        engine.session.add_message(Message(role="assistant", content="ok"))
        engine.session.add_message(Message(
            role="user",
            content=[{"type": "text", "text": _pdf_marker_text(
                file_id="sha256:shared",
            )}],
        ))
        attachments = engine.get_context_attachments()
        assert len(attachments) == 1


class TestRemoveContextAttachmentStructured:
    """/attach remove must evict structured uploaded_file blocks."""

    def test_remove_by_file_id(self, engine):
        engine.session.add_message(Message(
            role="user",
            content=[_pdf_block(file_id="sha256:abc")],
        ))
        engine.session.add_message(Message(role="assistant", content="ok"))
        assert len(engine.get_context_attachments()) == 1

        removed = engine.remove_context_attachment("sha256:abc")
        assert removed >= 1
        assert engine.get_context_attachments() == []

    def test_remove_by_name_when_unique(self, engine):
        engine.session.add_message(Message(
            role="user",
            content=[_pdf_block(name="unique.pdf")],
        ))
        engine.session.add_message(Message(role="assistant", content="ok"))
        removed = engine.remove_context_attachment("unique.pdf")
        assert removed >= 1
        assert engine.get_context_attachments() == []

    def test_remove_all_evicts_structured(self, engine):
        engine.session.add_message(Message(
            role="user",
            content=[_pdf_block(file_id="sha256:a", name="a.pdf")],
        ))
        engine.session.add_message(Message(role="assistant", content="ok"))
        engine.session.add_message(Message(
            role="user",
            content=[_pdf_block(file_id="sha256:b", name="b.pdf")],
        ))
        engine.session.add_message(Message(role="assistant", content="ok"))
        removed = engine.remove_context_attachment("all")
        assert removed == 2
        assert engine.get_context_attachments() == []

    def test_remove_leaves_unrelated_attachments(self, engine):
        engine.session.add_message(Message(
            role="user",
            content=[
                _pdf_block(file_id="sha256:keep", name="keep.pdf"),
                _pdf_block(file_id="sha256:drop", name="drop.pdf"),
            ],
        ))
        engine.session.add_message(Message(role="assistant", content="ok"))
        removed = engine.remove_context_attachment("sha256:drop")
        assert removed == 1
        remaining = engine.get_context_attachments()
        assert len(remaining) == 1
        assert remaining[0]["file_id"] == "sha256:keep"


class TestRemoveContextAttachmentMixed:
    """Evicting across both shapes in the same call."""

    def test_remove_all_drops_both_shapes(self, engine):
        engine.session.add_message(Message(
            role="user",
            content=[
                _pdf_block(file_id="sha256:new"),
                {"type": "text", "text": _pdf_marker_text(file_id="sha256:old")},
            ],
        ))
        engine.session.add_message(Message(role="assistant", content="ok"))
        removed = engine.remove_context_attachment("all")
        assert removed == 2
        assert engine.get_context_attachments() == []
