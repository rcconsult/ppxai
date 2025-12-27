# Roadmap Discussion: December 27, 2025

This document captures the research and discussion about potential future directions for ppxai, to be reconciled into the main ROADMAP.md.

---

## Context

With Agent Mode complete in v1.11.9, we're evaluating what comes next. Four areas were researched:

1. AGENTS.md standard adoption
2. Atomic multi-file edits with checkpointing
3. Textual TUI framework migration
4. libghostty SDK integration

---

## 1. AGENTS.md as Universal Session Bootstrap

### Background

AGENTS.md is becoming the industry standard for AI agent configuration:
- Stewarded by Linux Foundation's Agentic AI Foundation
- 40,000+ projects adopted
- Supported by: OpenAI Codex, Cursor, Google Jules, Factory, Gemini CLI

### Current Fragmentation

| Tool | Configuration File |
|------|-------------------|
| Claude Code | `CLAUDE.md` |
| Cursor | `.cursorrules` |
| OpenAI/Jules | `AGENTS.md` |
| GitHub Copilot | `.github/copilot-instructions.md` |
| Windsurf | `.windsurfrules` |

Teams are using symlinks (`ln -s AGENTS.md CLAUDE.md`) to support multiple tools.

### Vision for ppxai

Not just "read a file" but **reproducible, configurable session initialization**:

```
User launches ppxai
    ↓
Load AGENTS.md (or CLAUDE.md) → Sets system context, rules, preferences
    ↓
Optionally load a saved session → Restores conversation history
    ↓
User has consistent, reproducible starting point
```

### Proposed Implementation

**File precedence** (nearest-file wins):
```
~/.ppxai/AGENTS.md          # Global defaults (your preferences)
~/project/AGENTS.md         # Project-specific rules (team shared)
~/project/src/api/AGENTS.md # Subdirectory overrides (monorepo)
```

**Commands**:
- `/agents show` - Display current AGENTS.md content
- `/agents reload` - Reload after editing
- `/agents edit` - Open in $EDITOR

**Key insight**: AGENTS.md + session restore together create a "workspace context" that's reproducible across sessions and team members.

### Decision Points

- Should ppxai support both `AGENTS.md` and `CLAUDE.md`?
- Is this a v1.12 priority or later?
- How does this interact with existing session management?

---

## 2. Atomic Multi-File Edits with Checkpointing

### The Problem

Current ppxai agent mode applies file changes one-by-one:

```
Agent iteration 2: replace_block(auth.py, old, new) → file modified
Agent iteration 4: insert_text(tests/test_auth.py, line 50, new_test) → file modified
```

If something goes wrong:
- No automatic "before" snapshot
- Can't easily undo both changes atomically
- 65% of developers report AI missing context in multi-file refactoring (research finding)
- Notable incident: Replit's agent deleted a production database

### What "Corrupted State" Actually Means

When multi-file edits fail mid-way, the problem is **filesystem state**, not AI context:

```
Agent Task: "Refactor auth module to use JWT"

Iteration 1: Edit auth.py ✅ (adds JWT imports, changes login())
Iteration 2: Edit user.py ✅ (updates User class)
Iteration 3: Edit tests/test_auth.py ❌ FAILS (syntax error, user rejects, or AI hallucinates)
```

**Result:** Codebase is in an **inconsistent intermediate state**:
- `auth.py` and `user.py` modified (expect JWT)
- `tests/test_auth.py` unchanged (expects old auth)
- Code may not compile/run
- `git diff` shows a mess of partial changes

| Corruption Aspect | Impact |
|-------------------|--------|
| **Code consistency** | Files reference functions/imports that don't exist or were partially changed |
| **Test failures** | Tests written for old code, implementation changed |
| **Build breakage** | Partial refactoring leaves dangling imports, missing symbols |
| **Manual recovery** | User must manually figure out what changed and how to fix it |

### Why Not Vector DBs (ChromaDB)?

Considered using embedded vector databases for checkpointing. **Rejected** because:

| Requirement | Vector DB | Git | In-Memory Snapshots |
|-------------|-----------|-----|---------------------|
| Store exact file content | Overkill | ✅ Perfect | ✅ Good |
| Point-in-time recovery | ❌ Not designed for | ✅ Native | ✅ Easy |
| Atomic multi-file rollback | ❌ No | ✅ `git revert` | ✅ Copy back |
| Diff viewing | ❌ No | ✅ `git diff` | Need to compute |
| Dependencies | Heavy (~300MB) | Already have | Zero |

Vector DBs are designed for semantic similarity search (RAG), not filesystem snapshots. Git already solves this problem perfectly.

### How Others Solve It

| Tool | Approach |
|------|----------|
| **Aider** | Every AI edit commits immediately to Git with descriptive message |
| **Claude Code** | Checkpoint system + `/rewind` command to browse/restore |
| **Replit** | Checkpoints capture entire project state (like game save points) |

### Proposed Implementation for ppxai

**Git-based checkpoints** (like Aider):

```
User: /agent refactor auth module
    ↓
ppxai creates Git commit: "ppxai: checkpoint before agent task"
    ↓
AI modifies auth.py + tests/test_auth.py (with user consent)
    ↓
ppxai creates Git commit: "ppxai: Refactored auth module"
    ↓
User can: /undo → git revert HEAD (undoes both files atomically)
```

**Safety semantics**:
```
Before: file1.py (original), file2.py (original)
Agent runs → Auto-checkpoint created
After: file1.py (modified), file2.py (modified)
User: /undo → Both files restored atomically
```

**Scope boundaries** (to avoid complexity explosion):
- Single project/repo at a time
- No cross-repo edits
- Git must be initialized (non-git dirs: warn and skip checkpointing)

### Effort Estimates

| Feature | Effort |
|---------|--------|
| Git-based auto-checkpoints | 4-6 hours |
| `/undo` command (revert HEAD) | 2 hours |
| `/rewind` browser (interactive) | 8-10 hours |
| Dry-run mode (`/agent --dry-run`) | 3-4 hours |

### Implementation Options

**Option 1: Git-based (Recommended)**
```python
# Before agent task
subprocess.run(["git", "stash", "push", "-m", "ppxai-checkpoint"])
# or: git commit with "ppxai: checkpoint" message

# After failure or /undo
subprocess.run(["git", "stash", "pop"])
# or: git revert HEAD
```
- Zero new dependencies (users already have Git)
- Full diff viewing for free
- Persists across sessions if desired

**Option 2: In-memory snapshots (session-scoped)**
```python
class CheckpointManager:
    def __init__(self):
        self.checkpoints: dict[str, dict[str, bytes]] = {}

    def create(self, files: list[str]) -> str:
        checkpoint_id = f"cp-{datetime.now().isoformat()}"
        self.checkpoints[checkpoint_id] = {
            path: Path(path).read_bytes() for path in files
        }
        return checkpoint_id

    def restore(self, checkpoint_id: str):
        for path, content in self.checkpoints[checkpoint_id].items():
            Path(path).write_bytes(content)
```
- Zero dependencies
- Ephemeral (gone when session ends)
- Fast for small files

**Option 3: SQLite (persistent without Git)**
```python
import sqlite3
conn = sqlite3.connect("~/.ppxai/checkpoints.db")
# Store: (checkpoint_id, file_path, content, timestamp)
```
- Tiny dependency (built into Python)
- ACID transactions
- Persists across sessions

### Recommendation

Start with **Git-based auto-commits** in agent mode:
- Zero new dependencies
- Battle-tested atomic operations
- Free diff viewing with `git diff`
- Aligns with Aider's proven pattern
- Low effort, high safety value

---

## 3. Textual TUI Framework Migration

### Background

Textual is a production-ready TUI framework built on Rich (which ppxai already uses).

**Production apps using Textual**:
- **Elia** - Terminal ChatGPT client (very similar to ppxai)
- **Toad** - Frontend for AI coding tools (OpenHands, Claude Code, Gemini CLI)
- **Harlequin** - SQL IDE

### Comparison

| Aspect | Current (Rich + prompt_toolkit) | With Textual |
|--------|--------------------------------|--------------|
| Output | Static print, scroll terminal | Reactive widgets, auto-refresh |
| Interactivity | Basic input handling | Full keyboard/mouse navigation |
| Layout | None | Grid, docking, split panes |
| Browser | No | `textual serve` runs same code |

### Potential "Killer App" Features

| Feature | Description |
|---------|-------------|
| **Split-pane view** | Chat + file tree + preview side-by-side |
| **Scrollable chat** | Page Up/Down through history |
| **Click to expand** | Click on tool call to see details |
| **Modal dialogs** | Native modals for consent prompts |
| **Inline diff viewer** | See file changes before applying |
| **Web deployment** | Same TUI runs in browser |

### Migration Approach (if pursued)

1. Keep current Rich output for v1.12 (stability)
2. Prototype Textual chat widget in parallel
3. Full migration in v1.14+ once validated

### Honest Assessment

- Current TUI is functional and works
- Migration is significant effort (~20-40 hours for full rewrite)
- Risk of bugs during migration
- Not a priority unless current TUI becomes limiting

---

## 4. libghostty SDK Integration

### Background

libghostty is the embeddable terminal library from Ghostty (Mitchell Hashimoto).

### Status

- Currently in alpha
- C API coming "within 6 months" (announced late 2025)
- Expected stable release: 2026

### Potential for ppxai

- GPU-accelerated terminal rendering
- True cross-platform terminal widget
- Could power a standalone ppxai desktop app

### Recommendation

**Watch and wait**. Not actionable until stable C API available.

---

## Proposed Priority Summary

| Priority | Feature | Rationale |
|----------|---------|-----------|
| **v1.12** | AGENTS.md as session bootstrap | Clear user value, aligns with industry standard, low-medium effort |
| **v1.12** | Git-based atomic checkpoints in agent mode | Safety, proven pattern (Aider), medium effort |
| **v1.13** | `/undo` and `/rewind` commands | Builds on checkpoints |
| **Future** | Textual TUI | Only if current TUI becomes limiting |
| **Watch** | libghostty | Wait for stable SDK (2026) |

---

## Research Sources

### AGENTS.md
- [AGENTS.md Official Site](https://agents.md)
- [GitHub Blog: How to write a great agents.md](https://github.blog/ai-and-ml/github-copilot/how-to-write-a-great-agents-md-lessons-from-over-2500-repositories/)
- [Anthropic: Claude Code Best Practices](https://www.anthropic.com/engineering/claude-code-best-practices)

### Atomic Edits
- [Aider Git Integration](https://aider.chat/docs/git.html)
- [Claude Code Checkpointing Docs](https://code.claude.com/docs/en/checkpointing)
- [Google Research: Accelerating Code Migrations with AI](https://research.google/blog/accelerating-code-migrations-with-ai/)

### Textual
- [Textual Official Documentation](https://textual.textualize.io/)
- [Real Python - Python Textual Tutorial](https://realpython.com/python-textual/)

### libghostty
- [Libghostty Is Coming - Mitchell Hashimoto](https://mitchellh.com/writing/libghostty-is-coming)
- [Ghostty Official Docs](https://ghostty.org/docs/about)

---

## Open Questions

1. **AGENTS.md priority**: Is reproducible session bootstrap a v1.12 must-have or nice-to-have?

2. **Checkpointing scope**: Should checkpoints apply to all file edits or only `/agent` mode?

3. **Textual investment**: Is there a specific UX limitation in current TUI that would justify the migration effort?

4. **Non-goals clarity**: Should ppxai explicitly position itself as "not trying to be Claude Code" or keep options open?

---

**Created**: December 27, 2025
**Status**: Pending decision - to be reconciled into ROADMAP.md
