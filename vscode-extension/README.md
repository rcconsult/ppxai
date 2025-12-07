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
- **Multi-Provider Support**: Perplexity, OpenAI, OpenRouter, local models
- **Session Management**: Save and load conversation sessions
- **Streaming Responses**: Real-time streaming output with timing info

## Requirements

- Python 3.8+
- ppxai Python package (parent directory)
- API key for your chosen provider

## Installation

### Development Setup

1. Install dependencies:
   ```bash
   cd vscode-extension
   npm install
   ```

2. Compile TypeScript:
   ```bash
   npm run compile
   ```

3. Press F5 in VS Code to launch Extension Development Host

### Production Build

```bash
npm run vscode:prepublish
npx vsce package
```

## Configuration

Configure the extension in VS Code settings:

| Setting | Description | Default |
|---------|-------------|---------|
| `ppxai.pythonPath` | Path to Python interpreter | `python3` |
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
│   ├── extension.ts      # Extension entry point
│   ├── backend.ts        # Python process manager
│   ├── chatPanel.ts      # Webview chat UI
│   └── sessionsProvider.ts # Sessions tree view
├── webview/              # (future) Separate webview assets
└── resources/
    └── icon.svg          # Activity bar icon
```

The extension spawns a Python subprocess (`ppxai.server`) and communicates via JSON-RPC over stdio.

## Development

### Watch Mode

```bash
npm run watch
```

### Debugging

1. Open the extension folder in VS Code
2. Press F5 to launch Extension Development Host
3. Use Debug Console for extension logs
4. Check Output > ppxai for backend logs
