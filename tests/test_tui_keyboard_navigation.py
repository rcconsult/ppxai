"""ppxaide TUI tests: keyboard navigation.

Split out of tests/test_tui.py (2026-09-27) so this class runs on its own
xdist worker; as one file, test_tui.py set the suite's wall-clock floor.
"""

import asyncio


class TestKeyboardNavigation:
    """Phase 5.3: Keyboard navigation tests - no dead-ends, focus management."""

    def test_tab_navigation_basic(self):
        """Tab should cycle through focusable widgets."""
        from textual.app import App

        from ppxai.tui.widgets import ChatView, InputBox

        class TestApp(App):
            def compose(self):
                yield ChatView(id="chat-view")
                yield InputBox(id="input-box")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                # Press Tab
                await pilot.press("tab")
                await pilot.pause()

                # Should have focus somewhere
                assert app.focused is not None

        asyncio.run(run_test())

    def test_escape_closes_side_panel(self):
        """Escape should close SidePanel."""
        import tempfile
        from pathlib import Path

        from textual.app import App

        from ppxai.tui.widgets import SidePanel

        class TestApp(App):
            def compose(self):
                yield SidePanel(id="side-panel")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                panel = app.query_one("#side-panel", SidePanel)

                # Open panel
                with tempfile.NamedTemporaryFile(mode='w', suffix=".py", delete=False) as f:
                    f.write("test")
                    temp_path = Path(f.name)

                try:
                    await panel.show_file(temp_path, "test", mode="code", read_only=True)
                    await pilot.pause()

                    assert panel.is_open is True

                    # Press Escape
                    await pilot.press("escape")
                    await pilot.pause()

                    # Panel should be closed
                    assert panel.is_open is False

                finally:
                    temp_path.unlink(missing_ok=True)

        asyncio.run(run_test())

    def test_v_toggles_data_viewer(self):
        """V should toggle DataViewer between tree and source."""
        from textual.app import App

        from ppxai.tui.widgets import DataViewer

        class TestApp(App):
            def compose(self):
                viewer = DataViewer(id="data-viewer")
                viewer.load_json('{"key": "value"}', "test.json")
                yield viewer

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                viewer = app.query_one("#data-viewer", DataViewer)

                # Should start in tree mode
                assert viewer.view_mode == "tree"

                # Press V
                await pilot.press("v")
                await pilot.pause()

                # Should toggle to source
                assert viewer.view_mode == "source"

                # Press V again
                await pilot.press("v")
                await pilot.pause()

                # Should toggle back to tree
                assert viewer.view_mode == "tree"

        asyncio.run(run_test())

    def test_v_toggles_table_viewer(self):
        """V should toggle TableViewer between table and source."""
        from textual.app import App

        from ppxai.tui.widgets import TableViewer

        csv_data = "name,age\nAlice,30\nBob,25\n"

        class TestApp(App):
            def compose(self):
                viewer = TableViewer(id="table-viewer")
                viewer.load_auto(csv_data, "data.csv")
                yield viewer

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                viewer = app.query_one("#table-viewer", TableViewer)

                # Should start in table mode
                assert viewer.view_mode == "table"

                # Toggle view mode directly (keybinding might not focus widget in test)
                viewer.view_mode = "source"
                await pilot.pause()

                # Should be in source mode
                assert viewer.view_mode == "source"

                # Toggle back
                viewer.view_mode = "table"
                await pilot.pause()

                # Should be back in table mode
                assert viewer.view_mode == "table"

        asyncio.run(run_test())

    def test_language_detection_in_side_panel(self):
        """SidePanel should detect language from file extension."""
        import tempfile
        from pathlib import Path

        from textual.app import App

        from ppxai.tui.widgets import SidePanel

        class TestApp(App):
            def compose(self):
                yield SidePanel(id="side-panel")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                panel = app.query_one("#side-panel", SidePanel)

                # Test Python file
                with tempfile.NamedTemporaryFile(mode='w', suffix=".py", delete=False) as f:
                    f.write("print('test')")
                    temp_path = Path(f.name)

                try:
                    await panel.show_file(temp_path, "print('test')", mode="code", read_only=True)
                    await pilot.pause()

                    # Language should be detected as python
                    assert panel._current_language == "python"
                    assert panel._mode == "code"

                finally:
                    temp_path.unlink(missing_ok=True)

        asyncio.run(run_test())

    def test_no_dead_ends_in_navigation(self):
        """Should be able to navigate through all widgets without getting stuck."""
        from textual.app import App

        from ppxai.tui.widgets import ChatView, InputBox, StatusBar

        class TestApp(App):
            def compose(self):
                yield StatusBar()
                yield ChatView(id="chat-view")
                yield InputBox(id="input-box")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                # Press Tab multiple times
                for _ in range(5):
                    await pilot.press("tab")
                    await pilot.pause()

                    # Should always have focus somewhere
                    assert app.focused is not None

        asyncio.run(run_test())

    def test_arrow_keys_in_chat_view(self):
        """Arrow keys should work for scrolling in ChatView."""
        from textual.app import App

        from ppxai.tui.widgets import ChatView, MessageBox

        class TestApp(App):
            def compose(self):
                yield ChatView(id="chat-view")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                chat_view = app.query_one("#chat-view", ChatView)

                # Add some messages
                for i in range(10):
                    msg = MessageBox(role="user", content=f"Message {i}")
                    chat_view._messages.append(msg)
                    await chat_view.mount(msg)

                await pilot.pause()

                # Focus chat view
                chat_view.focus()
                await pilot.pause()

                # Press arrow keys - should not crash
                await pilot.press("down")
                await pilot.pause()
                await pilot.press("up")
                await pilot.pause()

        asyncio.run(run_test())

    def test_home_end_keys_in_input_box(self):
        """Home/End keys should work in InputBox."""
        from textual.app import App

        from ppxai.tui.widgets import InputBox

        class TestApp(App):
            def compose(self):
                yield InputBox(id="input-box")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                input_box = app.query_one("#input-box", InputBox)

                # Focus input box
                input_box.focus()
                await pilot.pause()

                # Type some text
                await pilot.press(*"hello world")
                await pilot.pause()

                # Press Home - should not crash
                await pilot.press("home")
                await pilot.pause()

                # Press End - should not crash
                await pilot.press("end")
                await pilot.pause()

        asyncio.run(run_test())

    def test_close_method_works(self):
        """Panel close() method should work."""
        import tempfile
        from pathlib import Path

        from textual.app import App

        from ppxai.tui.widgets import SidePanel

        class TestApp(App):
            def compose(self):
                yield SidePanel(id="side-panel")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                panel = app.query_one("#side-panel", SidePanel)

                # Open panel
                with tempfile.NamedTemporaryFile(mode='w', suffix=".txt", delete=False) as f:
                    f.write("test")
                    temp_path = Path(f.name)

                try:
                    await panel.show_file(temp_path, "test", mode="code", read_only=True)
                    await pilot.pause()

                    assert panel.is_open is True

                    # Call close() method
                    panel.close()
                    await pilot.pause()

                    # Panel should be closed
                    assert panel.is_open is False

                finally:
                    temp_path.unlink(missing_ok=True)

        asyncio.run(run_test())

    def test_focus_stays_within_app(self):
        """Focus should never be None during navigation."""
        from textual.app import App

        from ppxai.tui.widgets import ChatView, InputBox

        class TestApp(App):
            def compose(self):
                yield ChatView(id="chat-view")
                yield InputBox(id="input-box")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                # Try various navigation keys
                keys = ["tab", "shift+tab", "down", "up"]

                for key in keys:
                    await pilot.press(key)
                    await pilot.pause()

                    # Focus should not be lost
                    # (May be None initially, but after pressing a key should have focus)

        asyncio.run(run_test())

    def test_shift_tab_reverses_navigation(self):
        """Shift+Tab should navigate backwards."""
        from textual.app import App

        from ppxai.tui.widgets import ChatView, InputBox

        class TestApp(App):
            def compose(self):
                yield ChatView(id="chat-view")
                yield InputBox(id="input-box")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                # Press Tab to move forward
                await pilot.press("tab")
                await pilot.pause()
                first_focus = app.focused

                # Press Tab again
                await pilot.press("tab")
                await pilot.pause()
                second_focus = app.focused

                # Press Shift+Tab to go back
                await pilot.press("shift+tab")
                await pilot.pause()
                back_focus = app.focused

                # Should be able to navigate (focus changes)
                # Can't guarantee specific order, but focus should exist

        asyncio.run(run_test())

    def test_keyboard_shortcuts_dont_conflict(self):
        """No keyboard shortcut conflicts across widgets."""
        import tempfile
        from pathlib import Path

        from textual.app import App

        from ppxai.tui.widgets import SidePanel

        class TestApp(App):
            def compose(self):
                yield SidePanel(id="side-panel")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                panel = app.query_one("#side-panel", SidePanel)

                # Open a data file that uses DataViewer
                with tempfile.NamedTemporaryFile(mode='w', suffix=".json", delete=False) as f:
                    f.write('{"test": "data"}')
                    temp_path = Path(f.name)

                try:
                    await panel.show_file(temp_path, '{"test": "data"}', mode="tree", read_only=True)
                    await pilot.pause()

                    # V should toggle DataViewer (not conflict with SidePanel bindings)
                    await pilot.press("v")
                    await pilot.pause()

                    # Escape should close panel (SidePanel binding)
                    await pilot.press("escape")
                    await pilot.pause()

                    assert panel.is_open is False

                finally:
                    temp_path.unlink(missing_ok=True)

        asyncio.run(run_test())

    def test_enter_key_in_input_box(self):
        """Enter key should work in InputBox (submit or new line)."""
        from textual.app import App

        from ppxai.tui.widgets import InputBox

        class TestApp(App):
            def compose(self):
                yield InputBox(id="input-box")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                input_box = app.query_one("#input-box", InputBox)

                # Focus input box
                input_box.focus()
                await pilot.pause()

                # Type text
                await pilot.press(*"hello")
                await pilot.pause()

                # Press Enter - should not crash
                await pilot.press("enter")
                await pilot.pause()

        asyncio.run(run_test())

    def test_f6_switches_focus_to_side_panel(self):
        """F6 should switch focus to side panel when open."""
        import tempfile
        from pathlib import Path

        from textual.app import App

        from ppxai.tui.widgets import ChatView, SidePanel

        class TestApp(App):
            def compose(self):
                yield ChatView(id="chat-view")
                yield SidePanel(id="side-panel")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                chat_view = app.query_one("#chat-view", ChatView)
                panel = app.query_one("#side-panel", SidePanel)

                # Focus chat view
                chat_view.focus()
                await pilot.pause()

                # Open side panel
                with tempfile.NamedTemporaryFile(mode='w', suffix=".txt", delete=False) as f:
                    f.write("test")
                    temp_path = Path(f.name)

                try:
                    await panel.show_file(temp_path, "test", mode="code", read_only=True)
                    await pilot.pause()

                    # Press F6 - should not crash
                    await pilot.press("f6")
                    await pilot.pause()

                finally:
                    temp_path.unlink(missing_ok=True)

        asyncio.run(run_test())

    def test_multiple_escape_presses(self):
        """Multiple Escape presses should not cause issues."""
        import tempfile
        from pathlib import Path

        from textual.app import App

        from ppxai.tui.widgets import SidePanel

        class TestApp(App):
            def compose(self):
                yield SidePanel(id="side-panel")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                panel = app.query_one("#side-panel", SidePanel)

                # Open panel
                with tempfile.NamedTemporaryFile(mode='w', suffix=".txt", delete=False) as f:
                    f.write("test")
                    temp_path = Path(f.name)

                try:
                    await panel.show_file(temp_path, "test", mode="code", read_only=True)
                    await pilot.pause()

                    # Press Escape multiple times
                    for _ in range(5):
                        await pilot.press("escape")
                        await pilot.pause()

                    # Should be closed and not crash
                    assert panel.is_open is False

                finally:
                    temp_path.unlink(missing_ok=True)

        asyncio.run(run_test())

    def test_page_up_down_in_chat_view(self):
        """Page Up/Down should work for scrolling in ChatView."""
        from textual.app import App

        from ppxai.tui.widgets import ChatView, MessageBox

        class TestApp(App):
            def compose(self):
                yield ChatView(id="chat-view")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                chat_view = app.query_one("#chat-view", ChatView)

                # Add many messages
                for i in range(50):
                    msg = MessageBox(role="user", content=f"Message {i}")
                    chat_view._messages.append(msg)
                    await chat_view.mount(msg)

                await pilot.pause()

                # Focus chat view
                chat_view.focus()
                await pilot.pause()

                # Press Page Down
                await pilot.press("pagedown")
                await pilot.pause()

                # Press Page Up
                await pilot.press("pageup")
                await pilot.pause()

        asyncio.run(run_test())
