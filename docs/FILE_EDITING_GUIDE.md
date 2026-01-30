# File Editing Tools Guide (v1.11.0)

Both **ppxai** (Rich TUI) and **ppxaide** (Textual TUI) include powerful file editing capabilities that allow AI to make autonomous code modifications with your consent. This guide shows you how to use these tools effectively.

## Table of Contents

- [Overview](#overview)
- [Safety & Consent](#safety--consent)
- [Getting Started](#getting-started)
- [Practical Examples](#practical-examples)
- [Tool Reference](#tool-reference)
- [Best Practices](#best-practices)
- [Troubleshooting](#troubleshooting)

---

## Overview

### What's New in v1.11.0

The AI can now autonomously edit files during conversations! It can:
- ✅ Apply patches and diffs
- ✅ Replace code blocks
- ✅ Insert new code at specific locations
- ✅ Delete lines or line ranges
- ✅ Make multiple edits in a single conversation

**All with your explicit consent before any changes.**

### 4 File Editing Tools

| Tool | Purpose | Use Case |
|------|---------|----------|
| `apply_patch` | Apply unified diff patches | Precision edits, code reviews |
| `replace_block` | Find and replace text blocks | Refactoring, bug fixes |
| `insert_text` | Add lines at specific positions | Adding features, imports |
| `delete_lines` | Remove line ranges | Cleanup, removing code |

---

## Safety & Consent

### Consent System

**Every file edit requires your permission.** When AI wants to edit a file, you'll see a prompt with 4 options:

#### In TUI (Terminal):
```
⚠️  File Edit Request
AI wants to edit: /path/to/file.py
Options: y (yes), n (no), always (all files), never (block all)

Allow edit?
```

#### In VSCode Extension:
A modal dialog appears with buttons:
- **Yes (this file)** - Allow editing just this file
- **No** - Deny this edit
- **Always (all files)** - Auto-approve all edits this session
- **Never (block all)** - Block all edits this session

### Consent Options Explained

| Response | Effect | Scope |
|----------|--------|-------|
| **y / Yes (this file)** | Approves edit for this file | Same file can be edited again without asking |
| **n / No** | Denies edit | File remains unchanged, AI continues |
| **always / Always (all files)** | Approves all edits | All files in this session |
| **never / Never (block all)** | Blocks all edits | No files can be edited this session |

### Safety Features

✅ **Session-scoped consent** - Permissions persist only during your session
✅ **Atomic operations** - Edits happen in transactions (all or nothing)
✅ **Automatic rollback** - Failed edits restore original content
✅ **No silent changes** - You always see what's being modified
✅ **Safe defaults** - Errors and timeouts deny edits

---

## Getting Started

### 1. Enable Tools

File editing tools are included when you enable AI tools:

**TUI:**
```bash
/tools enable
```

> **Tip:** Use Tab for autocomplete: `/tools <tab>` shows all subcommands, `/tools help <tab>` shows tool names.

**VSCode:**
Enable tools in settings or via the tools toggle button in chat panel.

### 2. Check Tools Status

**TUI:**
```bash
/tools status

# Get help for a specific editing tool
/tools help apply_patch
```

Output:
```
✓ Tools enabled (12 tools available)
✓ File editing tools enabled (4 editing tools)
Consent mode: ask
```

**VSCode:**
Click the tools badge to see status.

### 3. Start Using

Just ask AI to make file changes! The tools are invoked automatically when needed.

---

## Practical Examples

### Example 1: Simple Bug Fix

**User:** "Fix the typo in config.py - 'databse' should be 'database'"

**Chat Flow:**
```
You: Fix the typo in config.py - 'databse' should be 'database'

AI: I'll fix that typo for you.

[Consent Prompt]
⚠️  File Edit Request
AI wants to edit: /Users/you/project/config.py
Allow edit? y

AI: ✓ Successfully replaced block in config.py at line 15 (+0 lines)

Done! Changed 'databse' to 'database' in config.py.
```

**What happened:**
1. AI read config.py
2. AI requested consent to edit
3. You approved with 'y'
4. AI used `replace_block` tool to make the change
5. File was modified atomically

### Example 2: Add New Function

**User:** "Add a helper function to utils.py that converts timestamps to ISO format"

**Chat Flow:**
```
You: Add a helper function to utils.py that converts timestamps to ISO format

AI: I'll add a timestamp conversion function to utils.py.

[Consent Prompt - First Edit]
⚠️  File Edit Request
AI wants to edit: /Users/you/project/utils.py
Allow edit? y

AI: ✓ Successfully inserted text in utils.py at lines 45-52

Added timestamp_to_iso() function after the existing datetime utilities.
The function handles both Unix timestamps and datetime objects.
```

**What happened:**
1. AI analyzed utils.py structure
2. AI identified best location (after existing datetime code)
3. You approved the edit
4. AI used `insert_text` to add the new function
5. AI provided context about what was added

### Example 3: Apply Code Review Feedback

**User:** "Apply this code review feedback: Remove debug print statements from authentication.py"

**Chat Flow:**
```
You: Apply this code review feedback: Remove debug print statements from authentication.py

AI: I'll clean up the debug print statements.

[Reading authentication.py]

I found 3 debug print statements to remove (lines 23, 47, 89).

[Consent Prompt]
⚠️  File Edit Request
AI wants to edit: /Users/you/project/authentication.py
Allow edit? y

AI: ✓ Successfully deleted lines 23-23 from authentication.py (1 line)
AI: ✓ Successfully deleted lines 47-47 from authentication.py (1 line)
AI: ✓ Successfully deleted lines 89-89 from authentication.py (1 line)

Removed all 3 debug print statements. The code is now production-ready.
```

**What happened:**
1. AI read the file and found debug statements
2. You approved edits for this file (consent only asked once)
3. AI used `delete_lines` three times
4. All edits completed successfully

### Example 4: Refactor with Multiple Files

**User:** "Refactor the database connection logic - move it from main.py into a new db_connection.py module"

**Chat Flow:**
```
You: Refactor the database connection logic - move it from main.py into a new db_connection.py module

AI: I'll refactor the database connection into a separate module.

Step 1: Create db_connection.py with the connection logic
Step 2: Update main.py to import from the new module

[Consent Prompt - New File]
⚠️  File Edit Request
AI wants to edit: /Users/you/project/db_connection.py
Allow edit? always

AI: ✓ Created db_connection.py with connection logic
AI: ✓ Successfully replaced block in main.py (removed old connection code)
AI: ✓ Successfully inserted text in main.py (added import statement)

Refactoring complete! Database connection is now in db_connection.py.
main.py imports: from db_connection import get_connection
```

**What happened:**
1. You chose "always" for the first file
2. AI created the new module
3. AI modified main.py (no additional consent needed)
4. Multi-file refactoring completed smoothly

### Example 5: Apply a Patch from PR Review

**User:** "Apply this patch from the PR review:"
````
```diff
--- a/api.py
+++ b/api.py
@@ -10,7 +10,7 @@
 def get_user(user_id: int):
-    return database.query(f"SELECT * FROM users WHERE id={user_id}")
+    return database.query("SELECT * FROM users WHERE id=?", (user_id,))
```
````

**Chat Flow:**
```
You: Apply this patch from the PR review: [diff content]

AI: I'll apply the security fix to prevent SQL injection.

[Consent Prompt]
⚠️  File Edit Request
AI wants to edit: /Users/you/project/api.py
Allow edit? y

AI: ✓ Successfully applied patch to api.py (1 line changed)

Applied the patch. Changed raw SQL query to use parameterized queries,
preventing SQL injection vulnerabilities.
```

**What happened:**
1. AI recognized the unified diff format
2. You approved the security patch
3. AI used `apply_patch` tool
4. Vulnerability fixed with proper parameterized query

---

## Tool Reference

### 1. apply_patch

**Purpose:** Apply unified diff patches (git diff format)

**Use Cases:**
- Applying code review feedback
- Cherry-picking changes from PRs
- Precision multi-line edits

**Example Prompt:**
- "Apply this diff to fix the bug"
- "Cherry-pick this change from the PR"
- "Use this patch from the code review"

**Tool Parameters:**
```python
apply_patch(
    file_path="/path/to/file.py",
    unified_diff="@@ -10,3 +10,3 @@\n context\n-old line\n+new line\n"
)
```

---

### 2. replace_block

**Purpose:** Find exact text and replace it (must be unique)

**Use Cases:**
- Renaming variables/functions
- Fixing typos
- Updating configuration values
- Replacing code blocks

**Example Prompts:**
- "Replace the old error handling with proper try/catch"
- "Change DATABASE_URL to use environment variable"
- "Fix the typo 'recieve' to 'receive'"

**Tool Parameters:**
```python
replace_block(
    file_path="/path/to/file.py",
    search="old_function_name()",
    replace="new_function_name()"
)
```

**Important:** Search text must appear exactly once in the file.

---

### 3. insert_text

**Purpose:** Insert text at a specific line number

**Use Cases:**
- Adding new functions
- Adding imports
- Adding configuration
- Inserting documentation

**Example Prompts:**
- "Add a new endpoint after the existing /users route"
- "Insert import statement at the top"
- "Add this docstring to the function"

**Tool Parameters:**
```python
insert_text(
    file_path="/path/to/file.py",
    line_number=10,  # 1-indexed
    text="new code here\n"
)
```

---

### 4. delete_lines

**Purpose:** Delete a range of lines (inclusive)

**Use Cases:**
- Removing dead code
- Cleaning up debug statements
- Removing deprecated functions
- Deleting comments

**Example Prompts:**
- "Remove the deprecated authentication function"
- "Delete all the debug print statements"
- "Clean up the commented-out code"

**Tool Parameters:**
```python
delete_lines(
    file_path="/path/to/file.py",
    start_line=10,  # 1-indexed, inclusive
    end_line=15     # 1-indexed, inclusive
)
```

---

## Best Practices

### ✅ Do's

1. **Start with small edits** - Test the workflow with simple changes first
2. **Use descriptive prompts** - "Fix the null pointer exception in line 42" is better than "fix this"
3. **Review before approving** - Check the file path in consent prompts
4. **Use "always" for multi-file tasks** - Reduces interruptions during refactoring
5. **Let AI read files first** - AI will analyze context before editing
6. **Combine with @file references** - Include related files for better context

### ❌ Don'ts

1. **Don't skip reading consent prompts** - Always verify which file is being edited
2. **Don't use on critical files without backups** - Use git or have backups
3. **Don't approve edits you don't understand** - Ask AI to explain first
4. **Don't mix manual edits during AI sessions** - Let AI complete its changes first
5. **Don't panic if something goes wrong** - Atomic operations + git = easy recovery

### 💡 Pro Tips

**For Refactoring:**
```
You: Refactor the authentication module - extract password hashing
     into utils/crypto.py

[Approve with "always" on first prompt]
```

**For Code Reviews:**
```
You: Apply all the suggestions from code_review.md

AI will read the review, identify files, and apply changes systematically.
```

**For Bug Fixes:**
```
You: @bug_report.txt @user_service.py
     Fix the race condition described in the bug report

[AI analyzes both files and applies the fix]
```

**For New Features:**
```
You: Implement user profile editing:
     1. Add PUT /users/:id endpoint to api.py
     2. Add update_user() to database.py
     3. Update user model with last_modified field

[AI will edit all 3 files with consent]
```

---

## Troubleshooting

### "Search text not found"

**Problem:** `replace_block` can't find the text you want to replace.

**Solutions:**
- Ensure exact match (including whitespace)
- Ask AI to read the file first: "Show me the current implementation"
- Use `@filename` to include file context
- Try `apply_patch` for multi-line changes

---

### "Search text found X times (must be unique)"

**Problem:** Text appears multiple times, `replace_block` requires uniqueness.

**Solutions:**
- Include more context in search string
- Use line numbers with `insert_text` or `delete_lines`
- Use `apply_patch` with full context
- Be more specific: "Replace the version check in the __init__ function"

---

### "Invalid line number"

**Problem:** Tried to insert/delete at a line that doesn't exist.

**Solutions:**
- Ask AI to check file length first
- Use `@filename` to show file content
- Let AI determine the correct line number

---

### Edit denied but I wanted to approve

**Problem:** Accidentally clicked "No" or typed "n"

**Solutions:**
- Just ask again: "Try that edit again"
- Consent state resets, you can approve next time
- Or: "Set consent to always and retry"

---

### Multiple edits needed, consent annoying

**Problem:** Refactoring multiple files, constant prompts interrupt flow.

**Solutions:**
- Use "always" on first prompt
- Tell AI upfront: "I approve all file edits for this task"
- Consent persists for the session

---

### How to undo an edit?

**Solutions:**
1. **Git:** `git checkout filename` or `git diff` to see changes
2. **Manual:** Edit the file normally (AI edits are just regular edits)
3. **Ask AI:** "Revert the last change to config.py"
4. **File history:** Most editors have local history (VS Code: Timeline)

---

## Advanced Patterns

### Pattern 1: Iterative Development

```
Session 1: Initial implementation
You: Create a basic REST API with GET /users
[Approve edits]

Session 2: Add features
You: Add POST /users endpoint with validation
[Edits auto-approved - same file]

Session 3: Refinement
You: Add pagination to GET /users
[Edits auto-approved - same file]
```

### Pattern 2: Code Migration

```
You: Migrate from requests library to httpx:
     1. Update requirements.txt
     2. Change all imports in services/
     3. Update async HTTP calls to use httpx syntax

[Approve with "always"]
[AI systematically updates all files]
```

### Pattern 3: Test-Driven Development

```
You: I have failing tests in test_auth.py.
     Fix the authentication logic in auth.py to make them pass.

[AI reads both files, identifies issues, applies fixes]
```

---

## Security Considerations

### ⚠️ Important Security Notes

1. **Consent is not a security boundary** - It's a safety feature, not authentication
2. **Review before production** - Always review AI-generated changes
3. **Use version control** - Git is your safety net
4. **Sensitive files** - Be cautious with .env, credentials, keys
5. **Code review** - AI edits should go through normal review process

### 🔒 Recommended Workflow

1. **Development branch**: Let AI edit freely
2. **Review changes**: `git diff` to see all modifications
3. **Test thoroughly**: Run tests after AI edits
4. **Code review**: Treat AI PRs like human PRs
5. **Merge**: Standard merge process

---

## Examples by Use Case

### Bug Fixing
```
"Fix the off-by-one error in pagination logic"
"Handle the edge case when user_id is None"
"Add null check before accessing user.email"
```

### Refactoring
```
"Extract the email validation into a separate function"
"Rename userId to user_id throughout the file"
"Move constants to the top of the file"
```

### Adding Features
```
"Add a rate limiting decorator to the API endpoints"
"Implement user avatar upload functionality"
"Add logging to all database operations"
```

### Code Cleanup
```
"Remove all unused imports"
"Delete commented-out code"
"Fix all formatting issues to match PEP 8"
```

### Testing
```
"Add unit tests for the password hashing function"
"Generate integration tests for the user API"
"Add edge case tests for date parsing"
```

---

## FAQ

**Q: Can AI create new files?**
A: Yes! AI can edit any file path. If the file doesn't exist, consent works the same way.

**Q: What happens if my internet drops during an edit?**
A: Edits are atomic. Either the full edit completes or the file is unchanged. No partial edits.

**Q: Can I use this in production?**
A: Yes, but use version control and review changes. Treat AI edits like any code change.

**Q: Does consent persist across ppxai restarts?**
A: No. Consent is session-scoped. Each new session starts with "ask" mode.

**Q: Can I approve edits via command line flag?**
A: Not yet. Safety requires interactive consent. Use "always" mode for batch operations.

**Q: What if AI wants to edit a binary file?**
A: Editing tools work with text files. Binary files will cause errors (and rollback).

---

## Next Steps

Ready to try file editing tools? Here's your checklist:

- [ ] Update to v1.11.0
- [ ] Enable tools with `/tools enable`
- [ ] Try a simple edit: "Fix typo X in file Y"
- [ ] Review the consent prompt
- [ ] Check the edit with `git diff`
- [ ] Try a multi-file refactoring with "always" mode
- [ ] Read [docs/v1.11.0-agentic-workflow-plan.md](v1.11.0-agentic-workflow-plan.md) for technical details

---

## Feedback & Support

Found a bug? Have suggestions?
- [GitHub Issues](https://github.com/rcconsult/ppxai/issues)
- [Discussions](https://github.com/rcconsult/ppxai/discussions)

---

**Happy Coding with AI! 🚀**
