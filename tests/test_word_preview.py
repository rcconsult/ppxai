"""Tests for Word document preview endpoint.

v1.17.4: Word documents (.docx/.doc) are converted to PDF via
LibreOffice headless and served through the /files/preview endpoint.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestIsWordDocument:
    def test_docx_mime(self):
        from ppxai.server.routes.file_serve import is_word_document
        meta = MagicMock()
        meta.media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        meta.name = "report.docx"
        assert is_word_document(meta) is True

    def test_doc_mime(self):
        from ppxai.server.routes.file_serve import is_word_document
        meta = MagicMock()
        meta.media_type = "application/msword"
        meta.name = "report.doc"
        assert is_word_document(meta) is True

    def test_docx_extension_fallback(self):
        from ppxai.server.routes.file_serve import is_word_document
        meta = MagicMock()
        meta.media_type = "application/octet-stream"
        meta.name = "report.docx"
        assert is_word_document(meta) is True

    def test_not_word(self):
        from ppxai.server.routes.file_serve import is_word_document
        meta = MagicMock()
        meta.media_type = "application/pdf"
        meta.name = "report.pdf"
        assert is_word_document(meta) is False

    def test_pptx_not_word(self):
        from ppxai.server.routes.file_serve import is_word_document
        meta = MagicMock()
        meta.media_type = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        meta.name = "slides.pptx"
        assert is_word_document(meta) is False


class TestConvertDocxToPdf:
    def test_returns_cached_pdf(self, tmp_path):
        from ppxai.common.docx_to_pdf import convert_docx_to_pdf
        cache_dir = tmp_path / "preview"
        cache_dir.mkdir()
        cached = cache_dir / "preview.pdf"
        cached.write_bytes(b"%PDF-1.4 cached")

        result = convert_docx_to_pdf(tmp_path / "dummy.docx", cache_dir)
        assert result == cached
        assert result.read_bytes() == b"%PDF-1.4 cached"

    def test_raises_on_no_output(self, tmp_path):
        from ppxai.common.docx_to_pdf import convert_docx_to_pdf
        cache_dir = tmp_path / "preview"

        with patch("subprocess.run", return_value=MagicMock(returncode=1)):
            with pytest.raises(RuntimeError, match="no PDF output"):
                convert_docx_to_pdf(tmp_path / "dummy.docx", cache_dir)

    def test_successful_conversion(self, tmp_path):
        from ppxai.common.docx_to_pdf import convert_docx_to_pdf
        source = tmp_path / "test.docx"
        source.write_bytes(b"PK fake docx")
        cache_dir = tmp_path / "preview"

        def fake_libreoffice(cmd, **kwargs):
            # Simulate LibreOffice creating a PDF in the outdir
            outdir = cmd[cmd.index("--outdir") + 1]
            pdf_name = source.stem + ".pdf"
            (Path(outdir) / pdf_name).write_bytes(b"%PDF-1.4 converted")
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=fake_libreoffice) as mock_sub:
            result = convert_docx_to_pdf(source, cache_dir)

        assert result.exists()
        assert result.read_bytes() == b"%PDF-1.4 converted"
        # Second call should return cached
        result2 = convert_docx_to_pdf(source, cache_dir)
        assert result2 == result
