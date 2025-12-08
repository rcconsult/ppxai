# IDE Integration Plan: Workspace Awareness & Code Actions

## Executive Summary

This document outlines the implementation plan for deep IDE integration, enabling ppxai to have full awareness of the VS Code workspace, interact with open files, apply code changes, and execute commands - similar to Claude Code and Gemini Code Assist.

**Target Versions:**
- v1.14.0: Workspace Awareness (Read-only)
- v1.15.0: Code Actions (Write capabilities)

**Prerequisites:** Complete [SSE migration](sse-migration-plan.md) (v1.9.0 Part B)

---

## Motivation

### Current Limitations

| Capability | Current ppxai | Claude Code | Gemini Code Assist |
|------------|---------------|-------------|-------------------|
| Workspace file list | - | Yes | Yes |
| Read any file | @file in chat only | Yes | Yes |
| Current selection | - | Yes | Yes |
| Apply code edits | - | Yes | Yes |
| Navigate to line | - | Yes | Yes |
| Run terminal | - | Yes | Yes |
| Diagnostics | - | Yes | Yes |
| Git integration | - | Yes | Yes |

### User Experience Goals

1. **Extension users**: Seamless IDE integration without extra setup
2. **TUI users**: Optional `/ide connect` for bridge mode
3. **AI capabilities**: Full context awareness for better assistance

---

## Architecture

### Hybrid Approach

The architecture supports both native extension integration and TUI bridge mode:

```
┌─────────────────────────────────────────────────────────────────┐
│                      VS Code Extension                           │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐  │
│  │   Chat UI    │  │  IDE Tools   │  │   Bridge Server       │  │
│  │  (webview)   │  │  (native)    │  │   (for TUI)           │  │
│  │              │  │              │  │   port 54321          │  │
│  └──────┬───────┘  └──────┬───────┘  └───────────┬───────────┘  │
│         │                 │                      │               │
│         │         VS Code APIs                   │               │
│         │    (workspace, window,                 │               │
│         │     languages, git)                    │               │
│         │                 │                      │               │
└─────────┼─────────────────┼──────────────────────┼───────────────┘
          │                 │                      │
          │    HTTP + SSE   │                      │ HTTP (Bridge)
          │    (chat)       │                      │
          ▼                 ▼                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Python Engine                               │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐  │
│  │   AI Chat    │  │ Tool Router  │  │   IDE Client          │  │
│  │  (providers) │  │              │  │   (httpx)             │  │
│  └──────────────┘  └──────┬───────┘  └───────────────────────┘  │
│                           │                                      │
│              ┌────────────┴────────────┐                        │
│              ▼                         ▼                        │
│     Local Tools                   IDE Tools                     │
│  (fs, web, calc)            (workspace, editor,                 │
│  Python executes            terminal, git)                      │
│                             Extension executes                  │
└─────────────────────────────────────────────────────────────────┘
```

### Communication Flow

#### Extension Mode (Native)

```
1. User sends message in extension chat
2. Extension → Python HTTP server (SSE)
3. AI generates tool call (e.g., ide.read_file)
4. Python detects "ide.*" tool → sends to callback
5. Extension receives callback → executes VS Code API
6. Result returned to Python → AI continues
```

#### TUI Mode (Bridge)

```
1. User runs `/ide connect http://localhost:54321` in TUI
2. Python registers callback URL with bridge
3. User sends message in TUI
4. AI generates tool call (e.g., ide.open_file)
5. Python POSTs to bridge → Extension executes
6. Result returned → AI continues
```

### Bidirectional Communication

SSE is server→client only. For IDE tools requiring extension execution:

**Solution: Callback Endpoint**

```typescript
// Extension registers callback with Python on connect
POST /register-ide-callback
{
  "callback_url": "http://localhost:54321/ide/execute",
  "capabilities": ["workspace", "editor", "terminal", "git"]
}

// When AI needs IDE action, Python POSTs to callback
POST http://localhost:54321/ide/execute
{
  "id": "uuid-123",
  "tool": "ide.read_file",
  "args": { "path": "src/main.py" }
}

// Extension executes via VS Code API, returns result
{
  "id": "uuid-123",
  "success": true,
  "result": { "content": "..." }
}
```

---

## IDE Tools Specification

### Workspace Tools (v1.14.0)

| Tool | Description | VS Code API |
|------|-------------|-------------|
| `ide.get_workspace_info` | Get workspace name, root path, folders | `workspace.workspaceFolders` |
| `ide.list_files` | List files matching glob pattern | `workspace.findFiles()` |
| `ide.read_file` | Read file contents | `workspace.fs.readFile()` |
| `ide.search_files` | Search text across workspace | `workspace.findTextInFiles()` |
| `ide.get_open_files` | List currently open editor tabs | `window.tabGroups` |

### Editor Tools (v1.14.0)

| Tool | Description | VS Code API |
|------|-------------|-------------|
| `ide.get_active_file` | Get active editor file path and content | `window.activeTextEditor` |
| `ide.get_selection` | Get highlighted text and location | `editor.selection` |
| `ide.get_visible_range` | Get currently visible lines | `editor.visibleRanges` |
| `ide.open_file` | Open file at optional line/column | `window.showTextDocument()` |
| `ide.reveal_line` | Scroll to specific line | `editor.revealRange()` |

### Diagnostics Tools (v1.14.0)

| Tool | Description | VS Code API |
|------|-------------|-------------|
| `ide.get_diagnostics` | Get errors/warnings for file or workspace | `languages.getDiagnostics()` |
| `ide.get_hover_info` | Get hover information at position | `commands.executeCommand('vscode.executeHoverProvider')` |
| `ide.get_definition` | Get definition location for symbol | `commands.executeCommand('vscode.executeDefinitionProvider')` |

### Code Action Tools (v1.15.0)

| Tool | Description | VS Code API |
|------|-------------|-------------|
| `ide.apply_edit` | Apply text edits to file(s) | `workspace.applyEdit()` |
| `ide.insert_text` | Insert text at position | `editor.edit()` |
| `ide.replace_selection` | Replace current selection | `editor.edit()` |
| `ide.show_diff` | Show diff preview before applying | `commands.executeCommand('vscode.diff')` |
| `ide.format_document` | Format current document | `commands.executeCommand('editor.action.formatDocument')` |

### Terminal Tools (v1.15.0)

| Tool | Description | VS Code API |
|------|-------------|-------------|
| `ide.run_in_terminal` | Run command in integrated terminal | `Terminal.sendText()` |
| `ide.create_terminal` | Create new terminal with name | `window.createTerminal()` |
| `ide.get_terminal_output` | Get recent terminal output (if available) | Custom implementation |

### Git Tools (v1.15.0)

| Tool | Description | VS Code API |
|------|-------------|-------------|
| `ide.git_status` | Get git status (staged, modified, untracked) | Git extension API |
| `ide.git_diff` | Get diff for file or all changes | Git extension API |
| `ide.git_stage` | Stage file(s) | Git extension API |
| `ide.git_commit` | Create commit with message | Git extension API |
| `ide.git_log` | Get recent commit history | Git extension API |

---

## Implementation Plan

### v1.14.0: Workspace Awareness (Phase 1)

**Goal**: Read-only IDE integration with workspace awareness

**Effort**: 12-16 hours

#### Phase 1.1: Extension Bridge Server (3-4 hours)

**File:** `vscode-extension/src/bridge.ts`

```typescript
import * as http from 'http';
import * as vscode from 'vscode';

export class BridgeServer {
    private server: http.Server | null = null;
    private port: number;

    constructor(port: number = 54321) {
        this.port = port;
    }

    async start(): Promise<void> {
        this.server = http.createServer(async (req, res) => {
            // CORS headers for local development
            res.setHeader('Access-Control-Allow-Origin', '*');
            res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
            res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

            if (req.method === 'OPTIONS') {
                res.writeHead(200);
                res.end();
                return;
            }

            const url = new URL(req.url!, `http://localhost:${this.port}`);

            try {
                if (url.pathname === '/status') {
                    res.writeHead(200, { 'Content-Type': 'application/json' });
                    res.end(JSON.stringify({ status: 'ok', version: '1.14.0' }));
                } else if (url.pathname === '/ide/execute' && req.method === 'POST') {
                    const body = await this.readBody(req);
                    const result = await this.executeIDETool(JSON.parse(body));
                    res.writeHead(200, { 'Content-Type': 'application/json' });
                    res.end(JSON.stringify(result));
                } else {
                    res.writeHead(404);
                    res.end('Not Found');
                }
            } catch (error) {
                res.writeHead(500, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ error: String(error) }));
            }
        });

        return new Promise((resolve, reject) => {
            this.server!.listen(this.port, '127.0.0.1', () => {
                console.log(`Bridge server running on http://127.0.0.1:${this.port}`);
                resolve();
            });
            this.server!.on('error', reject);
        });
    }

    private async executeIDETool(request: { id: string; tool: string; args: any }): Promise<any> {
        const { id, tool, args } = request;

        try {
            let result: any;

            switch (tool) {
                case 'ide.get_workspace_info':
                    result = this.getWorkspaceInfo();
                    break;
                case 'ide.list_files':
                    result = await this.listFiles(args.pattern, args.exclude);
                    break;
                case 'ide.read_file':
                    result = await this.readFile(args.path);
                    break;
                case 'ide.get_selection':
                    result = this.getSelection();
                    break;
                case 'ide.get_active_file':
                    result = this.getActiveFile();
                    break;
                case 'ide.open_file':
                    result = await this.openFile(args.path, args.line, args.column);
                    break;
                case 'ide.get_diagnostics':
                    result = this.getDiagnostics(args.path);
                    break;
                default:
                    throw new Error(`Unknown tool: ${tool}`);
            }

            return { id, success: true, result };
        } catch (error) {
            return { id, success: false, error: String(error) };
        }
    }

    private getWorkspaceInfo() {
        const folders = vscode.workspace.workspaceFolders;
        return {
            name: vscode.workspace.name,
            folders: folders?.map(f => ({
                name: f.name,
                path: f.uri.fsPath
            })) || []
        };
    }

    private async listFiles(pattern: string, exclude?: string): Promise<string[]> {
        const files = await vscode.workspace.findFiles(pattern, exclude);
        return files.map(f => vscode.workspace.asRelativePath(f));
    }

    private async readFile(path: string): Promise<{ content: string; language: string }> {
        const uri = this.resolveUri(path);
        const content = await vscode.workspace.fs.readFile(uri);
        const doc = await vscode.workspace.openTextDocument(uri);
        return {
            content: Buffer.from(content).toString('utf-8'),
            language: doc.languageId
        };
    }

    private getSelection(): { text: string; file: string; start: any; end: any } | null {
        const editor = vscode.window.activeTextEditor;
        if (!editor) return null;

        return {
            text: editor.document.getText(editor.selection),
            file: vscode.workspace.asRelativePath(editor.document.uri),
            start: { line: editor.selection.start.line, column: editor.selection.start.character },
            end: { line: editor.selection.end.line, column: editor.selection.end.character }
        };
    }

    private getActiveFile(): { path: string; content: string; language: string } | null {
        const editor = vscode.window.activeTextEditor;
        if (!editor) return null;

        return {
            path: vscode.workspace.asRelativePath(editor.document.uri),
            content: editor.document.getText(),
            language: editor.document.languageId
        };
    }

    private async openFile(path: string, line?: number, column?: number): Promise<boolean> {
        const uri = this.resolveUri(path);
        const doc = await vscode.workspace.openTextDocument(uri);
        const editor = await vscode.window.showTextDocument(doc);

        if (line !== undefined) {
            const position = new vscode.Position(line - 1, column || 0);
            editor.selection = new vscode.Selection(position, position);
            editor.revealRange(new vscode.Range(position, position), vscode.TextEditorRevealType.InCenter);
        }

        return true;
    }

    private getDiagnostics(path?: string): any[] {
        if (path) {
            const uri = this.resolveUri(path);
            return vscode.languages.getDiagnostics(uri).map(d => this.formatDiagnostic(d, path));
        }

        const all: any[] = [];
        for (const [uri, diagnostics] of vscode.languages.getDiagnostics()) {
            const relativePath = vscode.workspace.asRelativePath(uri);
            for (const d of diagnostics) {
                all.push(this.formatDiagnostic(d, relativePath));
            }
        }
        return all;
    }

    private formatDiagnostic(d: vscode.Diagnostic, path: string) {
        return {
            path,
            severity: vscode.DiagnosticSeverity[d.severity],
            message: d.message,
            line: d.range.start.line + 1,
            column: d.range.start.character,
            source: d.source
        };
    }

    private resolveUri(path: string): vscode.Uri {
        if (path.startsWith('/')) {
            return vscode.Uri.file(path);
        }
        const folder = vscode.workspace.workspaceFolders?.[0];
        if (!folder) throw new Error('No workspace folder');
        return vscode.Uri.joinPath(folder.uri, path);
    }

    private readBody(req: http.IncomingMessage): Promise<string> {
        return new Promise((resolve, reject) => {
            let body = '';
            req.on('data', chunk => body += chunk);
            req.on('end', () => resolve(body));
            req.on('error', reject);
        });
    }

    stop(): void {
        this.server?.close();
        this.server = null;
    }
}
```

#### Phase 1.2: Python IDE Client (2-3 hours)

**File:** `ppxai/engine/ide_client.py`

```python
"""IDE Bridge client for communicating with VS Code extension."""

import httpx
from typing import Optional, Any
from dataclasses import dataclass

@dataclass
class IDEConnection:
    url: str
    capabilities: list[str]

class IDEClient:
    """Client for IDE bridge communication."""

    def __init__(self):
        self.connection: Optional[IDEConnection] = None
        self._client: Optional[httpx.AsyncClient] = None

    async def connect(self, url: str) -> bool:
        """Connect to IDE bridge server."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{url}/status", timeout=5.0)
                if response.status_code == 200:
                    data = response.json()
                    self.connection = IDEConnection(
                        url=url,
                        capabilities=data.get("capabilities", [])
                    )
                    self._client = httpx.AsyncClient(base_url=url)
                    return True
        except Exception as e:
            print(f"Failed to connect to IDE: {e}")
        return False

    async def disconnect(self):
        """Disconnect from IDE bridge."""
        if self._client:
            await self._client.aclose()
            self._client = None
        self.connection = None

    @property
    def is_connected(self) -> bool:
        return self.connection is not None

    async def execute_tool(self, tool: str, args: dict) -> dict:
        """Execute an IDE tool and return result."""
        if not self._client:
            raise RuntimeError("Not connected to IDE")

        import uuid
        request_id = str(uuid.uuid4())

        response = await self._client.post(
            "/ide/execute",
            json={"id": request_id, "tool": tool, "args": args},
            timeout=30.0
        )

        result = response.json()
        if not result.get("success"):
            raise RuntimeError(f"IDE tool error: {result.get('error')}")

        return result.get("result")

    # Convenience methods
    async def get_workspace_info(self) -> dict:
        return await self.execute_tool("ide.get_workspace_info", {})

    async def list_files(self, pattern: str = "**/*", exclude: str = "**/node_modules/**") -> list[str]:
        return await self.execute_tool("ide.list_files", {"pattern": pattern, "exclude": exclude})

    async def read_file(self, path: str) -> dict:
        return await self.execute_tool("ide.read_file", {"path": path})

    async def get_selection(self) -> Optional[dict]:
        return await self.execute_tool("ide.get_selection", {})

    async def get_active_file(self) -> Optional[dict]:
        return await self.execute_tool("ide.get_active_file", {})

    async def open_file(self, path: str, line: Optional[int] = None, column: Optional[int] = None) -> bool:
        return await self.execute_tool("ide.open_file", {"path": path, "line": line, "column": column})

    async def get_diagnostics(self, path: Optional[str] = None) -> list[dict]:
        return await self.execute_tool("ide.get_diagnostics", {"path": path})
```

#### Phase 1.3: IDE Tools for AI (2-3 hours)

**File:** `ppxai/engine/tools/builtin/ide.py`

```python
"""IDE integration tools for AI interaction with VS Code."""

from typing import Any, Optional
from ..base import BaseTool

class GetWorkspaceInfoTool(BaseTool):
    name = "ide.get_workspace_info"
    description = "Get information about the current VS Code workspace including name and folder paths"

    async def execute(self, **kwargs) -> dict:
        client = self.context.get("ide_client")
        if not client or not client.is_connected:
            return {"error": "Not connected to IDE. Use /ide connect first."}
        return await client.get_workspace_info()

class ListFilesTool(BaseTool):
    name = "ide.list_files"
    description = "List files in the workspace matching a glob pattern"
    parameters = {
        "pattern": {"type": "string", "description": "Glob pattern (e.g., '**/*.py')", "default": "**/*"},
        "exclude": {"type": "string", "description": "Exclusion pattern", "default": "**/node_modules/**"}
    }

    async def execute(self, pattern: str = "**/*", exclude: str = "**/node_modules/**", **kwargs) -> list[str]:
        client = self.context.get("ide_client")
        if not client or not client.is_connected:
            return {"error": "Not connected to IDE"}
        return await client.list_files(pattern, exclude)

class ReadFileTool(BaseTool):
    name = "ide.read_file"
    description = "Read the contents of a file in the workspace"
    parameters = {
        "path": {"type": "string", "description": "File path (relative to workspace root)"}
    }

    async def execute(self, path: str, **kwargs) -> dict:
        client = self.context.get("ide_client")
        if not client or not client.is_connected:
            return {"error": "Not connected to IDE"}
        return await client.read_file(path)

class GetSelectionTool(BaseTool):
    name = "ide.get_selection"
    description = "Get the currently selected/highlighted text in the active editor"

    async def execute(self, **kwargs) -> Optional[dict]:
        client = self.context.get("ide_client")
        if not client or not client.is_connected:
            return {"error": "Not connected to IDE"}
        return await client.get_selection()

class GetActiveFileTool(BaseTool):
    name = "ide.get_active_file"
    description = "Get the path and content of the currently active file in the editor"

    async def execute(self, **kwargs) -> Optional[dict]:
        client = self.context.get("ide_client")
        if not client or not client.is_connected:
            return {"error": "Not connected to IDE"}
        return await client.get_active_file()

class OpenFileTool(BaseTool):
    name = "ide.open_file"
    description = "Open a file in the IDE editor, optionally at a specific line"
    parameters = {
        "path": {"type": "string", "description": "File path to open"},
        "line": {"type": "integer", "description": "Line number to jump to (optional)"},
        "column": {"type": "integer", "description": "Column position (optional)"}
    }

    async def execute(self, path: str, line: Optional[int] = None, column: Optional[int] = None, **kwargs) -> bool:
        client = self.context.get("ide_client")
        if not client or not client.is_connected:
            return {"error": "Not connected to IDE"}
        return await client.open_file(path, line, column)

class GetDiagnosticsTool(BaseTool):
    name = "ide.get_diagnostics"
    description = "Get errors, warnings, and other diagnostics from the IDE"
    parameters = {
        "path": {"type": "string", "description": "File path (optional, all files if not specified)"}
    }

    async def execute(self, path: Optional[str] = None, **kwargs) -> list[dict]:
        client = self.context.get("ide_client")
        if not client or not client.is_connected:
            return {"error": "Not connected to IDE"}
        return await client.get_diagnostics(path)

# Tool registry
IDE_TOOLS = [
    GetWorkspaceInfoTool,
    ListFilesTool,
    ReadFileTool,
    GetSelectionTool,
    GetActiveFileTool,
    OpenFileTool,
    GetDiagnosticsTool,
]
```

#### Phase 1.4: CLI Commands (2 hours)

**Update:** `ppxai/commands.py`

```python
# Add /ide command handler

async def handle_ide_command(args: list[str], engine: EngineClient) -> str:
    """Handle /ide commands for IDE bridge connection."""
    if not args:
        return "Usage: /ide <connect|disconnect|status>\n  /ide connect <url> - Connect to VS Code bridge\n  /ide status - Show connection status"

    subcommand = args[0].lower()

    if subcommand == "connect":
        if len(args) < 2:
            return "Usage: /ide connect <url>\nExample: /ide connect http://localhost:54321"
        url = args[1]
        success = await engine.ide_client.connect(url)
        if success:
            info = await engine.ide_client.get_workspace_info()
            return f"Connected to IDE at {url}\nWorkspace: {info.get('name', 'Unknown')}"
        return f"Failed to connect to {url}"

    elif subcommand == "disconnect":
        await engine.ide_client.disconnect()
        return "Disconnected from IDE"

    elif subcommand == "status":
        if engine.ide_client.is_connected:
            info = await engine.ide_client.get_workspace_info()
            return f"Connected to: {engine.ide_client.connection.url}\nWorkspace: {info.get('name', 'Unknown')}\nFolders: {len(info.get('folders', []))}"
        return "Not connected to IDE. Use /ide connect <url>"

    return f"Unknown subcommand: {subcommand}"
```

#### Phase 1.5: Extension Integration (2 hours)

**Update:** `vscode-extension/src/extension.ts`

```typescript
import { BridgeServer } from './bridge';

let bridgeServer: BridgeServer | null = null;

export function activate(context: vscode.ExtensionContext) {
    // ... existing activation code ...

    // Start bridge server automatically
    bridgeServer = new BridgeServer(54321);
    bridgeServer.start().then(() => {
        console.log('IDE Bridge server started');
    }).catch(err => {
        console.error('Failed to start bridge server:', err);
    });

    // Register command to show bridge status
    context.subscriptions.push(
        vscode.commands.registerCommand('ppxai.showBridgeStatus', () => {
            if (bridgeServer) {
                vscode.window.showInformationMessage(
                    'ppxai IDE Bridge running on http://127.0.0.1:54321\n' +
                    'Connect from TUI with: /ide connect http://localhost:54321'
                );
            }
        })
    );
}

export function deactivate() {
    bridgeServer?.stop();
}
```

#### Phase 1.6: Testing & Documentation (2-3 hours)

- Test bridge server with curl/httpie
- Test from TUI with `/ide connect`
- Test all IDE tools from AI chat
- Update CLAUDE.md with IDE integration section
- Add troubleshooting guide

---

### v1.15.0: Code Actions (Phase 2)

**Goal**: Write capabilities - apply edits, run terminal, git operations

**Effort**: 16-20 hours

#### Phase 2.1: Code Edit Tools (4-5 hours)

Add to bridge server:
- `ide.apply_edit` - Apply text edits with WorkspaceEdit
- `ide.insert_text` - Insert at position
- `ide.replace_selection` - Replace selection
- `ide.show_diff` - Preview changes before applying

#### Phase 2.2: Terminal Tools (3-4 hours)

Add to bridge server:
- `ide.run_in_terminal` - Execute command
- `ide.create_terminal` - Create named terminal
- Terminal output capture (if possible)

#### Phase 2.3: Git Tools (4-5 hours)

Add to bridge server:
- `ide.git_status` - Get repository status
- `ide.git_diff` - Get file/repo diff
- `ide.git_stage` - Stage files
- `ide.git_commit` - Create commits

#### Phase 2.4: Undo/Rollback Support (2-3 hours)

- Track applied edits
- `/ide undo` command
- Edit history in session

#### Phase 2.5: Testing & Documentation (3-4 hours)

- Comprehensive testing of write operations
- Security review
- User documentation
- Demo videos/screenshots

---

## Security Considerations

### Local-Only Binding

Bridge server binds to `127.0.0.1` only - no remote access.

### Token Authentication (Optional)

```typescript
// Optional token for bridge requests
const BRIDGE_TOKEN = process.env.PPXAI_BRIDGE_TOKEN || crypto.randomUUID();

// Validate token in requests
if (req.headers['x-ppxai-token'] !== BRIDGE_TOKEN) {
    res.writeHead(401);
    res.end('Unauthorized');
    return;
}
```

### Confirmation for Destructive Operations

```typescript
// v1.15.0: Require confirmation for file writes
if (tool === 'ide.apply_edit' && !args.confirmed) {
    // Show diff preview and ask user
    const confirmed = await vscode.window.showWarningMessage(
        `Apply changes to ${args.files.length} file(s)?`,
        'Apply', 'Cancel'
    );
    if (confirmed !== 'Apply') {
        return { id, success: false, error: 'User cancelled' };
    }
}
```

---

## User Workflow Examples

### Example 1: Debug an Error (v1.14.0)

```
User: "I'm getting an error in my code, can you help?"

AI: Let me check the diagnostics in your workspace.
[Calls ide.get_diagnostics]

AI: I see an error in src/utils.py at line 42:
    "TypeError: unsupported operand type(s) for +: 'int' and 'str'"

Let me read that file to understand the context.
[Calls ide.read_file path="src/utils.py"]

AI: I see the issue. On line 42, you're concatenating an integer with a string.
Let me open that file for you.
[Calls ide.open_file path="src/utils.py" line=42]

The fix is to convert the integer to a string: str(count) + " items"
```

### Example 2: Apply a Fix (v1.15.0)

```
User: "Yes, please fix that for me"

AI: I'll apply the fix to line 42.
[Calls ide.apply_edit with replacement]

AI: Done! I've changed line 42 from:
    message = count + " items"
To:
    message = str(count) + " items"

The file has been saved. The error should be resolved.
```

### Example 3: TUI User with IDE Bridge

```
Terminal:
$ ppxai
> /ide connect http://localhost:54321
Connected to IDE at http://localhost:54321
Workspace: my-project

> What files are in this project?
[AI calls ide.list_files]

AI: Your project contains:
- src/main.py
- src/utils.py
- tests/test_main.py
- requirements.txt
- README.md

> Open the main.py file
[AI calls ide.open_file]

AI: I've opened src/main.py in VS Code.
```

---

## Migration Path

### From gemini-ide-analysis.md

The earlier `docs/gemini-ide-analysis.md` proposal is superseded by this plan. Key differences:

| Aspect | Original Proposal | This Plan |
|--------|------------------|-----------|
| Direction | VS Code as server only | Hybrid (native + bridge) |
| HTTP library | `requests` | `httpx` (async) |
| Tool categories | 2 tools | 15+ tools across categories |
| Integration | TUI only | TUI + Extension native |
| Phasing | Single release | Two phases (v1.14, v1.15) |

---

## References

- [VS Code Extension API](https://code.visualstudio.com/api)
- [VS Code Workspace API](https://code.visualstudio.com/api/references/vscode-api#workspace)
- [VS Code Language Features](https://code.visualstudio.com/api/language-extensions/programmatic-language-features)
- [ppxai SSE Migration Plan](sse-migration-plan.md)
- [ppxai Architecture Document](architecture-refactoring.md)
