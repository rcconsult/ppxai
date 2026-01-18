# chatPanel.ts Refactoring Design

**Status:** Proposed
**Target:** v1.14.x
**Current Size:** 5,123 lines
**Goal:** < 1,500 lines (70% reduction)

---

## Problem Statement

`vscode-extension/src/chatPanel.ts` is 5,123 lines - the last remaining monolithic file in the codebase. It mixes:
- Webview HTML/CSS/JavaScript generation (2,175 lines - 42%)
- Slash command handling (~400 lines)
- Stream event handling (~165 lines)
- Consent request handling (~220 lines)
- Agent loop logic (~100 lines)
- File reference processing (~100 lines)
- Status/initialization (~200 lines)

---

## Current Structure Analysis

```
chatPanel.ts (5,123 lines)
├── Imports & class declaration (1-54)
├── resolveWebviewView() - entry point (55-370)
│   └── Message handler switch (72-130)
├── handleStreamEvent() (371-550)
│   └── Event type switch (375-540)
├── handleConsentRequest() (551-770)
│   ├── handleFileConsentRequest()
│   └── handleShellConsentRequest()
├── handleChat() - main dispatcher (145-730)
│   └── Slash command switch (734-1020)
├── Command handlers (1020-1400)
│   ├── handleToolsCommand()
│   ├── handleCheckpointCommand()
│   ├── handleAgentCommand()
│   ├── handleShowCommand()
│   └── handleContextCommand()
├── Agent logic (1407-1500)
│   ├── buildAgentPrompt()
│   └── buildContinuationPrompt()
├── File processing (1500-1990)
│   └── processFileReferences()
├── Status updates (1992-2840)
├── _getNonce() (2836-2843)
├── getFileEditingHelp() (2845-2946)
└── _getHtmlForWebview() (2947-5122) ← 42% of file!
```

---

## Refactoring Plan

### Phase 1: Extract Webview Template (Priority: High)

**Target:** Reduce by ~2,100 lines (41%)

Extract `_getHtmlForWebview()` to external files:

```
vscode-extension/
├── src/
│   └── chatPanel.ts          # Reduced to ~3,000 lines
└── media/
    ├── webview/
    │   ├── index.html        # HTML template
    │   ├── styles.css        # CSS (currently inline)
    │   └── main.js           # JavaScript (currently inline)
    └── ... (existing)
```

**Changes:**
1. Create `media/webview/styles.css` - extract ~500 lines of inline CSS
2. Create `media/webview/main.js` - extract ~1,500 lines of inline JS
3. Create `media/webview/index.html` - minimal HTML skeleton with placeholders
4. Update `_getHtmlForWebview()` to load and compose template files
5. Use `${placeholder}` tokens for CSP nonce, URIs, etc.

**Benefits:**
- Syntax highlighting in IDE for CSS/JS
- Easier CSS/JS debugging
- Hot reload potential for webview development
- Clear separation of concerns

---

### Phase 2: Extract Command Handlers (Priority: Medium)

**Target:** Reduce by ~400 lines (8%)

Create `src/commandHandlers.ts`:

```typescript
// commandHandlers.ts
export interface CommandContext {
    view: vscode.WebviewView;
    backend: HttpClient;
    updateStatus: () => Promise<void>;
}

export async function handleToolsCommand(ctx: CommandContext, args: string[]): Promise<void>;
export async function handleCheckpointCommand(ctx: CommandContext, args: string[]): Promise<void>;
export async function handleAgentCommand(ctx: CommandContext, args: string[]): Promise<void>;
export async function handleShowCommand(ctx: CommandContext, args: string[]): Promise<void>;
export async function handleContextCommand(ctx: CommandContext, args: string[]): Promise<void>;
export async function handleModelCommand(ctx: CommandContext, args: string[]): Promise<void>;
export async function handleProviderCommand(ctx: CommandContext, args: string[]): Promise<void>;
export async function handleSessionsCommand(ctx: CommandContext, args: string[]): Promise<void>;
// ... etc
```

**Benefits:**
- Testable command handlers
- Reusable across potential future panels
- Cleaner chatPanel.ts focused on orchestration

---

### Phase 3: Extract Event Handlers (Priority: Medium)

**Target:** Reduce by ~200 lines (4%)

Create `src/eventHandlers.ts`:

```typescript
// eventHandlers.ts
export interface EventContext {
    view: vscode.WebviewView;
    postMessage: (msg: any) => void;
}

export function handleStreamEvent(ctx: EventContext, event: StreamEvent): void;
export function handleThinkingEvent(ctx: EventContext, data: any): void;
export function handleChunkEvent(ctx: EventContext, data: string): void;
export function handleToolCallEvent(ctx: EventContext, data: any): void;
export function handleAgentIterationEvent(ctx: EventContext, data: any): void;
// ... etc
```

---

### Phase 4: Extract Consent Handlers (Priority: Low)

**Target:** Reduce by ~220 lines (4%)

Create `src/consentHandlers.ts`:

```typescript
// consentHandlers.ts
export async function handleConsentRequest(
    event: StreamEvent,
    backend: HttpClient
): Promise<void>;

export async function handleFileConsentRequest(
    data: FileConsentRequest,
    metadata: EventMetadata | undefined,
    backend: HttpClient
): Promise<void>;

export async function handleShellConsentRequest(
    data: ShellConsentRequest,
    backend: HttpClient
): Promise<void>;
```

---

## Implementation Order

| Phase | Lines Removed | Cumulative | New Files |
|-------|-------------:|------------|-----------|
| 1. Webview template | ~2,100 | 3,000 | 3 (html, css, js) |
| 2. Command handlers | ~400 | 2,600 | 1 (commandHandlers.ts) |
| 3. Event handlers | ~200 | 2,400 | 1 (eventHandlers.ts) |
| 4. Consent handlers | ~220 | 2,180 | 1 (consentHandlers.ts) |

**Final target:** ~1,500 lines (70% reduction)

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Webview CSP issues | Test incrementally, validate nonce handling |
| TypeScript imports | Use barrel exports in index.ts |
| Breaking VSCode API | Keep webview.postMessage interface stable |
| Testing regression | Run manual extension tests after each phase |

---

## Dependencies

- Phase 1 is independent (highest impact, do first)
- Phases 2-4 can be done in any order after Phase 1
- Each phase should be a separate commit for easy rollback

---

## Alternatives Considered

1. **Keep as-is**: Rejected - file is too large to maintain
2. **Split into multiple panels**: Overkill - single panel with extracted helpers is sufficient
3. **Use Vue/React for webview**: Too much churn - keep vanilla JS for now

---

## Success Criteria

- [ ] chatPanel.ts < 1,500 lines
- [ ] All VSCode extension tests pass
- [ ] Extension loads and works correctly
- [ ] No TypeScript compilation errors
- [ ] PR review approved
