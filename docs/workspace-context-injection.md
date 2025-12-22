# Workspace Context Injection for VSCode Extension

**Issue ID**: Workspace Context Loss
**Date**: 2025-12-22
**Version**: v1.11.2+
**Status**: Resolved

## Problem Statement

The VSCode extension sets the working directory on the server during initialization via `setWorkingDir()`, but the AI doesn't receive this context when responding to chat messages. This causes the AI to:

1. Default to `/tmp` or other arbitrary directories
2. Ask users for explicit paths even when working in a known workspace
3. Create files in unexpected locations

### Example Scenario

**User asks**: "Create a test file"
**Expected**: File created in workspace root
**Actual**: AI asks "where should I create it?" or defaults to `/tmp`

## Root Cause

The workspace path is set on the server's engine, but **not included in the message context** sent to the AI. The server knows the working directory, but the AI model doesn't.

## Solution: Dual Context Injection

Implemented a two-part solution combining visibility and automatic context injection.

### Part 1: Auto-Inject Workspace Context

Every chat message automatically includes workspace context at the beginning:

```
[Context: Working in VSCode workspace "ppxai" at /Users/rado/git/utils/ppxai]

User's actual message here...
```

**Benefits:**
- AI always knows the workspace location
- No user action required
- Consistent with existing `@filename` pattern
- Minimal token overhead (~20-30 tokens)

**Implementation Location**: `chatPanel.ts` - `handleChat()` method

### Part 2: Visual Workspace Indicator

Added workspace information to the header UI:

```
📁 /Users/rado/git/utils/ppxai (ppxai)
```

**Benefits:**
- User can see current workspace
- Visual confirmation of context
- Compact, non-intrusive design

**Implementation Location**: `chatPanel.ts` - HTML template

## Technical Implementation

### Modified Files

1. **vscode-extension/src/chatPanel.ts**
   - Added `getWorkspaceContext()` method
   - Modified `handleChat()` to inject workspace context
   - Added workspace display to header HTML
   - Added CSS for workspace info styling

### Code Changes

#### Auto-Injection Logic

```typescript
private async getWorkspaceContext(): Promise<string> {
    const workspaceFolders = vscode.workspace.workspaceFolders;
    if (!workspaceFolders || workspaceFolders.length === 0) {
        return "";  // No context if no workspace
    }

    const workspaceRoot = workspaceFolders[0].uri.fsPath;
    const workspaceName = workspaceFolders[0].name;

    return `[Context: Working in VSCode workspace "${workspaceName}" at ${workspaceRoot}]\n\n`;
}
```

#### Message Augmentation

```typescript
// In handleChat()
const { message: augmentedMessage, files: resolvedFiles } =
    await this.processFileReferences(content);

// Add workspace context
const workspaceContext = await this.getWorkspaceContext();
const finalMessage = workspaceContext + augmentedMessage;
```

#### UI Display

```html
<div class="workspace-info" id="workspaceInfo" style="display: none;">
    <span class="workspace-icon">📁</span>
    <span id="workspacePath"></span>
    <span class="workspace-name">(<span id="workspaceName"></span>)</span>
</div>
```

## Token Cost Analysis

**Typical Workspace Context:**
```
[Context: Working in VSCode workspace "ppxai" at /Users/rado/git/utils/ppxai]

```

**Token Count**: ~25-35 tokens (depending on path length)

**Cost Impact**:
- Input cost: Negligible (< $0.001 per message)
- Benefit: Prevents confused AI responses that waste more tokens asking for clarification

**Verdict**: Cost is justified by improved UX and reduced token waste on clarifications.

## Alternative Solutions Considered

### Option A: System Prompt with Workspace
**Pros**: No per-message token cost
**Cons**: Requires server changes, less flexible
**Decision**: Not implemented (would require engine changes)

### Option B: Smart Path Resolution Dialog
**Pros**: User control
**Cons**: Interrupts flow, extra clicks
**Decision**: Not implemented (too disruptive)

### Option C: Visual Display Only (No Auto-Inject)
**Pros**: Zero token cost
**Cons**: AI still doesn't know workspace
**Decision**: Implemented as Part 2, combined with Part 1

## Testing Checklist

- [x] Workspace context injected into chat messages
- [x] Workspace info displays in header when workspace is open
- [x] Workspace info hidden when no workspace is open
- [x] Multi-root workspace handling (uses first workspace)
- [x] Context doesn't appear when loading from sessions (only new messages)
- [x] Existing @file references still work
- [x] No visual overlap with other header elements

## Edge Cases Handled

1. **No Workspace Open**: Context injection returns empty string, UI element hidden
2. **Multi-Root Workspaces**: Uses first workspace folder
3. **Long Paths**: CSS truncates with ellipsis
4. **Session Loading**: Context not injected for historical messages
5. **Slash Commands**: Context still injected (commands may use workspace)

## Performance Impact

**Negligible:**
- `getWorkspaceContext()`: < 1ms (reads from VSCode API cache)
- UI update: < 1ms (single DOM update on init)
- Memory: +25-50 bytes per message (string concatenation)

## Future Enhancements

Potential improvements for future versions:

1. **Workspace Switcher**: Dropdown to switch between multi-root workspaces
2. **Path Shortening**: Show `~/git/utils/ppxai` instead of full path
3. **Click to Copy**: Click workspace path to copy to clipboard
4. **Relative Path Mode**: Option to show relative paths in AI responses
5. **Git Branch Display**: Show current git branch in workspace info

## Related Features

This feature works alongside:
- `@filename` file references (existing)
- `setWorkingDir()` server API (existing)
- File path resolution in tool results (existing)

## Migration Notes

**Breaking Changes**: None
**Backward Compatibility**: 100%
**Upgrade Path**: Automatic on extension reload

## References

- VSCode API: `vscode.workspace.workspaceFolders`
- Related Issue: AI defaulting to `/tmp` directory
- Implementation PR: v1.11.2+ workspace context
