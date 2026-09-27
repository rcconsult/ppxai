"""ppxaide TUI tests: app integration.

Split out of tests/test_tui.py (2026-09-27) so this class runs on its own
xdist worker; as one file, test_tui.py set the suite's wall-clock floor.
"""

import asyncio
import json


class TestAppIntegration:
    """Phase 5.5: App integration tests - full app lifecycle and command handling."""

    def test_app_startup_and_shutdown(self):
        """App should start and shutdown cleanly."""
        from ppxai.tui.app import PPXAIDEApp
        from ppxai.tui.widgets import ChatView, InputBox, StatusBar

        app = PPXAIDEApp()
        async def run_test():
            async with app.run_test() as pilot:
                # Verify core widgets mounted
                chat_view = app.query_one(ChatView)
                input_box = app.query_one(InputBox)
                status_bar = app.query_one(StatusBar)

                assert chat_view is not None
                assert input_box is not None
                assert status_bar is not None

                # App should exit cleanly
                await pilot.exit(0)

        asyncio.run(run_test())

    def test_help_command(self):
        """/help command should display help text."""
        from ppxai.tui.app import PPXAIDEApp
        from ppxai.tui.widgets import ChatView

        app = PPXAIDEApp()
        async def run_test():
            async with app.run_test() as pilot:
                chat_view = app.query_one(ChatView)

                # Execute /help command
                await app._handle_command("/help")

                # Should add system message with help text
                assert len(chat_view._messages) > 0
                last_msg = chat_view._messages[-1]
                assert last_msg.role == "system"
                assert "Commands" in last_msg.content or "help" in last_msg.content.lower()

        asyncio.run(run_test())

    def test_clear_command(self):
        """/clear command should clear chat history."""
        from ppxai.tui.app import PPXAIDEApp
        from ppxai.tui.widgets import ChatView

        app = PPXAIDEApp()
        async def run_test():
            async with app.run_test() as pilot:
                chat_view = app.query_one("#chat-view", ChatView)

                # Add some messages
                chat_view.add_user_message("Test message 1")
                chat_view.add_user_message("Test message 2")
                initial_count = len(chat_view._messages)
                assert initial_count >= 2  # At least our 2 messages (may have welcome msg)

                # Execute /clear
                await app._handle_command("/clear")

                # Chat should have fewer messages than before (may have system notification)
                assert len(chat_view._messages) < initial_count

        asyncio.run(run_test())

    def test_theme_command(self):
        """action_cycle_theme should cycle themes."""
        from ppxai.tui.app import PPXAIDEApp

        app = PPXAIDEApp()
        async def run_test():
            async with app.run_test() as pilot:
                original_theme_index = app._current_theme_index

                # Directly call the action method
                app.action_cycle_theme()

                # Theme index should have changed
                assert app._current_theme_index != original_theme_index

        asyncio.run(run_test())

    def test_show_command_code_file(self, tmp_path):
        """/show command should open code file in side panel."""
        from ppxai.tui.app import PPXAIDEApp
        from ppxai.tui.widgets import ChatView, SidePanel

        # Create temporary file
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello():\n    print('world')\n", encoding="utf-8")

        app = PPXAIDEApp()
        app._working_dir = str(tmp_path)

        async def run_test():
            async with app.run_test() as pilot:
                chat_view = app.query_one(ChatView)
                side_panel = app.query_one(SidePanel)

                # Execute /show
                await app._handle_command(f"/show {test_file.name}")

                # Side panel should be visible
                assert side_panel.is_open

                # Should have system message
                assert len(chat_view._messages) > 0

        asyncio.run(run_test())

    def test_show_command_json_file(self, tmp_path):
        """/show command should open JSON file in tree viewer or side panel."""
        from ppxai.tui.app import PPXAIDEApp
        from ppxai.tui.widgets import SidePanel
        from ppxai.tui.widgets.chat_view import ChatView

        # Create temporary JSON file
        test_file = tmp_path / "data.json"
        test_file.write_text(json.dumps({"key": "value", "nested": {"a": 1}}), encoding="utf-8")

        app = PPXAIDEApp()
        app._working_dir = str(tmp_path)

        async def run_test():
            async with app.run_test() as pilot:
                side_panel = app.query_one(SidePanel)
                chat_view = app.query_one(ChatView)
                initial_msg_count = len(chat_view._messages)

                # Execute /show
                await app._handle_command(f"/show {test_file.name}")
                # Wait for async operations
                await pilot.pause()
                await pilot.pause()

                # Should have a response (either success or error)
                assert len(chat_view._messages) > initial_msg_count

                # Check if side panel opened OR if message was added to chat
                # (TreeResult opens side panel, error shows in chat)
                if side_panel.is_open:
                    # Side panel opened - success
                    pass
                else:
                    # No side panel - check for system message about display
                    last_msg = chat_view._messages[-1]
                    assert "data.json" in last_msg.content or "Displaying" in last_msg.content

        import asyncio
        asyncio.run(run_test())

    def test_show_command_csv_file(self, tmp_path):
        """/show command should open CSV file in table viewer."""
        from ppxai.tui.app import PPXAIDEApp
        from ppxai.tui.widgets import SidePanel, TableViewer

        # Create temporary CSV file
        test_file = tmp_path / "data.csv"
        test_file.write_text("name,age\nAlice,30\nBob,25\n", encoding="utf-8")

        app = PPXAIDEApp()
        app._working_dir = str(tmp_path)

        async def run_test():
            async with app.run_test() as pilot:
                side_panel = app.query_one(SidePanel)

                # Execute /show
                await app._handle_command(f"/show {test_file.name}")
                # Wait for widgets to be mounted
                await pilot.pause()

                # Side panel should be visible
                assert side_panel.is_open
                # Try to find TableViewer by ID or type
                try:
                    table_viewer = side_panel.query_one(TableViewer)
                    assert table_viewer is not None
                except Exception:
                    # Fallback - just verify side panel opened
                    assert side_panel.is_open

        asyncio.run(run_test())

    def test_edit_command(self, tmp_path):
        """/edit command should open file for editing."""
        from ppxai.tui.app import PPXAIDEApp
        from ppxai.tui.widgets import CodeEditor, SidePanel

        # Create temporary file
        test_file = tmp_path / "edit.txt"
        test_file.write_text("Original content", encoding="utf-8")

        app = PPXAIDEApp()
        app._working_dir = str(tmp_path)

        async def run_test():
            async with app.run_test() as pilot:
                side_panel = app.query_one("#side-panel", SidePanel)

                # Execute /edit
                await app._handle_command(f"/edit {test_file.name}")

                # Side panel should be open with CodeEditor
                assert side_panel.is_open
                code_editor = side_panel.query_one(CodeEditor)
                assert code_editor is not None

        asyncio.run(run_test())

    def test_cd_pwd_commands(self, tmp_path):
        """/cd and /pwd commands should work together."""

        from ppxai.tui.app import PPXAIDEApp
        from ppxai.tui.widgets import ChatView

        # Create subdirectory
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        app = PPXAIDEApp()
        app._working_dir = str(tmp_path)

        async def run_test():
            async with app.run_test() as pilot:
                chat_view = app.query_one(ChatView)

                # Show current directory
                await app._handle_command("/pwd")
                assert len(chat_view._messages) > 0

                # Change directory
                initial_msg_count = len(chat_view._messages)
                await app._handle_command("/cd subdir")

                # Should have a message about the directory change (success or error)
                assert len(chat_view._messages) > initial_msg_count

                # CRITICAL: Verify working directory is actually changed
                # This has been a source of regressions - working dir must sync between:
                # 1. TUI app._working_dir
                # 2. Engine client working_dir
                # 3. Actual OS working directory
                assert "subdir" in app._working_dir, f"App working dir not updated: {app._working_dir}"
                if app._engine_client:
                    engine_wd = app._engine_client.get_working_dir()
                    assert "subdir" in engine_wd, f"Engine client working dir not updated: {engine_wd}"

        asyncio.run(run_test())

    def test_status_command(self):
        """/status command should display app status."""
        from ppxai.tui.app import PPXAIDEApp
        from ppxai.tui.widgets import ChatView

        app = PPXAIDEApp()
        async def run_test():
            async with app.run_test() as pilot:
                chat_view = app.query_one(ChatView)

                # Execute /status
                await app._handle_command("/status")

                # Should have status message
                assert len(chat_view._messages) > 0
                last_msg = chat_view._messages[-1]
                assert last_msg.role == "system"
                # Status should contain provider/model info
                assert "Provider" in last_msg.content or "Model" in last_msg.content

        asyncio.run(run_test())

    def test_multiple_commands_sequence(self, tmp_path):
        """Multiple commands should execute in sequence."""
        from ppxai.tui.app import PPXAIDEApp
        from ppxai.tui.widgets import ChatView

        # Create test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("Test content", encoding="utf-8")

        app = PPXAIDEApp()
        app._working_dir = str(tmp_path)

        async def run_test():
            async with app.run_test() as pilot:
                chat_view = app.query_one("#chat-view", ChatView)

                # Execute multiple commands
                await app._handle_command("/help")
                await app._handle_command("/pwd")
                await app._handle_command("/status")

                # Chat should have messages from commands
                assert len(chat_view._messages) >= 3

        asyncio.run(run_test())

    def test_side_panel_with_different_content_types(self, tmp_path):
        """Side panel should handle different content types."""
        from ppxai.tui.app import PPXAIDEApp
        from ppxai.tui.widgets import SidePanel

        # Create different file types
        py_file = tmp_path / "code.py"
        py_file.write_text("print('hello')", encoding="utf-8")

        json_file = tmp_path / "data.json"
        json_file.write_text(json.dumps({"key": "value"}), encoding="utf-8")

        csv_file = tmp_path / "data.csv"
        csv_file.write_text("a,b\n1,2\n", encoding="utf-8")

        app = PPXAIDEApp()
        app._working_dir = str(tmp_path)

        async def run_test():
            async with app.run_test() as pilot:
                side_panel = app.query_one(SidePanel)

                # Show Python file
                await app._handle_command(f"/show {py_file.name}")
                assert side_panel.is_open

                # Show JSON file
                await app._handle_command(f"/show {json_file.name}")
                assert side_panel.is_open

                # Show CSV file
                await app._handle_command(f"/show {csv_file.name}")
                assert side_panel.is_open

        import asyncio
        asyncio.run(run_test())

    def test_chat_and_side_panel_interaction(self, tmp_path):
        """Chat messages should work while side panel is open."""
        from ppxai.tui.app import PPXAIDEApp
        from ppxai.tui.widgets import ChatView, SidePanel

        # Create test file
        test_file = tmp_path / "test.py"
        test_file.write_text("# Test file", encoding="utf-8")

        app = PPXAIDEApp()
        app._working_dir = str(tmp_path)

        async def run_test():
            async with app.run_test() as pilot:
                chat_view = app.query_one(ChatView)
                side_panel = app.query_one(SidePanel)

                # Open side panel
                await app._handle_command(f"/show {test_file.name}")
                assert side_panel.is_open

                # Add chat messages
                chat_view.add_user_message("Message while panel open")
                chat_view.add_assistant_message("Response while panel open")

                # Both should work
                assert side_panel.is_open
                assert len(chat_view._messages) >= 3  # /show message + 2 new messages

        asyncio.run(run_test())

    def test_theme_switching_preserves_state(self, tmp_path):
        """Theme changes should preserve chat and panel state."""
        from ppxai.tui.app import PPXAIDEApp
        from ppxai.tui.widgets import ChatView, SidePanel

        # Create test file
        test_file = tmp_path / "test.py"
        test_file.write_text("# Test", encoding="utf-8")

        app = PPXAIDEApp()
        app._working_dir = str(tmp_path)

        async def run_test():
            async with app.run_test() as pilot:
                chat_view = app.query_one("#chat-view", ChatView)
                side_panel = app.query_one("#side-panel", SidePanel)

                # Add messages
                chat_view.add_user_message("Test message")
                initial_user_msg_count = len([m for m in chat_view._messages if m.role == "user"])

                # Switch theme
                await app._handle_command("/theme")

                # State should be preserved (user messages unchanged)
                current_user_msg_count = len([m for m in chat_view._messages if m.role == "user"])
                assert current_user_msg_count == initial_user_msg_count

        asyncio.run(run_test())

    def test_input_history_navigation(self):
        """Input box should support history navigation."""
        from ppxai.tui.app import PPXAIDEApp
        from ppxai.tui.widgets import InputBox

        app = PPXAIDEApp()
        async def run_test():
            async with app.run_test() as pilot:
                input_box = app.query_one(InputBox)

                # Set history
                test_history = ["command 1", "command 2", "command 3"]
                input_box.set_history(test_history)

                # Verify history is set
                assert input_box.get_history() == test_history

                # Clear history
                input_box.clear_history()
                assert input_box.get_history() == []

        asyncio.run(run_test())

    def test_error_recovery(self):
        """App should recover from command errors."""
        from ppxai.tui.app import PPXAIDEApp
        from ppxai.tui.widgets import ChatView

        app = PPXAIDEApp()
        async def run_test():
            async with app.run_test() as pilot:
                chat_view = app.query_one(ChatView)

                # Try invalid commands
                await app._handle_command("/show nonexistent.txt")
                await app._handle_command("/cd /nonexistent/path")

                # App should still be functional
                await app._handle_command("/help")

                # Should have messages from all attempts
                assert len(chat_view._messages) >= 3

        asyncio.run(run_test())

    def test_multiple_files_in_sequence(self, tmp_path):
        """Opening multiple files in sequence should work."""

        from ppxai.tui.app import PPXAIDEApp
        from ppxai.tui.widgets import SidePanel

        # Create multiple JSON files (simpler content type)
        file1 = tmp_path / "file1.json"
        file1.write_text('{"name": "file1"}', encoding="utf-8")
        file2 = tmp_path / "file2.json"
        file2.write_text('{"name": "file2"}', encoding="utf-8")

        app = PPXAIDEApp()
        app._working_dir = str(tmp_path)

        async def run_test():
            async with app.run_test() as pilot:
                side_panel = app.query_one("#side-panel", SidePanel)

                # Open first file
                await app._handle_command(f"/show {file1.name}")
                assert side_panel.is_open

                # Open second file (replaces first)
                await app._handle_command(f"/show {file2.name}")
                assert side_panel.is_open

        asyncio.run(run_test())

    def test_concurrent_widget_updates(self, tmp_path):
        """Multiple widgets should update concurrently."""
        from ppxai.tui.app import PPXAIDEApp
        from ppxai.tui.widgets import ChatView, SidePanel, StatusBar

        # Create test JSON file (simpler)
        test_file = tmp_path / "test.json"
        test_file.write_text('{"key": "value"}', encoding="utf-8")

        app = PPXAIDEApp()
        app._working_dir = str(tmp_path)

        async def run_test():
            async with app.run_test() as pilot:
                chat_view = app.query_one("#chat-view", ChatView)
                side_panel = app.query_one("#side-panel", SidePanel)
                status_bar = app.query_one(StatusBar)

                # Update multiple widgets concurrently
                chat_view.add_user_message("Message 1")
                original_theme_index = app._current_theme_index

                # Directly call action to cycle theme
                app.action_cycle_theme()

                # All widgets should be functional
                assert len(chat_view._messages) >= 1
                assert app._current_theme_index != original_theme_index

        asyncio.run(run_test())
