# ppxai - Perplexity AI Text UI

A terminal-based interface for interacting with Perplexity AI models.

## Features

- 🤖 Interactive chat with Perplexity AI models
- 🔄 Model selection (Sonar, Sonar Pro, Sonar Reasoning, and more)
- 💬 Conversation history management
- ⚡ Streaming responses for real-time interaction
- 📝 Command history support
- 🎨 Rich terminal UI with markdown rendering
- 🔗 Clickable source citations in terminal
- 📦 Standalone executables available (no Python required!)

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

- Type your question or prompt to chat with the AI
- `/model` - Change the current model
- `/clear` - Clear conversation history
- `/help` - Show help message
- `/quit` or `/exit` - Exit the application

### Available Models

1. **Sonar** - Lightweight search model with real-time grounding
2. **Sonar Pro** - Advanced search model for complex queries
3. **Sonar Reasoning** - Fast reasoning model for problem-solving with search
4. **Sonar Reasoning Pro** - Precision reasoning with Chain of Thought capabilities
5. **Sonar Deep Research** - Exhaustive research with comprehensive reports

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
