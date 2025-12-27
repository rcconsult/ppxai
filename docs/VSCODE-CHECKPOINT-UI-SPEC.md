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

## Input State Management During Agent Execution

### Concurrent Request Prevention

**Requirement**: Prevent user from sending new prompts while agent is executing a multi-file task.

**Implementation**:
- **HTTP Server**: Requests are serialized with `asyncio.Lock` (v1.12.0)
  - `/chat` and `/coding_task` endpoints hold lock during streaming
  - Subsequent requests wait for current task to complete
  - Lock released after streaming finishes or error occurs

- **VSCode Extension**: Input field should be disabled while agent is running
  - Disable input textarea when agent mode is ON and streaming is active
  - Show visual indicator: "Agent is working... (streaming updates below)"
  - Re-enable input after streaming completes or is interrupted

**Why**: Prevents concurrent requests from corrupting conversation state and ensures consistent UX with TUI (which naturally blocks via `asyncio.run()`).

### Streaming Interrupt Handling

**Requirement**: User can interrupt agent execution anytime via the "⏹ Streaming..." button.

**Current Button**: Orange pulsing "⏹ Streaming..." badge in chat panel header (v1.10.8)

**New Behavior (v1.12.0)**: When user clicks stop button during agent execution:

1. **Client-side**:
   - Close SSE connection immediately
   - Show system message: "⚠️  Agent interrupted by user"
   - Display interrupt recovery UI (see below)

2. **Server-side**:
   - Detect closed connection (client dropped SSE stream)
   - Raise `KeyboardInterrupt` in agent loop
   - Trigger same interrupt handler as TUI

3. **Interrupt Recovery UI**:
```typescript
// Show modal dialog:
{
  title: "Agent Task Interrupted",
  message: `
    Agent task incomplete due to interrupt.

    Checkpoint: ${checkpointId}
    Backend: ${backend}

    Rollback all changes from this task?
  `,
  buttons: [
    {
      label: "Rollback to Checkpoint",
      description: "Undo all changes made by this agent task",
      action: "rollback"
    },
    {
      label: "Keep Partial Changes",
      description: "Keep changes for manual review",
      action: "keep"
    }
  ]
}

// If user chooses "Rollback":
// 1. POST /checkpoint/undo
// 2. Show system message: "✓ Checkpoint reverted successfully"
//
// 3. If git backend AND uncommitted changes detected:
//    Show second modal:
{
  title: "Uncommitted Changes Detected",
  message: `
    Working directory has uncommitted changes from interrupted task.

    Clean working directory?
  `,
  buttons: [
    {
      label: "Remove All Changes",
      description: "git reset --hard (clean slate)",
      action: "clean"
    },
    {
      label: "Keep for Review",
      description: "Manual review and cleanup",
      action: "keep"
    }
  ]
}

// If user chooses "Remove All Changes":
// 4. Show system message: "Running git reset --hard..."
// 5. Show system message: "✓ Working directory cleaned"
```

**Key Points**:
- ⏹ Streaming button remains available during agent execution (user can stop anytime)
- Input field is disabled (prevents new prompts)
- Interrupt triggers same rollback flow as TUI Ctrl-C
- User gets full control: rollback or keep changes, clean or review

### Streaming Progress Updates

**Requirement**: Show real-time progress while agent is executing.

**Implementation**:
- SSE events stream progress updates to extension
- Relevant event types (from `ppxai/engine/types.py`):
  - `EventType.STATUS` - Checkpoint notifications, warnings
  - `EventType.AGENT_ITERATION` - "━━━ Iteration 3/10 ━━━"
  - `EventType.AGENT_COMPLETE` - "✅ Task completed!"
  - `EventType.AGENT_MAX_ITERATIONS` - "⚠️  Max iterations reached"
  - `EventType.TOOL_CALL` - "→ Calling tool: read_file"
  - `EventType.STREAM_CHUNK` - AI response chunks

**Display**:
- Render all events as system messages in chat panel
- Format iteration messages with visual separators
- Show tool calls in real-time (not just at end)
- Stream AI response chunks as they arrive

**Example Flow**:
```
You: Refactor authentication module

🔒 Agent Mode enabled with Git checkpoints      ← EventType.STATUS
✓ Checkpoint created: f3a7b2c1                   ← EventType.STATUS

━━━ Iteration 1/10 ━━━                           ← EventType.AGENT_ITERATION
→ Calling tool: read_file (auth/login.py)        ← EventType.TOOL_CALL
I'll analyze the current auth implementation...  ← EventType.STREAM_CHUNK

━━━ Iteration 2/10 ━━━                           ← EventType.AGENT_ITERATION
→ Calling tool: apply_patch                      ← EventType.TOOL_CALL
[User clicks ⏹ Stop button]

⚠️  Agent interrupted by user                    ← Client-side message
[Interrupt recovery modal shown]
```

## Notes

- The VSCode extension should **never** directly manipulate git or files
- All checkpoint operations go through the server API
- UI is purely presentational and reactive to server state
- Maintain consistency with TUI in terminology and messaging
- Use VSCode's native UI components (buttons, modals, notifications)
- Input locking + interrupt button = same UX as TUI (blocking but interruptible)
