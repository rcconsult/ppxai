"""`SidePanel.show_widget(focus=...)` — output that accompanies vs replaces.

Every panel mount used to steal focus unconditionally. That is right for the
file viewers, `/sessions` and `/tools list`: the user opens a panel they
immediately want to drive.

It is wrong for `/task ls` and `/run ls`. Those commands exist to report on
work happening in the BACKGROUND, and their whole promise is that chat stays
usable — a run list that grabs the cursor contradicts the thing it is
reporting on (T8b).

So the default is unchanged and the opt-out is explicit, declared by the
command through `TableResult.metadata["focus_panel"]` rather than guessed by
the renderer.

Driven through a real Textual app via `run_test()`, because focus is a
runtime property of a mounted widget tree — asserting it any other way would
be asserting my reading of the code rather than the behaviour.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual", reason="Textual TUI extra not installed")

from textual.app import App, ComposeResult  # noqa: E402
from textual.widgets import DataTable, Input  # noqa: E402

from ppxai.tui.widgets.side_panel import SidePanel  # noqa: E402


class _Host(App):
    """Minimal host: an input to hold focus, and the panel under test."""

    def compose(self) -> ComposeResult:
        yield Input(id="chat-input")
        yield SidePanel(id="side-panel")

    def on_mount(self) -> None:
        self.query_one("#chat-input", Input).focus()


def _table() -> DataTable:
    table = DataTable()
    table.add_columns("Run", "Status")
    table.add_row("run_0123456789ab", "running")
    return table


def test_focus_true_moves_focus_to_the_panel():
    """The existing contract, pinned so the opt-out can't silently invert it."""
    app = _Host()

    async def run():
        async with app.run_test() as pilot:
            panel = app.query_one("#side-panel", SidePanel)
            await panel.show_widget(_table(), title="runs", focus=True)
            await pilot.pause()
            assert not isinstance(app.focused, Input), (
                "focus=True should have moved focus off the chat input"
            )

    asyncio.run(run())


def test_focus_false_leaves_the_cursor_in_chat():
    """The T8b requirement: glanceable output must not take the cursor."""
    app = _Host()

    async def run():
        async with app.run_test() as pilot:
            panel = app.query_one("#side-panel", SidePanel)
            before = app.focused
            await panel.show_widget(_table(), title="runs", focus=False)
            await pilot.pause()
            assert app.focused is before, (
                f"focus moved to {type(app.focused).__name__} — a background-run "
                f"list must leave the user typing"
            )
            assert isinstance(app.focused, Input)

    asyncio.run(run())


def test_panel_is_still_shown_when_focus_is_declined():
    """Declining focus must not decline the panel — it still opens."""
    app = _Host()

    async def run():
        async with app.run_test() as pilot:
            panel = app.query_one("#side-panel", SidePanel)
            await panel.show_widget(_table(), title="runs", focus=False)
            await pilot.pause()
            assert panel.is_open
            assert panel.has_class("visible")
            assert panel.query_one(DataTable) is not None

    asyncio.run(run())


def test_default_is_focus_for_backwards_compatibility():
    """Existing callers pass no `focus` and must behave exactly as before."""
    app = _Host()

    async def run():
        async with app.run_test() as pilot:
            panel = app.query_one("#side-panel", SidePanel)
            await panel.show_widget(_table(), title="runs")
            await pilot.pause()
            assert not isinstance(app.focused, Input)

    asyncio.run(run())
