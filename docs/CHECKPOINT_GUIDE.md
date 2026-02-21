# Checkpoint System User Guide (v1.12.4)

## Overview

The checkpoint system provides **atomic multi-file rollback** for agent mode tasks. Works with both **ppxai** (Rich TUI) and **ppxaide** (Textual TUI). Before executing autonomous tasks, a checkpoint is created that lets you undo all changes with a single `/undo` command.

**Key Features:**
- ✅ **Atomic Rollback** - Revert all file changes from the last agent task
- ✅ **Git Integration** - Uses native git commits for version-controlled projects
- ✅ **File Backup Fallback** - Works even without git via snapshot system
- ✅ **Auto-Detection** - Automatically chooses the best backend
- ✅ **Zero Configuration** - Works out of the box with sensible defaults

---

## Quick Start

### Basic Usage

1. **Enable agent mode** (checkpoints enabled automatically):
   ```
   /agent refactor the authentication module to use JWT
   ```

2. **Check status** (see checkpoint backend in status line):
   ```
   [Perplexity | sonar-pro | Tools: ON | Agent: ON | Checkpoints: git]
   ```

3. **Undo if needed**:
   ```
   /undo
   ```

That's it! The checkpoint system handles everything automatically.

---

## How It Works

### Git Backend (Preferred)

When your project has a git repository, the TUI uses **git-based checkpoints**:

1. **Before Agent Task:**
   ```bash
   # Automatically runs:
   git add -A
   git commit -m "ppxai checkpoint: refactor auth module"
   ```

2. **After /undo:**
   ```bash
   # Automatically runs:
   git revert HEAD --no-edit
   ```

**Advantages:**
- ✅ Atomic commits visible in git history
- ✅ Standard git workflow (push, pull, merge work normally)
- ✅ Zero storage overhead
- ✅ Works with existing git hooks

**Limitations:**
- ⚠️ Requires a git repository
- ⚠️ Creates visible commits in git log

---

### File Backend (Fallback)

When git is not available, ppxai uses **file-based snapshots**:

1. **Before Agent Task:**
   - Copies all modified files to `~/.ppxai/checkpoints/{session_id}/cp-{timestamp}/`
   - Preserves directory structure

2. **After /undo:**
   - Restores files from the snapshot
   - Overwrites current versions

**Advantages:**
- ✅ Works without git
- ✅ Simple snapshot-based recovery
- ✅ No git history pollution

**Limitations:**
- ⚠️ Requires disk space for snapshots
- ⚠️ Not atomic (individual file restores)
- ⚠️ Old checkpoints must be manually cleaned

**Note:** File backend checkpoints are automatically cleaned up, keeping the last 10 by default.

---

## Configuration

### Backend Selection

Edit `ppxai-config.json` to customize checkpoint behavior:

```json
{
  "tools": {
    "agent": {
      "checkpoint_backend": "auto",
      "checkpoint_message": "ppxai checkpoint: {task}"
    }
  }
}
```

**Backend Options:**

| Value | Behavior |
|-------|----------|
| `"auto"` | Auto-detect: Use git if available, else file backend (default) |
| `"git"` | Git-only: Disable checkpoints if no git repository |
| `"file"` | Force file backend even if git is available |
| `"none"` | Disable checkpoints entirely |

**Examples:**

```json
// Force git-only (fail if no git)
{"checkpoint_backend": "git"}

// Always use file snapshots
{"checkpoint_backend": "file"}

// Disable checkpoints
{"checkpoint_backend": "none"}
```

---

## Commands

### `/agent <task>` - Execute Agent Task

Runs an autonomous agent loop with automatic checkpointing:

```
/agent refactor the auth module to use JWT tokens
```

**What happens:**
1. Checkpoint created automatically (git commit or file snapshot)
2. Agent executes the task using available tools
3. Notification shown: `✓ Checkpoint created: abc123de (refactor auth module)`

**Status Line Indicators:**

| Status | Meaning |
|--------|---------|
| `Checkpoints: git` | Git backend active (green) |
| `Checkpoints: file` | File backend active (yellow) |
| `Checkpoints: OFF` | Disabled (red warning) |

---

### `/undo` - Revert Last Agent Task

Reverts all changes from the last agent task:

```
/undo
```

**Confirmation Prompt:**
```
⚠️  Undo Last Agent Task
Backend: git
Checkpoint: abc123de

Confirm undo? (y/n):
```

**What happens:**
- **Git backend:** Runs `git revert HEAD --no-edit`
- **File backend:** Restores files from last snapshot

**Success:**
```
✓ Changes reverted using git revert (checkpoint: abc123de)
```

**Limitations:**
- Only reverts the **last** checkpoint
- Cannot undo if no checkpoint exists
- Git backend: Creates a revert commit (visible in history)
- File backend: Overwrites current files (no intermediate versions)

---

### `/checkpoint` - Checkpoint Management (v1.12.4)

The `/checkpoint` command provides checkpoint status, listing, and configuration:

```
/checkpoint [subcommand] [args]
```

**Subcommands:**

| Subcommand | Description |
|------------|-------------|
| `status` (default) | Show current checkpoint status |
| `list` | List recent checkpoints |
| `backend <mode>` | Set checkpoint backend for this session |
| `clear` | Clear old file-based snapshots |
| `info <id>` | Show details about a specific checkpoint |
| `undo` | Alias for `/undo` command |

**Tab Autocomplete:**
Both TUI and VSCode extension support autocomplete for subcommands and backend options.

---

#### `/checkpoint status`

Show current checkpoint configuration:

```
/checkpoint status
```

**Output:**
```
📍 Checkpoint Status
  Backend: git
  Session: default
  Working Dir: /path/to/project
  Last Checkpoint: abc123de
```

---

#### `/checkpoint list`

List recent checkpoints (up to 10):

```
/checkpoint list
```

**Output (Git Backend):**
```
📋 Recent Checkpoints
  abc123de  refactor auth module           2025-12-31 14:30:22
  def456gh  add user registration          2025-12-31 12:15:00
  ghi789jk  update dependencies            2025-12-30 16:45:33
```

**Output (File Backend):**
```
📋 Recent Checkpoints
  cp-20251231-143022  refactor auth module    2025-12-31T14:30:22
  cp-20251231-121500  add user registration   2025-12-31T12:15:00
```

---

#### `/checkpoint backend <mode>`

Change checkpoint backend for the current session:

```
/checkpoint backend git    # Use git commits
/checkpoint backend file   # Use file snapshots
/checkpoint backend auto   # Auto-detect best backend
/checkpoint backend none   # Disable checkpoints
```

**Note:** This only affects the current session. To persist the setting, edit `ppxai-config.json`.

**Output:**
```
✓ Checkpoint backend set to: git
```

**Error (no git repo):**
```
⚠️  Git repository not found. Falling back to file backend.
```

---

#### `/checkpoint clear`

Clear old file-based checkpoint snapshots:

```
/checkpoint clear
```

**Output:**
```
🗑️  Cleared 8 old checkpoint snapshots
```

**Note:** This only affects file-based checkpoints. Git checkpoints are managed by git history.

---

#### `/checkpoint info <id>`

Show details about a specific checkpoint:

```
/checkpoint info abc123de
```

**Output (Git Backend):**
```
📍 Checkpoint: abc123de
  Full Hash: abc123de456789...
  Description: refactor auth module
  Timestamp: 2025-12-31 14:30:22
  Valid: ✓ (HEAD~1)
```

**Output (File Backend):**
```
📍 Checkpoint: cp-20251231-143022
  Description: refactor auth module
  Timestamp: 2025-12-31T14:30:22
  Files: 3 files snapshotted
```

---

#### `/checkpoint undo`

Alias for the `/undo` command:

```
/checkpoint undo
```

This is equivalent to running `/undo` directly.

---

## Workflow Examples

### Example 1: Git Project with Undo

```
# Status shows git checkpoints
[Perplexity | sonar-pro | Tools: ON | Agent: ON | Checkpoints: git]

# Run agent task
You: /agent add user registration endpoint

🔒 Agent Mode enabled with Git checkpoints
   • Changes will be auto-committed before each task
   • Use /undo to revert the last agent task atomically

✓ Checkpoint created: f3a7b2c1 (add user registration endpoint)

🤖 Starting autonomous agent...
[Agent executes task, creates files, edits code...]

# Realize there's an issue
You: /undo

⚠️  Undo Last Agent Task
Backend: git
Checkpoint: f3a7b2c1

Confirm undo? (y/n): y

✓ Changes reverted using git revert (checkpoint: f3a7b2c1)

# All changes undone! Git history shows:
# - abc123de: ppxai checkpoint: add user registration endpoint
# - f3a7b2c1: Revert "ppxai checkpoint: add user registration endpoint"
```

---

### Example 2: Non-Git Project

```
# No git repo, file backend active
[Perplexity | sonar-pro | Tools: ON | Agent: ON | Checkpoints: file]

# Run agent task
You: /agent refactor config.py to use environment variables

⚠️  Agent Mode enabled with File checkpoints
   • Snapshots will be saved to ~/.ppxai/checkpoints
   • Use /undo to restore from snapshot
   • Tip: Initialize git repo for atomic commits

✓ Checkpoint created: cp-20251227-143022 (refactor config.py)

🤖 Starting autonomous agent...
[Agent modifies files...]

# Undo the changes
You: /undo

✓ Changes restored from snapshot (checkpoint: cp-20251227-143022)

# Files restored from ~/.ppxai/checkpoints/default/cp-20251227-143022/
```

---

### Example 3: Disabled Checkpoints

```
# Checkpoints explicitly disabled
[Perplexity | sonar-pro | Tools: ON | Agent: ON | Checkpoints: OFF]

# Warning shown when running agent
You: /agent update dependencies

⚠️  Agent Mode enabled WITHOUT checkpoints
   • Changes CANNOT be undone
   • Initialize git repo or enable file backend for safety

🤖 Starting autonomous agent...
[Agent runs but no checkpoint created]

# /undo not available
You: /undo
⚠️  Checkpoints are not enabled
```

---

### Example 4: Interrupt Handling (Ctrl-C)

```
# Agent task in progress
You: /agent refactor authentication module

✓ Checkpoint created: d4b8f2a1 (refactor authentication module)

🤖 Starting autonomous agent...
━━━ Iteration 1/10 ━━━

[Agent starts making changes...]
  → Modified: auth/login.py
  → Created: auth/jwt_utils.py

# User presses Ctrl-C (realizes agent is going wrong direction)
^C

⚠️  Agent interrupted by user (Ctrl-C)

Agent task incomplete due to interrupt.

Checkpoint: d4b8f2a1
Backend: git

Rollback all changes from this task?
  y - Rollback to checkpoint (undo all changes)
  n - Keep partial changes

Rollback? (y/n): y

Rolling back changes...
✓ Checkpoint reverted successfully

⚠️  Uncommitted changes detected in working directory
These are partial changes from the interrupted agent task.

Clean working directory?
  y - Remove all uncommitted changes (git reset --hard)
  n - Keep uncommitted changes for manual review

Clean working directory? (y/n): y

Running git reset --hard...
✓ Working directory cleaned
Removing untracked files...
✓ All changes removed

# All clean! Back to state before /agent command
```

**File Backend (Non-Git):**
```
# Same interrupt scenario, but with file backend
^C

⚠️  Agent interrupted by user (Ctrl-C)

Agent task incomplete due to interrupt.

Checkpoint: cp-20251227-153045
Backend: file

Rollback all changes from this task?
  y - Rollback to checkpoint (undo all changes)
  n - Keep partial changes

Rollback? (y/n): y

Rolling back changes...
✓ Checkpoint reverted successfully

# File backend restores all snapshotted files automatically
# No additional cleanup needed
```

---

## Safety and Best Practices

### ✅ Recommended

1. **Use git repositories** for best experience
   - Initialize git: `git init`
   - Atomic commits, standard workflow
   - Push/pull works normally

2. **Review changes before continuing**
   - Check `git status` or `git diff` after agent tasks
   - Undo immediately if issues found

3. **Commit frequently**
   - Checkpoint commits are normal commits
   - Can be merged, pushed, squashed like any git commit

4. **Test `/undo` early**
   - Try the undo flow on a simple task first
   - Verify your workflow before complex refactoring

### ⚠️ Limitations

1. **Only one undo level**
   - `/undo` reverts the last checkpoint only
   - Cannot undo multiple tasks sequentially
   - To undo earlier changes, use git directly

2. **File backend not atomic**
   - Restores files individually (not transactional)
   - Partial restores possible if errors occur
   - Git backend recommended for critical tasks

3. **Checkpoints for agent mode only**
   - Regular chat doesn't create checkpoints
   - File editing tools don't auto-checkpoint (yet)
   - Use `/agent` for checkpoint protection

4. **Disk space (file backend)**
   - Old snapshots consume disk space
   - Auto-cleanup keeps last 10 by default
   - Manual cleanup: `rm -rf ~/.ppxai/checkpoints/*`

---

## Troubleshooting

### "Checkpoints are not enabled"

**Symptom:** Status line shows `Checkpoints: OFF`

**Causes:**
1. No git repository and file backend disabled
2. Explicitly set to `"checkpoint_backend": "none"`
3. Git backend selected but no `.git` directory

**Solutions:**
```bash
# Option 1: Initialize git
cd /path/to/project
git init
git add .
git commit -m "Initial commit"

# Option 2: Enable file backend
# Edit ppxai-config.json:
{"checkpoint_backend": "file"}

# Option 3: Use auto-detection
{"checkpoint_backend": "auto"}
```

---

### "/undo does nothing"

**Symptom:** No changes reverted after `/undo`

**Causes:**
1. No checkpoint created (no changes before agent task)
2. Checkpoint already undone
3. Files manually modified after checkpoint

**Solutions:**
- Check if agent task actually modified files: `git status` or `git log`
- Verify checkpoint exists: Look for "✓ Checkpoint created" message
- Use `git log` to see checkpoint commits

---

### "Permission denied" (file backend)

**Symptom:** Cannot create checkpoint directory

**Cause:** `~/.ppxai/checkpoints/` not writable

**Solution:**
```bash
mkdir -p ~/.ppxai/checkpoints
chmod 755 ~/.ppxai/checkpoints
```

---

### "Git revert failed"

**Symptom:** `/undo` fails with git error

**Causes:**
1. Merge conflicts
2. Working directory not clean
3. Checkpoint commit modified manually

**Solutions:**
```bash
# Check git status
git status

# If conflicts, resolve manually or abort
git revert --abort

# Try manual revert
git log  # Find checkpoint commit hash
git revert <commit-hash>
```

---

## Advanced Usage

### Manual Checkpoint Inspection

**Git Backend:**
```bash
# List checkpoint commits
git log --grep="ppxai checkpoint:"

# View specific checkpoint
git show <commit-hash>

# Manually revert (same as /undo)
git revert <commit-hash> --no-edit
```

**File Backend:**
```bash
# List checkpoint snapshots
ls -la ~/.ppxai/checkpoints/default/

# View checkpoint metadata
cat ~/.ppxai/checkpoints/default/cp-20251227-143022/metadata.txt

# Manually restore file
cp ~/.ppxai/checkpoints/default/cp-20251227-143022/config.py ./
```

---

### Integration with Git Workflow

Checkpoint commits work with standard git workflows:

```bash
# After agent task, inspect changes
git log -1 --stat
git diff HEAD~1

# Keep the changes - push normally
git push origin main

# Revert the changes - use /undo or git revert
git revert HEAD --no-edit

# Squash checkpoint commits before merge
git rebase -i HEAD~5  # Mark checkpoint commits as 'fixup'
```

---

### Custom Checkpoint Messages

Edit `ppxai-config.json` to customize commit messages:

```json
{
  "tools": {
    "agent": {
      "checkpoint_message": "[AGENT] {task}"
    }
  }
}
```

**Variables:**
- `{task}` - First 100 characters of agent task description

**Examples:**
```json
// Prefix with project name
{"checkpoint_message": "[MyApp] Agent checkpoint: {task}"}

// Include timestamp
{"checkpoint_message": "🤖 {task} [automated]"}

// Conventional commits style
{"checkpoint_message": "chore(agent): {task}"}
```

---

## VSCode Extension Differences

The checkpoint system works identically in VSCode extension:

**UI Differences:**
- **Status Line** → Enhanced agent toggle button (🔒/⚠️ indicators)
- **Notifications** → System messages in chat
- **Undo Button** → Clickable button in header (next to agent toggle)

**Same Functionality:**
- Same HTTP API endpoints (`/agent/status`, `/checkpoint/undo`)
- Same backend selection logic
- Same checkpoint creation/restore behavior

See [docs/VSCODE-CHECKPOINT-UI-SPEC.md](archive/v1.15.2-completed/VSCODE-CHECKPOINT-UI-SPEC.md) for implementation details.

---

## FAQ

**Q: Do checkpoints work with file editing tools?**
A: Currently, checkpoints are only created for `/agent` tasks. File editing tools (apply_patch, etc.) require manual consent but don't auto-checkpoint. This may change in future versions.

**Q: Can I undo multiple tasks?**
A: No, `/undo` only reverts the last checkpoint. Use git commands directly for multiple undos:
```bash
git log --grep="ppxai checkpoint:"  # Find checkpoints
git revert <commit1> <commit2> <commit3>  # Revert multiple
```

**Q: What happens if I push checkpoint commits?**
A: Checkpoint commits are normal git commits. They can be pushed, merged, and shared like any commit. Team members will see them in git history.

**Q: How do I clean up old file backend snapshots?**
A: ppxai auto-cleans, keeping the last 10 checkpoints. Manual cleanup:
```bash
rm -rf ~/.ppxai/checkpoints/*
```

**Q: Can I use checkpoints with remote git repos?**
A: Yes! Checkpoint commits are local until you push. They work with `git pull`, `git push`, and `git merge` normally.

**Q: Does /undo work on already-pushed commits?**
A: Yes, but it creates a revert commit (doesn't rewrite history). The original checkpoint commit remains in history. Use `git rebase` or `git reset` for history rewriting (advanced users only).

**Q: How do I switch from git to file backend?**
A: Use `/checkpoint backend file` to switch for the current session. To persist permanently, edit `ppxai-config.json` and set `"checkpoint_backend": "file"`.

**Q: How do I see what checkpoints are available?**
A: Use `/checkpoint list` to see the last 10 checkpoints, or `/checkpoint info <id>` to get details about a specific checkpoint.

---

## Version History

- **v1.12.4** - `/checkpoint` command for checkpoint management
  - `/checkpoint status` - View checkpoint configuration
  - `/checkpoint list` - List recent checkpoints
  - `/checkpoint backend <mode>` - Switch backend (session-only)
  - `/checkpoint clear` - Clear file-based snapshots
  - `/checkpoint info <id>` - View checkpoint details
  - `/checkpoint undo` - Alias for `/undo`
  - Tab autocomplete for subcommands and backends

- **v1.12.0** - Initial checkpoint system release
  - Git backend with auto-commits
  - File backend with snapshots
  - Auto-detection and configuration
  - `/undo` command for rollback
  - Status line integration

---

## See Also

- [Agent Mode Guide](AGENT_MODE_GUIDE.md) - Autonomous agent mode documentation
- [VSCode Checkpoint UI Spec](archive/v1.15.2-completed/VSCODE-CHECKPOINT-UI-SPEC.md) - VSCode extension implementation
- [Release Notes v1.12.0](archive/release-notes/RELEASE-NOTES-v1.12.0.md) - Full feature list and changelog
