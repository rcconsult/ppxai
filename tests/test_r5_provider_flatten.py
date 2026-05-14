"""R5 Stage 2 — provider adapters flatten uploaded_file blocks before API call.

The LLM-facing invariant: after R5 the engine emits structured
`{"type": "uploaded_file", ...}` blocks internally, but no provider
supports unknown block types. Each provider's message-conversion path
must call `flatten_uploaded_file_blocks` so the SDK sees the same
legacy text marker it saw pre-R5.

Covers:
  - base.BaseProvider._convert_messages (used by openai_compat,
    openai_native chat-completions path, perplexity)
  - gemini.GeminiProvider._content_to_gemini_parts (Gemini overrides
    the whole conversion chain)
  - openai_native.OpenAINativeProvider._convert_messages_for_responses
    (Responses API path for codex / pro models)

Each test builds a Message whose content contains a structured
uploaded_file block, runs it through the provider's conversion, and
asserts the resulting API payload carries the legacy text marker —
byte-identical to what pre-R5 producers emitted.
"""

from unittest.mock import MagicMock, patch

import pytest

from ppxai.engine.types import Message
from ppxai.engine.uploaded_file import (
    flatten_uploaded_file_blocks,
    format_uploaded_file_reference,
    make_uploaded_file_block,
)


def _pdf_block():
    """Canonical PDF uploaded_file block used in assertions below."""
    return make_uploaded_file_block(
        name="report.pdf",
        media_type="application/pdf",
        file_id="sha256:abc",
        summary="PDF attached: report.pdf (12 pages). Use read_pdf.",
        extra={"pages": "12", "size_kb": "520.3"},
    )


def _expected_marker():
    return format_uploaded_file_reference(
        name="report.pdf",
        media_type="application/pdf",
        file_id="sha256:abc",
        body="PDF attached: report.pdf (12 pages). Use read_pdf.",
        extra_attrs={"pages": "12", "size_kb": "520.3"},
    )


class TestBaseProviderFlatten:
    """base.BaseProvider._convert_messages covers openai_compat, openai_native
    (chat path), perplexity — any provider that doesn't override.
    """

    def test_uploaded_file_block_becomes_text_marker(self):
        from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider

        with patch("ppxai.engine.providers.base.OpenAI"):
            provider = OpenAICompatibleProvider(
                api_key="test", base_url="http://localhost:8000/v1",
            )

        messages = [
            Message(role="user", content=[
                {"type": "text", "text": "Summarize this:"},
                _pdf_block(),
            ]),
        ]
        api_messages = provider._convert_messages(messages)
        # The content list the API sees: text + text (no uploaded_file type)
        content = api_messages[0]["content"]
        assert isinstance(content, list)
        assert [b["type"] for b in content] == ["text", "text"]
        assert content[0]["text"] == "Summarize this:"
        assert content[1]["text"] == _expected_marker()

    def test_string_content_untouched(self):
        """Plain string messages must not be forced into list shape."""
        from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider

        with patch("ppxai.engine.providers.base.OpenAI"):
            provider = OpenAICompatibleProvider(
                api_key="test", base_url="http://localhost:8000/v1",
            )

        messages = [Message(role="user", content="hello")]
        api_messages = provider._convert_messages(messages)
        assert api_messages[0]["content"] == "hello"

    def test_content_without_uploaded_file_is_identity(self):
        """Messages with no uploaded_file blocks must not be rewritten."""
        from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider

        with patch("ppxai.engine.providers.base.OpenAI"):
            provider = OpenAICompatibleProvider(
                api_key="test", base_url="http://localhost:8000/v1",
            )

        original = [
            {"type": "text", "text": "hi"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}},
        ]
        messages = [Message(role="user", content=original)]
        api_messages = provider._convert_messages(messages)
        # flatten_uploaded_file_blocks returns the same list object when
        # no uploaded_file is present — identity preserved so the hot path
        # avoids re-allocation.
        assert api_messages[0]["content"] is original


class TestGeminiFlatten:
    """Gemini overrides the whole conversion chain — verify its parts
    converter still flattens uploaded_file before walking blocks.
    """

    def test_uploaded_file_becomes_text_part(self):
        from ppxai.engine.providers.gemini import GeminiProvider

        with patch("ppxai.engine.providers.gemini.genai") as mock_genai:
            mock_genai.Client.return_value = MagicMock()
            provider = GeminiProvider(api_key="test")

        parts = provider._content_to_gemini_parts([
            {"type": "text", "text": "Here:"},
            _pdf_block(),
        ])
        # Gemini emits {"text": ...} parts — both user prose AND the
        # flattened marker are text, so we get exactly 2 parts.
        assert len(parts) == 2
        assert parts[0] == {"text": "Here:"}
        assert parts[1] == {"text": _expected_marker()}

    def test_gemini_parts_still_handle_images(self):
        """Flatten must not disturb image_url → inline_data conversion."""
        from ppxai.engine.providers.gemini import GeminiProvider

        with patch("ppxai.engine.providers.gemini.genai") as mock_genai:
            mock_genai.Client.return_value = MagicMock()
            provider = GeminiProvider(api_key="test")

        parts = provider._content_to_gemini_parts([
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUFB"}},
            _pdf_block(),
        ])
        assert len(parts) == 2
        assert parts[0] == {"inline_data": {"mime_type": "image/png", "data": "QUFB"}}
        assert parts[1] == {"text": _expected_marker()}


class TestOpenAINativeResponsesFlatten:
    """openai_native Responses API path (codex / pro models) has its own
    converter — verify it also flattens.
    """

    def test_user_message_flattened(self):
        from ppxai.engine.providers.openai_native import OpenAINativeProvider

        with patch("ppxai.engine.providers.openai_native.OpenAI"):
            OpenAINativeProvider(api_key="test")

        messages = [
            Message(role="user", content=[
                {"type": "text", "text": "Check this doc:"},
                _pdf_block(),
            ]),
        ]
        _instructions, input_items = (
            OpenAINativeProvider._convert_messages_for_responses(messages)
        )
        content = input_items[0]["content"]
        assert isinstance(content, list)
        assert [b["type"] for b in content] == ["text", "text"]
        assert content[0]["text"] == "Check this doc:"
        assert content[1]["text"] == _expected_marker()

    def test_tool_message_flattened(self):
        """Tool messages carry content too — must flatten there."""
        from ppxai.engine.providers.openai_native import OpenAINativeProvider

        messages = [
            Message(role="tool", content=[_pdf_block()], tool_call_id="call_1"),
        ]
        _instructions, input_items = (
            OpenAINativeProvider._convert_messages_for_responses(messages)
        )
        content = input_items[0]["content"]
        assert content[0]["type"] == "text"
        assert content[0]["text"] == _expected_marker()


class TestTextContentRendersNewType:
    """Message.text_content must render the new block as [File: name (media_type)]
    so logs, token estimates, and markdown exports stay human-readable.
    """

    def test_uploaded_file_block_in_text_content(self):
        m = Message(role="user", content=[
            {"type": "text", "text": "Read this:"},
            _pdf_block(),
        ])
        rendered = m.text_content()
        assert "Read this:" in rendered
        assert "[File: report.pdf (application/pdf)]" in rendered

    def test_uploaded_file_without_media_type(self):
        m = Message(role="user", content=[
            make_uploaded_file_block(
                name="thing", media_type="", file_id="x", summary="",
            ),
        ])
        assert m.text_content() == "[File: thing]"


class TestTextContentReadsAttachmentRef:
    """ADR 0006 Phase 2a: Message.text_content's image_url branch reads
    the filename from Message.attachments (via block_index) instead of
    from the in-block `name` key. Pins the new code path so a future
    refactor doesn't silently regress to the legacy in-block read.
    """

    def test_image_url_uses_attachment_ref_name_when_present(self):
        """In-block name and AttachmentRef.name deliberately differ —
           reader must trust the AttachmentRef. Phase 3 will drop the
           in-block name entirely; until then it must be IGNORED when
           AttachmentRef is present."""
        from ppxai.engine.types import AttachmentRef
        m = Message(
            role="user",
            content=[
                {"type": "text", "text": "look:"},
                {"type": "image_url", "name": "stale-in-block-name.png",
                 "image_url": {"url": "data:image/png;base64,X"}},
            ],
            attachments=[
                AttachmentRef(block_index=1, name="authoritative.png",
                              file_id="sha256:abc", media_type="image/png"),
            ],
        )
        rendered = m.text_content()
        assert "[Image: authoritative.png]" in rendered
        assert "stale-in-block-name.png" not in rendered

    def test_image_url_falls_back_to_in_block_name_when_no_ref(self):
        """Pre-Phase-1 messages have empty attachments. Reader falls
           back to in-block `name` so legacy fixtures + manual API
           callers keep working."""
        m = Message(
            role="user",
            content=[
                {"type": "image_url", "name": "legacy.png",
                 "image_url": {"url": "data:image/png;base64,X"}},
            ],
        )
        rendered = m.text_content()
        assert "[Image: legacy.png]" in rendered

    def test_image_url_falls_back_to_url_when_no_ref_no_name(self):
        """Final fallback chain: no AttachmentRef, no in-block name →
           parse the URL. Behavior preserved from pre-Phase-2a."""
        m = Message(
            role="user",
            content=[
                {"type": "image_url",
                 "image_url": {"url": "https://example.com/path/foo.png"}},
            ],
        )
        rendered = m.text_content()
        assert "[Image: foo.png]" in rendered
