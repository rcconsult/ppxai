"""
Tests for the ppxai data visualization module (v1.13.8).

Tests format detection, parsing, and data structures.
"""

from pathlib import Path

# Test fixtures directory
FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestFormatDetector:
    """Tests for format_detector module."""

    def test_detect_format_csv(self):
        """Test CSV format detection from extension."""
        from ppxai.data import detect_format

        assert detect_format("data.csv") == "csv"
        assert detect_format("path/to/file.CSV") == "csv"

    def test_detect_format_tsv(self):
        """Test TSV format detection from extension."""
        from ppxai.data import detect_format

        assert detect_format("data.tsv") == "tsv"
        assert detect_format("data.tab") == "tsv"

    def test_detect_format_json(self):
        """Test JSON format detection from extension."""
        from ppxai.data import detect_format

        assert detect_format("config.json") == "json"
        assert detect_format("data.jsonl") == "jsonl"

    def test_detect_format_yaml(self):
        """Test YAML format detection from extension."""
        from ppxai.data import detect_format

        assert detect_format("config.yaml") == "yaml"
        assert detect_format("config.yml") == "yaml"

    def test_detect_format_toml(self):
        """Test TOML format detection from extension."""
        from ppxai.data import detect_format

        assert detect_format("pyproject.toml") == "toml"

    def test_detect_format_hcl(self):
        """Test HCL/Terraform format detection from extension."""
        from ppxai.data import detect_format

        assert detect_format("main.hcl") == "hcl"
        assert detect_format("main.tf") == "hcl"
        assert detect_format("variables.tfvars") == "hcl"

    def test_detect_format_unknown(self):
        """Test unknown format returns None."""
        from ppxai.data import detect_format

        assert detect_format("script.py") is None
        assert detect_format("readme.md") is None

    def test_detect_delimiter_comma(self):
        """Test comma delimiter detection."""
        from ppxai.data import detect_delimiter

        content = "a,b,c\n1,2,3\n4,5,6"
        assert detect_delimiter(content) == ","

    def test_detect_delimiter_tab(self):
        """Test tab delimiter detection."""
        from ppxai.data import detect_delimiter

        content = "a\tb\tc\n1\t2\t3\n4\t5\t6"
        assert detect_delimiter(content) == "\t"

    def test_detect_delimiter_semicolon(self):
        """Test semicolon delimiter detection."""
        from ppxai.data import detect_delimiter

        content = "a;b;c\n1;2;3\n4;5;6"
        assert detect_delimiter(content) == ";"

    def test_is_data_format(self):
        """Test is_data_format helper."""
        from ppxai.data import is_data_format

        assert is_data_format("data.csv") is True
        assert is_data_format("config.json") is True
        assert is_data_format("script.py") is False


class TestParsers:
    """Tests for parsers module."""

    def test_parse_csv_basic(self):
        """Test basic CSV parsing."""
        from ppxai.data import parse_csv

        content = "name,age\nAlice,25\nBob,30"
        data = parse_csv(content)

        assert data.headers == ["name", "age"]
        assert len(data.rows) == 2
        assert data.rows[0] == ["Alice", "25"]
        assert data.rows[1] == ["Bob", "30"]
        assert data.row_count == 2
        assert data.column_count == 2

    def test_parse_csv_with_delimiter(self):
        """Test CSV parsing with custom delimiter."""
        from ppxai.data import parse_csv

        content = "name\tage\nAlice\t25"
        data = parse_csv(content, delimiter="\t")

        assert data.headers == ["name", "age"]
        assert data.rows[0] == ["Alice", "25"]

    def test_parse_csv_max_rows(self):
        """Test CSV parsing respects max_rows limit."""
        from ppxai.data import parse_csv

        lines = ["a,b"] + [f"{i},{i*2}" for i in range(100)]
        content = "\n".join(lines)
        data = parse_csv(content, max_rows=10)

        assert len(data.rows) == 10
        assert data.truncated is True

    def test_parse_csv_fixture(self):
        """Test parsing sample.csv fixture."""
        from ppxai.data import parse_csv

        csv_file = FIXTURES_DIR / "sample.csv"
        if csv_file.exists():
            content = csv_file.read_text(encoding="utf-8")
            data = parse_csv(content)

            assert "name" in data.headers
            assert "age" in data.headers
            assert data.row_count > 0

    def test_parse_json_basic(self):
        """Test basic JSON parsing."""
        from ppxai.data import parse_json

        content = '{"name": "test", "value": 42}'
        tree = parse_json(content)

        assert tree.key == "root"
        assert tree.node_type == "object"
        assert len(tree.children) == 2

    def test_parse_json_nested(self):
        """Test nested JSON parsing."""
        from ppxai.data import parse_json

        content = '{"outer": {"inner": {"deep": true}}}'
        tree = parse_json(content)

        assert tree.node_type == "object"
        assert tree.children[0].key == "outer"
        assert tree.children[0].node_type == "object"

    def test_parse_json_array(self):
        """Test JSON array parsing."""
        from ppxai.data import parse_json

        content = '[1, 2, 3]'
        tree = parse_json(content)

        assert tree.node_type == "array"
        assert len(tree.children) == 3
        assert tree.children[0].value == 1

    def test_parse_json_fixture(self):
        """Test parsing sample.json fixture."""
        from ppxai.data import parse_json

        json_file = FIXTURES_DIR / "sample.json"
        if json_file.exists():
            content = json_file.read_text(encoding="utf-8")
            tree = parse_json(content)

            assert tree.node_type == "object"
            # Check for expected keys
            keys = [child.key for child in tree.children]
            assert "name" in keys
            assert "version" in keys

    def test_tree_node_properties(self):
        """Test TreeNode properties."""
        from ppxai.data import parse_json

        content = '{"key": "value"}'
        tree = parse_json(content)

        assert tree.is_leaf is False
        assert tree.child_count == 1
        assert tree.children[0].is_leaf is True


class TestTableData:
    """Tests for TableData dataclass."""

    def test_table_data_creation(self):
        """Test TableData creation."""
        from ppxai.data import TableData

        data = TableData(
            headers=["a", "b", "c"],
            rows=[["1", "2", "3"], ["4", "5", "6"]],
        )

        assert data.row_count == 2
        assert data.column_count == 3
        assert data.truncated is False


class TestTreeNode:
    """Tests for TreeNode dataclass."""

    def test_tree_node_creation(self):
        """Test TreeNode creation."""
        from ppxai.data import TreeNode

        node = TreeNode(
            key="test",
            value="hello",
            node_type="string",
        )

        assert node.key == "test"
        assert node.value == "hello"
        assert node.node_type == "string"
        assert node.is_leaf is True
        assert node.child_count == 0

    def test_tree_node_with_children(self):
        """Test TreeNode with children."""
        from ppxai.data import TreeNode

        child = TreeNode(key="child", value=1, node_type="number")
        parent = TreeNode(
            key="parent",
            node_type="object",
            children=[child],
        )

        assert parent.is_leaf is False
        assert parent.child_count == 1


class TestExtensionMapping:
    """Tests for extension mapping constants."""

    def test_extension_map_completeness(self):
        """Test EXTENSION_MAP has expected extensions."""
        from ppxai.data import EXTENSION_MAP

        expected = [".csv", ".tsv", ".json", ".yaml", ".yml", ".toml", ".hcl", ".tf"]
        for ext in expected:
            assert ext in EXTENSION_MAP, f"Missing extension: {ext}"

    def test_format_sets(self):
        """Test TABULAR_FORMATS and STRUCTURED_FORMATS."""
        from ppxai.data import STRUCTURED_FORMATS, TABULAR_FORMATS

        assert "csv" in TABULAR_FORMATS
        assert "tsv" in TABULAR_FORMATS
        assert "json" in STRUCTURED_FORMATS
        assert "yaml" in STRUCTURED_FORMATS
        assert "toml" in STRUCTURED_FORMATS
        assert "hcl" in STRUCTURED_FORMATS
