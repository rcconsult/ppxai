"""
Input handling for ppxai-native — keyboard and mouse events.
"""

from dataclasses import dataclass
from typing import List, Union

import pyray as rl


# Action types returned by handle_input()
@dataclass
class InsertChar:
    char: str

@dataclass
class DeleteBack:
    pass

@dataclass
class DeleteForward:
    pass

@dataclass
class SubmitMessage:
    pass

@dataclass
class NewLine:
    pass

@dataclass
class Scroll:
    pixels: float

@dataclass
class CursorLeft:
    pass

@dataclass
class CursorRight:
    pass

@dataclass
class CursorHome:
    pass

@dataclass
class CursorEnd:
    pass

@dataclass
class HistoryPrev:
    pass

@dataclass
class HistoryNext:
    pass

@dataclass
class Cancel:
    pass


Action = Union[
    InsertChar, DeleteBack, DeleteForward, SubmitMessage, NewLine,
    Scroll, CursorLeft, CursorRight, CursorHome, CursorEnd,
    HistoryPrev, HistoryNext, Cancel,
]


def handle_input() -> List[Action]:
    """Process Raylib input events and return a list of actions."""
    actions: List[Action] = []

    # Text input via GetCharPressed (handles Unicode)
    while True:
        ch = rl.get_char_pressed()
        if ch == 0:
            break
        actions.append(InsertChar(chr(ch)))

    # Special keys
    ctrl = rl.is_key_down(rl.KeyboardKey.KEY_LEFT_CONTROL) or rl.is_key_down(rl.KeyboardKey.KEY_RIGHT_CONTROL)

    if rl.is_key_pressed(rl.KeyboardKey.KEY_ENTER) or rl.is_key_pressed(rl.KeyboardKey.KEY_KP_ENTER):
        if ctrl:
            actions.append(SubmitMessage())
        else:
            actions.append(NewLine())

    if rl.is_key_pressed(rl.KeyboardKey.KEY_BACKSPACE) or rl.is_key_pressed_repeat(rl.KeyboardKey.KEY_BACKSPACE):
        actions.append(DeleteBack())

    if rl.is_key_pressed(rl.KeyboardKey.KEY_DELETE):
        actions.append(DeleteForward())

    if rl.is_key_pressed(rl.KeyboardKey.KEY_LEFT):
        actions.append(CursorLeft())

    if rl.is_key_pressed(rl.KeyboardKey.KEY_RIGHT):
        actions.append(CursorRight())

    if rl.is_key_pressed(rl.KeyboardKey.KEY_HOME):
        actions.append(CursorHome())

    if rl.is_key_pressed(rl.KeyboardKey.KEY_END):
        actions.append(CursorEnd())

    if rl.is_key_pressed(rl.KeyboardKey.KEY_UP) and ctrl:
        actions.append(HistoryPrev())

    if rl.is_key_pressed(rl.KeyboardKey.KEY_DOWN) and ctrl:
        actions.append(HistoryNext())

    if rl.is_key_pressed(rl.KeyboardKey.KEY_C) and ctrl:
        actions.append(Cancel())

    if rl.is_key_pressed(rl.KeyboardKey.KEY_ESCAPE):
        actions.append(Cancel())

    # Mouse wheel scroll
    wheel = rl.get_mouse_wheel_move()
    if wheel != 0:
        actions.append(Scroll(wheel * -40))

    return actions
