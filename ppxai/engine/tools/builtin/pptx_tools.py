"""
PowerPoint tools for multimodal attachments.

Phase 4.2 (v1.17.4). Two tools that let the model explore and read PPTX
files the user has attached via `/attach slides.pptx`:

    list_pptx_slides(file_id)
        → slide inventory with shape types (TEXT, TABLE, CHART, IMAGE)

    read_pptx_slide_text(file_id, slide)
        → text + tables from a specific slide as markdown

Both tools resolve `file_id` through the engine's SessionFileStore.
Guarded by `try: import pptx` (python-pptx package) at registration.

Slide rasterization (RenderPptxSlideTool via LibreOffice headless) and
embedded image extraction (ExtractPptxImagesTool) are deferred to a
follow-up step — they require system dependencies not all users have.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from ...types import ToolEngineProtocol, ToolManagerProtocol
from ..base import BaseTool


_MAX_TEXT_CHARS = 100_000


def _resolve_file(engine: Any, file_id: str) -> Tuple[Optional[Any], Optional[str]]:
    """Look up a file_id in the engine's SessionFileStore."""
    file_store = getattr(engine, "file_store", None)
    if file_store is None:
        return None, "No SessionFileStore available. PPTX tools require the file store."
    meta = file_store.get_metadata(file_id)
    if meta is None:
        return None, f"Unknown file_id: {file_id!r}. The attachment may have been removed."
    if not meta.path.exists():
        return None, f"File for {file_id!r} is missing on disk."
    return meta, None


def _is_pptx(meta: Any) -> bool:
    """Check if a file is a PowerPoint presentation."""
    if "presentation" in (meta.media_type or ""):
        return True
    name = (meta.name or "").lower()
    return name.endswith((".pptx", ".ppt"))


def _shape_type_label(shape) -> str:
    """Human-readable label for a slide shape."""
    if shape.has_table:
        return "TABLE"
    if shape.has_chart:
        return "CHART"
    if hasattr(shape, "image") and shape.shape_type == 13:  # MSO_SHAPE_TYPE.PICTURE
        return "IMAGE"
    if shape.has_text_frame:
        return "TEXT"
    return "OTHER"


class ListPptxSlidesTool(BaseTool):
    """List all slides in an attached PPTX file with shape inventories."""

    def __init__(self, engine: ToolEngineProtocol):
        self.engine = engine
        self.name = "list_pptx_slides"
        self.description = (
            "List all slides in an attached PowerPoint file. Returns slide "
            "numbers, titles (if any), and an inventory of shape types "
            "(TEXT, TABLE, CHART, IMAGE) per slide. Use this first to "
            "understand the presentation structure before reading specific "
            "slides. Pass the 'file_id' from the <uploaded_file> reference."
        )
        self.parameters = {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "The file_id from the <uploaded_file> reference.",
                },
            },
            "required": ["file_id"],
        }

    async def execute(self, file_id: str, **kwargs) -> str:
        meta, err = _resolve_file(self.engine, file_id)
        if err:
            return f"Error: {err}"
        if not _is_pptx(meta):
            return f"Error: {meta.name!r} is not a PowerPoint file (type={meta.media_type!r})."

        try:
            from pptx import Presentation
        except ImportError:
            return "Error: python-pptx not installed. Install with: pip install 'ppxai[data]'"

        try:
            prs = Presentation(str(meta.path))
        except Exception as exc:
            return f"Error opening {meta.name!r}: {exc}"

        slides = prs.slides
        total = len(slides)
        if total == 0:
            return f"{meta.name}: empty presentation (0 slides)."

        lines: List[str] = [f"# {meta.name} — {total} slide(s)\n"]

        for i, slide in enumerate(slides, 1):
            # Extract title from title placeholder if present
            title = ""
            if slide.shapes.title and slide.shapes.title.has_text_frame:
                title = slide.shapes.title.text_frame.text.strip()

            # Inventory shape types
            type_counts: dict = {}
            for shape in slide.shapes:
                label = _shape_type_label(shape)
                type_counts[label] = type_counts.get(label, 0) + 1

            shapes_str = ", ".join(
                f"{count}×{stype}" for stype, count in sorted(type_counts.items())
            ) or "(empty slide)"

            title_str = f" — {title}" if title else ""
            lines.append(
                f"## Slide {i}{title_str}\n"
                f"- Shapes: {shapes_str}\n"
            )

        return "\n".join(lines)


class ReadPptxSlideTextTool(BaseTool):
    """Read text + tables from a specific slide as markdown."""

    def __init__(self, engine: ToolEngineProtocol):
        self.engine = engine
        self.name = "read_pptx_slide_text"
        self.description = (
            "Read all text and tables from a specific slide of an attached "
            "PowerPoint file. Returns the content as markdown. Tables are "
            "rendered as markdown tables. Use list_pptx_slides first to see "
            "available slides."
        )
        self.parameters = {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "The file_id from the <uploaded_file> reference.",
                },
                "slide": {
                    "type": "integer",
                    "description": "1-indexed slide number.",
                },
            },
            "required": ["file_id", "slide"],
        }

    async def execute(self, file_id: str, slide: int = 1, **kwargs) -> str:
        meta, err = _resolve_file(self.engine, file_id)
        if err:
            return f"Error: {err}"
        if not _is_pptx(meta):
            return f"Error: {meta.name!r} is not a PowerPoint file."

        try:
            from pptx import Presentation
        except ImportError:
            return "Error: python-pptx not installed. Install with: pip install 'ppxai[data]'"

        try:
            prs = Presentation(str(meta.path))
        except Exception as exc:
            return f"Error opening {meta.name!r}: {exc}"

        total = len(prs.slides)
        try:
            slide_num = int(slide)
        except (TypeError, ValueError):
            return f"Error: slide must be an integer (got {slide!r})."

        if slide_num < 1 or slide_num > total:
            return f"Error: slide {slide_num} out of range (presentation has {total} slides)."

        target_slide = prs.slides[slide_num - 1]
        lines: List[str] = [f"# {meta.name} — Slide {slide_num} of {total}\n"]

        # Title
        if target_slide.shapes.title and target_slide.shapes.title.has_text_frame:
            title = target_slide.shapes.title.text_frame.text.strip()
            if title:
                lines.append(f"## {title}\n")

        total_chars = sum(len(line) for line in lines)

        for shape in target_slide.shapes:
            if total_chars > _MAX_TEXT_CHARS:
                lines.append(
                    f"\n[Output truncated at {_MAX_TEXT_CHARS:,} chars.]"
                )
                break

            if shape.has_table:
                table_md = _table_to_markdown(shape.table)
                lines.append(table_md + "\n")
                total_chars += len(table_md)

            elif shape.has_text_frame:
                # Skip the title shape (already rendered above)
                if (
                    target_slide.shapes.title
                    and shape.shape_id == target_slide.shapes.title.shape_id
                ):
                    continue

                text = _text_frame_to_markdown(shape.text_frame)
                if text.strip():
                    lines.append(text + "\n")
                    total_chars += len(text)

            elif shape.has_chart:
                lines.append(f"[Chart: {shape.name}]\n")
                total_chars += 30

            elif hasattr(shape, "image") and shape.shape_type == 13:
                name = shape.name or "image"
                lines.append(f"[Image: {name}]\n")
                total_chars += 30

        result = "\n".join(lines)
        if not result.strip():
            return f"Slide {slide_num}: no text content found."

        return result


def _text_frame_to_markdown(text_frame) -> str:
    """Convert a text frame's paragraphs to markdown text.

    Preserves paragraph breaks, bold/italic runs where possible,
    and bullet indicators from the paragraph level.
    """
    parts: List[str] = []
    for para in text_frame.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        # Bullet detection: level > 0 or has bullet char
        level = para.level or 0
        if level > 0:
            indent = "  " * level
            parts.append(f"{indent}- {text}")
        else:
            parts.append(text)
    return "\n".join(parts)


def _table_to_markdown(table) -> str:
    """Convert a PPTX table to a markdown table."""
    rows: List[List[str]] = []
    for row in table.rows:
        cells = []
        for cell in row.cells:
            cells.append(cell.text.strip().replace("|", "\\|"))
        rows.append(cells)

    if not rows:
        return "(empty table)"

    header = rows[0]
    lines = []
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join("---" for _ in header) + " |")

    for row in rows[1:]:
        padded = row + [""] * (len(header) - len(row))
        lines.append("| " + " | ".join(padded[:len(header)]) + " |")

    return "\n".join(lines)


# =============================================================================
# Registration
# =============================================================================


def register_tools(manager: ToolManagerProtocol, engine: ToolEngineProtocol) -> bool:
    """Register PPTX tools. Returns False if python-pptx is not installed."""
    try:
        import pptx  # noqa: F401
    except ImportError:
        return False

    if engine is None:
        return False

    manager.register_tool(ListPptxSlidesTool(engine))
    manager.register_tool(ReadPptxSlideTextTool(engine))
    return True


__all__ = [
    "ListPptxSlidesTool",
    "ReadPptxSlideTextTool",
    "register_tools",
]
