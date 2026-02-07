# CRITICAL: Checkpoint Undo Safety Bug

**Status:** MUST FIX before v1.12.0 release
**Severity:** Critical - could cause data loss for non-advanced users
**Date Identified:** 2025-12-29

## Problem Description

The checkpoint system retains stale checkpoint IDs after the branch moves forward with non-agent commits. When a user clicks the Undo button, it attempts to `git revert` an old commit that may have been superseded by newer work.

### Example Scenario

1. User runs agent task → creates checkpoint commit `8668696`
2. User (or Claude) makes additional commits: `216ac00`, `afb86ad`
3. Server still reports `last_checkpoint: 86686965`
4. User clicks Undo → `git revert 8668696` runs
5. **Result:** Reverts old changes, potentially breaking newer code or causing conflicts

### Current Behavior (WRONG)

```
Commits:  afb86ad → 216ac00 → 8668696 → ... (older)
                              ↑
                    Server thinks this is "undoable"
```

### Expected Behavior (CORRECT)

The checkpoint should be invalidated when:
1. New commits are made after the checkpoint (manual or by another tool)
2. The checkpoint commit is no longer HEAD or HEAD~1
3. User explicitly clears the checkpoint

## Proposed Solutions

### Option A: Validate checkpoint before Undo (Minimum)
- Before executing undo, verify checkpoint commit is HEAD or HEAD~1
- If not, show error: "Checkpoint is stale. New commits have been made since the agent task."
- Clear the stale checkpoint

### Option B: Auto-invalidate on branch movement (Better)
- Track the commit SHA when checkpoint is created
- On any `/checkpoint/status` call, verify checkpoint is still valid
- If HEAD has moved beyond checkpoint, automatically clear it

### Option C: Checkpoint scoping (Best)
- Only allow undo if checkpoint commit is the direct parent of HEAD
- After successful agent task + auto-commit, checkpoint = pre-task commit
- Any subsequent commit (agent or manual) invalidates previous checkpoint

## Acceptance Criteria

- [ ] Undo button is disabled/hidden when checkpoint is stale
- [ ] Clear error message when user tries to undo stale checkpoint
- [ ] Checkpoint automatically cleared when branch moves forward
- [ ] No possibility of reverting wrong commit for non-advanced users

## Files Involved

- `ppxai/checkpoint.py` - Checkpoint manager
- `ppxai/server/http.py` - `/checkpoint/status`, `/checkpoint/undo` endpoints
- `vscode-extension/src/chatPanel.ts` - Undo button UI
- `vscode-extension/src/httpClient.ts` - `undoCheckpoint()` method

## Testing Required

1. Run agent task → checkpoint created
2. Make manual commit → checkpoint should be invalidated
3. Click Undo → should show "checkpoint stale" error, not revert
4. Run new agent task → new checkpoint should work correctly
