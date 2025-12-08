# Project Overview

The `ppxai` project is a comprehensive AI coding assistant and chat interface. It has evolved from a simple CLI into a robust platform supporting multiple AI providers (Perplexity, OpenAI, OpenRouter, Local Models), a structured Python package, and a full-featured VS Code extension. It focuses on developer workflows with specialized tools for code generation, debugging, testing, and documentation.

## Main Technologies

*   **Python:** Core application logic (v3.8+).
*   **TypeScript:** VS Code extension development.
*   **Rich:** Advanced terminal UI with markdown, panels, and tables.
*   **Prompt Toolkit:** Interactive CLI input handling.
*   **JSON-RPC:** Communication protocol between the VS Code extension and the Python backend.
*   **MCP (Model Context Protocol):** Support for external tool servers.
*   **PyInstaller:** For building standalone executables.

## Key Features

### Core CLI & Chat
*   **Multi-Provider:** Switch between Perplexity (Sonar), OpenAI (GPT-4), Claude, Gemini, and local models.
*   **Streaming:** Real-time response streaming with markdown rendering.
*   **Session Management:** Auto-save, load, and export conversations.
*   **Usage Tracking:** Token usage and cost monitoring per model.

### Developer Tools
*   **`/generate`**: Create code from natural language descriptions.
*   **`/test`**: Generate unit tests for specific files.
*   **`/docs`**: Generate documentation for code.
*   **`/debug`**: Analyze errors and provide fixes.
*   **`/explain`**: detailed code logic explanations.
*   **`/convert`**: Translate code between languages.
*   **`/tools`**: Enable/disable AI tools (File Search, Read, Shell, Calculator).

### VS Code Extension
*   **Chat Panel:** Integrated sidebar chat.
*   **Context:** `@file` referencing to pull code into context.
*   **Code Actions:** Context menu items for Explain, Test, and Document.
*   **Autocomplete:** Slash commands and file path completion.

## Project Structure

```
ppxai/
├── ppxai.py                              # Entry point wrapper
├── ppxai/                                # Main package
│   ├── main.py                           # CLI application entry
│   ├── client.py                         # AI client wrapper
│   ├── config.py                         # Hybrid configuration (Env + JSON)
│   ├── server.py                         # JSON-RPC server for VS Code
│   └── engine/                           # Core logic
│       ├── providers/                    # Provider implementations (Perplexity, OpenAI, etc.)
│       └── tools/                        # Tool system (Built-in & MCP)
├── vscode-extension/                     # VS Code Extension source
│   ├── src/                              # TypeScript source
│   └── package.json                      # Extension manifest
├── docs/                                 # Comprehensive documentation
└── tests/                                # Extensive test suite
```

## Configuration

*   **Secrets:** `.env` file for API keys (`PERPLEXITY_API_KEY`, `OPENAI_API_KEY`, etc.). **Never commit.**
*   **Settings:** `ppxai-config.json` for provider definitions, model lists, and non-secret settings. **Can commit.**
*   **User Data:** Stored in `~/.ppxai/` (sessions, logs, user config).

## Build & Release

*   **Version:** ~v1.8.0
*   **Executables:** `build.sh` (macOS/Linux) and `build.bat` (Windows) create standalone binaries using PyInstaller.
*   **VS Code:** `npm run compile` and `vsce package` for the extension.

## Development Status

*   **Tool Integration:** Complete. Supports built-in tools (Shell, Filesystem) and MCP servers.
*   **Shell Tool:** Implemented with safety checks (blocks interactive commands like `vim`).
*   **Testing:** Comprehensive test suite in `tests/`.
*   **Documentation:** Up-to-date guides in `docs/` for providers, tools, and contributing.