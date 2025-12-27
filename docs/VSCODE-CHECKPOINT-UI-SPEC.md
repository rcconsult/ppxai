# VSCode Extension Checkpoint UI Specification (v1.12.0)

This document specifies the UI changes needed in the VSCode extension to maintain UX parity with the TUI for the checkpoint/undo feature.

## Goal

Users should have the same experience in both TUI and VSCode extension regarding:
1. Checkpoint status visibility
2. Undo functionality
3. Informative notifications about checkpoint operations

## TUI Reference Implementation

**Status Line** (shown at every prompt):
```
[Perplexity | sonar-pro | Tools: ON | Agent: ON | Checkpoints: git]
```

**Notifications**:
- When agent mode enabled: "🔒 Agent Mode enabled with Git checkpoints..."
- When checkpoint created: "✓ Checkpoint created: abc123de (Task description)"
- When undo successful: "✓ Changes reverted using git revert (checkpoint: abc123de)"

## VSCode Extension UI Equivalents

### 1. Agent Toggle Button Enhancement

**Current State**: Simple ON/OFF toggle button

**New State (v1.12.0)**: Enhanced button with checkpoint status indicator

```typescript
// Button states:
// 1. Agent OFF
//    Icon: "Agent"
//    Color: Gray
//    Tooltip: "Enable Agent Mode"

// 2. Agent ON + Git checkpoints
//    Icon: "Agent 🔒"
//    Color: Green
//    Tooltip: "Agent Mode ON (Checkpoints: git)\n• Auto-commits before tasks\n• Use Undo button to revert"

// 3. Agent ON + File checkpoints
//    Icon: "Agent ⚠️"
//    Color: Yellow
//    Tooltip: "Agent Mode ON (Checkpoints: file)\n• Snapshots saved to ~/.ppxai/checkpoints\n• Use Undo button to revert\n• Tip: Init git repo for atomic commits"

// 4. Agent ON + No checkpoints
//    Icon: "Agent ⚠️"
//    Color: Orange/Red
//    Tooltip: "Agent Mode ON (Checkpoints: DISABLED)\n• Changes cannot be undone\n• Initialize git repo to enable checkpoints"
```

### 2. New Undo Button

**Location**: Next to Agent toggle button in chat panel header

**Visibility**: Only visible when agent mode is enabled AND checkpoint exists

**Implementation**:
```typescript
interface UndoButtonState {
  visible: boolean;      // Show only if agent mode ON
  enabled: boolean;      // Enable only if checkpoint exists
  checkpointId: string;  // Last checkpoint ID
  backend: "git" | "file" | "none";
}

// Button appearance:
// - Icon: "↶" (undo arrow) or vscode "discard" icon
// - Color: When enabled: blue/white, When disabled: gray
// - Tooltip (enabled): "Undo Last Agent Task\nCheckpoint: abc123de (git)"
// - Tooltip (disabled): "No checkpoint to undo"

// On click:
// 1. Show confirmation modal:
//    "Undo Last Agent Task?"
//    "This will revert all changes made by the last agent task."
//    "Backend: git"
//    "Checkpoint: abc123de"
//    [Cancel] [Undo]
//
// 2. On confirm:
//    POST /checkpoint/undo
//
// 3. On success:
//    Show notification: "✓ Changes reverted (checkpoint: abc123de)"
//
// 4. On failure:
//    Show error: "✗ Undo failed. Check logs for details."
```

### 3. Checkpoint Notifications in Chat

**When agent mode enabled**:
```typescript
// Add system message to chat:
{
  role: "system",
  content: "🔒 Agent Mode enabled with Git checkpoints\n• Changes will be auto-committed before each task\n• Use Undo button to revert the last agent task atomically",
  timestamp: "10:30:45"
}
```

**When checkpoint created**:
```typescript
// Add system message to chat:
{
  role: "system",
  content: "✓ Checkpoint created: abc123de (Refactor auth module)",
  timestamp: "10:31:00"
}
```

**When undo successful**:
```typescript
// Add system message to chat:
{
  role: "system",
  content: "✓ Changes reverted using git revert (checkpoint: abc123de)",
  timestamp: "10:35:12"
}
```

### 4. Status Polling

The extension should poll `/agent/status` to keep UI in sync:

```typescript
// Poll every 2-3 seconds when agent mode is enabled
async function updateAgentStatus() {
  const response = await fetch(`${serverUrl}/agent/status`);
  const status = await response.json();

  // Update agent toggle button state
  updateAgentButton(status.agent_mode, status.checkpoint);

  // Update undo button visibility/state
  updateUndoButton(status.checkpoint);
}

// status.checkpoint structure (from v1.12.0 API):
{
  enabled: boolean,
  backend: "git" | "file" | "none",
  last_checkpoint: string | null,
  status_description: string
}
```

## API Endpoints Used

1. **GET /agent/status** - Returns agent mode + checkpoint status
2. **GET /checkpoint/status** - Returns detailed checkpoint info (optional)
3. **POST /checkpoint/undo** - Performs undo operation

## Implementation Checklist

- [ ] Update `src/chatPanel.ts` - Add undo button to webview HTML
- [ ] Update agent toggle button - Add checkpoint status indicator (🔒 or ⚠️)
- [ ] Add undo button click handler - Call POST /checkpoint/undo
- [ ] Add confirmation modal for undo - Prevent accidental undo
- [ ] Update status polling - Include checkpoint status
- [ ] Add system messages for notifications - Checkpoint created/undo success
- [ ] Update button tooltips - Show checkpoint backend and status
- [ ] Handle SSE events for checkpoints - Display STATUS events from engine
- [ ] Test git backend - Verify commit/revert workflow
- [ ] Test file backend - Verify snapshot/restore workflow
- [ ] Test no-git scenario - Proper warnings shown

## Visual Mockup

```
┌─────────────────────────────────────────────────────────┐
│ PPXAI Chat Panel                          [Agent 🔒] [↶]│  <-- Enhanced buttons
├─────────────────────────────────────────────────────────┤
│                                                         │
│ You: Refactor the auth module to use JWT              │
│                                                         │
│ 🔒 Agent Mode enabled with Git checkpoints            │  <-- System notification
│ • Changes will be auto-committed before each task      │
│ • Use Undo button to revert the last agent task       │
│                                                         │
│ ✓ Checkpoint created: f3a7b2c1 (Refactor auth module)│  <-- Checkpoint notification
│                                                         │
│ 🤖 Starting autonomous agent...                        │
│ [Agent response with tool calls]                       │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

## Configuration

Same configuration as TUI (from `ppxai-config.json`):

```json
{
  "tools": {
    "agent": {
      "checkpoint_backend": "auto",  // "auto" | "git" | "file" | "none"
      "max_iterations": 10,
      "context_char_limit": 2000,
      "min_task_words": 3
    }
  }
}
```

## Notes

- The VSCode extension should **never** directly manipulate git or files
- All checkpoint operations go through the server API
- UI is purely presentational and reactive to server state
- Maintain consistency with TUI in terminology and messaging
- Use VSCode's native UI components (buttons, modals, notifications)
