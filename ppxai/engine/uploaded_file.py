"""
Shared helpers for the `<uploaded_file>` marker convention used to
represent non-image file attachments (PDFs, Office docs, large CSVs)
inside `text` content blocks.

The marker format is an XML-ish tag with required attributes
`name`, `type`, `file_id` and an arbitrary set of optional attributes
(`pages`, `rows`, `columns`, `size_kb`, ...), followed by a
human-readable body, followed by a closing tag. Example:

    <uploaded_file name="report.pdf" type="application/pdf"
                   file_id="sha256:abc" pages="12" size_kb="520.3">
    PDF attached: report.pdf (12 pages, 520.3 KB). Use the read_pdf
    or get_pdf_page_image tools to access its content.
    </uploaded_file>

This module is the **single source of truth** for generating and
parsing these markers. Before v1.17.4 the regex and f-string lived
inline at four call sites; drift between them caused the `/attach
remove` parity bug (tracker handled the marker, remover didn't).
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional


# Required attributes. Order-independent in the regex so callers that
# emit them in different orders still round-trip (we emit in one fixed
# order but the parser doesn't rely on that).
_ATTR_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')

# Matches the whole marker from opening `<uploaded_file` through its
# closing `</uploaded_file>` (non-greedy body). The parser re-extracts
# attributes from the opening tag with _ATTR_RE, which is more robust
# than a fixed-position capture group when optional attrs vary.
UPLOADED_FILE_RE = re.compile(
    r'<uploaded_file\s+([^>]*)>'  # opening tag with its attrs
    r'(.*?)'                       # body (non-greedy)
    r'</uploaded_file>',
    re.DOTALL,
)


def format_uploaded_file_reference(
    *,
    name: str,
    media_type: str,
    file_id: str,
    body: str,
    extra_attrs: Optional[Dict[str, str]] = None,
) -> str:
    """Build a canonical `<uploaded_file>` marker string.

    Args:
        name: Display name (basename, as shown to user + model).
        media_type: MIME type, e.g. "application/pdf".
        file_id: Content-addressed identifier from SessionFileStore.
                 MUST be non-empty — callers that don't have one yet
                 should save to the store first. An empty file_id
                 triggers the name-based identity bugs tracked in R7.
        body: Human-readable text that follows the opening tag.
              Typically a short sentence naming the file and hinting
              at the tool(s) to use.
        extra_attrs: Optional additional attributes (e.g. "pages",
                     "rows", "columns", "size_kb"). Values are always
                     quoted as strings; coerce upstream if needed.

    Returns:
        Full marker string including the closing tag.
    """
    attrs = [
        f'name="{name}"',
        f'type="{media_type}"',
        f'file_id="{file_id}"',
    ]
    if extra_attrs:
        for k, v in extra_attrs.items():
            attrs.append(f'{k}="{v}"')
    return f'<uploaded_file {" ".join(attrs)}>\n{body}\n</uploaded_file>'


def parse_uploaded_file_markers(text: str) -> List[Dict[str, str]]:
    """Extract every `<uploaded_file>` marker from `text`.

    Returns a list (preserving order) of dicts with at least the
    required keys `name`, `type`, `file_id` plus any optional
    attributes that were present on the marker.

    Missing required attributes are returned as empty strings so
    the caller can decide how to handle malformed markers (log a
    warning, skip, etc.) without the parser raising.
    """
    results: List[Dict[str, str]] = []
    for match in UPLOADED_FILE_RE.finditer(text):
        attr_blob = match.group(1)
        attrs = dict(_ATTR_RE.findall(attr_blob))
        # Normalize — callers rely on these three keys always existing.
        attrs.setdefault("name", "")
        attrs.setdefault("type", "")
        attrs.setdefault("file_id", "")
        results.append(attrs)
    return results


def strip_uploaded_file_marker(
    text: str,
    *,
    name: Optional[str] = None,
    file_id: Optional[str] = None,
) -> tuple[str, int]:
    """Remove matching `<uploaded_file>` markers from `text`.

    Matching rules (evaluated in this order for each marker):
      * if `file_id` is given and non-empty → match markers whose
        `file_id` attribute equals it exactly
      * else if `name` is given and non-empty → match markers whose
        `name` attribute equals it exactly

    If both are None or empty the function is a no-op.

    Args:
        text: Source text, typically the `text` field of a content block.
        name: Display-name selector.
        file_id: file_id selector (preferred — unambiguous).

    Returns:
        A tuple of (new_text, removed_count). The caller should drop
        the containing text block entirely if the result is empty or
        whitespace-only.
    """
    if not text:
        return text, 0
    if not (name or file_id):
        return text, 0

    removed = 0

    def _match(m: re.Match) -> str:
        nonlocal removed
        attrs = dict(_ATTR_RE.findall(m.group(1)))
        if file_id and attrs.get("file_id") == file_id:
            removed += 1
            return ""
        if name and attrs.get("name") == name and not file_id:
            removed += 1
            return ""
        return m.group(0)

    new_text = UPLOADED_FILE_RE.sub(_match, text)
    return new_text, removed
