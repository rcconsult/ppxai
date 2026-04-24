"""
File preprocessing dispatcher for multimodal attachments.

Phase 2.2 (v1.17.4). Central entry point that takes raw file bytes and a
target model, and produces one or more OpenAI-format content parts ready
to merge into a user message. Called by `/attach`, the server chat route
(Phase 3), and future bulk upload tooling.

The dispatcher is the glue between four independent building blocks
landed earlier in Phase 2:

    SessionFileStore (2.1)       → durable binary storage, file_id refs
    ModelProfile.supports_vision (2.5) → image routing decision
    validate_image (2.6)         → format + size validation
    VL sidecar (2.7, pending)    → captioning fallback for text-only models

Responsibilities:

1. **Classify** the input by media type (image / text / pdf / office / other).
   Uses magic-byte sniffing for images so a misnamed file is still
   routed correctly; falls back to MIME detection + extension for text
   and office formats.

2. **Validate** images through the Phase 2.6 pipeline (format, size,
   dimensions, provider-aware limits). Validation failures produce a
   clear `error` on the result so the caller can surface a human-readable
   reason.

3. **Persist** binary content (images, PDFs, office documents) via
   `SessionFileStore` so the caller gets a stable `file_id` back. Text
   files are NOT persisted — they're inlined into the prompt directly.

4. **Route** images based on `supports_vision(model)`:
       - Vision-capable model → emit an `image_url` content part pointing
         at the persisted bytes (via a data: URI for in-memory use;
         serialization rewrites it to file_id at save time).
       - Text-only model + VL sidecar configured → call the captioner,
         emit a text part `[Image: name — <caption>]`.
       - Text-only model + no sidecar → emit a placeholder text part
         `[Image: name — vision not supported by current model]` so
         the user sees what was dropped and why.

5. **Return** a single `PreprocessResult` dataclass carrying the content
   parts, optional `file_id`, any warnings, and an error string on
   failure. Callers iterate over multiple files, collect all their
   parts, and merge with the user's prompt text into the final message
   content list.

Design: zero direct engine import. The function takes an optional
`file_store` and optional `vl_captioner` callable so tests can exercise
it in isolation, and so future clients (server route, batch scripts)
can drive it without instantiating an `EngineClient`.
"""

from __future__ import annotations

import base64
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .image_validation import sniff_media_type, validate_image
from .model_profiles import supports_vision as model_supports_vision
from .uploaded_file import make_uploaded_file_block
from .session_store import (
    KIND_IMAGE,
    KIND_OFFICE,
    KIND_OTHER,
    KIND_PDF,
    KIND_TEXT,
    SessionFileStore,
    classify_kind,
)

# VL captioner signature — Phase 2.7 will wire EngineClient.caption_image
# here. Takes (name, media_type, data) and returns a short text caption.
# Must be synchronous to keep `preprocess_file` simple; callers wanting
# async must wrap it themselves.
VLCaptioner = Callable[[str, str, bytes], str]


@dataclass
class PreprocessResult:
    """Outcome of running one file through the preprocessing dispatcher.

    Attributes:
        ok: True if the file was successfully prepared for sending.
            False results carry a non-empty `error` explaining why.
        parts: OpenAI-format content parts to merge into the user
            message. Empty when ok=False. For images with vision
            support: one `image_url` block. For text files: one
            `text` block containing the `<file name="…">` wrapper.
            For PDFs / Office: one `text` block containing the
            `<uploaded_file>` reference with metadata.
        file_id: SessionFileStore identifier when persisted bytes
            exist (image, pdf, office). Empty for text-only files
            and on failure.
        name: Canonical display name (basename only, sanitized).
        media_type: Canonical MIME type (may differ from what the
            caller declared — magic-byte sniffing wins).
        kind: Broad category — "image" | "text" | "pdf" | "office"
            | "other". Used by UI layers deciding which icon/chip
            style to render.
        warnings: Non-fatal notes — e.g., "PDF page count unknown
            (pypdf not installed)" or "image too large for current
            provider but sent anyway with override".
        error: Human-readable rejection reason when ok=False.
    """
    ok: bool
    parts: List[Dict[str, Any]] = field(default_factory=list)
    file_id: str = ""
    name: str = ""
    media_type: str = ""
    kind: str = ""
    warnings: List[str] = field(default_factory=list)
    error: str = ""


# Defer pypdf import to the caller of _count_pdf_pages — pypdf is an
# optional dependency shipped under the `[data]` extras group (Phase 2.9).
# Preprocessing still works without it; PDF page count becomes unknown.
def _count_pdf_pages(data: bytes) -> Optional[int]:
    """Return PDF page count, or None if pypdf is unavailable / data is malformed."""
    try:
        import pypdf  # noqa: PLC0415 — optional dep, local import
    except ImportError:
        return None

    try:
        import io
        reader = pypdf.PdfReader(io.BytesIO(data))
        return len(reader.pages)
    except Exception:
        # Corrupt PDF, encrypted, or library version mismatch — return
        # None rather than propagating. The caller surfaces a warning.
        return None


def _sanitize_name(name: str) -> str:
    """Strip directory components and whitespace from a filename.

    Matches the defensive handling in SessionFileStore.save() but runs
    here too so the returned `PreprocessResult.name` is already clean
    for UI display even when the file is rejected before reaching the
    store.
    """
    if not name:
        return "file"
    return Path(name).name.strip() or "file"


def _decode_text(data: bytes) -> str:
    """Best-effort UTF-8 decode with replacement on invalid bytes.

    Text files may contain non-UTF-8 sequences (Windows CP1252,
    binary-ish config files, etc.). Using `errors='replace'` means
    we never crash on encoding issues — the model sees U+FFFD
    markers where bytes couldn't be decoded, which is better than
    dropping the entire file.
    """
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")


def _classify_file(name: str, data: bytes, declared_media_type: Optional[str]) -> tuple[str, str]:
    """Determine canonical (media_type, kind) for the input.

    Priority:
    1. Magic-byte sniffing wins for images — a PNG named photo.jpg
       is still a PNG and must be routed correctly.
    2. Declared media type from the caller (HTTP header, /attach command).
    3. mimetypes.guess_type(name) from filename extension.
    4. `application/octet-stream` fallback.

    Then `session_store.classify_kind` maps (media_type, name) to the
    broad kind category used by downstream routing.
    """
    # Image sniffing trumps everything — lets us correct mislabeled files.
    sniffed = sniff_media_type(data)
    if sniffed:
        return sniffed, KIND_IMAGE

    if declared_media_type:
        media_type = declared_media_type
    else:
        guessed, _ = mimetypes.guess_type(name)
        media_type = guessed or "application/octet-stream"

    kind = classify_kind(media_type, name)
    return media_type, kind


# =============================================================================
# Per-kind handlers
# =============================================================================


def _preprocess_image(
    name: str,
    data: bytes,
    media_type: str,
    *,
    model: str,
    provider: Optional[str],
    file_store: Optional[SessionFileStore],
    vl_captioner: Optional[VLCaptioner],
) -> PreprocessResult:
    """Validate + route an image attachment.

    Flow:
    1. Validate format + size via Phase 2.6 pipeline.
    2. If invalid → PreprocessResult(ok=False, error=<reason>).
    3. Persist bytes to SessionFileStore (if available) to get a
       stable file_id.
    4. Route based on `supports_vision(model)`:
        - True → emit image_url data URI content part.
        - False + VL captioner configured → call it, emit text caption.
        - False + no VL → emit "[Image: name — vision not supported]"
          placeholder so the user sees what happened.
    """
    validation = validate_image(
        data,
        declared_media_type=media_type,
        provider=provider,
    )
    if not validation.ok:
        return PreprocessResult(
            ok=False,
            name=name,
            media_type=media_type,
            kind=KIND_IMAGE,
            error=validation.reason,
        )

    # Sniffed media type is authoritative.
    canonical_mt = validation.media_type or media_type

    # Persist to the store (if wired) so the caller gets a stable file_id.
    file_id = ""
    warnings: List[str] = []
    if file_store is not None:
        try:
            meta = file_store.save(name, data, media_type=canonical_mt)
            file_id = meta.file_id
            name = meta.name  # canonicalized basename
        except OSError as exc:
            warnings.append(
                f"file_store.save failed ({exc}); continuing without persistence"
            )

    # Emit a token-cost hint as a warning so UIs can surface it.
    if validation.estimated_tokens:
        warnings.append(
            f"~{validation.estimated_tokens} tokens "
            f"({validation.width}x{validation.height})"
        )

    # Routing decision: vision-capable model vs text-only + fallbacks.
    if model and model_supports_vision(model):
        b64 = base64.b64encode(data).decode("ascii")
        block: Dict[str, Any] = {
            "type": "image_url",
            "name": name,
            "image_url": {
                "url": f"data:{canonical_mt};base64,{b64}",
            },
        }
        if file_id:
            block["file_id"] = file_id
        return PreprocessResult(
            ok=True,
            parts=[block],
            file_id=file_id,
            name=name,
            media_type=canonical_mt,
            kind=KIND_IMAGE,
            warnings=warnings,
        )

    # Text-only model path. Try the VL sidecar captioner if one is wired.
    if vl_captioner is not None:
        try:
            caption = vl_captioner(name, canonical_mt, data)
        except Exception as exc:  # pragma: no cover — captioner is user code
            warnings.append(f"VL captioner raised: {exc}")
            caption = ""

        if caption:
            text_block = {
                "type": "text",
                "text": f"[Image: {name} — {caption}]",
            }
            return PreprocessResult(
                ok=True,
                parts=[text_block],
                file_id=file_id,
                name=name,
                media_type=canonical_mt,
                kind=KIND_IMAGE,
                warnings=warnings,
            )

    # No vision support, no captioner — emit a placeholder. The user
    # still sees the attachment was attempted and why it didn't go
    # through, rather than a silent drop.
    if model:
        reason = f"{model} does not support images and no VL sidecar is configured"
    else:
        reason = "no model provided and no VL sidecar is configured"
    placeholder = {
        "type": "text",
        "text": f"[Image: {name} — {reason}]",
    }
    return PreprocessResult(
        ok=True,  # The file was valid; we just couldn't send it as an image.
        parts=[placeholder],
        file_id=file_id,
        name=name,
        media_type=canonical_mt,
        kind=KIND_IMAGE,
        warnings=warnings + [reason],
    )


def _is_csv_file(name: str, media_type: str) -> bool:
    """Check if a file is a CSV based on extension or media type."""
    return (
        media_type == "text/csv"
        or name.lower().endswith(".csv")
    )


# Threshold above which CSVs are lazy-loaded via SessionFileStore
# instead of inlined into the prompt. 50 KB is generous for text
# context but prevents multi-MB data files from eating the context
# window.
_CSV_LAZY_THRESHOLD = 50 * 1024  # 50 KB


def _count_csv_rows_cols(data: bytes) -> tuple[int, int]:
    """Count rows and columns in a CSV. Returns (rows, columns).

    Uses csv.reader with delimiter sniffing. Row count excludes the
    header row. Returns (0, 0) on empty or unparseable data.

    R8: sniff the delimiter on the first 8 KB only, then stream the
    original bytes through TextIOWrapper so csv.reader iterates
    row-by-row without ever materializing the whole file as a Python
    string. For a 500 MB CSV this keeps peak memory at roughly the
    TextIOWrapper buffer (~8 KB) + one decoded row, instead of
    allocating a multi-hundred-MB string just to sniff the shape.
    """
    import csv as _csv
    import io as _io

    # Sniff on a small sample — enough for the delimiter heuristic,
    # no need to decode the full buffer.
    sample = _decode_text(data[:8192])
    try:
        dialect = _csv.Sniffer().sniff(sample)
        delimiter = dialect.delimiter
    except _csv.Error:
        delimiter = ","

    # Stream the raw bytes. TextIOWrapper decodes incrementally, so
    # csv.reader pulls one row's worth of text at a time.
    stream = _io.TextIOWrapper(
        _io.BytesIO(data), encoding="utf-8", errors="replace", newline=""
    )
    reader = _csv.reader(stream, delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration:
        return 0, 0
    columns = len(header)
    data_rows = sum(1 for _ in reader)
    return data_rows, columns


def _preprocess_csv(
    name: str,
    data: bytes,
    media_type: str,
    *,
    file_store: Optional[SessionFileStore],
) -> PreprocessResult:
    """Persist a large CSV and emit a text reference with metadata.

    Large CSVs are NOT inlined — instead the model sees a marker
    indicating the file is available via the read_csv and
    list_csv_columns tools. This mirrors the PDF lazy-loading pattern.
    """
    warnings: List[str] = []

    file_id = ""
    if file_store is not None:
        try:
            meta = file_store.save(name, data, media_type=media_type)
            file_id = meta.file_id
            name = meta.name
        except OSError as exc:
            return PreprocessResult(
                ok=False,
                name=name,
                media_type=media_type,
                kind=KIND_TEXT,
                error=f"file_store.save failed: {exc}",
            )
    else:
        warnings.append(
            "No SessionFileStore wired — CSV will be unreachable to tools"
        )

    row_count, col_count = _count_csv_rows_cols(data)
    size_kb = len(data) / 1024

    # R5 (v1.17.6): emit the first-class uploaded_file block. Provider
    # adapters flatten this back to the legacy text marker before the
    # API call via `flatten_uploaded_file_blocks`, so the LLM sees the
    # same string it did pre-R5.
    block = make_uploaded_file_block(
        name=name,
        media_type="text/csv",
        file_id=file_id,
        summary=(
            f"CSV attached: {name} ({row_count} rows, {col_count} columns, "
            f"{size_kb:.1f} KB). Use the read_csv tool to access its content."
        ),
        extra={
            "rows": str(row_count),
            "columns": str(col_count),
            "size_kb": f"{size_kb:.1f}",
        },
    )

    return PreprocessResult(
        ok=True,
        parts=[block],
        file_id=file_id,
        name=name,
        media_type=media_type,
        kind=KIND_TEXT,
        warnings=warnings,
    )


def _preprocess_text(
    name: str,
    data: bytes,
    media_type: str,
    *,
    file_store: Optional[SessionFileStore] = None,
) -> PreprocessResult:
    """Inline a text/code file into the prompt as a `<file>` block.

    Text files do NOT go through SessionFileStore — their content is
    model-visible text and doesn't benefit from binary storage. The
    returned content part wraps the file in `<file name="..." type="...">`
    tags so non-vision models can still consume it alongside the user's
    prompt text.

    Exception: Large CSV files (>= 50 KB) are routed to `_preprocess_csv`
    for lazy loading via SessionFileStore and tool-based access.
    """
    # Large CSV files get lazy-loaded to avoid eating context window.
    if _is_csv_file(name, media_type) and len(data) >= _CSV_LAZY_THRESHOLD:
        return _preprocess_csv(
            name, data, media_type, file_store=file_store,
        )

    text = _decode_text(data)
    block = {
        "type": "text",
        "text": (
            f'<file name="{name}" type="{media_type}">\n'
            f"{text}\n"
            f"</file>"
        ),
    }
    return PreprocessResult(
        ok=True,
        parts=[block],
        name=name,
        media_type=media_type,
        kind=KIND_TEXT,
    )


def _preprocess_pdf(
    name: str,
    data: bytes,
    media_type: str,
    *,
    file_store: Optional[SessionFileStore],
) -> PreprocessResult:
    """Persist a PDF and emit a text reference with page metadata.

    PDFs are NOT inlined — instead the model sees a marker indicating
    the file is available via tool calls. Phase 2.8 adds ReadPdfTool
    and GetPdfPageImageTool which resolve the file_id back to bytes
    through `file_store.get(file_id)`.

    Without pypdf installed, page count is unknown; we still persist
    the file and emit a reference so the preprocessing pipeline stays
    functional on minimal installs.
    """
    warnings: List[str] = []

    file_id = ""
    if file_store is not None:
        try:
            meta = file_store.save(name, data, media_type=media_type)
            file_id = meta.file_id
            name = meta.name
        except OSError as exc:
            return PreprocessResult(
                ok=False,
                name=name,
                media_type=media_type,
                kind=KIND_PDF,
                error=f"file_store.save failed: {exc}",
            )
    else:
        warnings.append(
            "No SessionFileStore wired — PDF will be unreachable to tools"
        )

    page_count = _count_pdf_pages(data)
    if page_count is None:
        warnings.append(
            "PDF page count unknown (pypdf not installed or file malformed). "
            "Install with: pip install 'ppxai[data]'"
        )
        page_info = "unknown page count"
    else:
        page_info = f"{page_count} page{'s' if page_count != 1 else ''}"

    size_kb = len(data) / 1024
    # R5 (v1.17.6): first-class uploaded_file block; flattened to
    # legacy text marker by provider adapters at API time.
    block = make_uploaded_file_block(
        name=name,
        media_type="application/pdf",
        file_id=file_id,
        summary=(
            f"PDF attached: {name} ({page_info}, {size_kb:.1f} KB). "
            f"Use the read_pdf or get_pdf_page_image tools to access its content."
        ),
        extra={
            "pages": str(page_count if page_count is not None else 0),
            "size_kb": f"{size_kb:.1f}",
        },
    )

    return PreprocessResult(
        ok=True,
        parts=[block],
        file_id=file_id,
        name=name,
        media_type=media_type,
        kind=KIND_PDF,
        warnings=warnings,
    )


def _preprocess_office(
    name: str,
    data: bytes,
    media_type: str,
    *,
    file_store: Optional[SessionFileStore],
) -> PreprocessResult:
    """Persist an Office document and emit a text reference.

    Excel (.xlsx), PowerPoint (.pptx), and Word (.docx) documents are
    handled the same way as PDFs — persist to store, emit a reference
    the model can route to Phase 4 tools. Phase 2.2 does NOT extract
    content; it just stages the file so downstream tools can read it.
    """
    if file_store is None:
        return PreprocessResult(
            ok=False,
            name=name,
            media_type=media_type,
            kind=KIND_OFFICE,
            error=(
                "Office document attachments require a SessionFileStore "
                "(pass file_store=engine.file_store)"
            ),
        )

    try:
        meta = file_store.save(name, data, media_type=media_type)
    except OSError as exc:
        return PreprocessResult(
            ok=False,
            name=name,
            media_type=media_type,
            kind=KIND_OFFICE,
            error=f"file_store.save failed: {exc}",
        )

    size_kb = len(data) / 1024
    doc_type = _office_friendly_name(media_type, name)

    # Provide type-specific tool hints
    lower_name = name.lower()
    if lower_name.endswith((".docx", ".doc")) or "wordprocessing" in media_type:
        tool_hint = "Use the read_docx tool to access its text content."
    elif lower_name.endswith((".xlsx", ".xls")) or "spreadsheet" in media_type or "excel" in media_type:
        tool_hint = "Use list_excel_sheets and read_excel_sheet tools to access its content."
    elif lower_name.endswith((".pptx", ".ppt")) or "presentation" in media_type:
        tool_hint = "Use list_pptx_slides, read_pptx_slide_text, or summarize_pptx_visual tools to access its content."
    else:
        tool_hint = "Use the appropriate extraction tools to access its content."

    # R5 (v1.17.6): first-class uploaded_file block; flattened to
    # legacy text marker by provider adapters at API time.
    block = make_uploaded_file_block(
        name=meta.name,
        media_type=media_type,
        file_id=meta.file_id,
        summary=(
            f"{doc_type} attached: {meta.name} ({size_kb:.1f} KB). {tool_hint}"
        ),
        extra={"size_kb": f"{size_kb:.1f}"},
    )

    return PreprocessResult(
        ok=True,
        parts=[block],
        file_id=meta.file_id,
        name=meta.name,
        media_type=media_type,
        kind=KIND_OFFICE,
    )


def _office_friendly_name(media_type: str, name: str) -> str:
    """Human-readable document type for the reference block."""
    if "spreadsheet" in media_type or name.lower().endswith((".xlsx", ".xls")):
        return "Excel spreadsheet"
    if "presentation" in media_type or name.lower().endswith((".pptx", ".ppt")):
        return "PowerPoint presentation"
    if "wordprocessing" in media_type or name.lower().endswith((".docx", ".doc")):
        return "Word document"
    return "Office document"


# =============================================================================
# Public entry point
# =============================================================================


def preprocess_file(
    name: str,
    data: bytes,
    *,
    model: str = "",
    provider: Optional[str] = None,
    media_type: Optional[str] = None,
    file_store: Optional[SessionFileStore] = None,
    vl_captioner: Optional[VLCaptioner] = None,
) -> PreprocessResult:
    """Preprocess a file into OpenAI-format content parts.

    Single entry point for all file-upload flows. Callers (`/attach`,
    server chat route, bulk scripts) pass raw bytes + metadata and get
    back a `PreprocessResult` whose `parts` can be merged into a user
    message's content list.

    Args:
        name: Original filename. Only the basename is kept — directory
              components are stripped defensively.
        data: Raw file bytes.
        model: Target model ID (e.g., "gpt-5.2", "gemini-3-flash-preview").
               Used to decide whether to inline images as `image_url`
               or route through the VL sidecar. Empty string means
               "no routing decision" — images will always go through
               the placeholder fallback unless `vl_captioner` is
               provided.
        provider: Provider name for per-provider image size limits
                  ("openai", "gemini", "perplexity", ...). Optional;
                  omitted providers fall back to the conservative
                  10 MB default.
        media_type: Declared MIME type from the caller. Used as a
                    hint — magic-byte sniffing overrides it for
                    images. Falls back to `mimetypes.guess_type(name)`
                    when not provided.
        file_store: SessionFileStore instance for persisting binary
                    content. Pass `engine.file_store` from an
                    EngineClient, or None for tests / text-only
                    callers. When None, PDFs and Office docs cannot
                    be persisted (returns ok=False error); images
                    continue to work but without file_id references.
        vl_captioner: Optional callable `(name, media_type, data) -> str`
                      used to caption images for text-only models.
                      Phase 2.7 wires `engine.caption_image` here.
                      When None and the model is text-only, image
                      attachments become text placeholders.

    Returns:
        PreprocessResult with ok=True + populated parts on success,
        or ok=False + error on validation/persistence failure.
    """
    name = _sanitize_name(name)
    canonical_mt, kind = _classify_file(name, data, media_type)

    # CSV special-case: on Windows `mimetypes.guess_type("x.csv")` returns
    # `application/vnd.ms-excel` (Excel is the default registered app),
    # which classifies as KIND_OFFICE and routes to the binary-office
    # path requiring a SessionFileStore. CSV is a text format with its
    # own lazy-loading path (`_preprocess_text` → `_preprocess_csv` for
    # files >= _CSV_LAZY_THRESHOLD), so force-route it there regardless
    # of platform classification.
    if _is_csv_file(name, canonical_mt):
        return _preprocess_text(name, data, "text/csv", file_store=file_store)

    if kind == KIND_IMAGE:
        return _preprocess_image(
            name,
            data,
            canonical_mt,
            model=model,
            provider=provider,
            file_store=file_store,
            vl_captioner=vl_captioner,
        )

    if kind == KIND_TEXT:
        return _preprocess_text(name, data, canonical_mt, file_store=file_store)

    if kind == KIND_PDF:
        return _preprocess_pdf(
            name,
            data,
            canonical_mt,
            file_store=file_store,
        )

    if kind == KIND_OFFICE:
        return _preprocess_office(
            name,
            data,
            canonical_mt,
            file_store=file_store,
        )

    # KIND_OTHER — unsupported / unknown format.
    return PreprocessResult(
        ok=False,
        name=name,
        media_type=canonical_mt,
        kind=KIND_OTHER,
        error=(
            f"Unsupported file type: {canonical_mt}. "
            f"Accepted: images (PNG/JPEG/WEBP/GIF), text/code, PDF, "
            f"Excel/PowerPoint/Word documents."
        ),
    )


__all__ = [
    "PreprocessResult",
    "VLCaptioner",
    "preprocess_file",
]
