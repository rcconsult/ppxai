"""Tests for PPTX slide rendering and visual summary tools.

Tests the LibreOffice-based rendering pipeline and the VL sidecar
batch captioning tool added in v1.17.4.
"""

import base64
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine(file_store=None, has_vl=False, caption_result="A slide"):
    """Create a mock engine for tool tests."""
    engine = MagicMock()
    engine.file_store = file_store
    engine.get_working_dir.return_value = "/workspace"
    engine.set_working_dir = MagicMock()
    engine.request_file_edit_consent = AsyncMock(return_value=True)
    engine.has_vision_model.return_value = has_vl
    engine.caption_image.return_value = caption_result
    return engine


def _make_file_store_with_pptx(tmp_path):
    """Create a mock file store with a minimal PPTX-like file."""
    store = MagicMock()
    pptx_dir = tmp_path / "uploads" / "test_pptx_id"
    pptx_dir.mkdir(parents=True)
    pptx_path = pptx_dir / "test.pptx"
    # We can't create a real PPTX without python-pptx, so we just
    # create a placeholder. Tests that call LibreOffice are skipped.
    pptx_path.write_bytes(b"PK\x03\x04fake-pptx-content")

    meta = MagicMock()
    meta.path = pptx_path
    meta.name = "test.pptx"
    meta.media_type = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    meta.file_id = "test_pptx_id"

    store.get_metadata.return_value = meta
    return store, meta


# ---------------------------------------------------------------------------
# render_pptx_slides
# ---------------------------------------------------------------------------

class TestRenderPptxSlides:
    """Tests for the render_pptx_slides helper function."""

    def test_returns_cached_pngs_if_present(self, tmp_path):
        """If the cache directory already has slide-*.png files, return them."""
        from ppxai.engine.tools.builtin.pptx_tools import render_pptx_slides

        cache_dir = tmp_path / "slides"
        cache_dir.mkdir()
        (cache_dir / "slide-01.png").write_bytes(b"PNG1")
        (cache_dir / "slide-02.png").write_bytes(b"PNG2")

        result = render_pptx_slides(tmp_path / "dummy.pptx", cache_dir)
        assert len(result) == 2
        assert result[0].name == "slide-01.png"
        assert result[1].name == "slide-02.png"

    def test_empty_cache_dir_not_created_yet(self, tmp_path):
        """If cache_dir doesn't exist and LibreOffice fails, return empty."""
        from ppxai.engine.tools.builtin.pptx_tools import render_pptx_slides

        cache_dir = tmp_path / "slides"

        with patch("ppxai.engine.tools.builtin.pptx_tools.subprocess") as mock_sub:
            mock_sub.run.return_value = MagicMock(returncode=1)
            result = render_pptx_slides(tmp_path / "dummy.pptx", cache_dir)

        # No PNGs produced
        assert result == []


# ---------------------------------------------------------------------------
# RenderPptxSlideTool
# ---------------------------------------------------------------------------

class TestRenderPptxSlideTool:
    """Tests for the RenderPptxSlideTool."""

    def test_tool_metadata(self):
        from ppxai.engine.tools.builtin.pptx_tools import RenderPptxSlideTool

        engine = _make_engine()
        tool = RenderPptxSlideTool(engine)
        assert tool.name == "render_pptx_slide"
        assert "file_id" in tool.parameters["properties"]
        assert "slide" in tool.parameters["properties"]

    @pytest.mark.asyncio
    async def test_missing_libreoffice(self):
        from ppxai.engine.tools.builtin.pptx_tools import RenderPptxSlideTool

        engine = _make_engine()
        tool = RenderPptxSlideTool(engine)

        with patch("ppxai.engine.tools.builtin.pptx_tools._libreoffice_available", return_value=False):
            result = await tool.execute(file_id="abc")
        assert "not installed" in result.lower()

    @pytest.mark.asyncio
    async def test_unknown_file_id(self, tmp_path):
        from ppxai.engine.tools.builtin.pptx_tools import RenderPptxSlideTool

        store = MagicMock()
        store.get_metadata.return_value = None
        engine = _make_engine(file_store=store)
        tool = RenderPptxSlideTool(engine)

        with patch("ppxai.engine.tools.builtin.pptx_tools._libreoffice_available", return_value=True):
            result = await tool.execute(file_id="nonexistent")
        assert "unknown" in result.lower() or "error" in result.lower()

    @pytest.mark.asyncio
    async def test_slide_out_of_range(self, tmp_path):
        from ppxai.engine.tools.builtin.pptx_tools import RenderPptxSlideTool

        store, meta = _make_file_store_with_pptx(tmp_path)
        engine = _make_engine(file_store=store)
        tool = RenderPptxSlideTool(engine)

        # Mock render to return 3 PNGs
        cache_dir = meta.path.parent / "slides"
        cache_dir.mkdir(parents=True)
        for i in range(1, 4):
            (cache_dir / f"slide-0{i}.png").write_bytes(b"PNG")

        with patch("ppxai.engine.tools.builtin.pptx_tools._libreoffice_available", return_value=True):
            result = await tool.execute(file_id="test_pptx_id", slide=10)
        assert "out of range" in result.lower()

    @pytest.mark.asyncio
    async def test_successful_render(self, tmp_path):
        from ppxai.engine.tools.builtin.pptx_tools import RenderPptxSlideTool

        store, meta = _make_file_store_with_pptx(tmp_path)
        engine = _make_engine(file_store=store)
        tool = RenderPptxSlideTool(engine)

        # Pre-populate cache
        cache_dir = meta.path.parent / "slides"
        cache_dir.mkdir(parents=True)
        png_data = b"\x89PNG\r\n\x1a\nfake-png-data"
        (cache_dir / "slide-01.png").write_bytes(png_data)

        with patch("ppxai.engine.tools.builtin.pptx_tools._libreoffice_available", return_value=True):
            result = await tool.execute(file_id="test_pptx_id", slide=1)

        assert result.startswith("data:image/png;base64,")
        decoded = base64.b64decode(result.split(",", 1)[1])
        assert decoded == png_data


# ---------------------------------------------------------------------------
# SummarizePptxVisualTool
# ---------------------------------------------------------------------------

class TestSummarizePptxVisualTool:
    """Tests for the VL-based visual summary tool."""

    def test_tool_metadata(self):
        from ppxai.engine.tools.builtin.pptx_tools import SummarizePptxVisualTool

        engine = _make_engine(has_vl=True)
        tool = SummarizePptxVisualTool(engine)
        assert tool.name == "summarize_pptx_visual"
        assert "file_id" in tool.parameters["properties"]
        assert "slides" in tool.parameters["properties"]

    @pytest.mark.asyncio
    async def test_unknown_file_id(self):
        from ppxai.engine.tools.builtin.pptx_tools import SummarizePptxVisualTool

        store = MagicMock()
        store.get_metadata.return_value = None
        engine = _make_engine(file_store=store, has_vl=True)
        tool = SummarizePptxVisualTool(engine)

        result = await tool.execute(file_id="nonexistent")
        assert "error" in result.lower()

    @pytest.mark.asyncio
    async def test_successful_visual_summary(self, tmp_path):
        from ppxai.engine.tools.builtin.pptx_tools import SummarizePptxVisualTool

        store, meta = _make_file_store_with_pptx(tmp_path)
        engine = _make_engine(file_store=store, has_vl=True, caption_result="Title slide with logo")
        tool = SummarizePptxVisualTool(engine)

        # Pre-populate cache with 3 slides
        cache_dir = meta.path.parent / "slides"
        cache_dir.mkdir(parents=True)
        for i in range(1, 4):
            (cache_dir / f"slide-0{i}.png").write_bytes(b"\x89PNGfake")

        with patch("ppxai.engine.tools.builtin.pptx_tools.render_pptx_slides") as mock_render:
            mock_render.return_value = sorted(cache_dir.glob("slide-*.png"))
            result = await tool.execute(file_id="test_pptx_id", slides="all")

        assert "Visual Summary" in result
        assert "Slide 1" in result
        assert "Slide 2" in result
        assert "Slide 3" in result
        assert "Title slide with logo" in result
        assert engine.caption_image.call_count == 3

    @pytest.mark.asyncio
    async def test_slide_range_selection(self, tmp_path):
        from ppxai.engine.tools.builtin.pptx_tools import SummarizePptxVisualTool

        store, meta = _make_file_store_with_pptx(tmp_path)
        engine = _make_engine(file_store=store, has_vl=True, caption_result="Content")
        tool = SummarizePptxVisualTool(engine)

        cache_dir = meta.path.parent / "slides"
        cache_dir.mkdir(parents=True)
        for i in range(1, 6):
            (cache_dir / f"slide-0{i}.png").write_bytes(b"\x89PNGfake")

        with patch("ppxai.engine.tools.builtin.pptx_tools.render_pptx_slides") as mock_render:
            mock_render.return_value = sorted(cache_dir.glob("slide-*.png"))
            result = await tool.execute(file_id="test_pptx_id", slides="1-3")

        # Only slides 1-3 should be captioned
        assert engine.caption_image.call_count == 3
        assert "Slide 1" in result
        assert "Slide 3" in result
        assert "Slide 4" not in result

    @pytest.mark.asyncio
    async def test_vl_returns_empty_caption(self, tmp_path):
        from ppxai.engine.tools.builtin.pptx_tools import SummarizePptxVisualTool

        store, meta = _make_file_store_with_pptx(tmp_path)
        engine = _make_engine(file_store=store, has_vl=True, caption_result="")
        tool = SummarizePptxVisualTool(engine)

        cache_dir = meta.path.parent / "slides"
        cache_dir.mkdir(parents=True)
        (cache_dir / "slide-01.png").write_bytes(b"\x89PNGfake")

        with patch("ppxai.engine.tools.builtin.pptx_tools.render_pptx_slides") as mock_render:
            mock_render.return_value = sorted(cache_dir.glob("slide-*.png"))
            result = await tool.execute(file_id="test_pptx_id", slides="all")

        assert "no description" in result.lower()


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

class TestPptxToolRegistration:
    """Tests for conditional tool registration."""

    @pytest.fixture(autouse=True)
    def _mock_pptx_import(self):
        """Mock the pptx import so register_tools succeeds without python-pptx."""
        with patch.dict("sys.modules", {"pptx": MagicMock()}):
            yield

    def test_registers_base_tools_without_libreoffice(self):
        from ppxai.engine.tools.builtin.pptx_tools import register_tools

        manager = MagicMock()
        engine = _make_engine()

        with patch("ppxai.engine.tools.builtin.pptx_tools._libreoffice_available", return_value=False):
            result = register_tools(manager, engine)

        assert result is True
        # Only ListPptxSlidesTool and ReadPptxSlideTextTool
        assert manager.register_tool.call_count == 2

    def test_registers_render_tool_with_libreoffice(self):
        from ppxai.engine.tools.builtin.pptx_tools import register_tools

        manager = MagicMock()
        engine = _make_engine(has_vl=False)

        with patch("ppxai.engine.tools.builtin.pptx_tools._libreoffice_available", return_value=True):
            result = register_tools(manager, engine)

        assert result is True
        # ListPptxSlidesTool + ReadPptxSlideTextTool + RenderPptxSlideTool
        assert manager.register_tool.call_count == 3

    def test_registers_visual_summary_with_libreoffice_and_vl(self):
        from ppxai.engine.tools.builtin.pptx_tools import register_tools

        manager = MagicMock()
        engine = _make_engine(has_vl=True)

        with patch("ppxai.engine.tools.builtin.pptx_tools._libreoffice_available", return_value=True):
            result = register_tools(manager, engine)

        assert result is True
        # All 4: List + ReadText + Render + SummarizeVisual
        assert manager.register_tool.call_count == 4
