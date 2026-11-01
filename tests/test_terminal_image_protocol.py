"""`detect_image_protocol`: which image protocol a terminal gets.

tai (TERM_PROGRAM=tai) implements the Kitty graphics protocol, including
Unicode-placeholder placements, and neither iTerm2 inline images nor (by
default) Sixel. It must get KITTY even when a parent Windows Terminal leaks
WT_SESSION into it, or ppxaide inside tai shows "Terminal does not support
image display".
"""

from __future__ import annotations

import pytest

from ppxai.tui.terminal import ImageProtocol, detect_image_protocol

_VARS = ("PPXAI_IMAGE_PROTOCOL", "TERM_PROGRAM", "KITTY_WINDOW_ID", "TERM", "WT_SESSION")


@pytest.fixture
def env(monkeypatch):
    for var in _VARS:
        monkeypatch.delenv(var, raising=False)

    def set_env(**values):
        for key, value in values.items():
            monkeypatch.setenv(key, value)
    return set_env


@pytest.mark.parametrize("values, expected", [
    ({"TERM_PROGRAM": "tai"}, ImageProtocol.KITTY),
    ({"TERM_PROGRAM": "tai", "WT_SESSION": "leaked-from-parent"}, ImageProtocol.KITTY),
    ({"TERM_PROGRAM": "tai", "TERM": "xterm-sixel"}, ImageProtocol.KITTY),
    ({"TERM_PROGRAM": "kitty"}, ImageProtocol.KITTY),
    ({"KITTY_WINDOW_ID": "1"}, ImageProtocol.KITTY),
    ({"TERM_PROGRAM": "WezTerm"}, ImageProtocol.ITERM2),
    ({"WT_SESSION": "x"}, ImageProtocol.SIXEL),
    ({}, ImageProtocol.NONE),
])
def test_protocol_by_terminal(env, values, expected):
    env(**values)
    assert detect_image_protocol() is expected


def test_the_user_override_still_wins_over_tai(env):
    env(TERM_PROGRAM="tai", PPXAI_IMAGE_PROTOCOL="none")
    assert detect_image_protocol() is ImageProtocol.NONE
