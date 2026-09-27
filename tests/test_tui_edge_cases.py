"""ppxaide TUI tests: edge cases.

Split out of tests/test_tui.py (2026-09-27) so this class runs on its own
xdist worker; as one file, test_tui.py set the suite's wall-clock floor.
"""

import asyncio
import json


class TestEdgeCases:
    """Phase 5.4: Edge case tests - empty states, errors, long content, Unicode."""

    def test_empty_chat_view(self):
        """ChatView should handle zero messages."""
        from textual.app import App

        from ppxai.tui.widgets import ChatView

        class TestApp(App):
            def compose(self):
                yield ChatView(id="chat-view")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                chat_view = app.query_one("#chat-view", ChatView)

                # Should start with zero messages
                assert len(chat_view._messages) == 0

        asyncio.run(run_test())

    def test_empty_string_message(self):
        """MessageBox should handle empty content."""
        from textual.app import App

        from ppxai.tui.widgets import MessageBox

        class TestApp(App):
            def compose(self):
                yield MessageBox(role="user", content="")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                msg = app.query_one(MessageBox)
                assert msg.content == ""

        asyncio.run(run_test())

    def test_data_viewer_with_empty_json(self):
        """DataViewer should handle empty JSON object."""
        from textual.app import App

        from ppxai.tui.widgets import DataViewer

        class TestApp(App):
            def compose(self):
                viewer = DataViewer(id="data-viewer")
                viewer.load_json('{}', "empty.json")
                yield viewer

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                viewer = app.query_one("#data-viewer", DataViewer)
                assert viewer._source == '{}'

        asyncio.run(run_test())

    def test_table_viewer_with_empty_csv(self):
        """TableViewer should handle empty CSV."""
        from textual.app import App

        from ppxai.tui.widgets import TableViewer

        class TestApp(App):
            def compose(self):
                viewer = TableViewer(id="table-viewer")
                viewer.load_auto("", "empty.csv")
                yield viewer

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                viewer = app.query_one("#table-viewer", TableViewer)
                # Should handle empty data gracefully
                assert viewer._source == ""

        asyncio.run(run_test())

    def test_unicode_in_messages(self):
        """Messages should support Unicode characters."""
        from textual.app import App

        from ppxai.tui.widgets import MessageBox

        unicode_text = "Hello 世界 🌍 Привет مرحبا"

        class TestApp(App):
            def compose(self):
                yield MessageBox(role="user", content=unicode_text)

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                msg = app.query_one(MessageBox)
                assert unicode_text in msg.content

        asyncio.run(run_test())

    def test_unicode_in_data_viewer(self):
        """DataViewer should support Unicode in JSON."""
        from textual.app import App

        from ppxai.tui.widgets import DataViewer

        unicode_data = {"message": "Hello 世界", "emoji": "🎉"}

        class TestApp(App):
            def compose(self):
                viewer = DataViewer(id="data-viewer")
                viewer.load_json(json.dumps(unicode_data, ensure_ascii=False), "unicode.json")
                yield viewer

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                viewer = app.query_one("#data-viewer", DataViewer)
                assert "世界" in viewer._source

        import asyncio
        asyncio.run(run_test())

    def test_very_long_message(self):
        """ChatView should handle very long messages."""
        from textual.app import App

        from ppxai.tui.widgets import ChatView, MessageBox

        long_content = "A" * 10000  # 10k character message

        class TestApp(App):
            def compose(self):
                yield ChatView(id="chat-view")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                chat_view = app.query_one("#chat-view", ChatView)

                msg = MessageBox(role="user", content=long_content)
                chat_view._messages.append(msg)
                await chat_view.mount(msg)
                await pilot.pause()

                # Should handle long message
                assert len(chat_view._messages) == 1

        asyncio.run(run_test())

    def test_many_messages_performance(self):
        """ChatView should handle hundreds of messages."""
        from textual.app import App

        from ppxai.tui.widgets import ChatView, MessageBox

        class TestApp(App):
            def compose(self):
                yield ChatView(id="chat-view")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                chat_view = app.query_one("#chat-view", ChatView)

                # Add 100 messages
                for i in range(100):
                    msg = MessageBox(role="user", content=f"Message {i}")
                    chat_view._messages.append(msg)
                    await chat_view.mount(msg)

                await pilot.pause()

                # Should have all messages
                assert len(chat_view._messages) == 100

        asyncio.run(run_test())

    def test_invalid_json_handling(self):
        """DataViewer should handle invalid JSON gracefully."""
        from textual.app import App

        from ppxai.tui.widgets import DataViewer

        class TestApp(App):
            def compose(self):
                viewer = DataViewer(id="data-viewer")
                yield viewer

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                viewer = app.query_one("#data-viewer", DataViewer)

                # Try to load invalid JSON
                result = viewer.load_json("not valid json{", "bad.json")

                # Should return False for invalid JSON
                assert result is False

        asyncio.run(run_test())

    def test_special_characters_in_filenames(self):
        """SidePanel should handle special characters in filenames."""
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

                # Create file with special chars
                with tempfile.NamedTemporaryFile(mode='w', suffix=" (copy).txt", delete=False) as f:
                    f.write("test")
                    temp_path = Path(f.name)

                try:
                    await panel.show_file(temp_path, "test", mode="code", read_only=True)
                    await pilot.pause()

                    # Should handle the filename
                    assert panel.is_open is True

                finally:
                    temp_path.unlink(missing_ok=True)

        asyncio.run(run_test())

    def test_newlines_in_messages(self):
        """Messages should preserve newlines."""
        from textual.app import App

        from ppxai.tui.widgets import MessageBox

        multiline_content = "Line 1\nLine 2\nLine 3"

        class TestApp(App):
            def compose(self):
                yield MessageBox(role="user", content=multiline_content)

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                msg = app.query_one(MessageBox)
                assert "\n" in msg.content
                assert msg.content == multiline_content

        asyncio.run(run_test())

    def test_code_editor_with_empty_text(self):
        """CodeEditor should handle empty text."""
        from textual.app import App

        from ppxai.tui.widgets import CodeEditor

        class TestApp(App):
            def compose(self):
                yield CodeEditor(text="", language="python", id="editor")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                editor = app.query_one("#editor", CodeEditor)
                assert editor.text == ""

        asyncio.run(run_test())

    def test_large_json_file(self):
        """DataViewer should handle large JSON."""
        from textual.app import App

        from ppxai.tui.widgets import DataViewer

        # Create large JSON structure
        large_data = {"items": [{"id": i, "name": f"Item {i}"} for i in range(100)]}

        class TestApp(App):
            def compose(self):
                viewer = DataViewer(id="data-viewer")
                viewer.load_json(json.dumps(large_data), "large.json")
                yield viewer

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                viewer = app.query_one("#data-viewer", DataViewer)
                assert viewer._data is not None

        import asyncio
        asyncio.run(run_test())

    def test_large_csv_file(self):
        """TableViewer should handle large CSV (row limit)."""
        from textual.app import App

        from ppxai.tui.widgets import TableViewer

        # Create CSV with many rows
        rows = ["name,age"] + [f"Person{i},{20+i}" for i in range(500)]
        csv_data = "\n".join(rows)

        class TestApp(App):
            def compose(self):
                viewer = TableViewer(id="table-viewer")
                viewer.load_auto(csv_data, "large.csv")
                yield viewer

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                viewer = app.query_one("#table-viewer", TableViewer)

                # Should have loaded data
                assert len(viewer._headers) > 0
                # May be limited by MAX_INITIAL_ROWS
                assert len(viewer._rows) > 0

        asyncio.run(run_test())

    def test_mixed_line_endings(self):
        """Content with mixed line endings should be handled."""
        from textual.app import App

        from ppxai.tui.widgets import CodeEditor

        mixed_content = "Line 1\nLine 2\r\nLine 3\r"

        class TestApp(App):
            def compose(self):
                yield CodeEditor(text=mixed_content, language="python", id="editor")

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                editor = app.query_one("#editor", CodeEditor)
                # Should have the content
                assert len(editor.text) > 0

        asyncio.run(run_test())

    def test_status_bar_with_long_values(self):
        """StatusBar should handle long provider/model names."""
        from textual.app import App

        from ppxai.tui.widgets import StatusBar

        class TestApp(App):
            def compose(self):
                yield StatusBar(
                    provider="very-long-provider-name-that-might-overflow",
                    model="extremely-long-model-name-with-many-characters"
                )

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                status_bar = app.query_one(StatusBar)
                # Should have the values
                assert "very-long" in status_bar.provider

        asyncio.run(run_test())

    def test_side_panel_rapid_open_close(self):
        """SidePanel should handle rapid open/close cycles."""
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

                with tempfile.NamedTemporaryFile(mode='w', suffix=".txt", delete=False) as f:
                    f.write("test")
                    temp_path = Path(f.name)

                try:
                    # Rapid cycles
                    for _ in range(5):
                        await panel.show_file(temp_path, "test", mode="code", read_only=True)
                        await pilot.pause()
                        panel.close()
                        await pilot.pause()

                    # Should end in closed state
                    assert panel.is_open is False

                finally:
                    temp_path.unlink(missing_ok=True)

        asyncio.run(run_test())

    def test_data_viewer_view_mode_toggle_many_times(self):
        """DataViewer should handle many view toggles."""
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

                # Toggle 10 times
                for i in range(10):
                    viewer.view_mode = "source" if i % 2 == 0 else "tree"
                    await pilot.pause()

                # Should end in tree mode
                assert viewer.view_mode == "tree"

        asyncio.run(run_test())

    def test_malformed_yaml(self):
        """DataViewer should handle malformed YAML."""
        from textual.app import App

        from ppxai.tui.widgets import DataViewer

        class TestApp(App):
            def compose(self):
                viewer = DataViewer(id="data-viewer")
                yield viewer

        app = TestApp()
        async def run_test():
            async with app.run_test() as pilot:
                viewer = app.query_one("#data-viewer", DataViewer)

                # Try to load malformed YAML
                result = viewer.load_yaml("not: valid: yaml: : :", "bad.yaml")

                # Should return False
                assert result is False

        asyncio.run(run_test())
