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

### Code Generation & Analysis Tools
- 🔨 `/generate` - Generate code from natural language descriptions
- 🧪 `/test` - Generate comprehensive unit tests for code files
- 📚 `/docs` - Generate documentation for existing code
- 🏗️ `/implement` - Implement features from detailed specifications
- 🐛 `/debug` - Analyze errors, exceptions, and bugs with solutions
- 📖 `/explain` - Explain code logic and design decisions step-by-step
- 🔄 `/convert` - Convert code between programming languages
- 📋 `/spec` - Access specification templates and guidelines
- 🎯 `/autoroute` - Smart model routing for coding tasks (auto-enabled)

See [SPECIFICATIONS.md](SPECIFICATIONS.md) for detailed guides on writing effective specifications for code generation.

### AI Tools (Experimental) 🆕
- 🛠️ `/tools enable` - Enable AI tools (file search, calculator, code analyzer, etc.)
- 📋 `/tools list` - Show available tools
- ✅ `/tools status` - Check tools status
- ❌ `/tools disable` - Disable tools

**Built-in Tools:**
- `search_files` - Find files by pattern
- `read_file` - Read file contents
- `list_directory` - List directory contents
- `calculator` - Evaluate mathematical expressions

**Extensible System:**
- Add custom Python tools in minutes
- Optional MCP (Model Context Protocol) server support
- See [docs/TOOL_CREATION_GUIDE.md](docs/TOOL_CREATION_GUIDE.md) for details

**Learn More:** [Tool Documentation](docs/README.md)

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

#### Code Generation & Analysis Tools
- `/generate <description>` - Generate code from natural language
  - Example: `/generate a function to validate email addresses in Python`
- `/test <file>` - Generate unit tests for a code file
  - Example: `/test ./src/utils.py`
- `/docs <file>` - Generate documentation for a code file
  - Example: `/docs ./src/api.py`
- `/implement <specification>` - Implement a feature from detailed spec
  - Example: `/implement a REST API endpoint for user authentication`
- `/debug <error>` - Analyze and fix errors with explanations
  - Example: `/debug TypeError: 'NoneType' object is not subscriptable at line 42`
- `/explain <file>` - Explain code logic and design decisions
  - Example: `/explain ./src/algorithm.py`
- `/convert <from> <to> <file>` - Convert code between languages
  - Example: `/convert python javascript ./utils.py`
  - Example: `/convert go rust 'func hello() { fmt.Println("Hi") }'`
- `/spec [type]` - Show specification guidelines and templates
  - Types: `api`, `cli`, `lib`, `algo`, `ui`
  - See [SPECIFICATIONS.md](SPECIFICATIONS.md) for details
- `/autoroute [on|off]` - Toggle smart model routing for coding tasks
  - Auto-routes coding commands to Sonar Pro for best results
  - Enabled by default, can be disabled for manual control

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
- **Debugging**: Get help analyzing errors and finding solutions with root cause analysis
- **Code Understanding**: Explain complex codebases and design decisions
- **Architecture Planning**: Use specification templates to design features before coding
- **Code Review**: Generate documentation and tests for existing code
- **Language Migration**: Convert code between programming languages with idiomatic patterns
- **Quick Prototypes**: Rapidly generate boilerplate code and implementations

## Example Outputs

### `/explain` - Code Explanation

When you run `/explain ./ppxai.py`, you get comprehensive analysis like:

> **High-Level Structure & Purpose**
>
> This code implements a comprehensive command-line interface (CLI) application for interacting with Perplexity AI models, providing tools for conversational AI, code generation, documentation, debugging, and session management—all from the terminal.
>
> **Key Design Patterns:**
> - Separation of concerns (UI, business logic, API communication)
> - Dependency injection for extensibility
> - Defensive programming with comprehensive error handling
> - Modern CLI design with rich terminal UI
>
> **Core Components:**
> 1. **Session Management** - Persistent conversation state with save/load/export
> 2. **Usage Tracking** - Real-time token and cost monitoring per model
> 3. **Auto-routing** - Smart model selection for coding tasks
> 4. **Coding Tools** - Specialized commands with tailored system prompts
>
> [Full detailed explanation with architecture diagrams, component interaction, and best practices...]

The explanation includes citations from official documentation and explains not just *what* the code does, but *why* it's designed that way.

### `/debug` - Error Analysis

Provide error details:
```
/debug TypeError: 'NoneType' object is not subscriptable at line 42
```

Get comprehensive debugging help:
> **Root Cause:** You're trying to access an index on a None object, which occurs when a function returns None instead of the expected list/dict.
>
> **Why This Happened:** The variable is None because [specific reason based on context]
>
> **Solution:**
> ```python
> # Before (causes error)
> result = get_data()
> value = result[0]  # Error if result is None
>
> # After (fixed)
> result = get_data()
> if result is not None:
>     value = result[0]
> else:
>     value = default_value
> ```
>
> **Preventive Measures:**
> - Add type hints and validation
> - Use Optional[] types
> - Implement proper error handling
>
> [Additional debugging techniques and best practices...]

### `/convert` - Language Translation

Convert Python to JavaScript:
```
/convert python javascript "def hello(name): return f'Hello, {name}!'"
```

Get idiomatic translation:
```javascript
// Converted from Python to JavaScript
function hello(name) {
    return `Hello, ${name}!`;
}

// Usage example:
console.log(hello("World")); // Output: Hello, World!
```

The conversion uses proper JavaScript conventions (arrow functions, template literals, etc.) rather than direct literal translation.

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

## Project Structure

```
ppxai/
├── ppxai.py                              # Main CLI application
├── tool_manager.py                       # Tool management system
├── perplexity_tools_prompt_based.py      # AI tool implementation
├── demo/
│   ├── example_builtin_tool.py           # Example Python tool
│   ├── example_mcp_server/               # Example MCP server
│   └── demo_tools_working.py             # Working demo
├── tests/
│   ├── test_all_tools.py                 # Tool tests
│   ├── test_mcp.py                       # MCP diagnostics
│   └── test_prompt_tools.py              # Quick test
├── docs/
│   ├── README.md                          # Documentation index
│   ├── TOOL_CREATION_GUIDE.md            # Step-by-step tool guide
│   ├── QUICK_START_TOOLS.md              # 60-second setup
│   └── ...                                # Additional guides
├── SPECIFICATIONS.md                     # Code generation specs
├── CLAUDE.md                             # Claude Code guidance
└── README.md                             # This file
```

## Documentation

- **Main Guide:** [README.md](README.md) (this file)
- **Tool System:** [docs/README.md](docs/README.md)
- **Tool Creation:** [docs/TOOL_CREATION_GUIDE.md](docs/TOOL_CREATION_GUIDE.md)
- **Code Generation:** [SPECIFICATIONS.md](SPECIFICATIONS.md)
- **Building:** [BUILD.md](BUILD.md)
- **Contributing:** [CONTRIBUTING.md](CONTRIBUTING.md)
- **Security:** [SECURITY.md](SECURITY.md)

## License

MIT
