"""R10 regression test — `_has_multimodal_attachments` is O(1) after first scan.

`save()` / `save_dirty()` call `_has_multimodal_attachments()` on every
invocation to decide flat vs. directory storage format. Pre-R10 that was
a full O(messages × parts) scan on every save — enough to add measurable
latency to long tool-heavy conversations that auto-save after every turn.

The cache:
  - starts as None (unknown — triggers one scan on first save)
  - flips eagerly to True in add_message when a multimodal part arrives
  - invalidates on mutation sites that can remove multimodal content
    (remove_last_message / clear / load / reset_for_model_switch /
    validate_and_fix_alternation)

This module pins the cache lifecycle so a well-intentioned "simplify
the save path" refactor doesn't silently turn it back into an O(N) scan.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from ppxai.engine.session import SessionManager
from ppxai.engine.types import Message


def _text(role: str, text: str) -> Message:
    return Message(role, text)


def _multimodal_user(text: str) -> Message:
    """Build a Message with a multimodal content list (text + image_url)."""
    return Message(
        role="user",
        content=[
            {"type": "text", "text": text},
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="},
                "name": "pixel.png",
            },
        ],
    )


class TestMultimodalCacheLifecycle:
    """R10: the cache must be invalidated/updated at every mutation site."""

    def test_cold_cache_scans_once_then_stays_hot(self, tmp_path):
        session = SessionManager(sessions_dir=tmp_path, exports_dir=tmp_path / "x")
        session.messages = [_text("user", "hi"), _text("assistant", "hello")]

        # Cold: cache is None
        assert session._multimodal_cache is None

        # First call scans + caches False
        assert session._has_multimodal_attachments() is False
        assert session._multimodal_cache is False

        # Repeated calls are O(1) — proven by patching out the helper.
        with patch("ppxai.engine.session._message_has_multimodal") as mock_helper:
            for _ in range(20):
                session._has_multimodal_attachments()
            mock_helper.assert_not_called()

    def test_add_message_with_multimodal_flips_cache_true(self, tmp_path):
        """Eager upgrade — adding multimodal never costs a full rescan."""
        session = SessionManager(sessions_dir=tmp_path, exports_dir=tmp_path / "x")

        # Prime the cache as False
        session.add_message(_text("user", "first"))
        assert session._has_multimodal_attachments() is False
        assert session._multimodal_cache is False

        # Add a multimodal message — cache should flip to True without
        # re-scanning existing messages.
        with patch("ppxai.engine.session._message_has_multimodal", wraps=__import__(
            "ppxai.engine.session", fromlist=["_message_has_multimodal"]
        )._message_has_multimodal) as spy:
            session.add_message(_multimodal_user("look at this"))
            assert session._multimodal_cache is True
            # Called exactly once — on the new message only. The flip
            # happened without walking existing history.
            assert spy.call_count == 1
            assert spy.call_args[0][0].content[1]["type"] == "image_url"

    def test_add_text_message_preserves_true_cache(self, tmp_path):
        """Text-only additions don't downgrade an existing True."""
        session = SessionManager(sessions_dir=tmp_path, exports_dir=tmp_path / "x")
        session.add_message(_multimodal_user("image"))
        assert session._has_multimodal_attachments() is True

        session.add_message(_text("assistant", "nice pic"))
        assert session._multimodal_cache is True  # unchanged

    def test_remove_last_multimodal_invalidates(self, tmp_path):
        """Popping the lone multimodal message must not leave cache=True."""
        session = SessionManager(sessions_dir=tmp_path, exports_dir=tmp_path / "x")
        session.add_message(_text("user", "before"))
        session.add_message(_multimodal_user("image"))
        assert session._has_multimodal_attachments() is True

        session.remove_last_message()
        # Cache was invalidated (None means "needs rescan"); subsequent
        # call correctly returns False.
        assert session._multimodal_cache is None
        assert session._has_multimodal_attachments() is False

    def test_remove_last_text_preserves_cache(self, tmp_path):
        """Popping a non-multimodal tail doesn't trigger a rescan."""
        session = SessionManager(sessions_dir=tmp_path, exports_dir=tmp_path / "x")
        session.add_message(_multimodal_user("image"))
        session.add_message(_text("assistant", "trailing text"))
        assert session._has_multimodal_attachments() is True

        session.remove_last_message()
        # Text message popped — cache stays True without a rescan.
        assert session._multimodal_cache is True

    def test_clear_sets_cache_false(self, tmp_path):
        """clear() produces an empty session — cache directly False, no scan."""
        session = SessionManager(sessions_dir=tmp_path, exports_dir=tmp_path / "x")
        session.add_message(_multimodal_user("image"))

        with patch("ppxai.engine.session._message_has_multimodal") as spy:
            session.clear()
            assert session._multimodal_cache is False
            spy.assert_not_called()

    def test_load_invalidates_cache(self, tmp_path):
        """Round-trip through save/load — cache must be None on load."""
        session = SessionManager(sessions_dir=tmp_path, exports_dir=tmp_path / "x")
        session.session_name = "cache_test"
        session.add_message(_text("user", "hello"))
        session.add_message(_text("assistant", "hi"))
        session.save("cache_test")

        # Load into a fresh session manager — cache starts None.
        fresh = SessionManager(sessions_dir=tmp_path, exports_dir=tmp_path / "x")
        assert fresh.load("cache_test") is True
        assert fresh._multimodal_cache is None

        # First _has_multimodal_attachments call scans and caches.
        assert fresh._has_multimodal_attachments() is False
        assert fresh._multimodal_cache is False

    def test_reset_for_model_switch_invalidates(self, tmp_path):
        """Model switch strips assistant/tool messages; cache must reset."""
        session = SessionManager(sessions_dir=tmp_path, exports_dir=tmp_path / "x")
        session.add_message(_text("user", "question"))
        # Simulate an assistant turn that carried multimodal tool output
        session.add_message(Message(
            role="assistant",
            content=[
                {"type": "text", "text": "here"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
            ],
        ))
        assert session._has_multimodal_attachments() is True

        session.reset_for_model_switch()
        # Cache invalidated — next check must rescan and return False
        # (only a user text message left).
        assert session._multimodal_cache is None
        assert session._has_multimodal_attachments() is False

    def test_validate_and_fix_alternation_invalidates_on_mutation(self, tmp_path):
        """When the alternation fix reassigns messages, cache must drop."""
        session = SessionManager(sessions_dir=tmp_path, exports_dir=tmp_path / "x")
        # Build an invalid sequence that triggers alternation mutation.
        session.messages = [
            _text("user", "a"),
            _text("user", "b"),  # consecutive user — invalid
            _multimodal_user("image"),
            _text("assistant", "ok"),
        ]
        session._has_multimodal_attachments()  # warm cache
        assert session._multimodal_cache is True

        removed = session.validate_and_fix_alternation()
        assert removed > 0
        # Mutation → cache invalidated. A later read scans lazily.
        assert session._multimodal_cache is None


class TestSavePerformance:
    """End-to-end: repeated save() calls must not re-scan messages."""

    def test_repeated_save_is_constant_time(self, tmp_path):
        """500-message session, one image — save() 20 times, scan at most once.

        Matches the R10 acceptance criterion from the TODO: the underlying
        scan must run at most twice (once on first save, once if
        attachments were removed in between).
        """
        session = SessionManager(sessions_dir=tmp_path, exports_dir=tmp_path / "x")
        session.session_name = "perf"
        # One multimodal message early on, then 499 text turns.
        session.add_message(_multimodal_user("image early"))
        for i in range(499):
            role = "assistant" if i % 2 == 0 else "user"
            session.add_message(_text(role, f"turn {i}"))

        # Warm cache via first save.
        session.save("perf")

        with patch("ppxai.engine.session._message_has_multimodal") as spy:
            for _ in range(20):
                session.save("perf")
            # Cache is hot — _message_has_multimodal must never be called
            # again for the save path's format decision.
            assert spy.call_count == 0, (
                f"R10 regressed — {spy.call_count} rescans in 20 saves"
            )
