"""R5 (v1.17.6) — tests for the first-class `uploaded_file` content block.

Promotes non-image attachments (PDF, Excel, PPTX, DOCX, large CSV)
from embedded XML markers inside `text` content blocks to a dedicated
content-part type. This module covers the helpers in
`ppxai/engine/uploaded_file.py` that define the schema and the
provider-flatten bridge.

Contract summary:
  - `make_uploaded_file_block(...)` produces the canonical dict.
  - `uploaded_file_block_to_text(block)` renders it as the legacy
    `<uploaded_file ...>body</uploaded_file>` marker — so LLM-facing
    strings stay byte-identical across the R5 rollout.
  - `flatten_uploaded_file_blocks(content)` walks a content list and
    replaces every uploaded_file block with a `text` block whose text
    is the legacy marker. Provider adapters call this right before the
    API call.
"""

from ppxai.engine.uploaded_file import (
    UPLOADED_FILE_BLOCK_TYPE,
    flatten_uploaded_file_blocks,
    format_uploaded_file_reference,
    make_uploaded_file_block,
    uploaded_file_block_to_text,
)


class TestMakeUploadedFileBlock:
    """Canonical shape of the new content-part type."""

    def test_required_fields(self):
        block = make_uploaded_file_block(
            name="report.pdf",
            media_type="application/pdf",
            file_id="sha256:abc",
            summary="PDF attached: report.pdf (12 pages). Use read_pdf.",
        )
        assert block["type"] == "uploaded_file"
        assert block["name"] == "report.pdf"
        assert block["media_type"] == "application/pdf"
        assert block["file_id"] == "sha256:abc"
        assert block["summary"] == "PDF attached: report.pdf (12 pages). Use read_pdf."
        # extra is omitted when not supplied — keeps the block minimal
        assert "extra" not in block

    def test_extra_fields_stored_as_copy(self):
        extra = {"pages": "12", "size_kb": "520.3"}
        block = make_uploaded_file_block(
            name="report.pdf",
            media_type="application/pdf",
            file_id="sha256:abc",
            summary="...",
            extra=extra,
        )
        assert block["extra"] == {"pages": "12", "size_kb": "520.3"}

        # Caller's dict must not be able to mutate the block after the fact.
        extra["pages"] = "99"
        assert block["extra"]["pages"] == "12"

    def test_constant_matches_block_type(self):
        """The exported constant must match what make_* emits — clients grep it."""
        block = make_uploaded_file_block(
            name="x", media_type="y", file_id="z", summary="",
        )
        assert block["type"] == UPLOADED_FILE_BLOCK_TYPE


class TestUploadedFileBlockToText:
    """Rendering a structured block back to the legacy marker."""

    def test_round_trip_with_existing_helper(self):
        """The rendered marker must match `format_uploaded_file_reference` byte-for-byte.

        This is the invariant that makes the R5 rollout safe — the LLM
        sees the same string whether the producer emitted a legacy text
        marker or the new structured block flattened at API time.
        """
        block = make_uploaded_file_block(
            name="report.pdf",
            media_type="application/pdf",
            file_id="sha256:abc",
            summary="PDF attached: report.pdf (12 pages). Use read_pdf.",
            extra={"pages": "12", "size_kb": "520.3"},
        )
        rendered = uploaded_file_block_to_text(block)
        expected = format_uploaded_file_reference(
            name="report.pdf",
            media_type="application/pdf",
            file_id="sha256:abc",
            body="PDF attached: report.pdf (12 pages). Use read_pdf.",
            extra_attrs={"pages": "12", "size_kb": "520.3"},
        )
        assert rendered == expected

    def test_missing_fields_render_minimal_marker(self):
        """A malformed block should still produce a legal marker, not crash."""
        block = {"type": "uploaded_file"}  # no fields at all
        rendered = uploaded_file_block_to_text(block)
        assert "<uploaded_file" in rendered
        assert "</uploaded_file>" in rendered


class TestFlattenUploadedFileBlocks:
    """Provider-side flatten: structured blocks → legacy text markers."""

    def test_passes_string_content_through(self):
        assert flatten_uploaded_file_blocks("hello") == "hello"

    def test_passes_none_through(self):
        assert flatten_uploaded_file_blocks(None) is None

    def test_empty_list_returns_identity(self):
        empty = []
        result = flatten_uploaded_file_blocks(empty)
        assert result is empty  # identity preserved for no-op

    def test_list_without_uploaded_file_returns_identity(self):
        """Short-circuit: pure text+image content avoids reallocation."""
        content = [
            {"type": "text", "text": "hello"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}},
        ]
        result = flatten_uploaded_file_blocks(content)
        assert result is content  # identity — no new list allocated

    def test_flattens_single_uploaded_file_block(self):
        block = make_uploaded_file_block(
            name="report.pdf",
            media_type="application/pdf",
            file_id="sha256:abc",
            summary="PDF attached. Use read_pdf.",
            extra={"pages": "12"},
        )
        content = [
            {"type": "text", "text": "Here is the file:"},
            block,
        ]
        result = flatten_uploaded_file_blocks(content)
        assert result is not content  # new list when any block is flattened
        assert len(result) == 2
        assert result[0] == {"type": "text", "text": "Here is the file:"}
        assert result[1]["type"] == "text"
        assert "<uploaded_file" in result[1]["text"]
        assert "report.pdf" in result[1]["text"]
        assert 'file_id="sha256:abc"' in result[1]["text"]
        assert 'pages="12"' in result[1]["text"]

    def test_flattens_multiple_uploaded_file_blocks(self):
        block1 = make_uploaded_file_block(
            name="a.pdf", media_type="application/pdf",
            file_id="id1", summary="A",
        )
        block2 = make_uploaded_file_block(
            name="b.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            file_id="id2", summary="B",
        )
        content = [block1, {"type": "text", "text": "between"}, block2]
        result = flatten_uploaded_file_blocks(content)

        assert len(result) == 3
        # Each uploaded_file block flattened independently; the text
        # block between them is preserved exactly.
        assert result[0]["type"] == "text"
        assert "a.pdf" in result[0]["text"]
        assert result[1] == {"type": "text", "text": "between"}
        assert result[2]["type"] == "text"
        assert "b.xlsx" in result[2]["text"]

    def test_preserves_other_block_types_unchanged(self):
        """image_url / input_file / file blocks must pass through untouched."""
        image_block = {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,AAA"},
            "name": "chart.png",
        }
        uploaded_block = make_uploaded_file_block(
            name="doc.pdf", media_type="application/pdf",
            file_id="id", summary="doc",
        )
        content = [image_block, uploaded_block]
        result = flatten_uploaded_file_blocks(content)

        # Image block is exactly the same object — untouched.
        assert result[0] is image_block
        # Uploaded-file block was converted.
        assert result[1]["type"] == "text"

    def test_byte_identical_to_legacy_producer_output(self):
        """LLM-facing invariant: flattening produces exactly what a pre-R5
        producer would have emitted inline.
        """
        # What producers used to emit directly:
        legacy_text = format_uploaded_file_reference(
            name="data.csv",
            media_type="text/csv",
            file_id="sha256:deadbeef",
            body="CSV attached: data.csv (200000 rows, 5 columns, 10.2 KB). Use the read_csv tool.",
            extra_attrs={"rows": "200000", "columns": "5", "size_kb": "10.2"},
        )
        legacy_content = [{"type": "text", "text": legacy_text}]

        # What R5 producers emit + what the flatten produces at API time:
        new_block = make_uploaded_file_block(
            name="data.csv",
            media_type="text/csv",
            file_id="sha256:deadbeef",
            summary="CSV attached: data.csv (200000 rows, 5 columns, 10.2 KB). Use the read_csv tool.",
            extra={"rows": "200000", "columns": "5", "size_kb": "10.2"},
        )
        flattened_content = flatten_uploaded_file_blocks([new_block])

        assert flattened_content == legacy_content
