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
from typing import Any, Dict, List, Optional


# R5 (v1.17.6): first-class content-part type for uploaded files.
#
# Previously non-image attachments (PDF, Excel, PPTX, DOCX, large CSV)
# lived as `<uploaded_file>` XML markers *inside* `{"type": "text"}`
# content blocks. Consumers had to regex-parse every text block to find
# attachments, and clients rendered the raw XML if they didn't know to
# strip it. The structured type below carries the same data as a
# dedicated block so consumers dispatch on `block["type"]` and clients
# render a badge from the fields.
#
# Provider adapters flatten this block back to the legacy text-marker
# shape via `flatten_uploaded_file_blocks()` before the API call — the
# LLM keeps seeing the exact same string it saw before, so model
# behavior and token counts don't drift as this rollout completes.
UPLOADED_FILE_BLOCK_TYPE = "uploaded_file"


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


# ---------------------------------------------------------------------------
# R5 — structured `uploaded_file` content block helpers
# ---------------------------------------------------------------------------


def make_uploaded_file_block(
    *,
    name: str,
    media_type: str,
    file_id: str,
    summary: str,
    extra: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Build a canonical `uploaded_file` content block (R5).

    Dedicated content-part type that replaces the legacy
    `<uploaded_file>` XML marker embedded in a text block. Consumers
    (`refresh_context_attachments`, `remove_context_attachment`) iterate
    on `block["type"]` instead of regex-parsing; clients render
    structured badges from the fields.

    The `extra` dict is always stringified values so the block
    round-trips cleanly through JSON session serialization without
    type ambiguity. Callers that have numeric values (page count, row
    count, size in KB) must coerce to `str` before passing.

    Providers never see this type directly — `flatten_uploaded_file_blocks`
    converts every uploaded_file block back to the legacy text marker
    via `format_uploaded_file_reference` before the API call, so model
    behavior and token counts stay identical to pre-R5.
    """
    block: Dict[str, Any] = {
        "type": UPLOADED_FILE_BLOCK_TYPE,
        "name": name,
        "media_type": media_type,
        "file_id": file_id,
        "summary": summary,
    }
    if extra:
        # Defensive copy so a caller's dict can't mutate the block later.
        block["extra"] = dict(extra)
    return block


def uploaded_file_block_to_text(block: Dict[str, Any]) -> str:
    """Render a structured uploaded_file block as its legacy text marker.

    Used by the provider-adapter flatten (so LLM-facing strings stay
    byte-identical across the R5 rollout) and by tests that assert
    the text representation hasn't drifted.

    Falls back to a minimal marker if the block is missing required
    keys — a malformed block shouldn't break the provider call, just
    produce a less-informative marker.
    """
    return format_uploaded_file_reference(
        name=block.get("name", ""),
        media_type=block.get("media_type", ""),
        file_id=block.get("file_id", ""),
        body=block.get("summary", ""),
        extra_attrs=block.get("extra") or None,
    )


# =============================================================================
# Wire-format validator (ADR 0006 Step 6 — defensive sentinel)
# =============================================================================
#
# OpenAI-style content blocks have a documented spec; engine-internal
# producers historically jammed extra metadata inside (e.g. `name` and
# `file_id` on `image_url` blocks for ppxai's bookkeeping). Real OpenAI
# silently ignores the extra keys; strict OpenAI-compat endpoints
# (corporate gateways, NIM, vLLM with strict validators) reject the
# whole request with `Invalid chat format. Unexpected keys in a message
# content image dict.`
#
# The validator below catches non-spec keys at the wire boundary —
# specifically inside `BaseProvider._convert_messages`, after
# `flatten_uploaded_file_blocks` has already converted engine-internal
# block types to text markers. It is `__debug__`-gated: tests + dev
# builds get a loud assertion failure naming the offending block;
# production builds compiled with `python -O` strip the assertion
# entirely, so production never pays the walk cost.
#
# This is a SENTINEL, not a runtime fix. Producers MUST emit spec-clean
# blocks; the validator just guarantees no producer-side regression
# slips through. ADR 0006 Steps 1-3 + 7 do the producer-side cleanup.

# Per OpenAI Chat Completions spec (https://platform.openai.com/docs/api-reference/chat/create).
# Keys allowed at the top level of each content block, by block `type`.
# Anything outside these is non-spec and the validator flags it.
_WIRE_ALLOWED_BLOCK_KEYS: Dict[str, frozenset] = {
    "text": frozenset({"type", "text"}),
    # image_url's inner dict accepts {url, detail} per spec; the validator
    # checks the OUTER block keys only — inner dict shape is provider-
    # specific (Gemini parses it differently anyway).
    "image_url": frozenset({"type", "image_url"}),
    # Audio (preview API) — OpenAI gpt-4o-audio-preview shape.
    "input_audio": frozenset({"type", "input_audio"}),
    # File attachments (OpenAI Assistants-style file references).
    "file": frozenset({"type", "file"}),
    # Engine-internal types that should NEVER reach the wire because
    # `flatten_uploaded_file_blocks` converts them to text first. Listed
    # here as `frozenset()` (empty) so the validator flags them LOUDLY
    # if the flatten step was somehow skipped — a real bug indicator.
    "uploaded_file": frozenset(),
}


def assert_wire_blocks_clean(content: Any, *, role: str = "?") -> None:
    """Assert every content block matches the OpenAI wire-format spec.

    ADR 0006 Step 6 defensive sentinel. Called from
    `BaseProvider._convert_messages` AFTER `flatten_uploaded_file_blocks`
    so engine-internal types have already been converted. Any remaining
    non-spec keys indicate a producer bug — typically a Phase 7
    regression where someone re-introduced `name` or `file_id` inside
    an `image_url` block.

    `__debug__`-gated: production builds with `python -O` strip the
    `assert`, so this has zero runtime cost in production. Tests and
    dev builds (the default) get a loud assertion failure naming the
    block, the role, and the offending key.

    Pure read-only — never mutates `content`. Safe to call from
    multiple threads (no shared state). Identity-preserved (returns
    None — caller already has the content).

    Identity-preserving on the data: `content` itself is not modified.
    Identity-preserving on absence: non-list content (string, None)
    short-circuits without walking — pure-text messages cost nothing.

    Args:
        content: The Message.content value about to be sent on the wire.
            String content and non-list content are no-ops.
        role: Optional message role for richer error messages
            ("user", "assistant", "tool", "system"). Helps diagnose
            which producer site is the culprit.

    Raises:
        AssertionError (only under __debug__): when a content block has
            keys outside the spec for its `type`. Message names the
            block index, the role, the type, and the offending keys.
    """
    if not __debug__:
        return  # pragma: no cover — production builds skip the call entirely
    if not isinstance(content, list):
        return
    for idx, block in enumerate(content):
        if not isinstance(block, dict):
            # Non-dict blocks (None, strings, etc.) are themselves a
            # producer bug, but flagging them here would be noise — a
            # later provider call will fail with a more specific error.
            continue
        btype = block.get("type")
        allowed = _WIRE_ALLOWED_BLOCK_KEYS.get(btype)
        if allowed is None:
            # Unknown block type. Could be a future-spec block (audio
            # variant we haven't catalogued) or a producer bug. The
            # validator's job is to catch ppxai-internal pollution,
            # not to police every block type — pass through.
            continue
        actual = set(block.keys())
        extra = actual - allowed
        if extra:
            # Sort the extra-keys list for deterministic message output —
            # set iteration order would make test failures non-reproducible.
            extras_sorted = sorted(extra)
            assert False, (
                f"ADR 0006 wire-format violation: message[role={role!r}] "
                f"content block #{idx} (type={btype!r}) carries non-spec "
                f"keys {extras_sorted}. Allowed keys for this type: "
                f"{sorted(allowed)}. Producer must emit spec-clean blocks; "
                f"engine-internal metadata belongs in Message.attachments. "
                f"See docs/decisions/0006-content-block-schema-separation.md."
            )


def flatten_uploaded_file_blocks(content: Any) -> Any:
    """Convert every uploaded_file block in `content` to a text block.

    Walks a multimodal content list; any block whose `type` equals
    `"uploaded_file"` is replaced by `{"type": "text", "text": <marker>}`
    where `<marker>` is produced by `uploaded_file_block_to_text`.
    Other block types (text, image_url, file, input_file) and non-list
    content pass through unchanged.

    Provider adapters call this on each message's content before shaping
    the API request. Because the flatten uses the same
    `format_uploaded_file_reference` helper the producers used pre-R5,
    the LLM sees byte-identical strings — so model behavior and token
    accounting are unchanged by the wire-format switch.

    Returns a new list when any flattening occurred; returns the input
    unchanged (identity-preserved) when no uploaded_file blocks are
    present, so the common case avoids allocation.
    """
    if not isinstance(content, list):
        return content

    # Short-circuit: no flattening needed → return original list.
    if not any(
        isinstance(b, dict) and b.get("type") == UPLOADED_FILE_BLOCK_TYPE
        for b in content
    ):
        return content

    result: List[Any] = []
    for block in content:
        if (
            isinstance(block, dict)
            and block.get("type") == UPLOADED_FILE_BLOCK_TYPE
        ):
            result.append({
                "type": "text",
                "text": uploaded_file_block_to_text(block),
            })
        else:
            result.append(block)
    return result
