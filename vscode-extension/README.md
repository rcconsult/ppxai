# ppxai VS Code Extension

Multi-provider AI chat interface for VS Code, powered by ppxai.

## Features

- **Chat Panel**: Interactive AI chat in the sidebar with markdown rendering
- **Message Timestamps**: Each message shows time and date (HH:MM:SS Mon DD)
- **Time Dividers**: Visual separators between conversations (after 5min gap or date change)
- **@file References**: Type `@filename` to include file content in your messages
- **Autocomplete**:
  - `/` commands with descriptions
  - `@` file references with fuzzy search
- **Tools Toggle**: Click the tools badge to enable/disable AI tools (persists across restarts)
- **Code Commands**: Right-click context menu for code operations
  - Explain Selection
  - Generate Tests
  - Generate Documentation
- **Slash Commands**: `/help`, `/show`, `/tools`, `/model`, `/provider`, `/generate`, etc.
- **Multi-Provider Support**: Perplexity, OpenAI, Gemini, OpenRouter, local models
- **Session Management**: Save and load conversation sessions
- **Streaming Responses**: Real-time SSE streaming with timing info

## Requirements

- Python 3.10+
- ppxai Python package with server dependencies
- API key for at least one provider (Perplexity, OpenAI, Gemini, etc.)

## Installation

### 1. Install ppxai with server support

```bash
pip install ppxai[server]
# Or with uv
uv pip install ppxai[server]
```

### 2. Configure API keys

Create a `.env` file in your project directory (or home directory `~/.ppxai/.env`):

```bash
# At least one API key is required
PERPLEXITY_API_KEY=pplx-xxxxxxxxxxxx
# Or
GEMINI_API_KEY=xxxxxxxxxxxx
# Or
OPENAI_API_KEY=sk-xxxxxxxxxxxx
```

The server loads `.env` from the current working directory when started.

### 3. Install the VSCode extension

Download the `.vsix` file from [GitHub Releases](https://github.com/rcconsult/ppxai/releases) and install:

```bash
code --install-extension ppxai-1.10.2.vsix
```

Or install via VSCode: Extensions → `...` menu → "Install from VSIX..."

### 4. Start ppxai-server

**Important:** Start the server from a directory containing your `.env` file:

```bash
cd /path/to/your/project  # Contains .env
ppxai-server
# Or with uv
uv run ppxai-server
```

The server runs on `http://127.0.0.1:54320` by default. Keep it running while using the extension.

### 5. Open the chat panel

In VSCode: Click the ppxai icon in the Activity Bar (sidebar), or run command `ppxai: Open Chat`.

## Troubleshooting

**"Could not connect to server"**
- Ensure ppxai-server is running: `ppxai-server`
- Check the server URL in settings matches (default: `http://127.0.0.1:54320`)

**"No API key configured"**
- Create `.env` file with your API key in the directory where you run ppxai-server
- Restart ppxai-server after adding keys

**Extension not showing**
- Reload VSCode window: Cmd/Ctrl+Shift+P → "Developer: Reload Window"

## Configuration

Configure the extension in VS Code settings:

| Setting | Description | Default |
|---------|-------------|---------|
| `ppxai.serverUrl` | URL of ppxai-server | `http://127.0.0.1:54320` |
| `ppxai.defaultProvider` | Default AI provider | `perplexity` |
| `ppxai.defaultModel` | Default model (empty for provider default) | `""` |
| `ppxai.enableTools` | Enable AI tools (file ops, shell, web) | `false` |

## Chat Slash Commands

Type these directly in the chat input:

### Coding Tasks
| Command | Description |
|---------|-------------|
| `/generate <desc>` | Generate code from description |
| `/explain <code>` | Explain code or concept |
| `/test <code or @file>` | Generate tests for code |
| `/docs <code or @file>` | Generate documentation |
| `/debug <error>` | Debug an error message |
| `/implement <desc>` | Implement from description |

### Session & Config
| Command | Description |
|---------|-------------|
| `/help` | Show all available commands |
| `/status` | Show current provider/model |
| `/provider [id]` | Switch or list providers |
| `/model [id]` | Switch or list models |
| `/tools [enable\|disable]` | Manage AI tools |
| `/show <file>` | Display file contents |
| `/save` / `/load` | Save/load sessions |
| `/clear` | Clear conversation |

## VSCode Commands (Cmd+Shift+P)

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
