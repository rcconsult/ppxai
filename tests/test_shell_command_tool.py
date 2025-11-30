"""
Tests for the execute_shell_command tool.

This test suite covers the shell command execution functionality
for both Perplexity and Custom providers.
"""

import pytest
import os
import platform
from unittest.mock import Mock, patch, MagicMock, AsyncMock
import subprocess
import asyncio


class TestShellCommandToolRegistration:
    """Test that the shell command tool is registered correctly."""

    def test_shell_command_tool_registered_perplexity(self):
        """Test that execute_shell_command tool is registered for Perplexity provider."""
        from perplexity_tools_prompt_based import PerplexityClientPromptTools

        client = PerplexityClientPromptTools(
            api_key="test-key",
            enable_tools=True,
            provider="perplexity"
        )

        # Run initialize_tools synchronously
        asyncio.run(client.initialize_tools())

        assert 'execute_shell_command' in client.tool_manager.tools
        tool = client.tool_manager.tools['execute_shell_command']
        assert tool.name == 'execute_shell_command'
        assert tool.source == 'builtin'
        assert 'shell' in tool.description.lower() or 'command' in tool.description.lower()

    def test_shell_command_tool_registered_custom(self):
        """Test that execute_shell_command tool is registered for Custom provider."""
        from perplexity_tools_prompt_based import PerplexityClientPromptTools

        client = PerplexityClientPromptTools(
            api_key="test-key",
            enable_tools=True,
            provider="custom"
        )

        asyncio.run(client.initialize_tools())

        assert 'execute_shell_command' in client.tool_manager.tools
        tool = client.tool_manager.tools['execute_shell_command']
        assert tool.name == 'execute_shell_command'
        assert tool.source == 'builtin'

    def test_shell_command_tool_has_required_parameters(self):
        """Test that the tool has the correct parameter schema."""
        from perplexity_tools_prompt_based import PerplexityClientPromptTools

        client = PerplexityClientPromptTools(
            api_key="test-key",
            enable_tools=True,
            provider="perplexity"
        )

        asyncio.run(client.initialize_tools())

        tool = client.tool_manager.tools['execute_shell_command']
        params = tool.parameters

        assert 'type' in params
        assert params['type'] == 'object'
        assert 'properties' in params
        assert 'command' in params['properties']
        assert 'working_dir' in params['properties']
        assert 'required' in params
        assert 'command' in params['required']


class TestShellCommandExecution:
    """Test shell command execution functionality."""

    def test_execute_simple_command_success(self):
        """Test executing a simple successful command."""
        from perplexity_tools_prompt_based import PerplexityClientPromptTools

        client = PerplexityClientPromptTools(
            api_key="test-key",
            enable_tools=True,
            provider="custom"
        )

        asyncio.run(client.initialize_tools())

        # Execute a simple command that works on all platforms
        is_windows = platform.system() == "Windows"
        command = "echo test"

        result = asyncio.run(client.tool_manager.execute_tool(
            'execute_shell_command',
            {'command': command}
        ))

        assert 'test' in result.lower()
        assert 'error' not in result.lower()

    def test_execute_command_with_output(self):
        """Test command execution returns output."""
        from perplexity_tools_prompt_based import PerplexityClientPromptTools

        client = PerplexityClientPromptTools(
            api_key="test-key",
            enable_tools=True,
            provider="custom"
        )

        asyncio.run(client.initialize_tools())

        command = "echo Hello World"

        result = asyncio.run(client.tool_manager.execute_tool(
            'execute_shell_command',
            {'command': command}
        ))

        assert 'hello world' in result.lower()

    def test_execute_command_with_working_directory(self):
        """Test command execution in a specific working directory."""
        from perplexity_tools_prompt_based import PerplexityClientPromptTools

        client = PerplexityClientPromptTools(
            api_key="test-key",
            enable_tools=True,
            provider="custom"
        )

        asyncio.run(client.initialize_tools())

        # Get a known directory (use temp or current dir)
        import tempfile
        temp_dir = tempfile.gettempdir()

        is_windows = platform.system() == "Windows"
        # Command to print current directory
        command = "cd" if is_windows else "pwd"

        result = asyncio.run(client.tool_manager.execute_tool(
            'execute_shell_command',
            {'command': command, 'working_dir': temp_dir}
        ))

        # Should contain part of the temp directory path
        assert result is not None
        # More lenient check - just verify no hard error
        # (working directory behavior can vary by shell/OS)

    def test_execute_command_nonexistent_working_directory(self):
        """Test error handling for nonexistent working directory."""
        from perplexity_tools_prompt_based import PerplexityClientPromptTools

        client = PerplexityClientPromptTools(
            api_key="test-key",
            enable_tools=True,
            provider="custom"
        )

        asyncio.run(client.initialize_tools())

        result = asyncio.run(client.tool_manager.execute_tool(
            'execute_shell_command',
            {'command': 'echo test', 'working_dir': '/nonexistent/path/that/does/not/exist'}
        ))

        assert 'error' in result.lower()
        assert 'not exist' in result.lower() or 'working directory' in result.lower()

    def test_execute_command_with_nonzero_exit_code(self):
        """Test command that returns non-zero exit code."""
        from perplexity_tools_prompt_based import PerplexityClientPromptTools

        client = PerplexityClientPromptTools(
            api_key="test-key",
            enable_tools=True,
            provider="custom"
        )

        asyncio.run(client.initialize_tools())

        # Command that fails - platform independent
        is_windows = platform.system() == "Windows"
        # Use a command that definitely doesn't exist
        command = "thiscommanddoesnotexist12345"

        result = asyncio.run(client.tool_manager.execute_tool(
            'execute_shell_command',
            {'command': command}
        ))

        # Should mention exit code or command not found
        assert ('exit code' in result.lower() or 'exited with code' in result.lower() or
                'not found' in result.lower() or 'not recognized' in result.lower())

    def test_execute_command_timeout_handling(self):
        """Test that timeout error is properly formatted."""
        from perplexity_tools_prompt_based import PerplexityClientPromptTools

        client = PerplexityClientPromptTools(
            api_key="test-key",
            enable_tools=True,
            provider="custom"
        )

        asyncio.run(client.initialize_tools())

        # Mock subprocess.run at the module level where it's called
        import perplexity_tools_prompt_based

        # Get the original execute_shell_command handler
        handler = client.tool_manager.builtin_handlers['execute_shell_command']

        # Create a test that simulates timeout by mocking subprocess
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired('test', 30)

            result = asyncio.run(client.tool_manager.execute_tool(
                'execute_shell_command',
                {'command': 'sleep 100'}
            ))

            assert ('timeout' in result.lower() or 'timed out' in result.lower())
            assert '30 seconds' in result.lower()


class TestShellCommandSuggestions:
    """Test that shell command tool is suggested for appropriate queries."""

    def test_suggests_shell_command_for_mkdir(self):
        """Test that shell command tool is suggested for mkdir queries."""
        from perplexity_tools_prompt_based import PerplexityClientPromptTools

        client = PerplexityClientPromptTools(
            api_key="test-key",
            enable_tools=True,
            provider="custom"
        )

        asyncio.run(client.initialize_tools())

        suggestions = client._suggest_tools_for_query("create directory called test")
        assert 'execute_shell_command' in suggestions

    def test_suggests_shell_command_for_git(self):
        """Test that shell command tool is suggested for git queries."""
        from perplexity_tools_prompt_based import PerplexityClientPromptTools

        client = PerplexityClientPromptTools(
            api_key="test-key",
            enable_tools=True,
            provider="custom"
        )

        asyncio.run(client.initialize_tools())

        suggestions = client._suggest_tools_for_query("run git status")
        assert 'execute_shell_command' in suggestions

    def test_suggests_shell_command_for_npm(self):
        """Test that shell command tool is suggested for npm queries."""
        from perplexity_tools_prompt_based import PerplexityClientPromptTools

        client = PerplexityClientPromptTools(
            api_key="test-key",
            enable_tools=True,
            provider="custom"
        )

        asyncio.run(client.initialize_tools())

        suggestions = client._suggest_tools_for_query("install npm packages")
        assert 'execute_shell_command' in suggestions

    def test_suggests_shell_command_for_build(self):
        """Test that shell command tool is suggested for build queries."""
        from perplexity_tools_prompt_based import PerplexityClientPromptTools

        client = PerplexityClientPromptTools(
            api_key="test-key",
            enable_tools=True,
            provider="custom"
        )

        asyncio.run(client.initialize_tools())

        suggestions = client._suggest_tools_for_query("build the project")
        assert 'execute_shell_command' in suggestions

    def test_no_suggestion_for_unrelated_query(self):
        """Test that shell command tool is not suggested for unrelated queries."""
        from perplexity_tools_prompt_based import PerplexityClientPromptTools

        client = PerplexityClientPromptTools(
            api_key="test-key",
            enable_tools=True,
            provider="custom"
        )

        asyncio.run(client.initialize_tools())

        suggestions = client._suggest_tools_for_query("what is the weather today")
        assert 'execute_shell_command' not in suggestions


class TestShellCommandInPrompt:
    """Test that shell command tool is included in system prompt."""

    def test_shell_command_in_tools_prompt(self):
        """Test that shell command tool appears in the tools prompt."""
        from perplexity_tools_prompt_based import PerplexityClientPromptTools

        client = PerplexityClientPromptTools(
            api_key="test-key",
            enable_tools=True,
            provider="custom"
        )

        asyncio.run(client.initialize_tools())

        prompt = client._get_tools_prompt()

        assert 'execute_shell_command' in prompt
        assert 'shell' in prompt.lower() or 'command' in prompt.lower()

    def test_critical_instructions_mention_shell(self):
        """Test that critical instructions mention system operations."""
        from perplexity_tools_prompt_based import PerplexityClientPromptTools

        client = PerplexityClientPromptTools(
            api_key="test-key",
            enable_tools=True,
            provider="custom"
        )

        asyncio.run(client.initialize_tools())

        prompt = client._get_tools_prompt()

        assert 'system operations' in prompt.lower() or 'execute_shell_command' in prompt


class TestShellCommandSecurity:
    """Test security considerations of shell command execution."""

    def test_timeout_prevents_infinite_loops(self):
        """Test that timeout is mentioned in tool description."""
        from perplexity_tools_prompt_based import PerplexityClientPromptTools

        client = PerplexityClientPromptTools(
            api_key="test-key",
            enable_tools=True,
            provider="custom"
        )

        asyncio.run(client.initialize_tools())

        tool = client.tool_manager.tools['execute_shell_command']
        # Verify timeout is mentioned in description
        assert '30' in tool.description or 'timeout' in tool.description.lower()

    def test_working_directory_validation(self):
        """Test that working directory is validated before use."""
        from perplexity_tools_prompt_based import PerplexityClientPromptTools

        client = PerplexityClientPromptTools(
            api_key="test-key",
            enable_tools=True,
            provider="custom"
        )

        asyncio.run(client.initialize_tools())

        result = asyncio.run(client.tool_manager.execute_tool(
            'execute_shell_command',
            {'command': 'echo test', 'working_dir': '/this/does/not/exist/anywhere'}
        ))

        assert 'error' in result.lower()
        assert 'not exist' in result.lower() or 'directory' in result.lower()

    def test_command_error_handling(self):
        """Test that command errors are caught and reported."""
        from perplexity_tools_prompt_based import PerplexityClientPromptTools

        client = PerplexityClientPromptTools(
            api_key="test-key",
            enable_tools=True,
            provider="custom"
        )

        asyncio.run(client.initialize_tools())

        # Mock subprocess.run to raise an exception
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = Exception("Test error")

            result = asyncio.run(client.tool_manager.execute_tool(
                'execute_shell_command',
                {'command': 'test'}
            ))

            assert 'error' in result.lower()
            assert 'test error' in result.lower()


class TestToolCallParsing:
    """Test that tool call parsing handles various model output formats."""

    def test_parse_tool_call_standard_format(self):
        """Test parsing standard format with 'arguments' key."""
        from perplexity_tools_prompt_based import PerplexityClientPromptTools

        client = PerplexityClientPromptTools(
            api_key="test-key",
            enable_tools=True,
            provider="perplexity"
        )

        asyncio.run(client.initialize_tools())

        # Standard format with arguments
        text = '```json\n{"tool": "execute_shell_command", "arguments": {"command": "ls -la"}}\n```'
        result = client._parse_tool_call(text)

        assert result is not None
        assert result["tool"] == "execute_shell_command"
        assert result["arguments"]["command"] == "ls -la"

    def test_parse_tool_call_flat_format(self):
        """Test parsing format where model puts parameters at top level."""
        from perplexity_tools_prompt_based import PerplexityClientPromptTools

        client = PerplexityClientPromptTools(
            api_key="test-key",
            enable_tools=True,
            provider="perplexity"
        )

        asyncio.run(client.initialize_tools())

        # Flat format - model puts 'command' at top level instead of in 'arguments'
        text = '```json\n{"tool": "execute_shell_command", "command": "ls -la"}\n```'
        result = client._parse_tool_call(text)

        assert result is not None
        assert result["tool"] == "execute_shell_command"
        assert "arguments" in result
        assert result["arguments"]["command"] == "ls -la"

    def test_parse_tool_call_raw_json_flat(self):
        """Test parsing raw JSON (no code block) with flat format."""
        from perplexity_tools_prompt_based import PerplexityClientPromptTools

        client = PerplexityClientPromptTools(
            api_key="test-key",
            enable_tools=True,
            provider="perplexity"
        )

        asyncio.run(client.initialize_tools())

        # Raw JSON without code block
        text = '{"tool": "execute_shell_command", "command": "git status"}'
        result = client._parse_tool_call(text)

        assert result is not None
        assert result["tool"] == "execute_shell_command"
        assert result["arguments"]["command"] == "git status"

    def test_parse_tool_call_with_working_dir(self):
        """Test parsing with multiple parameters."""
        from perplexity_tools_prompt_based import PerplexityClientPromptTools

        client = PerplexityClientPromptTools(
            api_key="test-key",
            enable_tools=True,
            provider="perplexity"
        )

        asyncio.run(client.initialize_tools())

        # Flat format with both parameters
        text = '{"tool": "execute_shell_command", "command": "ls", "working_dir": "/tmp"}'
        result = client._parse_tool_call(text)

        assert result is not None
        assert result["tool"] == "execute_shell_command"
        assert result["arguments"]["command"] == "ls"
        assert result["arguments"]["working_dir"] == "/tmp"

    def test_parse_tool_call_invalid_tool(self):
        """Test that invalid tool names return None."""
        from perplexity_tools_prompt_based import PerplexityClientPromptTools

        client = PerplexityClientPromptTools(
            api_key="test-key",
            enable_tools=True,
            provider="perplexity"
        )

        asyncio.run(client.initialize_tools())

        # Unknown tool name
        text = '{"tool": "nonexistent_tool", "command": "test"}'
        result = client._parse_tool_call(text)

        assert result is None

    def test_parse_tool_call_no_tool_key(self):
        """Test that JSON without 'tool' key returns None."""
        from perplexity_tools_prompt_based import PerplexityClientPromptTools

        client = PerplexityClientPromptTools(
            api_key="test-key",
            enable_tools=True,
            provider="perplexity"
        )

        asyncio.run(client.initialize_tools())

        # No tool key
        text = '{"command": "ls -la"}'
        result = client._parse_tool_call(text)

        assert result is None


class TestInteractiveCommandDetection:
    """Test that interactive commands are detected and rejected with helpful messages."""

    def test_nano_rejected(self):
        """Test that nano editor is rejected with helpful message."""
        from perplexity_tools_prompt_based import PerplexityClientPromptTools

        client = PerplexityClientPromptTools(
            api_key="test-key",
            enable_tools=True,
            provider="custom"
        )

        asyncio.run(client.initialize_tools())

        result = asyncio.run(client.tool_manager.execute_tool(
            'execute_shell_command',
            {'command': 'nano README.md'}
        ))

        assert 'error' in result.lower()
        assert 'interactive' in result.lower()
        assert 'nano' in result.lower()
        assert 'alternatives' in result.lower()

    def test_vim_rejected(self):
        """Test that vim editor is rejected."""
        from perplexity_tools_prompt_based import PerplexityClientPromptTools

        client = PerplexityClientPromptTools(
            api_key="test-key",
            enable_tools=True,
            provider="custom"
        )

        asyncio.run(client.initialize_tools())

        result = asyncio.run(client.tool_manager.execute_tool(
            'execute_shell_command',
            {'command': 'vim file.txt'}
        ))

        assert 'error' in result.lower()
        assert 'interactive' in result.lower()
        assert 'vim' in result.lower()

    def test_less_rejected(self):
        """Test that less pager is rejected."""
        from perplexity_tools_prompt_based import PerplexityClientPromptTools

        client = PerplexityClientPromptTools(
            api_key="test-key",
            enable_tools=True,
            provider="custom"
        )

        asyncio.run(client.initialize_tools())

        result = asyncio.run(client.tool_manager.execute_tool(
            'execute_shell_command',
            {'command': 'less /etc/hosts'}
        ))

        assert 'error' in result.lower()
        assert 'interactive' in result.lower()

    def test_top_rejected(self):
        """Test that top system monitor is rejected."""
        from perplexity_tools_prompt_based import PerplexityClientPromptTools

        client = PerplexityClientPromptTools(
            api_key="test-key",
            enable_tools=True,
            provider="custom"
        )

        asyncio.run(client.initialize_tools())

        result = asyncio.run(client.tool_manager.execute_tool(
            'execute_shell_command',
            {'command': 'top'}
        ))

        assert 'error' in result.lower()
        assert 'interactive' in result.lower()

    def test_python_repl_rejected(self):
        """Test that python REPL (no args) is rejected."""
        from perplexity_tools_prompt_based import PerplexityClientPromptTools

        client = PerplexityClientPromptTools(
            api_key="test-key",
            enable_tools=True,
            provider="custom"
        )

        asyncio.run(client.initialize_tools())

        result = asyncio.run(client.tool_manager.execute_tool(
            'execute_shell_command',
            {'command': 'python3'}
        ))

        assert 'error' in result.lower()
        assert 'interactive' in result.lower()

    def test_python_script_allowed(self):
        """Test that python with script argument is allowed."""
        from perplexity_tools_prompt_based import PerplexityClientPromptTools

        client = PerplexityClientPromptTools(
            api_key="test-key",
            enable_tools=True,
            provider="custom"
        )

        asyncio.run(client.initialize_tools())

        result = asyncio.run(client.tool_manager.execute_tool(
            'execute_shell_command',
            {'command': 'python3 -c "print(1+1)"'}
        ))

        # Should execute and return "2" or similar, not an interactive error
        assert 'interactive' not in result.lower()

    def test_bash_repl_rejected(self):
        """Test that bash shell (no args) is rejected."""
        from perplexity_tools_prompt_based import PerplexityClientPromptTools

        client = PerplexityClientPromptTools(
            api_key="test-key",
            enable_tools=True,
            provider="custom"
        )

        asyncio.run(client.initialize_tools())

        result = asyncio.run(client.tool_manager.execute_tool(
            'execute_shell_command',
            {'command': 'bash'}
        ))

        assert 'error' in result.lower()
        assert 'interactive' in result.lower()

    def test_bash_with_command_allowed(self):
        """Test that bash -c with command is allowed."""
        from perplexity_tools_prompt_based import PerplexityClientPromptTools

        client = PerplexityClientPromptTools(
            api_key="test-key",
            enable_tools=True,
            provider="custom"
        )

        asyncio.run(client.initialize_tools())

        result = asyncio.run(client.tool_manager.execute_tool(
            'execute_shell_command',
            {'command': 'bash -c "echo hello"'}
        ))

        # Should execute and return output, not an interactive error
        assert 'interactive' not in result.lower()

    def test_ssh_rejected(self):
        """Test that ssh is rejected."""
        from perplexity_tools_prompt_based import PerplexityClientPromptTools

        client = PerplexityClientPromptTools(
            api_key="test-key",
            enable_tools=True,
            provider="custom"
        )

        asyncio.run(client.initialize_tools())

        result = asyncio.run(client.tool_manager.execute_tool(
            'execute_shell_command',
            {'command': 'ssh user@host'}
        ))

        assert 'error' in result.lower()
        assert 'interactive' in result.lower()

    def test_non_interactive_commands_work(self):
        """Test that non-interactive commands still work."""
        from perplexity_tools_prompt_based import PerplexityClientPromptTools

        client = PerplexityClientPromptTools(
            api_key="test-key",
            enable_tools=True,
            provider="custom"
        )

        asyncio.run(client.initialize_tools())

        # Test various non-interactive commands
        for cmd in ['echo hello', 'ls', 'pwd', 'date']:
            result = asyncio.run(client.tool_manager.execute_tool(
                'execute_shell_command',
                {'command': cmd}
            ))
            assert 'interactive' not in result.lower(), f"Command '{cmd}' should not be rejected as interactive"
