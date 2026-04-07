"""Tests for CSV lazy-loading tools and preprocessing threshold.

v1.17.4: Large CSVs (>50KB) are stored in SessionFileStore with a
reference marker. The model uses read_csv and list_csv_columns tools.
"""

import csv
import io
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_engine(file_store=None):
    engine = MagicMock()
    engine.file_store = file_store
    engine.get_working_dir.return_value = "/workspace"
    engine.set_working_dir = MagicMock()
    engine.request_file_edit_consent = AsyncMock(return_value=True)
    return engine


def _make_csv_store(tmp_path, name="data.csv", content=None, rows=10, cols=3):
    """Create a mock file store with a CSV file."""
    store = MagicMock()
    csv_dir = tmp_path / "uploads" / "csv_file_id"
    csv_dir.mkdir(parents=True)
    csv_path = csv_dir / name

    if content is None:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([f"col{i}" for i in range(cols)])
        for r in range(rows):
            writer.writerow([f"val_{r}_{c}" for c in range(cols)])
        content = buf.getvalue()

    csv_path.write_text(content)

    meta = MagicMock()
    meta.path = csv_path
    meta.name = name
    meta.media_type = "text/csv"
    meta.file_id = "csv_file_id"
    meta.size = csv_path.stat().st_size

    store.get_metadata.return_value = meta
    return store, meta


class TestReadCsvTool:
    def test_tool_metadata(self):
        from ppxai.engine.tools.builtin.csv_tools import ReadCsvTool
        tool = ReadCsvTool(_make_engine())
        assert tool.name == "read_csv"
        assert "file_id" in tool.parameters["properties"]
        assert "rows" in tool.parameters["properties"]

    @pytest.mark.asyncio
    async def test_unknown_file_id(self):
        from ppxai.engine.tools.builtin.csv_tools import ReadCsvTool
        store = MagicMock()
        store.get_metadata.return_value = None
        tool = ReadCsvTool(_make_engine(file_store=store))
        result = await tool.execute(file_id="nonexistent")
        assert "error" in result.lower()

    @pytest.mark.asyncio
    async def test_read_default_rows(self, tmp_path):
        from ppxai.engine.tools.builtin.csv_tools import ReadCsvTool
        store, _ = _make_csv_store(tmp_path, rows=5, cols=3)
        tool = ReadCsvTool(_make_engine(file_store=store))
        result = await tool.execute(file_id="csv_file_id")
        # Should contain header and all 5 rows as markdown table
        assert "col0" in result
        assert "col1" in result
        assert "val_0_0" in result
        assert "val_4_2" in result

    @pytest.mark.asyncio
    async def test_read_row_range(self, tmp_path):
        from ppxai.engine.tools.builtin.csv_tools import ReadCsvTool
        store, _ = _make_csv_store(tmp_path, rows=20, cols=2)
        tool = ReadCsvTool(_make_engine(file_store=store))
        result = await tool.execute(file_id="csv_file_id", rows="5-10")
        assert "val_4_0" in result  # row 5 (0-indexed row 4)
        assert "val_9_0" in result  # row 10
        assert "val_0_0" not in result  # row 1 excluded
        assert "val_10_0" not in result  # row 11 excluded

    @pytest.mark.asyncio
    async def test_read_csv_format(self, tmp_path):
        from ppxai.engine.tools.builtin.csv_tools import ReadCsvTool
        store, _ = _make_csv_store(tmp_path, rows=3, cols=2)
        tool = ReadCsvTool(_make_engine(file_store=store))
        result = await tool.execute(file_id="csv_file_id", format="csv")
        # CSV format should not have markdown table pipes
        assert "|" not in result
        assert "col0" in result

    @pytest.mark.asyncio
    async def test_column_filter(self, tmp_path):
        from ppxai.engine.tools.builtin.csv_tools import ReadCsvTool
        store, _ = _make_csv_store(tmp_path, rows=3, cols=4)
        tool = ReadCsvTool(_make_engine(file_store=store))
        result = await tool.execute(file_id="csv_file_id", columns="col0,col2")
        assert "col0" in result
        assert "col2" in result
        # col1 and col3 should be filtered out
        assert "col1" not in result
        assert "col3" not in result


class TestListCsvColumnsTool:
    def test_tool_metadata(self):
        from ppxai.engine.tools.builtin.csv_tools import ListCsvColumnsTool
        tool = ListCsvColumnsTool(_make_engine())
        assert tool.name == "list_csv_columns"

    @pytest.mark.asyncio
    async def test_list_columns(self, tmp_path):
        from ppxai.engine.tools.builtin.csv_tools import ListCsvColumnsTool
        store, _ = _make_csv_store(tmp_path, rows=5, cols=3)
        tool = ListCsvColumnsTool(_make_engine(file_store=store))
        result = await tool.execute(file_id="csv_file_id")
        assert "col0" in result
        assert "col1" in result
        assert "col2" in result
        assert "5" in result  # row count


class TestCsvPreprocessing:
    """Test the CSV lazy-loading threshold in file_preprocessing."""

    def test_small_csv_inlines(self):
        from ppxai.engine.file_preprocessing import preprocess_file
        # Small CSV (< 50KB) should inline as text
        small_csv = b"a,b,c\n1,2,3\n4,5,6\n"
        result = preprocess_file("small.csv", small_csv, media_type="text/csv")
        assert result.ok
        # Should be a text part, not an uploaded_file reference
        assert any(p.get("type") == "text" for p in result.parts)
        text = result.parts[0].get("text", "")
        assert "a,b,c" in text  # content is inlined
        assert "<uploaded_file" not in text

    def test_large_csv_lazy_loads(self, tmp_path):
        from ppxai.engine.file_preprocessing import preprocess_file
        from ppxai.engine.session_store import SessionFileStore

        store = SessionFileStore(base_dir=tmp_path / "uploads")

        # Create a CSV larger than 50KB
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["name", "value", "category"])
        for i in range(3000):
            writer.writerow([f"item_{i}", str(i * 1.5), f"cat_{i % 10}"])
        large_csv = buf.getvalue().encode()
        assert len(large_csv) > 50 * 1024  # verify it's > 50KB

        result = preprocess_file(
            "large.csv", large_csv,
            media_type="text/csv",
            file_store=store,
        )
        assert result.ok
        text = result.parts[0].get("text", "")
        assert "<uploaded_file" in text
        assert 'type="text/csv"' in text
        assert "read_csv" in text

    def test_csv_detection_by_extension(self):
        from ppxai.engine.file_preprocessing import preprocess_file
        # .csv extension with no media_type hint
        small_csv = b"x,y\n1,2\n"
        result = preprocess_file("report.csv", small_csv)
        assert result.ok


class TestCsvToolRegistration:
    def test_registers_both_tools(self):
        from ppxai.engine.tools.builtin.csv_tools import register_tools
        manager = MagicMock()
        engine = _make_engine()
        register_tools(manager, engine)
        assert manager.register_tool.call_count == 2
        names = [call.args[0].name for call in manager.register_tool.call_args_list]
        assert "read_csv" in names
        assert "list_csv_columns" in names
