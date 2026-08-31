"""
Data format detection for ppxai.

Detects file formats from extension and content sniffing.
Supports CSV, TSV, JSON, YAML, TOML, HCL formats.

v1.13.8: Initial implementation
"""

import json
import re
from pathlib import Path

# Extension to format mapping
EXTENSION_MAP = {
    # Tabular data
    ".csv": "csv",
    ".tsv": "tsv",
    ".tab": "tsv",
    # Structured data
    ".json": "json",
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".hcl": "hcl",
    ".tf": "hcl",
    ".tfvars": "hcl",
}

TABULAR_FORMATS = {"csv", "tsv"}
STRUCTURED_FORMATS = {"json", "jsonl", "yaml", "toml", "hcl"}
ALL_DATA_FORMATS = TABULAR_FORMATS | STRUCTURED_FORMATS

# Delimiter detection patterns
DELIMITER_CANDIDATES = [",", "\t", ";", "|"]


def detect_format(
    filepath: str,
    content: str | None = None,
    auto_detect: bool = True,
) -> str | None:
    """
    Detect data format from file path and optionally content.

    Args:
        filepath: Path to the file
        content: Optional file content for sniffing
        auto_detect: If True, attempt content sniffing for ambiguous cases

    Returns:
        Format string ('csv', 'tsv', 'json', 'yaml', 'toml', 'hcl') or None
    """
    path = Path(filepath)
    ext = path.suffix.lower()

    # First try extension mapping
    if ext in EXTENSION_MAP:
        return EXTENSION_MAP[ext]

    # Content sniffing for unknown extensions
    if content and auto_detect:
        return _sniff_format(content)

    return None


def detect_delimiter(content: str) -> str:
    """
    Auto-detect CSV delimiter from content.

    Analyzes first few lines to determine most likely delimiter.

    Args:
        content: File content to analyze

    Returns:
        Detected delimiter character (default: ',')
    """
    lines = content.split("\n")[:10]  # Check first 10 lines
    if not lines:
        return ","

    # Count occurrences of each delimiter candidate
    delimiter_scores = {}

    for delim in DELIMITER_CANDIDATES:
        counts = [line.count(delim) for line in lines if line.strip()]
        if not counts:
            continue

        # Score based on consistency and count
        # Good delimiter: consistent count across lines, reasonable count
        if len(set(counts)) == 1 and counts[0] > 0:
            # Perfect consistency - high score
            delimiter_scores[delim] = counts[0] * 10
        elif counts:
            # Some consistency - lower score based on variance
            avg = sum(counts) / len(counts)
            variance = sum((c - avg) ** 2 for c in counts) / len(counts)
            if variance < avg:  # Low variance relative to mean
                delimiter_scores[delim] = avg * (1 / (1 + variance))

    if delimiter_scores:
        return max(delimiter_scores, key=delimiter_scores.get)

    return ","


def is_data_format(filepath: str) -> bool:
    """
    Check if file is a recognized data format.

    Args:
        filepath: Path to check

    Returns:
        True if file extension maps to a data format
    """
    ext = Path(filepath).suffix.lower()
    return ext in EXTENSION_MAP


def _sniff_format(content: str) -> str | None:
    """
    Attempt to detect format from content.

    Args:
        content: File content to analyze

    Returns:
        Detected format or None
    """
    content = content.strip()
    if not content:
        return None

    # JSON detection - starts with { or [
    if content.startswith(("{", "[")):
        try:
            json.loads(content)
            return "json"
        except (json.JSONDecodeError, ValueError):
            pass

    # JSONL detection - multiple JSON objects per line
    if _looks_like_jsonl(content):
        return "jsonl"

    # YAML detection - has YAML markers or structure
    if _looks_like_yaml(content):
        return "yaml"

    # TOML detection - has [section] headers and key = value
    if _looks_like_toml(content):
        return "toml"

    # HCL detection - has resource/variable blocks
    if _looks_like_hcl(content):
        return "hcl"

    # CSV/TSV detection - tabular structure
    if _looks_like_csv(content):
        delim = detect_delimiter(content)
        return "tsv" if delim == "\t" else "csv"

    return None


def _looks_like_jsonl(content: str) -> bool:
    """Check if content looks like JSON Lines format."""
    lines = [l for l in content.split("\n") if l.strip()]
    if len(lines) < 2:
        return False

    # Each line should be valid JSON object/array
    try:
        for line in lines[:5]:  # Check first 5 lines
            obj = json.loads(line)
            if not isinstance(obj, (dict, list)):
                return False
        return True
    except (json.JSONDecodeError, ValueError):
        return False


def _looks_like_yaml(content: str) -> bool:
    """Check if content looks like YAML."""
    # YAML document markers
    if content.startswith("---") or "\n---\n" in content:
        return True

    # Key: value patterns (not JSON, not TOML)
    lines = content.split("\n")[:20]
    yaml_patterns = 0

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # YAML-style key: value (not key = value, not {})
        if re.match(r"^[\w_-]+:\s*.+", line) and "=" not in line[:20]:
            yaml_patterns += 1
        # List items
        elif line.startswith("- "):
            yaml_patterns += 1

    return yaml_patterns >= 2


def _looks_like_toml(content: str) -> bool:
    """Check if content looks like TOML."""
    lines = content.split("\n")[:30]
    has_section = False
    has_key_value = False

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # [section] or [section.subsection]
        if re.match(r"^\[[\w.-]+\]$", line):
            has_section = True
        # key = value (TOML style)
        elif re.match(r'^[\w_-]+\s*=\s*.+', line):
            has_key_value = True

    return has_section and has_key_value


def _looks_like_hcl(content: str) -> bool:
    """Check if content looks like HCL/Terraform."""
    # HCL patterns
    hcl_keywords = [
        r'\bresource\s+"',
        r'\bvariable\s+"',
        r'\bmodule\s+"',
        r'\bprovider\s+"',
        r'\boutput\s+"',
        r'\bdata\s+"',
        r'\blocals\s*\{',
        r'\bterraform\s*\{',
    ]

    for pattern in hcl_keywords:
        if re.search(pattern, content):
            return True

    return False


def _looks_like_csv(content: str) -> bool:
    """Check if content looks like CSV/TSV."""
    lines = [l for l in content.split("\n") if l.strip()]
    if len(lines) < 2:
        return False

    # Check for consistent delimiter usage
    delim = detect_delimiter(content)
    counts = [line.count(delim) for line in lines[:10]]

    # Should have consistent column count
    if len(set(counts)) <= 2 and counts[0] > 0:
        return True

    return False
