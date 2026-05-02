# ppxai VS Code Extension

Multi-provider AI chat interface for VS Code, powered by ppxai.

## Features

- **Chat Panel**: Interactive AI chat in the sidebar with markdown rendering
- **Message Timestamps**: Each message shows time and date (HH:MM:SS Mon DD)
- **Time Dividers**: Visual separators between conversations (after 5min gap or date change)
- **@file References**: Type `@filename` to include file content, `@clipboard` for clipboard text, `@url` for web content
- **Autocomplete** (unified with all ppxai clients via `POST /complete`):
  - `/` commands + aliases + `/quit`/`/exit` (dynamic, from server's `CommandFactory`)
  - `/tools`, `/usage`, `/checkpoint`, `/status`, `/theme` subcommands + second-level args (`/usage show <mode>`, `/theme emoji on/off`, `/checkpoint backend <backend>`, `/tools help <tool>`)
  - Dynamic `/model <name>` for the active provider, `/provider <name>` for configured providers
  - Path arguments for `/attach`, `/cd`, `/ls`, `/show`, `/tree`, `/preview` with alias resolution
  - `@file` fuzzy search + `@git`, `@tree`, `@clipboard`, `@url` context providers in one dropdown
- **Tools Toggle**: Click the tools badge to enable/disable AI tools (persists across restarts)
- **Code Commands**: Right-click context menu for code operations
  - Explain Selection
  - Generate Tests
  - Generate Documentation
- **Live HTML Preview** (v1.15.4): `/preview` opens HTML files in a WebviewPanel with live reload via `FileSystemWatcher`
- **Slash Commands**: `/help`, `/show`, `/tools`, `/model`, `/provider`, `/generate`, `/preview`, etc.
- **Multi-Provider Support**: Perplexity, OpenAI, Gemini, OpenRouter, local models
- **Session Management**: Save and load conversation sessions
- **Streaming Responses**: Real-time SSE streaming with timing info
- **Syntax Highlighting**: PowerShell, Dockerfile, DOS, AppleScript support (v1.15.4)

## Requirements

- API key for at least one provider (Perplexity, OpenAI, Gemini, etc.)
- **Option A:** Pre-built binaries (no Python needed)
- **Option B:** Python 3.10+ with ppxai package

## Installation

### Option A: Pre-built Binaries (Recommended)

**No Python installation required!**

#### 1. Download binaries from [GitHub Releases](https://github.com/rcconsult/ppxai/releases)

Download for your platform:
- **macOS (Apple Silicon):** `ppxai-server-macos-arm64` + `ppxai-1.18.3.vsix`
- **macOS (Intel):** `ppxai-server-macos-intel` + `ppxai-1.18.3.vsix`
- **Linux:** `ppxai-server-linux-amd64` + `ppxai-1.18.3.vsix`
- **Windows:** `ppxai-server-windows.exe` + `ppxai-1.18.3.vsix`

#### 2. Configure API keys

Create a `.env` file in your project directory (or `~/.ppxai/.env`):

```bash
# At least one API key is required
PERPLEXITY_API_KEY=pplx-xxxxxxxxxxxx
# Or
GEMINI_API_KEY=xxxxxxxxxxxx
# Or
OPENAI_API_KEY=sk-xxxxxxxxxxxx
```

#### 3. Install the VSCode extension

```bash
code --install-extension ppxai-1.18.3.vsix
```

Or in VSCode: Extensions → `...` menu → "Install from VSIX..."

#### 4. Start ppxai-server

**Option A: Auto-Start (v1.13.3+)**

The extension can auto-start `ppxai-server` when you open the chat panel. Just configure the binary path in VS Code settings or place it in a standard location:
- `~/.local/bin/ppxai-server` (Linux/macOS)
- `~/.ppxai/bin/ppxai-server.exe` (Windows)
- `/Applications/ppxai.app/Contents/MacOS/ppxai-server` (macOS app bundle)

**Option B: Manual Start**

```bash
# macOS/Linux - make executable first
chmod +x ppxai-server-macos-arm64
./ppxai-server-macos-arm64

# Windows
ppxai-server-windows.exe
```

**Important:** Start the server from a directory containing your `.env` file, or place `.env` in `~/.ppxai/`.

The server runs on `http://127.0.0.1:54320` by default. Keep it running while using the extension.

#### 5. Open the chat panel

In VSCode: Click the ppxai icon in the Activity Bar (sidebar), or run command `ppxai: Open Chat`.

---

### Option B: Install from PyPI (Python required)

#### 1. Install ppxai with server support

```bash
pip install ppxai[server]
# Or with uv
uv pip install ppxai[server]
```

#### 2. Configure API keys

Create a `.env` file in your project directory (or `~/.ppxai/.env`):

```bash
# At least one API key is required
PERPLEXITY_API_KEY=pplx-xxxxxxxxxxxx
# Or
GEMINI_API_KEY=xxxxxxxxxxxx
# Or
OPENAI_API_KEY=sk-xxxxxxxxxxxx
```

#### 3. Install the VSCode extension

Download the `.vsix` file from [GitHub Releases](https://github.com/rcconsult/ppxai/releases) and install:

```bash
code --install-extension ppxai-1.18.3.vsix
```

Or in VSCode: Extensions → `...` menu → "Install from VSIX..."

#### 4. Start ppxai-server

```bash
cd /path/to/your/project  # Contains .env
ppxai-server
# Or with uv
uv run ppxai-server
```

The server runs on `http://127.0.0.1:54320` by default. Keep it running while using the extension.

#### 5. Open the chat panel

In VSCode: Click the ppxai icon in the Activity Bar (sidebar), or run command `ppxai: Open Chat`.

## File Upload & Multimodal (v1.17.4)

Attach images, PDFs, Excel, PowerPoint, Word, CSV, and code files to your conversations using the paperclip button, drag-drop, or the `/attach` command.

**No extra setup needed for:** images, text/code files, Word (.docx), CSV

**Optional dependencies for advanced file tools:**

| File Type | Python Package | System Package | Install |
|-----------|---------------|----------------|---------|
| PDF text extraction | `pypdf` | — | `pip install 'ppxai[data]'` |
| PDF page images | `pdf2image` | `poppler-utils` | see below |
| Excel (.xlsx) | `openpyxl` | — | `pip install 'ppxai[data]'` |
| PowerPoint (.pptx) | `python-pptx` | — | `pip install 'ppxai[data]'` |
| PPTX slide rendering | — | `libreoffice` | see below |

**Install all Python extras at once:**
```bash
pip install 'ppxai[data]'
# Or with uv
uv pip install 'ppxai[data]'
```

**System dependencies (only needed for PDF page images and PPTX slide rendering):**
```bash
# macOS
brew install poppler libreoffice

# Debian/Ubuntu
apt install poppler-utils libreoffice-nogui

# Windows — poppler: download from https://github.com/oschwartz10612/poppler-windows
# Windows — LibreOffice: download from https://www.libreoffice.org/download
```

Pre-built server binaries include all Python `[data]` dependencies. System packages (poppler, LibreOffice) must be installed separately if you need PDF rasterization or PPTX slide rendering.

## Voice Input (optional)

ppxai doesn't ship with speech-to-text, but the chat input accepts dictation from any system transcription tool. [**Handy**](https://github.com/cjpais/Handy) (MIT, offline, Whisper/Parakeet) pairs well:

1. Install Handy from https://github.com/cjpais/Handy/releases and grant microphone + accessibility permissions.
2. Configure a global hotkey (default: push-to-talk).
3. Click into the ppxai chat input, hold your hotkey, speak. Handy types the transcript into the focused field.
4. Press **Ctrl+Enter** (or **Ctrl+J**) to send.

This is a zero-integration workflow — ppxai and Handy don't talk to each other; Handy just types into whatever window has focus. Works reliably in the VSCode webview. For the Rich/Textual TUIs, synthetic keystroke injection into terminal apps is less reliable; use the VSCode extension or desktop web app for voice input today.

Other transcription tools (macOS Dictation, Windows Voice Access, wispr-flow, etc.) work the same way — if they can type into any text field, they can type into ppxai.

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
| `/preview <file>` | Live-reloading HTML preview (v1.15.4) |

### Session & Config
| Command | Description |
|---------|-------------|
| `/help` | Show all available commands |
| `/status` | Show current provider/model |
| `/context` | Show context window usage and injected files |
| `/context show` | Display bootstrap hierarchy with scope labels |
| `/context clear` | Remove all injected context |
| `/edit <file[:line]>` | Open file in VSCode editor (v1.14.1+) |
| `/provider [id]` | Switch or list providers |
| `/model [id]` | Switch or list models |
| `/tools [enable\|disable]` | Manage AI tools |
| `/show <file>` | Display file contents |
| `/save` | Save session to JSON |
| `/export [filename]` | Export last answer to markdown |
| `/load` | Load saved session |
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
│   ├── chatPanel.ts       # Webview chat UI (orchestrator)
│   ├── previewPanel.ts    # Live HTML preview panel (v1.15.4)
│   ├── sessionsProvider.ts # Sessions tree view
│   └── handlers/          # Extracted handlers (v1.14.0+)
│       ├── eventBus.ts    # Type-safe pub/sub communication
│       ├── stream.ts      # Stream event processing
│       ├── consent.ts     # Consent dialog handlers
│       ├── agentStateMachine.ts # Agent loop state machine
│       ├── commands.ts    # Slash command handlers
│       └── types.ts       # HandlerContext interface
├── media/webview/         # External CSS/JS for webview
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
