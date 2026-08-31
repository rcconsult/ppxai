"""Tests for the file preprocessing dispatcher (Phase 2.2, v1.17.4).

Exercises every routing branch of `preprocess_file`:

    Image (vision model)       → image_url data URI content part
    Image (text-only, no VL)   → [Image: name — vision not supported] placeholder
    Image (text-only, VL)      → [Image: name — <caption>] with captioner output
    Text / code file           → <file name="…"> inlined text block
    PDF                        → <uploaded_file …> reference + persisted bytes
    Office (xlsx/pptx/docx)    → <uploaded_file …> reference + persisted bytes
    Image validation failures  → ok=False with specific error reason
    Unknown format             → ok=False with "Unsupported file type"

Plus invariants:
    - SessionFileStore integration produces stable file_ids
    - Magic-byte sniffing overrides a mislabeled declared media type
    - Defensive filename sanitization (path traversal)
    - Provider-aware size limits propagate from validation
    - Warnings are collected but don't block ok=True results
    - pypdf optional dependency — PDF still works without it, warns
"""

from __future__ import annotations

import base64
import struct

import pytest

from ppxai.engine.file_preprocessing import (
    preprocess_file,
)
from ppxai.engine.session_store import (
    KIND_IMAGE,
    KIND_OFFICE,
    KIND_OTHER,
    KIND_PDF,
    KIND_TEXT,
    SessionFileStore,
)

# -----------------------------------------------------------------------------
# Test fixtures — synthesized image bytes with real headers
# -----------------------------------------------------------------------------


def _make_png(width: int = 10, height: int = 10) -> bytes:
    """Minimal valid PNG header — enough for sniff + dimension extraction."""
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr_payload = struct.pack(
        ">IIBBBBB", width, height, 8, 2, 0, 0, 0
    )
    ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_payload + b"\x00\x00\x00\x00"
    return signature + ihdr


def _make_jpeg(width: int = 10, height: int = 10) -> bytes:
    soi = b"\xff\xd8"
    sof_payload = struct.pack(">BHHB", 8, height, width, 3) + b"\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    sof = b"\xff\xc0" + struct.pack(">H", 2 + len(sof_payload)) + sof_payload
    return soi + sof + b"\xff\xd9"


# Real 1x1 red PNG.
_RED_PIXEL_PNG = base64.b64decode(
    b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8DwHwAFAQH/c4"
    b"X0gAAAAABJRU5ErkJggg=="
)


@pytest.fixture
def store(tmp_path) -> SessionFileStore:
    """Throwaway SessionFileStore rooted in tmp_path."""
    return SessionFileStore(base_dir=tmp_path / "uploads")


# -----------------------------------------------------------------------------
# Image routing — vision model
# -----------------------------------------------------------------------------


class TestImageVisionModel:
    def test_png_with_gpt5_emits_image_url_part(self, store):
        result = preprocess_file(
            "chart.png",
            _make_png(100, 50),
            model="gpt-5.2",
            provider="openai",
            file_store=store,
        )
        assert result.ok is True
        assert result.kind == KIND_IMAGE
        assert result.media_type == "image/png"
        assert result.file_id  # persisted
        assert len(result.parts) == 1

        block = result.parts[0]
        # ADR 0006 Step 7c (v1.18.6): image_url blocks carry ONLY the
        # OpenAI-spec keys ({type, image_url}). Engine-internal metadata
        # (name, file_id, media_type) lives on the ImageAttachmentRef
        # surfaced via result.attachment_ref + Message.attachments.
        assert block["type"] == "image_url"
        assert set(block.keys()) == {"type", "image_url"}
        # Data URI carries the same bytes back in base64.
        url = block["image_url"]["url"]
        assert url.startswith("data:image/png;base64,")
        # Engine-internal metadata available via the attachment ref.
        ref = result.attachment_ref
        assert ref is not None
        assert ref.name == "chart.png"
        assert ref.file_id == result.file_id
        assert ref.media_type == "image/png"

    def test_jpeg_with_gemini_emits_image_url_part(self, store):
        result = preprocess_file(
            "photo.jpg",
            _make_jpeg(200, 150),
            model="gemini-3-flash-preview",
            provider="gemini",
            file_store=store,
        )
        assert result.ok is True
        assert result.parts[0]["type"] == "image_url"
        assert result.media_type == "image/jpeg"

    def test_sonar_pro_is_vision_capable(self, store):
        result = preprocess_file(
            "screen.png",
            _make_png(),
            model="sonar-pro",
            provider="perplexity",
            file_store=store,
        )
        assert result.ok is True
        assert result.parts[0]["type"] == "image_url"

    def test_real_png_bytes_round_trip(self, store):
        result = preprocess_file(
            "dot.png",
            _RED_PIXEL_PNG,
            model="gpt-5",
            file_store=store,
        )
        assert result.ok is True
        # Decode the data URI and verify bytes survive base64 round-trip.
        url = result.parts[0]["image_url"]["url"]
        prefix = "data:image/png;base64,"
        assert url.startswith(prefix)
        decoded = base64.b64decode(url[len(prefix):])
        assert decoded == _RED_PIXEL_PNG

    def test_token_estimate_warning(self, store):
        result = preprocess_file(
            "big.png",
            _make_png(1024, 768),
            model="gpt-5.2",
            file_store=store,
        )
        assert result.ok is True
        # Expect a token-cost warning like "~N tokens (1024x768)".
        assert any("tokens" in w for w in result.warnings)
        assert any("1024x768" in w for w in result.warnings)


# -----------------------------------------------------------------------------
# Image routing — text-only model (no VL), placeholder fallback
# -----------------------------------------------------------------------------


class TestImageTextOnlyFailLoud:
    """When no consumption path exists (no native vision, no VL sidecar,
    no shell-CLI route), the image must FAIL LOUD — ``ok=False`` with an
    actionable error — instead of silently degrading to a text placeholder
    that invites the model to hallucinate the image contents. (Item 24.)"""

    def test_text_only_model_fails_loud(self, store):
        result = preprocess_file(
            "chart.png",
            _make_png(),
            model="sonar-reasoning-pro",  # text-only per Phase 2.5
            provider="perplexity",
            file_store=store,
        )
        assert result.ok is False
        assert not result.parts
        assert result.error
        # Names the offending model and the concrete remedies.
        assert "sonar-reasoning-pro" in result.error
        assert "vision-capable model" in result.error
        assert "VL sidecar" in result.error

    def test_no_model_provided_fails_loud(self, store):
        # Empty model = no routing decision → still can't consume the image.
        result = preprocess_file(
            "x.png",
            _make_png(),
            file_store=store,
        )
        assert result.ok is False
        assert result.error
        assert "no model is selected" in result.error

    def test_fail_loud_still_records_file_id(self, store):
        # Even when we can't send the image, the bytes should still be
        # persisted in the store so a later session (with a sidecar or a
        # shell utility) can reach them by file_id.
        result = preprocess_file(
            "x.png",
            _make_png(),
            model="o3-mini",  # text-only reasoning
            file_store=store,
        )
        assert result.ok is False
        assert result.file_id
        assert store.get(result.file_id) is not None


class TestImageShellRoute:
    """With ``shell_image_route=True`` (the active model has the shell tool
    enabled), a text-only model can still consume the image: the persisted
    on-disk path is surfaced so the model can OCR/inspect it with an
    installed CLI (ImageMagick/tesseract) rather than failing. (Item 24.)"""

    def test_shell_route_surfaces_on_disk_path(self, store):
        result = preprocess_file(
            "chart.png",
            _make_png(),
            model="sonar-reasoning-pro",  # text-only
            file_store=store,
            shell_image_route=True,
        )
        assert result.ok is True
        assert len(result.parts) == 1
        block = result.parts[0]
        assert block["type"] == "text"
        assert "chart.png" in block["text"]
        # Surfaces the real on-disk path and a concrete shell suggestion.
        meta = store.get_metadata(result.file_id)
        assert str(meta.path) in block["text"]
        assert "shell tool" in block["text"]
        assert "Do NOT" in block["text"]  # explicit "do not guess" guard

    def test_shell_route_requires_persisted_file(self, store):
        # No file_store → nothing on disk → shell route can't apply, so we
        # fall through to fail-loud rather than emitting a path-less hint.
        result = preprocess_file(
            "x.png",
            _make_png(),
            model="o3-mini",
            file_store=None,
            shell_image_route=True,
        )
        assert result.ok is False
        assert result.error


# -----------------------------------------------------------------------------
# Image routing — VL captioner fallback
# -----------------------------------------------------------------------------


class TestImageVLCaptioner:
    def test_captioner_output_becomes_text_block(self, store):
        def fake_captioner(name, media_type, data):
            return "a red dot on a white background"

        result = preprocess_file(
            "dot.png",
            _RED_PIXEL_PNG,
            model="gpt-oss-20b",  # text-only per Phase 2.5
            file_store=store,
            vl_captioner=fake_captioner,
        )
        assert result.ok is True
        assert len(result.parts) == 1
        block = result.parts[0]
        assert block["type"] == "text"
        assert "[Image: dot.png" in block["text"]
        assert "a red dot on a white background" in block["text"]

    def test_captioner_receives_canonical_args(self, store):
        captured = {}

        def capturing_captioner(name, media_type, data):
            captured["name"] = name
            captured["media_type"] = media_type
            captured["data_len"] = len(data)
            return "test caption"

        preprocess_file(
            "chart.png",
            _make_png(50, 50),
            model="gpt-oss-120b",
            file_store=store,
            vl_captioner=capturing_captioner,
        )
        assert captured["name"] == "chart.png"
        assert captured["media_type"] == "image/png"
        assert captured["data_len"] == len(_make_png(50, 50))

    def test_empty_caption_falls_through_to_fail_loud(self, store):
        def empty_captioner(name, media_type, data):
            return ""  # simulates captioner refusing / failing soft

        result = preprocess_file(
            "x.png",
            _make_png(),
            model="openai/gpt-oss-20b",
            file_store=store,
            vl_captioner=empty_captioner,
        )
        # An empty caption is not a usable result; with no shell route the
        # image now fails loud rather than degrading to a placeholder.
        assert result.ok is False
        assert result.error
        assert "VL sidecar" in result.error

    def test_empty_caption_falls_through_to_shell_route(self, store):
        def empty_captioner(name, media_type, data):
            return ""

        result = preprocess_file(
            "x.png",
            _make_png(),
            model="openai/gpt-oss-20b",
            file_store=store,
            vl_captioner=empty_captioner,
            shell_image_route=True,
        )
        # Captioner soft-failed, but the shell route can still consume it.
        assert result.ok is True
        assert "shell tool" in result.parts[0]["text"]

    def test_captioner_not_called_for_vision_model(self, store):
        calls = []

        def tracking_captioner(name, media_type, data):
            calls.append(name)
            return "should not appear"

        result = preprocess_file(
            "x.png",
            _make_png(),
            model="gpt-5.2",  # vision-capable
            file_store=store,
            vl_captioner=tracking_captioner,
        )
        assert result.ok is True
        assert result.parts[0]["type"] == "image_url"
        # Captioner should not have been invoked.
        assert calls == []


# -----------------------------------------------------------------------------
# Image validation failures
# -----------------------------------------------------------------------------


class TestImageValidationFailures:
    def test_fake_image_rejected_by_validation(self, store):
        # A file whose name says .png but whose content isn't a real image:
        # filename-based MIME detection routes it as image/png, then
        # `validate_image` rejects it because no magic bytes match.
        # The user gets a clear "Unrecognized image format" error rather
        # than a silent drop or an opaque provider API failure.
        result = preprocess_file(
            "fake.png",
            b"this is definitely not an image",
            model="gpt-5.2",
            file_store=store,
        )
        assert result.ok is False
        assert result.kind == KIND_IMAGE  # routed as image by extension
        assert "unrecognized" in result.error.lower()
        assert result.parts == []  # nothing to send

    def test_oversized_image_rejected(self, store):
        # Build a 15 MB PNG — over the 10 MB default.
        big_png = _make_png(1, 1) + b"\x00" * (15 * 1024 * 1024)
        result = preprocess_file(
            "big.png",
            big_png,
            model="gpt-5.2",
            provider="openai",
            file_store=store,
        )
        # OpenAI allows 20 MB so this should pass.
        assert result.ok is True

    def test_oversized_image_rejected_for_anthropic(self, store):
        # 10 MB PNG — over Anthropic's 5 MB cap.
        big_png = _make_png(1, 1) + b"\x00" * (10 * 1024 * 1024)
        result = preprocess_file(
            "big.png",
            big_png,
            model="gpt-5.2",
            provider="anthropic",
            file_store=store,
        )
        assert result.ok is False
        assert "exceeds" in result.error.lower()
        assert "anthropic" in result.error.lower()

    def test_rejected_image_has_no_parts(self, store):
        big_png = _make_png(1, 1) + b"\x00" * (10 * 1024 * 1024)
        result = preprocess_file(
            "big.png",
            big_png,
            model="gpt-5.2",
            provider="anthropic",
            file_store=store,
        )
        assert result.parts == []
        assert result.file_id == ""


# -----------------------------------------------------------------------------
# Text / code files
# -----------------------------------------------------------------------------


class TestTextFiles:
    def test_python_file_inlined(self):
        src = b"def greet(name):\n    return f'Hello, {name}'\n"
        result = preprocess_file("greet.py", src)
        assert result.ok is True
        assert result.kind == KIND_TEXT
        assert len(result.parts) == 1
        block = result.parts[0]
        assert block["type"] == "text"
        assert '<file name="greet.py"' in block["text"]
        assert "def greet" in block["text"]
        assert "</file>" in block["text"]

    def test_text_files_not_persisted(self, store):
        # Text goes directly into the prompt, never into the store.
        result = preprocess_file(
            "notes.md",
            b"# Heading\n\ncontent",
            file_store=store,
        )
        assert result.ok is True
        assert result.file_id == ""  # no persistence
        assert store.list_all() == []  # store untouched

    def test_invalid_utf8_uses_replacement(self):
        data = b"valid prefix \xff\xfe invalid middle \xc0\x80 end"
        result = preprocess_file("weird.txt", data)
        assert result.ok is True
        # Replacement chars should appear for invalid sequences, but no crash.
        assert "valid prefix" in result.parts[0]["text"]
        assert "end" in result.parts[0]["text"]

    def test_json_classified_as_text(self):
        result = preprocess_file("config.json", b'{"key": "value"}')
        assert result.kind == KIND_TEXT

    def test_yaml_classified_as_text(self):
        result = preprocess_file("config.yaml", b"key: value")
        assert result.kind == KIND_TEXT


# -----------------------------------------------------------------------------
# PDF files
# -----------------------------------------------------------------------------


class TestPdfFiles:
    def test_pdf_persisted_and_reference_emitted(self, store):
        # Minimal PDF stub — won't be parseable by pypdf, but the
        # preprocessor still persists it and emits a reference.
        pdf_bytes = b"%PDF-1.4\n%fake\n" + b"\x00" * 100
        result = preprocess_file(
            "doc.pdf",
            pdf_bytes,
            media_type="application/pdf",
            file_store=store,
        )
        assert result.ok is True
        assert result.kind == KIND_PDF
        assert result.file_id
        # R5 (v1.17.6): producers emit the first-class uploaded_file
        # content block. Provider adapters flatten it to the legacy
        # text marker before the API call via
        # `flatten_uploaded_file_blocks` — see test_r5_provider_flatten.py
        # for the byte-identical invariant.
        block = result.parts[0]
        assert block["type"] == "uploaded_file"
        assert block["name"] == "doc.pdf"
        assert block["media_type"] == "application/pdf"
        assert block["file_id"] == result.file_id
        assert "read_pdf" in block["summary"]
        # And the bytes are actually on disk.
        assert store.get(result.file_id).read_bytes() == pdf_bytes

    def test_pdf_warns_when_pypdf_unavailable_or_malformed(self, store):
        pdf_bytes = b"%PDF-1.4\n" + b"\x00" * 50  # too minimal for pypdf
        result = preprocess_file(
            "doc.pdf",
            pdf_bytes,
            media_type="application/pdf",
            file_store=store,
        )
        assert result.ok is True
        # One warning should reference pypdf or the extras group.
        assert any("pypdf" in w.lower() or "page count" in w.lower()
                   for w in result.warnings)

    def test_pdf_without_file_store_warns_but_succeeds(self):
        # No file_store → the PDF can't be persisted, but the dispatcher
        # emits a warning and still returns a reference block (tools
        # won't work, but the user isn't left with a silent failure).
        result = preprocess_file(
            "doc.pdf",
            b"%PDF-1.4\n",
            media_type="application/pdf",
        )
        assert result.ok is True
        assert result.file_id == ""
        assert any("SessionFileStore" in w for w in result.warnings)


# -----------------------------------------------------------------------------
# Office documents
# -----------------------------------------------------------------------------


class TestOfficeFiles:
    def test_xlsx_persisted_and_referenced(self, store):
        xlsx_bytes = b"PK\x03\x04" + b"\x00" * 1000  # ZIP magic + stub
        result = preprocess_file(
            "sheet.xlsx",
            xlsx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            file_store=store,
        )
        assert result.ok is True
        assert result.kind == KIND_OFFICE
        assert result.file_id
        # R5: structured uploaded_file block, not a text block.
        block = result.parts[0]
        assert block["type"] == "uploaded_file"
        assert block["name"] == "sheet.xlsx"
        assert block["file_id"] == result.file_id
        assert "Excel spreadsheet" in block["summary"]

    def test_pptx_persisted_and_referenced(self, store):
        pptx_bytes = b"PK\x03\x04" + b"\x00" * 500
        result = preprocess_file(
            "slides.pptx",
            pptx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            file_store=store,
        )
        assert result.ok is True
        block = result.parts[0]
        assert block["type"] == "uploaded_file"
        assert "PowerPoint presentation" in block["summary"]

    def test_docx_persisted_and_referenced(self, store):
        docx_bytes = b"PK\x03\x04" + b"\x00" * 300
        result = preprocess_file(
            "report.docx",
            docx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            file_store=store,
        )
        assert result.ok is True
        block = result.parts[0]
        assert block["type"] == "uploaded_file"
        assert "Word document" in block["summary"]

    def test_office_without_store_rejected(self):
        # Office docs REQUIRE a store — unlike PDFs which degrade with
        # a warning, office docs return ok=False because the extraction
        # tools won't work without file_id resolution.
        result = preprocess_file(
            "sheet.xlsx",
            b"PK\x03\x04" + b"\x00" * 100,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        assert result.ok is False
        assert "SessionFileStore" in result.error


# -----------------------------------------------------------------------------
# Unknown formats
# -----------------------------------------------------------------------------


class TestUnknownFormats:
    def test_unknown_binary_rejected(self, store):
        result = preprocess_file(
            "file.bin",
            b"\x00\x01\x02\x03random binary",
            file_store=store,
        )
        assert result.ok is False
        assert result.kind == KIND_OTHER
        assert "Unsupported" in result.error

    def test_archive_rejected(self, store):
        # .tar, .zip, etc. fall through as "other" — we don't extract.
        result = preprocess_file(
            "archive.tar",
            b"\x00" * 200,
            file_store=store,
        )
        assert result.ok is False
        assert "Unsupported" in result.error


# -----------------------------------------------------------------------------
# Invariants
# -----------------------------------------------------------------------------


class TestInvariants:
    def test_magic_bytes_override_mislabeled_filename(self, store):
        # PNG bytes but filename says .jpg — dispatcher must classify as PNG.
        result = preprocess_file(
            "photo.jpg",
            _make_png(10, 10),
            model="gpt-5.2",
            file_store=store,
        )
        assert result.ok is True
        assert result.media_type == "image/png"
        assert result.parts[0]["image_url"]["url"].startswith("data:image/png")

    def test_path_traversal_in_name_sanitized(self, store):
        result = preprocess_file(
            "../../etc/passwd.png",
            _make_png(),
            model="gpt-5.2",
            file_store=store,
        )
        assert result.ok is True
        # Name is just the basename — no directory components.
        assert result.name == "passwd.png"
        assert "/" not in result.name
        assert ".." not in result.name

    def test_empty_name_falls_back_to_default(self, store):
        result = preprocess_file(
            "",
            _make_png(),
            model="gpt-5.2",
            file_store=store,
        )
        assert result.ok is True
        assert result.name  # non-empty default
        assert result.name != ""

    def test_result_structure_stable_on_success(self, store):
        result = preprocess_file(
            "x.png",
            _make_png(),
            model="gpt-5.2",
            file_store=store,
        )
        # Every field has the expected type — catches accidental shape drift.
        assert isinstance(result.ok, bool)
        assert isinstance(result.parts, list)
        assert isinstance(result.file_id, str)
        assert isinstance(result.name, str)
        assert isinstance(result.media_type, str)
        assert isinstance(result.kind, str)
        assert isinstance(result.warnings, list)
        assert isinstance(result.error, str)

    def test_result_structure_stable_on_failure(self, store):
        result = preprocess_file(
            "random.bin",
            b"\x00" * 10,
            file_store=store,
        )
        assert result.ok is False
        assert result.parts == []
        assert result.file_id == ""
        assert result.error  # non-empty
