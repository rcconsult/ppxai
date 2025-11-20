# ppxai - Perplexity AI Text UI

A terminal-based interface for interacting with Perplexity AI models.

## Features

### Core Features
- 🤖 Interactive chat with Perplexity AI models
- 🔄 Model selection (Sonar, Sonar Pro, Sonar Reasoning, and more)
- ⚡ Streaming responses for real-time interaction
- 🎨 Rich terminal UI with markdown rendering (headings, lists, tables, code blocks)
- 🔗 Clickable source citations in terminal
- 📝 Command history support
- 📦 Standalone executables available (no Python required!)

### Session Management
- 💾 Auto-save sessions every 10 messages
- 📂 Load and continue previous conversations
- 📤 Export conversations to markdown files
- 🗂️ Session browser with metadata

### Usage Tracking
- 📊 Real-time token usage monitoring
- 💰 Cost estimation based on model pricing
- 📈 Global usage statistics and history
- 📅 Daily usage tracking by model

### Code Generation Tools
- 🔨 `/generate` - Generate code from natural language descriptions
- 🧪 `/test` - Generate comprehensive unit tests for code files
- 📚 `/docs` - Generate documentation for existing code
- 🏗️ `/implement` - Implement features from detailed specifications
- 📋 `/spec` - Access specification templates and guidelines

See [SPECIFICATIONS.md](SPECIFICATIONS.md) for detailed guides on writing effective specifications for code generation.

## Quick Start

### Option 1: Download Standalone Executable (Recommended for Users)

**No Python installation required!**

1. Download the appropriate executable for your platform from [Releases](../../releases)
2. Create a `.env` file with your API key:
   ```
   PERPLEXITY_API_KEY=your_api_key_here
   ```
3. Run the executable:
   - **macOS/Linux:** `./ppxai`
   - **Windows:** `ppxai.exe`

### Option 2: Run from Source (For Developers)

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd ppxai
```

2. Create and activate a virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate  # On macOS/Linux
# On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up your API key:
```bash
cp .env.example .env
```

Edit `.env` and add your Perplexity API key:
```
PERPLEXITY_API_KEY=your_api_key_here
```

## Usage

Run the application:
```bash
python ppxai.py
```

Or make it executable:
```bash
chmod +x ppxai.py
./ppxai.py
```

### Available Commands

While in the chat interface:

#### General Commands
- Type your question or prompt to chat with the AI
- `/help` - Show help message with all commands
- `/model` - Change the current model
- `/clear` - Clear conversation history
- `/quit` or `/exit` - Exit the application (auto-saves session)

#### Session Management
- `/save [filename]` - Export conversation to markdown file
- `/sessions` - List all saved sessions
- `/load <session>` - Load and continue a previous session
- `/usage` - Show token usage and cost statistics

#### Code Generation Tools
- `/generate <description>` - Generate code from natural language
  - Example: `/generate a function to validate email addresses in Python`
- `/test <file>` - Generate unit tests for a code file
  - Example: `/test ./src/utils.py`
- `/docs <file>` - Generate documentation for a code file
  - Example: `/docs ./src/api.py`
- `/implement <specification>` - Implement a feature from detailed spec
  - Example: `/implement a REST API endpoint for user authentication`
- `/spec [type]` - Show specification guidelines and templates
  - Types: `api`, `cli`, `lib`, `algo`, `ui`
  - See [SPECIFICATIONS.md](SPECIFICATIONS.md) for details

### Available Models

1. **Sonar** - Lightweight search model with real-time grounding
2. **Sonar Pro** - Advanced search model for complex queries
3. **Sonar Reasoning** - Fast reasoning model for problem-solving with search
4. **Sonar Reasoning Pro** - Precision reasoning with Chain of Thought capabilities
5. **Sonar Deep Research** - Exhaustive research with comprehensive reports

## Use Cases

ppxai is particularly useful for:

- **Research & Learning**: Leverage Perplexity's real-time search for up-to-date information
- **Code Development**: Generate code, tests, and documentation with specialized prompts
- **Debugging**: Get help analyzing errors and finding solutions
- **Architecture Planning**: Use specification templates to design features before coding
- **Code Review**: Generate documentation and tests for existing code
- **Quick Prototypes**: Rapidly generate boilerplate code and implementations

## Data Storage

ppxai stores data locally in `~/.ppxai/`:

- `~/.ppxai/sessions/` - Saved conversation sessions (JSON)
- `~/.ppxai/exports/` - Exported markdown files
- `~/.ppxai/usage.json` - Token usage and cost tracking

All data stays on your machine. No data is sent anywhere except to Perplexity's API during chat.

## API Key

You need a Perplexity API key to use this application. Get one at [Perplexity AI](https://www.perplexity.ai/).

## Building Executables

Want to build your own standalone executable? See [BUILD.md](BUILD.md) for detailed instructions on building for:
- Windows 11
- macOS (Intel & Apple Silicon)
- Linux

**Quick build:**
```bash
# macOS/Linux
./build.sh

# Windows
build.bat
```

## Requirements

- **For standalone executable:** None! Just download and run.
- **For running from source:** Python 3.8+ (see `requirements.txt` for package dependencies)

## Terminal Compatibility

Clickable links work best in modern terminals:
- **macOS:** Terminal.app, iTerm2 (Cmd+Click)
- **Windows:** Windows Terminal (Ctrl+Click)
- **Linux:** GNOME Terminal, Konsole, etc. (Ctrl+Click)

## License

MIT
