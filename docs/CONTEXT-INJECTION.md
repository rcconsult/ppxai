# Context Injection Guide

**Version:** v1.11.4+
**Last Updated:** 2025-12-24

## Overview

ppxai supports automatic context injection via `@` references. Type special keywords in your messages to automatically include file contents, git changes, or project structure in your AI conversations.

## Supported Context Providers

### 1. File References (`@filename`)

Include file contents in your message.

**Syntax:**
```
@/path/to/file.py
@./relative/file.js
@~/home/directory/file.txt
@"path with spaces.md"
```

**Examples:**
```
Review the implementation in @src/utils.py

Compare @file1.py and @file2.py

Explain what @./README.md describes
```

**Features:**
- Detects `.py`, `.js`, `.md`, and 90+ file extensions
- Auto-detects language for syntax highlighting
- Truncates large files (max 100KB per file, 200KB total)
- Skips binary files automatically
- Supports relative, absolute, and home directory paths

**Automatic Injection:**
Context is automatically injected when:
- Message contains `@` followed by a file path
- Message contains keywords: `read`, `show`, `display`, `explain`, `review`, `analyze`
- Message is short (≤10 words) and mentions a file

### 2. Git Changes (`@git`)

Include current git diff (staged and unstaged changes) in your message.

**Syntax:**
```
@git
```

**Examples:**
```
Review the changes in @git

Based on @git, suggest improvements to the code

Explain what was modified in @git
```

**What's Included:**
- **Staged changes** (`git diff --staged`) - Files added with `git add`
- **Unstaged changes** (`git diff`) - Modified files not yet staged
- Both shown with unified diff format

**Output Format:**
```
=== Staged Changes ===
diff --git a/file.py b/file.py
...

=== Unstaged Changes ===
diff --git a/file.js b/file.js
...
```

**Edge Cases:**
- Returns `None` if not in a git repository
- Returns "No changes in working directory" if clean working tree
- Skipped if git is not installed

### 3. Project Structure (`@tree`)

Include directory tree structure in your message.

**Syntax:**
```
@tree
```

**Examples:**
```
Here's the project structure: @tree

Based on @tree, suggest where to add the new module

Review @tree and identify missing test files
```

**What's Included:**
- Directory tree with ASCII art (├── └── │)
- File and directory counts
- Respects common ignore patterns
- Configurable maximum depth (default: 3)

**Output Format:**
```
Project: ppxai
Directories: 15, Files: 42
Max depth: 3

ppxai/
├── __init__.py
├── main.py
├── config.py
├── engine/
│   ├── __init__.py
│   ├── client.py
│   └── types.py
└── tests/
    ├── test_config.py
    └── test_engine.py
```

**Ignored Patterns:**
- `.git`, `__pycache__`, `node_modules`, `.venv`, `venv`
- `.pytest_cache`, `.mypy_cache`, `dist`, `build`
- Hidden files (except `.gitignore`, `.env.example`, `.dockerignore`)

**Configuration:**
```python
# Adjust max depth programmatically
injector.inject_tree_context(max_depth=5)
```

## Combined Usage

You can use multiple context providers in the same message:

```
Review @git changes, check @tree structure, and update @src/README.md accordingly
```

This will inject:
1. Git diff (staged + unstaged)
2. Project directory tree
3. Contents of src/README.md

All contexts are attached to the message and sent to the AI model together.

## How It Works

### Context Detection

1. **Pattern Matching**: Message is scanned for `@git`, `@tree`, or `@filepath` patterns
2. **Content Injection**: Matched patterns trigger content reading
3. **Message Enhancement**: Original message is enhanced with injected content
4. **Pattern Replacement**: `@git` → `` `git diff` ``, `@tree` → `` `project tree` `` in message body

### Message Format

Enhanced messages have this structure:

```
[Your original message with @references replaced]

---
**Attached context:**

**`@git`** (1.2 KB):
```diff
[git diff content]
```

**`@tree`** (856 B):
```text
[directory tree]
```

**`/path/to/file.py`** (3.4 KB):
```python
[file content]
```
```

### Size Limits

- **Per-file limit**: 100 KB
- **Total context limit**: 200 KB
- Files larger than 200 KB show `[File too large: X MB]` message
- Content truncated at 100 KB shows `*(truncated)*` note

## Implementation Details

### Engine Layer

Context injection is implemented in `ppxai/engine/context.py`:

```python
from ppxai.engine.context import ContextInjector

# Create injector
injector = ContextInjector(working_dir="/path/to/project")

# Inject contexts
enhanced_message, contexts = injector.inject_context(message)

# Access injected contexts
for ctx in contexts:
    print(f"Source: {ctx.source}")
    print(f"Language: {ctx.language}")
    print(f"Content: {ctx.content}")
    print(f"Truncated: {ctx.truncated}")
    print(f"Size: {ctx.size} bytes")
```

### TUI Integration

Context injection is automatic in the TUI. Just type your message with `@` references:

```
You: Review the changes in @git and update @README.md

A: [AI receives your message with git diff and README.md content attached]
```

### VSCode Extension Integration

The VSCode extension supports the same `@` references:

- Autocomplete for `@` references as you type
- File picker for `@filename` references
- Real-time preview of what will be injected

## Examples

### Example 1: Code Review

```
You: Review @git and suggest improvements

Attached context:
- @git: Shows diff of modified files
```

### Example 2: Architecture Analysis

```
You: Analyze @tree and suggest better organization

Attached context:
- @tree: Shows current project structure with file counts
```

### Example 3: File Comparison

```
You: Compare @src/old.py and @src/new.py

Attached context:
- /path/to/src/old.py: Full file content
- /path/to/src/new.py: Full file content
```

### Example 4: Comprehensive Context

```
You: Based on @git changes, @tree structure, and @docs/plan.md, implement the feature

Attached context:
- @git: Current staged and unstaged changes
- @tree: Full project directory tree
- /path/to/docs/plan.md: Feature implementation plan
```

## Best Practices

### When to Use @git

- Before committing to review your changes
- When asking AI to explain what you modified
- To generate commit messages from diffs
- To check for potential issues in uncommitted code

### When to Use @tree

- Starting a new project to get AI suggestions
- When asking where to add new files
- To identify missing test files or documentation
- To understand project organization

### When to Use @file

- When asking about specific file contents
- To explain existing code
- To compare multiple files
- When generating tests or docs for a file

### Performance Tips

- **Large repositories**: Use `@tree` carefully (respects max_depth)
- **Binary files**: Automatically skipped
- **Large files**: Truncated at 100KB (shows warning)
- **Multiple files**: Limited to 200KB total context

## Troubleshooting

### "No changes in working directory"

**Cause**: Git working tree is clean (no modifications)

**Solution**: Make changes and try again, or use `@tree` or `@file` instead

### "@git returns None"

**Cause**: Not in a git repository or git not installed

**Solution**: Initialize git repo (`git init`) or check git installation

### "File too large"

**Cause**: File exceeds 100KB limit

**Solution**:
- Split large files into smaller modules
- Use `@file` with specific sections only
- Truncated content still available (first 100KB)

### Context not injected

**Cause**: Message doesn't trigger auto-injection heuristics

**Solution**:
- Use explicit `@` syntax
- Add keywords like "read", "show", "review"
- Keep message short if mentioning files

## API Reference

### ContextInjector Class

```python
class ContextInjector:
    """Detects and injects file/URL content into messages."""

    def __init__(self, working_dir: Optional[str] = None):
        """Initialize with base directory for relative paths."""

    def inject_context(self, message: str) -> Tuple[str, List[InjectedContext]]:
        """Process message and inject contexts."""

    def inject_git_context(self, working_dir: Optional[str] = None) -> Optional[InjectedContext]:
        """Inject git diff as context."""

    def inject_tree_context(self, working_dir: Optional[str] = None, max_depth: int = 3) -> Optional[InjectedContext]:
        """Inject directory tree as context."""

    def read_file(self, filepath: str) -> Optional[InjectedContext]:
        """Read a file and return its content."""
```

### InjectedContext Dataclass

```python
@dataclass
class InjectedContext:
    source: str          # "@git", "@tree", or file path
    content: str         # Actual content
    language: str        # Language for syntax highlighting ("diff", "text", "python", etc.)
    truncated: bool      # Whether content was truncated
    size: int            # Original size in bytes
```

## Related Documentation

- [v1.11.0 Agentic Workflow Plan](v1.11.0-agentic-workflow-plan.md) - Context injection roadmap
- [Architecture Refactoring](architecture-refactoring.md) - Engine layer design
- [CLAUDE.md](../CLAUDE.md) - AI assistant development guide

## Version History

- **v1.11.4** (2025-12-24): Added `@git` and `@tree` context providers
- **v1.8.0** (2025-01-XX): Initial `@file` context injection
- **v1.7.0** (2025-01-XX): Engine layer foundation

---

**Feedback**: Report issues or suggest improvements at [GitHub Issues](https://github.com/rcconsult/ppxai/issues)
