# IDE Bridge Implementation Analysis

This document outlines the architectural changes and implementation steps required to support the `/ide enable/connect` command, specifically targeting VS Code integration. This feature allows the standalone `ppxai` CLI to control the IDE (e.g., opening files, reading selections) via a bidirectional bridge.

## Architecture: The "IDE Bridge"

Since the standalone Python CLI and VS Code run as separate processes, they require a communication channel. The proposed solution is a lightweight **HTTP Bridge**.

### Data Flow

1.  **VS Code Extension** acts as the **Server**, listening for commands.
2.  **Python Engine** acts as the **Client**, sending requests via built-in tools.
3.  **User** facilitates the handshake via the `/ide connect` command.

## Implementation Plan

### 1. VS Code Extension (The Server)

The extension needs to run a local HTTP server to expose VS Code APIs to the external process.

**New File:** `vscode-extension/src/bridge.ts`

This file implements the server logic:
*   **Server**: Uses Node.js `http` module.
*   **Port**: Configurable, defaulting to something like `54321`.
*   **Security**: Should use a simple token or at least local-only binding.
*   **Endpoints**:
    *   `POST /open`: Accepts `{ path, line }`. Uses `vscode.window.showTextDocument`.
    *   `GET /selection`: Returns `vscode.window.activeTextEditor.selection`.
    *   `GET /status`: Health check.

**Modifications:** `vscode-extension/src/extension.ts`
*   Initialize `BridgeServer` on activation.
*   Register command `ppxai.enableBridge` to start the server and display the connection URL (e.g., `http://localhost:54321`) to the user.
*   Update `package.json` to include configuration for `bridgePort`.

### 2. Python Engine (The Client)

The Python side needs a client to communicate with the bridge and new tools to wrap these capabilities for the LLM.

**New File:** `ppxai/engine/ide_bridge.py`
*   **Class `IDEClient`**:
    *   Manages connection state (Connected/Disconnected).
    *   Methods: `connect(url)`, `open_file(path, line)`, `get_selection()`.
    *   Uses `requests` to call the VS Code endpoints.

**New File:** `ppxai/engine/tools/builtin/ide.py`
*   **Tool**: `open_in_ide`
    *   **Description**: "Opens a specific file and line number in the user's IDE."
    *   **Handler**: Delegates to `IDEClient.open_file`.
*   **Tool**: `get_active_code`
    *   **Description**: "Gets the code currently highlighted in the user's IDE."
    *   **Handler**: Delegates to `IDEClient.get_selection`.

**Update:** `ppxai/engine/tools/builtin/__init__.py`
*   Register the new `ide_control` tools.

**Update:** `ppxai/engine/client.py`
*   Integrate `IDEClient` into the main `EngineClient`.

### 3. CLI Command (The Handshake)

A new slash command is needed to establish the connection.

**Update:** `ppxai/commands.py`

*   **Command**: `/ide connect <url>`
    *   **Action**:
        1.  Pings `<url>/status` to verify the bridge is running.
        2.  Configures `IDEClient` with the URL.
        3.  Enables the `ide_control` tools in `ToolManager`.
    *   **Output**: Success message or error details.
*   **Command**: `/ide status`
    *   **Action**: Checks and reports connection health.

## User Workflow Example

1.  **User (in VS Code)**: Runs command `PPXAI: Enable Bridge`.
2.  **VS Code**: Starts server and notifies: `Bridge running on http://localhost:54321`.
3.  **User (in Terminal)**: Runs `/ide connect http://localhost:54321`.
4.  **PPXAI**: Verifies connection: `Connected to IDE at http://localhost:54321`.
5.  **User**: "Check the error on line 50 of ppxai.py".
6.  **AI**: Calls tool `open_in_ide(file="ppxai.py", line=50)`.
7.  **VS Code**: Automatically opens `ppxai.py` and scrolls to line 50.

## Summary of Changes

| Component | File | Change |
| :--- | :--- | :--- |
| **VS Code** | `package.json` | Add `bridgePort` config. |
| **VS Code** | `src/bridge.ts` | **NEW**: HTTP server to accept "open/read" commands. |
| **VS Code** | `src/extension.ts` | Integrate bridge startup/shutdown. |
| **Python** | `ppxai/engine/ide_bridge.py` | **NEW**: HTTP client logic. |
| **Python** | `ppxai/engine/tools/builtin/ide.py` | **NEW**: Define tools for the LLM. |
| **Python** | `ppxai/commands.py` | Add `/ide` command handler. |
| **Python** | `ppxai/engine/client.py` | Integrate `IDEClient` into engine. |
