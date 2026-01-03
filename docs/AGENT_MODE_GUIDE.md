# Agent Mode User Guide

**Version**: v1.13.0+
**Status**: Production Ready

This guide explains how to use ppxai's autonomous agent mode for multi-step task execution.

---

## Table of Contents

1. [Overview](#overview)
2. [Getting Started](#getting-started)
3. [Commands Reference](#commands-reference)
4. [Research Workflows](#research-workflows)
5. [Development Workflows](#development-workflows)
6. [VSCode Extension](#vscode-extension)
7. [Best Practices](#best-practices)
8. [Troubleshooting](#troubleshooting)

---

## Overview

Agent mode transforms ppxai from a turn-based chat assistant into an autonomous developer agent. Instead of requiring manual direction for each step, the agent can:

- **Plan** - Analyze tasks and create execution strategies
- **Execute** - Use tools to read, edit files, and run commands
- **Verify** - Check results and iterate until complete
- **Report** - Summarize what was accomplished

### How It Works

![Agent Flow Diagram](future-agentic-flow.png)

1. You issue an `/agent <task>` command
2. The agent enters an autonomous loop (max 10 iterations by default)
3. Each iteration: Plan → Execute tools → Check completion
4. Loop continues until:
   - AI signals `TASK_COMPLETE:` (success)
   - Max iterations reached (configurable, default: 10)
   - User interrupts with Ctrl-C

### Comparison: Turn-Based vs Agent Mode

| Aspect | Turn-Based (Default) | Agent Mode |
|--------|---------------------|------------|
| User involvement | Every step | Initial task only |
| Tool calls | Single per turn | Multiple per iteration |
| Iterations | Manual | Automatic (up to 10) |
| Best for | Simple queries | Multi-step tasks |

---

## Getting Started

### Prerequisites

1. Tools must be available (they are auto-enabled with agent mode)
2. For file editing, you'll need to approve edits (consent system)

### Quick Start

```bash
# Start ppxai
ppxai

# Enable agent mode (optional - auto-enabled when using /agent)
/tools agent on

# Run an autonomous task
/agent Fix the failing test in test_auth.py
```

### Your First Agent Task

Try this simple task to see agent mode in action:

```bash
/agent Create a hello.py file that prints "Hello, Agent Mode!"
```

The agent will:
1. Analyze the task
2. Use `insert_text` tool to create the file
3. Signal completion with a summary

---

## Commands Reference

### `/agent <task>` - Run Autonomous Task

The main command for agent mode. Runs an autonomous loop until the task is complete.

**Syntax:**
```bash
/agent <task description>
```

**Examples:**
```bash
# Simple file creation
/agent Create a Python script that calculates fibonacci numbers

# Bug fixing
/agent Fix the TypeError in utils.py line 42

# Code review with context
/agent Review @git changes and fix any issues

# Refactoring with structure awareness
/agent Reorganize the API module based on @tree
```

**Interrupt:** Press `Ctrl-C` at any time to stop the agent loop.

### `/tools agent` - Manage Agent Mode

Enable, disable, or check agent mode status.

**Syntax:**
```bash
/tools agent          # Show current status
/tools agent on       # Enable agent mode
/tools agent off      # Disable agent mode
```

**Notes:**
- Enabling agent mode automatically enables tools
- Agent mode is session-scoped (resets on restart)

### Context Providers with Agent Mode

Agent mode works seamlessly with context providers:

| Provider | Description | Example |
|----------|-------------|---------|
| `@file` | Include file contents | `/agent Refactor @auth.py` |
| `@git` | Include git diff | `/agent Review @git and fix issues` |
| `@tree` | Include project structure | `/agent Suggest improvements for @tree` |

**Combined usage:**
```bash
/agent Review my changes @git in the context of @tree and fix any bugs
```

---

## Research Workflows

Agent mode excels at research and analysis tasks that require multiple steps.

### Codebase Analysis

```bash
# Find and explain a pattern
/agent Find all uses of the Observer pattern in this codebase and explain how they work

# Security audit
/agent Analyze @tree for potential security issues and list them

# Dependency analysis
/agent Review the imports in @main.py and identify any unused or deprecated dependencies
```

### Code Review Workflow

```bash
# Review staged changes
/agent Review @git changes for bugs, security issues, and style problems

# Compare with design doc
/agent Compare my implementation @git against the spec in DESIGN.md
```

### Documentation Research

```bash
# Generate documentation
/agent Read @utils.py and generate comprehensive docstrings for all functions

# Update outdated docs
/agent Compare @README.md with the current @tree structure and update outdated sections
```

---

## Development Workflows

Agent mode is powerful for development tasks that span multiple files.

### Bug Fixing

```bash
# Single file fix
/agent Fix the failing test in test_auth.py

# Multi-file fix
/agent The login fails with 401 - find the cause in auth.py and fix it

# With test verification
/agent Fix the bug in parser.py and verify the tests pass
```

### Feature Implementation

```bash
# Simple feature
/agent Add a --verbose flag to the CLI

# Multi-step feature
/agent Implement user session management with tests

# With context
/agent Based on @tree, add a caching layer in the appropriate location
```

### Refactoring

```bash
# Rename across files
/agent Rename the class 'OldName' to 'NewName' in all files

# Extract function
/agent Extract the validation logic from auth.py into a separate validator.py

# Restructure
/agent Based on @tree, move utility functions from main.py to utils.py
```

### Test Development

```bash
# Generate tests
/agent Generate unit tests for @calculator.py

# Fix failing tests
/agent Fix all failing tests in tests/test_api.py

# Add test coverage
/agent Add edge case tests for the parse_date function in utils.py
```

---

## VSCode Extension

The VSCode extension provides a graphical interface for agent mode.

### Agent Toggle Button

In the ppxai chat panel, you'll see an **Agent** button next to the **Tools** button:

- **Gray (OFF)**: Agent mode disabled
- **Purple (ON)**: Agent mode enabled

Click to toggle. When enabled, tools are automatically enabled.

### Using Agent Mode in VSCode

1. Click the **Agent** button to enable agent mode
2. Type your task in the chat input
3. The agent will execute autonomously
4. Watch the streaming output for progress
5. Use Esc or the stop button to interrupt

### HTTP API Endpoints

If using the HTTP server directly:

```bash
# Check status
curl http://127.0.0.1:54320/agent/status

# Enable
curl -X POST http://127.0.0.1:54320/agent/enable

# Disable
curl -X POST http://127.0.0.1:54320/agent/disable
```

---

## Best Practices

### Writing Effective Tasks

**Be specific:**
```bash
# Good - specific target and action
/agent Fix the TypeError on line 42 of utils.py

# Less effective - vague
/agent Fix bugs
```

**Include context:**
```bash
# Good - context provided
/agent Review @git changes for security issues in the auth module

# Less effective - missing context
/agent Check for security issues
```

**Define success criteria:**
```bash
# Good - clear completion criteria
/agent Implement user validation and ensure all tests pass

# Less effective - unclear when done
/agent Add validation
```

### Managing Consent

The agent requires consent for file edits:

| Response | Effect |
|----------|--------|
| `y` (yes) | Allow this specific file edit |
| `n` (no) | Deny this edit |
| `always` | Allow all edits this session (autonomous mode) |
| `never` | Block all edits this session |

**Tip:** For fully autonomous execution, respond `always` to the first consent prompt.

### Handling Interrupts

- **Ctrl-C (once)**: Gracefully stops the current iteration
- **Ctrl-C (twice within 2s)**: Force stops immediately

After interrupting, the agent will summarize progress made.

### Iteration Limits

The default max is 10 iterations (configurable via `tools.agent.max_iterations`). If your task needs more:

1. Let the agent complete its iterations
2. Review the output
3. Run `/agent continue` or issue a follow-up task

---

## Configuration

Agent mode behavior can be customized in `ppxai-config.json`:

```json
{
  "tools": {
    "agent": {
      "max_iterations": 10,
      "context_char_limit": 2000,
      "min_task_words": 3
    }
  }
}
```

### Configuration Options

| Setting | Default | Description |
|---------|---------|-------------|
| `max_iterations` | 10 | Maximum autonomous loop iterations before stopping |
| `context_char_limit` | 2000 | Character limit for context display in tool results |
| `min_task_words` | 3 | Minimum word count required for agent tasks |

### Why These Settings Exist

**`max_iterations`**: Prevents runaway agent loops that could consume excessive API tokens or run indefinitely. The default of 10 balances giving the agent enough room to complete complex tasks while preventing infinite loops.

- **Lower values (3-5)**: Safer for simple tasks, uses fewer tokens, faster completion
- **Higher values (15-20)**: Allows complex multi-step tasks, but risks more API usage
- **Warning**: Values above 20 may lead to excessive token consumption

**`context_char_limit`**: Controls how much context from tool results is shown in the UI and passed back to the AI. Higher limits provide more context for accurate decisions but increase token usage.

- **Lower values (500-1000)**: Faster, cheaper, but may miss important details
- **Higher values (3000-5000)**: Better context retention, but more expensive
- **Warning**: Very high limits (>5000) may cause context overflow in some models

**`min_task_words`**: Safety feature that rejects vague single-word tasks. This prevents accidental dangerous actions from ambiguous commands like `/agent on` or `/agent delete`.

- **Default (3)**: Requires descriptive tasks like "Fix the bug in auth.py"
- **Lower values (1-2)**: Less safe, allows vague tasks
- **Warning**: Setting to 1 removes this safety check entirely

### Shell Command Safety

Agent mode includes built-in shell command safety patterns. These patterns are always active even without a config file:

**Dangerous patterns (require consent):**
- `rm`, `mv`, `dd`, `chmod`, `chown`, `sudo`
- `kill`, `pkill`, `killall`
- `curl | bash`, `wget | bash`

**Never-allow patterns (always blocked):**
- `rm -rf /`, `dd of=/dev/`
- Fork bombs and system-level destructive commands

You can customize these in `ppxai-config.json`:

```json
{
  "tools": {
    "shell": {
      "safe_patterns": ["^ls\\s*", "^cat\\s+"],
      "dangerous_patterns": ["^rm\\s+", "^kill\\s+"],
      "never_allow_patterns": ["^rm\\s+-rf\\s+/"]
    }
  }
}
```

See [Shell Consent Guide](SHELL_CONSENT_GUIDE.md) for complete documentation.

---

## Troubleshooting

### Agent Not Starting

**Problem:** `/agent` command shows error

**Solutions:**
1. Ensure engine client is available: Check if ppxai started correctly
2. Try enabling tools manually: `/tools enable`
3. Check provider supports tools: Not all providers have tool support

### Agent Gets Stuck

**Problem:** Agent loops without making progress

**Solutions:**
1. Interrupt with Ctrl-C
2. Provide more specific instructions
3. Break the task into smaller sub-tasks

### Consent Prompts Interrupting Flow

**Problem:** Too many consent prompts

**Solutions:**
1. Respond `always` to enable autonomous file editing
2. Pre-approve directories in config (future feature)

### Max Iterations Reached

**Problem:** Task incomplete after max iterations

**Solutions:**
1. Review the agent's progress
2. Run a follow-up `/agent` command with updated context
3. Consider if the task should be split into smaller parts

### Tool Errors

**Problem:** Agent reports tool execution failed

**Solutions:**
1. Check file permissions
2. Verify the target file exists
3. Enable verbose mode: `/tools set verbose on`

---

## Examples: Complete Workflows

### Example 1: Debug and Fix

```bash
# Start agent mode
/tools agent on

# Run autonomous debugging
/agent The tests in test_parser.py are failing. Find the bug and fix it.

# Agent output:
# ━━━ Iteration 1/5 ━━━
# Analyzing test failures...
# [Uses read_file to check test_parser.py]
# Found assertion error on line 45...
#
# ━━━ Iteration 2/5 ━━━
# Reading parser.py to find the bug...
# [Uses read_file to check parser.py]
# Found issue: off-by-one error on line 78...
#
# ━━━ Iteration 3/5 ━━━
# Applying fix...
# [Uses replace_block to fix parser.py]
# [Uses execute_shell_command to run tests]
# Tests pass!
#
# ✅ Task completed!
# Summary: Fixed off-by-one error in parser.py line 78. All tests now pass.
```

### Example 2: Code Review

```bash
# Review git changes
/agent Review @git changes for bugs and security issues

# Agent output:
# ━━━ Iteration 1/5 ━━━
# Analyzing git diff...
# Found changes in: auth.py, api.py, utils.py
#
# Issues found:
# 1. SQL injection risk in api.py line 42
# 2. Hardcoded secret in auth.py line 15
# 3. Missing input validation in utils.py
#
# ━━━ Iteration 2/5 ━━━
# Fixing SQL injection...
# [Uses replace_block to parameterize query]
#
# ━━━ Iteration 3/5 ━━━
# Moving secret to environment variable...
# [Uses replace_block in auth.py]
#
# ✅ Task completed!
# Summary: Fixed 2 security issues. auth.py now uses env var, api.py uses parameterized queries.
```

### Example 3: Feature Implementation

```bash
# Implement a feature
/agent Add a --dry-run flag to the CLI that shows what would happen without making changes

# Agent iterates through:
# 1. Reading CLI entry point
# 2. Adding argument parser option
# 3. Implementing dry-run logic
# 4. Updating help text
# 5. Testing the feature
#
# ✅ Task completed!
```

---

## Related Documentation

- [Checkpoint Guide](CHECKPOINT_GUIDE.md) - Atomic rollback for agent tasks
- [Shell Consent Guide](SHELL_CONSENT_GUIDE.md) - Shell command security
- [Custom Tools Guide](CUSTOM_TOOL_DEVELOPMENT_GUIDE.md) - Creating custom tools
- [Agentic Workflow Plan](v1.11.0-agentic-workflow-plan.md) - Technical implementation details

---

**Last Updated:** 2026-01-03
**Version:** v1.13.0
