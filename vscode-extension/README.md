# ppxai VS Code Extension

Multi-provider AI chat interface for VS Code, powered by ppxai.

## Features

- **Chat Panel**: Interactive AI chat in the sidebar with markdown rendering
- **@file References**: Type `@filename` to include file content in your messages
- **Autocomplete**:
  - `/` commands with descriptions
  - `@` file references with fuzzy search
- **Tools Toggle**: Click the tools badge to enable/disable AI tools
- **Code Commands**: Right-click context menu for code operations
  - Explain Selection
  - Generate Tests
  - Generate Documentation
- **Slash Commands**: `/help`, `/show`, `/tools`, `/model`, `/provider`, etc.
- **Multi-Provider Support**: Perplexity, OpenAI, Gemini, OpenRouter, local models
- **Session Management**: Save and load conversation sessions
- **Streaming Responses**: Real-time SSE streaming with timing info

## Requirements

- Python 3.10+
- ppxai Python package with server dependencies

## Installation

### 1. Install ppxai with server support

```bash
pip install ppxai[server]
# Or with uv
uv pip install ppxai[server]
```

### 2. Install the VSCode extension

Download the `.vsix` file from [GitHub Releases](https://github.com/rcconsult/ppxai/releases) and install:

```bash
code --install-extension ppxai-1.10.0.vsix
```

### 3. Start ppxai-server

Before using the extension, start the HTTP server:

```bash
ppxai-server
# Or with uv
uv run ppxai-server
```

The server runs on `http://127.0.0.1:54320` by default.

### 4. Configure API keys

Create a `.env` file with your API keys:

```bash
PERPLEXITY_API_KEY=your-key-here
# Or
GEMINI_API_KEY=your-key-here
```

## Configuration

Configure the extension in VS Code settings:

| Setting | Description | Default |
|---------|-------------|---------|
| `ppxai.serverUrl` | URL of ppxai-server | `http://127.0.0.1:54320` |
| `ppxai.defaultProvider` | Default AI provider | `perplexity` |
| `ppxai.defaultModel` | Default model (empty for provider default) | `""` |
| `ppxai.enableTools` | Enable AI tools (file ops, shell, web) | `false` |

## Commands

| Command | Description |
|---------|-------------|
| `ppxai: Open Chat` | Open the chat panel |
| `ppxai: Explain Selection` | Explain selected code |
| `ppxai: Generate Tests` | Generate unit tests |
| `ppxai: Generate Documentation` | Generate documentation |
| `ppxai: Debug Error` | Analyze an error message |
| `ppxai: Implement from Description` | Generate code from description |
| `ppxai: Switch Provider` | Change AI provider |
| `ppxai: Switch Model` | Change model |

## Architecture

```
vscode-extension/
├── src/
│   ├── extension.ts       # Extension entry point
│   ├── httpClient.ts      # HTTP + SSE client for ppxai-server
│   ├── chatPanel.ts       # Webview chat UI
│   └── sessionsProvider.ts # Sessions tree view
├── webview/               # (future) Separate webview assets
└── resources/
    └── icon.svg           # Activity bar icon
```

The extension communicates with `ppxai-server` via HTTP REST + SSE for streaming responses.

## Development

### Building from source

```bash
cd vscode-extension
npm install
npm run compile
npx vsce package --allow-missing-repository
```

### Watch Mode

```bash
npm run watch
```

### Debugging

1. Open the extension folder in VS Code
2. Press F5 to launch Extension Development Host
3. Use Debug Console for extension logs
4. Check Output > ppxai HTTP for client logs
