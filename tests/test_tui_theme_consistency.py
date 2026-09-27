"""ppxaide TUI tests: theme consistency across widgets.

Split out of tests/test_tui.py (2026-09-27) so this class runs on its own
xdist worker; as one file, test_tui.py set the suite's wall-clock floor.
"""

import asyncio


class TestThemeConsistency:
    """Phase 5.2: Theme consistency tests - all themes, all widgets."""

    def test_all_widgets_with_default_theme(self):
        """All widgets should render correctly with default theme."""

        from textual.app import App

        from ppxai.tui.widgets import (
            ChatView,
            InputBox,
            StatusBar,
        )

        class TestApp(App):
            def compose(self):
                yield StatusBar()
                yield ChatView(id="chat-view")
                yield InputBox(id="input-box")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                # All widgets should be mounted
                assert app.query_one(StatusBar) is not None
                assert app.query_one("#chat-view", ChatView) is not None
                assert app.query_one("#input-box", InputBox) is not None

                # Default theme should be textual-dark
                assert app.theme is not None

        asyncio.run(run_test())

    def test_status_bar_across_themes(self):
        """StatusBar should work with all themes."""
        from textual.app import App

        from ppxai.tui.widgets import StatusBar

        themes_to_test = [
            "textual-dark", "textual-light",
            "nord", "dracula", "catppuccin-mocha"
        ]

        for theme_name in themes_to_test:
            class TestApp(App):
                def compose(self):
                    yield StatusBar()

            app = TestApp()
            async def run_test():
                async with app.run_test() as pilot:
                    # Apply theme
                    app.theme = theme_name
                    await pilot.pause()

                    # Widget should still be visible
                    status_bar = app.query_one(StatusBar)
                    assert status_bar is not None
                    assert status_bar.provider is not None

            asyncio.run(run_test())

    def test_chat_view_across_themes(self):
        """ChatView should work with all themes."""
        from textual.app import App

        from ppxai.tui.widgets import ChatView, MessageBox

        themes_to_test = [
            "textual-dark", "nord", "monokai"
        ]

        for theme_name in themes_to_test:
            class TestApp(App):
                def compose(self):
                    yield ChatView(id="chat-view")

            app = TestApp()
            async def run_test():
                async with app.run_test() as pilot:
                    # Apply theme
                    app.theme = theme_name
                    await pilot.pause()

                    # Add a message
                    chat_view = app.query_one("#chat-view", ChatView)
                    msg = MessageBox(role="user", content="Test message")
                    chat_view._messages.append(msg)
                    await chat_view.mount(msg)
                    await pilot.pause()

                    # Message should be visible
                    assert len(chat_view._messages) == 1

            asyncio.run(run_test())

    def test_data_viewer_across_themes(self):
        """DataViewer should work with all themes."""
        from textual.app import App

        from ppxai.tui.widgets import DataViewer

        themes_to_test = ["textual-dark", "gruvbox", "solarized-light"]

        for theme_name in themes_to_test:
            class TestApp(App):
                def compose(self):
                    viewer = DataViewer(id="data-viewer")
                    viewer.load_json('{"key": "value"}', "test.json")
                    yield viewer

            app = TestApp()
            async def run_test():
                async with app.run_test() as pilot:
                    # Apply theme
                    app.theme = theme_name
                    await pilot.pause()

                    # Viewer should still work
                    viewer = app.query_one("#data-viewer", DataViewer)
                    assert viewer.view_mode == "tree"

                    # Toggle view
                    viewer.view_mode = "source"
                    await pilot.pause()
                    assert viewer.view_mode == "source"

            asyncio.run(run_test())

    def test_code_editor_syntax_themes(self):
        """CodeEditor syntax highlighting should work with app themes."""
        from textual.app import App

        from ppxai.tui.widgets import CodeEditor

        app_themes = ["textual-dark", "nord", "monokai"]

        for app_theme in app_themes:
            class TestApp(App):
                def compose(self):
                    yield CodeEditor(
                        text="def test():\n    pass\n",
                        language="python",
                        id="editor"
                    )

            app = TestApp()
            async def run_test():
                async with app.run_test() as pilot:
                    # Apply app theme
                    app.theme = app_theme
                    await pilot.pause()

                    # Editor should still work
                    editor = app.query_one("#editor", CodeEditor)
                    assert editor.text == "def test():\n    pass\n"
                    assert editor.language == "python"

            asyncio.run(run_test())

    def test_table_viewer_across_themes(self):
        """TableViewer should work with all themes."""
        from textual.app import App

        from ppxai.tui.widgets import TableViewer

        themes_to_test = ["textual-dark", "dracula", "textual-light"]

        csv_data = "name,age,city\nAlice,30,NYC\nBob,25,LA\n"

        for theme_name in themes_to_test:
            class TestApp(App):
                def compose(self):
                    viewer = TableViewer(id="table-viewer")
                    viewer.load_auto(csv_data, "data.csv")
                    yield viewer

            app = TestApp()
            async def run_test():
                async with app.run_test() as pilot:
                    # Apply theme
                    app.theme = theme_name
                    await pilot.pause()

                    # Viewer should work
                    viewer = app.query_one("#table-viewer", TableViewer)
                    assert viewer.view_mode == "table"

                    # Toggle view
                    viewer.view_mode = "source"
                    await pilot.pause()
                    assert viewer.view_mode == "source"

            asyncio.run(run_test())

    def test_side_panel_across_themes(self):
        """SidePanel should work with all themes."""
        import tempfile
        from pathlib import Path

        from textual.app import App

        from ppxai.tui.widgets import SidePanel

        themes_to_test = ["textual-dark", "nord", "monokai"]

        for theme_name in themes_to_test:
            class TestApp(App):
                def compose(self):
                    yield SidePanel(id="side-panel")

            app = TestApp()
            async def run_test():
                async with app.run_test() as pilot:
                    # Apply theme
                    app.theme = theme_name
                    await pilot.pause()

                    panel = app.query_one("#side-panel", SidePanel)

                    # Show a file
                    with tempfile.NamedTemporaryFile(mode='w', suffix=".py", delete=False) as f:
                        f.write("print('test')")
                        temp_path = Path(f.name)

                    try:
                        await panel.show_file(temp_path, "print('test')", mode="code", read_only=True)
                        await pilot.pause()

                        # Panel should be open
                        assert panel.is_open is True

                    finally:
                        temp_path.unlink(missing_ok=True)

            asyncio.run(run_test())

    def test_custom_themes_work(self):
        """Custom themes (tron-legacy, matrix) should be available in ppxaide."""
        from ppxai.tui.app import PPXAIDEApp

        app = PPXAIDEApp()
        async def run_test():
            async with app.run_test() as pilot:
                # Check that custom themes are registered
                assert "tron-legacy" in app.available_themes
                assert "matrix" in app.available_themes

                # Try switching to custom themes
                app.theme = "tron-legacy"
                await pilot.pause()
                assert app.theme == "tron-legacy"

                app.theme = "matrix"
                await pilot.pause()
                assert app.theme == "matrix"

        asyncio.run(run_test())

    def test_theme_switching_preserves_state(self):
        """Theme switching should not lose widget state."""
        from textual.app import App

        from ppxai.tui.widgets import DataViewer

        class TestApp(App):
            def compose(self):
                viewer = DataViewer(id="data-viewer")
                viewer.load_json('{"test": "data"}', "test.json")
                yield viewer

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                viewer = app.query_one("#data-viewer", DataViewer)

                # Toggle to source mode
                viewer.view_mode = "source"
                await pilot.pause()

                # Switch themes
                app.theme = "nord"
                await pilot.pause()

                # State should be preserved
                assert viewer.view_mode == "source"
                assert viewer._source == '{"test": "data"}'

                # Switch themes again
                app.theme = "dracula"
                await pilot.pause()

                # State still preserved
                assert viewer.view_mode == "source"
                assert viewer._source == '{"test": "data"}'

        asyncio.run(run_test())

    def test_message_box_styles_with_themes(self):
        """MessageBox styles should work with all themes."""
        from textual.app import App

        from ppxai.tui.widgets import ChatView, MessageBox

        themes_to_test = ["textual-dark", "nord", "monokai"]

        for theme_name in themes_to_test:
            class TestApp(App):
                def compose(self):
                    yield ChatView(id="chat-view")

            app = TestApp()
            async def run_test():
                async with app.run_test() as pilot:
                    # Apply theme
                    app.theme = theme_name
                    await pilot.pause()

                    chat_view = app.query_one("#chat-view", ChatView)

                    # Add messages with different roles
                    for role in ["user", "assistant", "system"]:
                        msg = MessageBox(role=role, content=f"Test {role}")
                        chat_view._messages.append(msg)
                        await chat_view.mount(msg)
                        await pilot.pause()

                    # All messages should be visible
                    assert len(chat_view._messages) == 3

            asyncio.run(run_test())

    def test_input_box_across_themes(self):
        """InputBox should work with all themes."""
        from textual.app import App

        from ppxai.tui.widgets import InputBox

        themes_to_test = ["textual-dark", "nord", "atom-one-light"]

        for theme_name in themes_to_test:
            class TestApp(App):
                def compose(self):
                    yield InputBox(id="input-box")

            app = TestApp()
            async def run_test():
                async with app.run_test() as pilot:
                    # Apply theme
                    app.theme = theme_name
                    await pilot.pause()

                    # Input box should work
                    input_box = app.query_one("#input-box", InputBox)
                    assert input_box is not None

            asyncio.run(run_test())

    def test_tree_viewer_across_themes(self):
        """TreeViewer should work with all themes."""
        from textual.app import App

        from ppxai.tui.widgets import TreeViewer

        themes_to_test = ["textual-dark", "nord", "solarized-dark"]

        for theme_name in themes_to_test:
            class TestApp(App):
                def compose(self):
                    yield TreeViewer(id="tree-viewer")

            app = TestApp()
            async def run_test():
                async with app.run_test() as pilot:
                    # Apply theme
                    app.theme = theme_name
                    await pilot.pause()

                    # Viewer should work
                    viewer = app.query_one("#tree-viewer", TreeViewer)
                    assert viewer is not None

            asyncio.run(run_test())

    def test_widgets_visible_after_theme_change(self):
        """All widgets should remain visible after theme change."""
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
                # Start with default theme
                initial_theme = app.theme
                await pilot.pause()

                # All widgets visible
                assert app.query_one(StatusBar) is not None
                assert app.query_one("#chat-view", ChatView) is not None
                assert app.query_one("#input-box", InputBox) is not None

                # Change theme
                app.theme = "nord"
                await pilot.pause()

                # All widgets still visible
                assert app.query_one(StatusBar) is not None
                assert app.query_one("#chat-view", ChatView) is not None
                assert app.query_one("#input-box", InputBox) is not None

        asyncio.run(run_test())
