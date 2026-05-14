"""ADR 0006 Phase 2a/2b — Message attachment helper API.

Tests `Message.attachment_for_block` (low-level lookup) and
`Message.resolve_attachment` (high-level lookup with in-block-key
fallback). Both are the shared abstraction used by ADR 0006 Phase 2+
readers (text_content, collect_context_attachments,
multimodal_ops.scan_attachments) so they don't each rewrite the
AttachmentRef-first-with-fallback pattern.

Why the helper exists: same pattern appeared in 3 reader sites during
the Phase 2 refactor. Without the helper:

    ref = msg.attachment_for_block(idx)
    if ref is not None and ref.name:
        name = ref.name
    elif block.get("name"):
        name = block.get("name")
    else:
        name = "image"

With the helper:

    ref = msg.resolve_attachment(idx)
    name = ref.name or "image"

The Phase 3 simplification path: drop the in-block-key synthesis
inside `resolve_attachment` once producers stop emitting those keys.
Callers don't change — only the helper internals do. This indirection
is what protects callers from the schema migration.
"""

from __future__ import annotations

import pytest

from ppxai.engine.types import AttachmentRef, Message


# =============================================================================
# attachment_for_block — low-level lookup
# =============================================================================


class TestAttachmentForBlock:
    """Direct lookup by block_index. Returns Optional[AttachmentRef]."""

    def test_empty_attachments_returns_none(self):
        m = Message(role="user", content=[])
        assert m.attachment_for_block(0) is None

    def test_match_by_block_index(self):
        m = Message(
            role="user",
            content=[
                {"type": "text", "text": "look:"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,X"}},
            ],
            attachments=[
                AttachmentRef(block_index=1, name="img.png", file_id="sha:abc",
                              media_type="image/png"),
            ],
        )
        ref = m.attachment_for_block(1)
        assert ref is not None
        assert ref.name == "img.png"
        assert ref.file_id == "sha:abc"

    def test_no_match_returns_none(self):
        m = Message(
            role="user",
            content=[{"type": "image_url", "image_url": {"url": "data:image/png;base64,X"}}],
            attachments=[
                AttachmentRef(block_index=0, name="a.png", file_id="", media_type=""),
            ],
        )
        # Block 5 doesn't exist; no AttachmentRef for it.
        assert m.attachment_for_block(5) is None

    def test_multiple_attachments_find_correct_one(self):
        m = Message(
            role="user",
            content=[
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,A"}},
                {"type": "text", "text": "between"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,B"}},
            ],
            attachments=[
                AttachmentRef(block_index=0, name="first.png", file_id="sha:1",
                              media_type="image/png"),
                AttachmentRef(block_index=2, name="second.png", file_id="sha:2",
                              media_type="image/png"),
            ],
        )
        assert m.attachment_for_block(0).name == "first.png"
        assert m.attachment_for_block(2).name == "second.png"
        assert m.attachment_for_block(1) is None  # text block, no attachment


# =============================================================================
# resolve_attachment — high-level lookup with in-block fallback
# =============================================================================


class TestResolveAttachment:
    """Always returns an AttachmentRef (never None). Used by Phase 2+
    readers as the single source of truth for the lookup pattern.
    """

    def test_returns_explicit_ref_when_present(self):
        """Step 1 of the resolution chain — explicit AttachmentRef wins."""
        m = Message(
            role="user",
            content=[
                {"type": "image_url", "name": "in-block-name.png",
                 "image_url": {"url": "data:image/png;base64,X"}},
            ],
            attachments=[
                AttachmentRef(block_index=0, name="explicit-name.png",
                              file_id="sha:abc", media_type="image/png"),
            ],
        )
        ref = m.resolve_attachment(0)
        assert ref.name == "explicit-name.png"
        assert ref.file_id == "sha:abc"
        # In-block key is IGNORED when an explicit AttachmentRef exists.

    def test_synthesizes_from_in_block_keys_when_no_ref(self):
        """Step 2 of the resolution chain — synthesize from in-block
           name + file_id keys for messages built outside the producer
           pipeline. Phase 3 drops this branch."""
        m = Message(
            role="user",
            content=[
                {"type": "image_url", "name": "from-in-block.png",
                 "file_id": "sha:fromblock",
                 "image_url": {"url": "data:image/png;base64,X"}},
            ],
            # attachments deliberately empty — pre-Phase-1 shape
        )
        ref = m.resolve_attachment(0)
        assert ref.name == "from-in-block.png"
        assert ref.file_id == "sha:fromblock"
        assert ref.block_index == 0

    def test_returns_empty_ref_when_no_metadata_anywhere(self):
        """Step 3 of the resolution chain — neither AttachmentRef nor
           in-block keys exist. Helper returns an empty AttachmentRef
           (NOT None) so callers can read `.name` / `.file_id` without
           None-handling."""
        m = Message(
            role="user",
            content=[
                {"type": "image_url",
                 "image_url": {"url": "https://example.com/x.png"}},
            ],
        )
        ref = m.resolve_attachment(0)
        assert ref.name == ""
        assert ref.file_id == ""

    def test_returns_empty_ref_for_non_image_block(self):
        """Helper only synthesizes for image_url blocks. Other block
           types (text, file, uploaded_file) return empty AttachmentRef
           because their metadata is intrinsic to the block schema and
           callers should read it from the block directly."""
        m = Message(
            role="user",
            content=[
                {"type": "text", "text": "hello"},
            ],
        )
        ref = m.resolve_attachment(0)
        assert ref.name == ""
        assert ref.file_id == ""

    def test_returns_empty_ref_for_out_of_range_index(self):
        """Defensive: out-of-range block_index returns empty ref, no
           IndexError. Callers iterating may pass any index — robust
           to drift between iteration and lookup."""
        m = Message(role="user", content=[{"type": "text", "text": "x"}])
        ref = m.resolve_attachment(99)
        assert ref.name == ""
        assert ref.file_id == ""
        assert ref.block_index == 99

    def test_returns_empty_ref_for_string_content(self):
        """Defensive: string-content messages have no blocks at all —
           still returns empty ref instead of crashing on `len(str)`."""
        m = Message(role="user", content="just text")
        ref = m.resolve_attachment(0)
        assert ref.name == ""
        assert ref.file_id == ""

    def test_explicit_ref_overrides_in_block_keys(self):
        """Cross-check: when BOTH AttachmentRef and in-block keys exist
           with conflicting values, the AttachmentRef wins. This pins
           the resolution-chain order so a future regression doesn't
           silently flip them."""
        m = Message(
            role="user",
            content=[
                {"type": "image_url", "name": "block-name.png",
                 "file_id": "sha:fromblock",
                 "image_url": {"url": "data:image/png;base64,X"}},
            ],
            attachments=[
                AttachmentRef(block_index=0, name="ref-name.png",
                              file_id="sha:fromref", media_type=""),
            ],
        )
        ref = m.resolve_attachment(0)
        assert ref.name == "ref-name.png"
        assert ref.file_id == "sha:fromref"
