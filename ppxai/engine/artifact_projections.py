"""Per-kind projection handlers for the ArtifactProjector framework.

ADR 0006 Step 7a (v1.18.6). Plug-n-play registration site: each
artifact kind declares how it projects into every consumer projector
(ContextAttachmentProjector, TextMarkerProjector, MessageBoxProjector).

Adding a new artifact kind in v1.19.x:
    1. Define the dataclass + register with ArtifactRegistry in types.py
    2. Add a section here decorating one handler per consumer projector
    3. Done — no reader code edits required

Adding a new consumer projector (e.g. WireBlockProjector for v1.19.x
sub-agent message construction):
    1. Define the projector subclass in artifact_projector.py
    2. Add one decorator per kind in this file
    3. Update the consumer code to call `WireBlockProjector.project(ref)`

Import-side-effect chain:
    main entry imports engine → engine __init__.py imports this module
    → handlers register on import → consumers see populated projector
    registries.

Why this module instead of registering inside the dataclass body in
types.py: keeps types.py focused on data shape (dataclass + to_dict +
from_dict for serialization). Projection logic for UI / DTO / text
markers is a separate concern that belongs adjacent to the projector
framework, not bundled into the type.
"""

from __future__ import annotations

from typing import Any, Dict

from .artifact_projector import (
    ContextAttachmentProjector,
    MessageBoxProjector,
    TextMarkerProjector,
)
from .types import (
    ImageAttachmentRef,
    OfficeAttachmentRef,
    PdfAttachmentRef,
    TextAttachmentRef,
)


# =============================================================================
# image — ImageAttachmentRef
# =============================================================================


@ContextAttachmentProjector.register("image")
def _image_to_context_dto(ref: ImageAttachmentRef) -> Dict[str, Any]:
    """Image → context_attachments DTO entry.

    `name` is the canonical filename (file_store-normalized); empty
    for in-memory previews that bypassed the store. UI renderers
    fall back to "image" when name is empty — matches today's
    `name = block.get("name") or "image"` chain in multimodal_ops.
    """
    return {
        "name": ref.name or "image",
        "kind": "image",
        "media_type": ref.media_type or "",
        "file_id": ref.file_id or "",
    }


@TextMarkerProjector.register("image")
def _image_to_text_marker(ref: ImageAttachmentRef) -> str:
    """Image → `[Image: name]` placeholder for token-counted text.

    Matches the pre-Step-7 marker shape so message_count + token
    estimates don't shift when consumers migrate to the projector.
    """
    name = ref.name or "image"
    return f"[Image: {name}]"


@MessageBoxProjector.register("image")
def _image_to_message_box_label(ref: ImageAttachmentRef) -> str:
    """Image → message-box chip label."""
    name = ref.name or "image"
    return f"⊞ {name}"


# =============================================================================
# pdf — PdfAttachmentRef
# =============================================================================


@ContextAttachmentProjector.register("pdf")
def _pdf_to_context_dto(ref: PdfAttachmentRef) -> Dict[str, Any]:
    """PDF → context_attachments DTO entry. UI uses `kind="pdf"` so
    the chip can render with a PDF-specific icon."""
    return {
        "name": ref.name or "file",
        "kind": "pdf",
        "media_type": ref.media_type or "application/pdf",
        "file_id": ref.file_id or "",
    }


@TextMarkerProjector.register("pdf")
def _pdf_to_text_marker(ref: PdfAttachmentRef) -> str:
    """PDF → `[Attached PDF: name (N pages)]` placeholder."""
    name = ref.name or "file"
    if ref.page_count:
        return f"[Attached PDF: {name} ({ref.page_count} pages)]"
    return f"[Attached PDF: {name}]"


@MessageBoxProjector.register("pdf")
def _pdf_to_message_box_label(ref: PdfAttachmentRef) -> str:
    """PDF → message-box chip label."""
    name = ref.name or "file"
    return f"⎙ {name}"


# =============================================================================
# office — OfficeAttachmentRef (xlsx, pptx, docx)
# =============================================================================


@ContextAttachmentProjector.register("office")
def _office_to_context_dto(ref: OfficeAttachmentRef) -> Dict[str, Any]:
    """Office doc → context_attachments DTO entry. UI uses `kind="file"`
    today since pre-Step-7 multimodal_ops mapped non-PDF uploaded_file
    blocks to `kind="file"`. A future v1.19.x UI can add explicit
    spreadsheet/presentation icons by switching this to `"office"`
    once the renderers learn that kind."""
    return {
        "name": ref.name or "file",
        "kind": "file",
        "media_type": ref.media_type or "",
        "file_id": ref.file_id or "",
    }


@TextMarkerProjector.register("office")
def _office_to_text_marker(ref: OfficeAttachmentRef) -> str:
    """Office doc → `[Attached: name]` placeholder. Detail (sheet
    count, slide count) intentionally omitted from the marker — keeps
    text-content stable for token estimation; UI surfaces detail via
    the message-box projection instead."""
    name = ref.name or "file"
    return f"[Attached: {name}]"


@MessageBoxProjector.register("office")
def _office_to_message_box_label(ref: OfficeAttachmentRef) -> str:
    """Office doc → message-box chip label."""
    name = ref.name or "file"
    return f"⎘ {name}"


# =============================================================================
# text — TextAttachmentRef (markdown, code, csv, plain text)
# =============================================================================


@ContextAttachmentProjector.register("text")
def _text_to_context_dto(ref: TextAttachmentRef) -> Dict[str, Any]:
    """Text artifact → context_attachments DTO entry. `kind="file"`
    matches multimodal_ops's pre-Step-7 mapping for the legacy
    `<uploaded_file>`-marker text branch."""
    return {
        "name": ref.name or "file",
        "kind": "file",
        "media_type": ref.media_type or "text/plain",
        "file_id": ref.file_id or "",
    }


@TextMarkerProjector.register("text")
def _text_to_text_marker(ref: TextAttachmentRef) -> str:
    """Text artifact → `[Attached: name]` placeholder. char_count
    omitted from the marker (same reasoning as office)."""
    name = ref.name or "file"
    return f"[Attached: {name}]"


@MessageBoxProjector.register("text")
def _text_to_message_box_label(ref: TextAttachmentRef) -> str:
    """Text artifact → message-box chip label."""
    name = ref.name or "file"
    return f"⎙ {name}"
