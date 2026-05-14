"""ADR 0006 Step 6 — wire-format validator (assert_wire_blocks_clean).

Pins the contract that BaseProvider._convert_messages enforces at the
wire boundary: every content block dict carries only spec-allowed
keys for its `type`. Producer-side regressions (e.g. accidentally
re-introducing `name` or `file_id` inside an image_url block) fail
LOUDLY in tests + dev builds; production builds with `python -O` skip
the assertion entirely.

Two directions tested:

1. **Clean blocks pass silently.** Spec-compliant content lists never
   raise. Identity-preserved (validator is read-only).
2. **Dirty blocks raise AssertionError with diagnostic info** —
   message names the block index, role, type, and offending keys so
   a developer hitting this in CI can find the culprit producer in
   one search.

Why these tests matter for ADR 0006: Steps 1-3 + 7 land the producer
cleanup that makes the validator a true sentinel. Until those steps
land, this validator is the GUARD that prevents the bug from
re-appearing AFTER the cleanup. If someone in v1.19.x accidentally
re-emits `image_url.name` from the agent platform's sub-agent
spawning code, this validator catches it in their test run before
the strict-endpoint user reports it again.
"""

from __future__ import annotations

import pytest

from ppxai.engine.uploaded_file import (
    _WIRE_ALLOWED_BLOCK_KEYS,
    assert_wire_blocks_clean,
)


# =============================================================================
# Direction 1 — clean blocks pass silently
# =============================================================================


class TestSpecCleanContentPassesSilently:
    def test_string_content_no_op(self):
        """Plain-text messages have no content list — short-circuit."""
        assert_wire_blocks_clean("hello world")  # no raise

    def test_none_content_no_op(self):
        """Defensive: None content (rare but possible) doesn't crash."""
        assert_wire_blocks_clean(None)

    def test_empty_list_no_op(self):
        """Empty list — nothing to walk."""
        assert_wire_blocks_clean([])

    def test_text_only_blocks_pass(self):
        content = [
            {"type": "text", "text": "first paragraph"},
            {"type": "text", "text": "second paragraph"},
        ]
        assert_wire_blocks_clean(content)

    def test_image_url_with_only_spec_keys_passes(self):
        """The shape Steps 1-3+7 will produce after the cleanup —
        image_url block carries ONLY {type, image_url}, no name/file_id."""
        content = [
            {"type": "image_url",
             "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}},
        ]
        assert_wire_blocks_clean(content)

    def test_image_url_with_detail_inside_inner_dict_passes(self):
        """The OpenAI spec allows {url, detail} INSIDE image_url's
        inner dict. The validator only checks OUTER block keys —
        inner-dict shape is provider-specific (Gemini parses it
        differently anyway)."""
        content = [
            {"type": "image_url",
             "image_url": {"url": "data:image/png;base64,X", "detail": "high"}},
        ]
        assert_wire_blocks_clean(content)

    def test_mixed_text_and_image_passes_when_clean(self):
        content = [
            {"type": "text", "text": "what does this show?"},
            {"type": "image_url",
             "image_url": {"url": "data:image/png;base64,X"}},
        ]
        assert_wire_blocks_clean(content)

    def test_unknown_block_type_passes_through(self):
        """Unknown block types (future spec additions, custom tooling)
        pass through unchanged — validator's job is to catch ppxai-internal
        pollution on KNOWN spec types, not to police every block type."""
        content = [
            {"type": "future_video", "url": "...", "duration_ms": 5000},
        ]
        assert_wire_blocks_clean(content)


# =============================================================================
# Direction 2 — dirty blocks raise with diagnostic info
# =============================================================================


class TestNonSpecBlocksRaiseLoudly:
    def test_image_url_with_name_key_fails(self):
        """The exact regression Steps 1-3+7 fix: producer emits `name`
        alongside the spec-compliant {type, image_url}. Strict
        OpenAI-compat endpoints reject the whole request — this
        validator catches it before the wire."""
        content = [
            {"type": "image_url",
             "name": "screenshot.png",
             "image_url": {"url": "data:image/png;base64,X"}},
        ]
        with pytest.raises(AssertionError) as exc_info:
            assert_wire_blocks_clean(content, role="user")
        msg = str(exc_info.value)
        # Diagnostic info: block index, role, type, offending key.
        assert "block #0" in msg
        assert "role='user'" in msg
        assert "image_url" in msg
        assert "['name']" in msg

    def test_image_url_with_file_id_key_fails(self):
        """file_id is the second offender from file_preprocessing.py."""
        content = [
            {"type": "image_url",
             "file_id": "sha256:abc123",
             "image_url": {"url": "data:image/png;base64,X"}},
        ]
        with pytest.raises(AssertionError) as exc_info:
            assert_wire_blocks_clean(content, role="user")
        assert "['file_id']" in str(exc_info.value)

    def test_image_url_with_both_name_and_file_id_fails(self):
        """Today's producer (file_preprocessing.py:264-272) emits BOTH.
        Validator must surface BOTH in the diagnostic, sorted for
        deterministic test output."""
        content = [
            {"type": "image_url",
             "name": "x.png",
             "file_id": "sha256:abc",
             "image_url": {"url": "data:image/png;base64,X"}},
        ]
        with pytest.raises(AssertionError) as exc_info:
            assert_wire_blocks_clean(content, role="user")
        msg = str(exc_info.value)
        # Sorted alphabetically for reproducibility.
        assert "['file_id', 'name']" in msg

    def test_text_block_with_extra_key_fails(self):
        """Spec for text is just {type, text}. Anything else is non-spec."""
        content = [
            {"type": "text", "text": "hi", "user_id": "alice"},
        ]
        with pytest.raises(AssertionError) as exc_info:
            assert_wire_blocks_clean(content, role="assistant")
        assert "role='assistant'" in str(exc_info.value)
        assert "['user_id']" in str(exc_info.value)

    def test_uploaded_file_block_at_wire_fails_loudly(self):
        """uploaded_file is engine-internal; flatten_uploaded_file_blocks
        MUST convert it to text before wire. If a wire-bound content
        list still has it, that's a missing flatten call — a real bug
        the validator surfaces."""
        content = [
            {"type": "uploaded_file", "name": "report.pdf",
             "media_type": "application/pdf", "file_id": "sha:abc"},
        ]
        with pytest.raises(AssertionError) as exc_info:
            assert_wire_blocks_clean(content, role="user")
        # The validator entry for uploaded_file has empty allowed-set,
        # so EVERY key is non-spec. Diagnostic surfaces the full list.
        msg = str(exc_info.value)
        assert "uploaded_file" in msg
        assert "block #0" in msg

    def test_diagnostic_includes_allowed_keys_hint(self):
        """The error message should tell the developer WHAT was allowed
        so they can fix the producer without grepping the spec."""
        content = [
            {"type": "image_url", "name": "x.png",
             "image_url": {"url": "data:image/png;base64,X"}},
        ]
        with pytest.raises(AssertionError) as exc_info:
            assert_wire_blocks_clean(content)
        msg = str(exc_info.value)
        # Allowed keys list appears in the diagnostic, sorted.
        assert "['image_url', 'type']" in msg
        # ADR reference for follow-up reading.
        assert "0006-content-block-schema-separation" in msg

    def test_second_block_in_list_is_caught(self):
        """Validator walks the WHOLE list, not just block[0]. Pollution
        in a later block must still be flagged with its correct index."""
        content = [
            {"type": "text", "text": "look at this"},
            {"type": "image_url",
             "name": "shot.png",
             "image_url": {"url": "data:image/png;base64,X"}},
        ]
        with pytest.raises(AssertionError) as exc_info:
            assert_wire_blocks_clean(content, role="user")
        # Index 1 (the image), not 0 (the text).
        assert "block #1" in str(exc_info.value)


# =============================================================================
# Direction 3 — production builds (__debug__ off) skip the check
# =============================================================================


class TestDebugGated:
    def test_validator_uses_assert_not_raise(self):
        """The validator MUST use `assert` so production builds with
        `python -O` strip the check. This pins that contract — if a
        future refactor switches to `if not <cond>: raise`, this test
        fails. Production-cost-zero is a load-bearing property of the
        defensive sentinel design.
        """
        import ast
        import inspect
        from ppxai.engine.uploaded_file import assert_wire_blocks_clean

        source = inspect.getsource(assert_wire_blocks_clean)
        tree = ast.parse(source)
        # Find any `raise SomeException(...)` — ALL raise statements
        # would mean a non-debug-stripped path.
        raise_nodes = [n for n in ast.walk(tree) if isinstance(n, ast.Raise)]
        assert len(raise_nodes) == 0, (
            f"assert_wire_blocks_clean must use `assert`, not `raise`, "
            f"so production builds with `python -O` strip the check. "
            f"Found {len(raise_nodes)} raise node(s) — switch them to "
            f"`assert <cond>, <message>` form."
        )
        # And there MUST be at least one assert (otherwise the function
        # does nothing).
        assert_nodes = [n for n in ast.walk(tree) if isinstance(n, ast.Assert)]
        assert len(assert_nodes) >= 1, (
            "assert_wire_blocks_clean has no assert statements — the "
            "validator is silently a no-op."
        )


# =============================================================================
# Direction 4 — schema documentation pins
# =============================================================================


class TestAllowedKeysSchema:
    def test_text_blocks_only_carry_type_and_text(self):
        """The spec for text content blocks is fixed and unlikely to grow."""
        assert _WIRE_ALLOWED_BLOCK_KEYS["text"] == frozenset({"type", "text"})

    def test_image_url_blocks_only_carry_type_and_image_url(self):
        """The bug class this whole ADR fixes — image_url's outer keys
        are STRICTLY {type, image_url}. Inner-dict shape is separate."""
        assert _WIRE_ALLOWED_BLOCK_KEYS["image_url"] == frozenset({
            "type", "image_url",
        })

    def test_uploaded_file_blocks_have_empty_allowed_set(self):
        """uploaded_file is engine-internal — it should never reach the
        wire validator (flatten converts it first). The empty allowed
        set ensures a stale flatten step gets caught LOUDLY."""
        assert _WIRE_ALLOWED_BLOCK_KEYS["uploaded_file"] == frozenset()

    def test_known_block_types_count(self):
        """Sentinel for the schema. Bump this count when adding a new
        spec block type to _WIRE_ALLOWED_BLOCK_KEYS — ensures schema
        additions are deliberate, not accidental.

        Current entries: text, image_url, input_audio, file, uploaded_file.
        """
        assert len(_WIRE_ALLOWED_BLOCK_KEYS) == 5
