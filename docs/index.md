# ppxai Documentation

**Multi-LLM Interface for Developers** - Use your favorite AI provider in terminal or VSCode with zero vendor lock-in.

[![Version](https://img.shields.io/badge/version-1.18.1-blue)](https://github.com/rcconsult/ppxai/releases)
[![License](https://img.shields.io/badge/license-MIT-brightgreen)](https://github.com/rcconsult/ppxai/blob/master/LICENSE)

## Why ppxai?

| Problem | ppxai Solution |
|---------|----------------|
| Locked to one AI vendor | Switch between Perplexity, Gemini, OpenAI, OpenRouter, Ollama anytime |
| Can't use local models | Full Ollama/vLLM support with same interface |
| AI modifies files without asking | Consent-based safety for all file operations |
| Lost context when switching models | Preserve conversation across provider changes |
| Expensive cloud-only pricing | Mix cloud and local models per task |

## Quick Start

### Installation

=== "Linux/macOS"

    ```bash
    curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/scripts/install.sh | bash
    ```

=== "Windows"

    ```powershell
    irm https://raw.githubusercontent.com/rcconsult/ppxai/master/scripts/install.ps1 | iex
    ```

=== "pip"

    ```bash
    pip install ppxai
    ```

### Configure API Keys

```bash
# Create ~/.ppxai/.env with your keys
PERPLEXITY_API_KEY=pplx-xxx
GEMINI_API_KEY=xxx
OPENAI_API_KEY=sk-xxx
```

### Run

```bash
ppxai              # Rich TUI (original)
ppxaide            # Textual TUI (v1.15.0+)
ppxai-server       # HTTP server for VSCode
ppxai-desktop      # Desktop web app
```

## Features

### Multi-Provider Support

- **Perplexity AI** - Real-time web search with citations
- **Google Gemini** - 1M token context, search grounding
- **OpenAI** - GPT-4o, o1 reasoning models
- **OpenRouter** - 100+ models including Claude
- **Local Models** - Ollama, vLLM, LMStudio

### Four Interfaces

| Feature | ppxai (Rich TUI) | ppxaide (Textual TUI) | VSCode | Web App |
|---------|------------------|----------------------|--------|---------|
| Streaming responses | ✅ | ✅ | ✅ | ✅ |
| Syntax highlighting | ✅ | ✅ | ✅ | ✅ |
| File editing tools | ✅ | ✅ | ✅ | ✅ |
| Agent mode | ✅ | ✅ | ✅ | ✅ |
| Checkpoint/undo | ✅ | ✅ | ✅ | ✅ |
| Markdown in chat | Limited | ✅ Full rendering | ✅ | ✅ |
| Themes | 6 themes | 17+ themes | N/A | N/A |
| Tab completion | ✅ | ✅ | N/A | N/A |

### Agent Mode

Enable autonomous multi-step task execution:

```
/agent on
```

The AI can chain tool calls, edit files, run commands - all with your consent.

### Bootstrap Context

Load project-specific instructions from `AGENTS.md`:

```markdown
---
provider_hints:
  local:
    - "Complete tasks fully without stopping."
model_hints:
  "deepseek-r1*":
    - "Show reasoning before actions."
---

# Project Instructions
Python 3.11+, pytest for testing.
```

## Documentation

<div class="grid cards" markdown>

-   :material-download:{ .lg .middle } **Installation**

    ---

    Install ppxai on Linux, macOS, or Windows

    [:octicons-arrow-right-24: Installation Guide](INSTALLATION.md)

-   :material-robot:{ .lg .middle } **Agent Mode**

    ---

    Autonomous task execution with tools

    [:octicons-arrow-right-24: Agent Mode Guide](AGENT_MODE_GUIDE.md)

-   :material-file-document:{ .lg .middle } **Bootstrap Context**

    ---

    Project-specific AI instructions

    [:octicons-arrow-right-24: Bootstrap Context Guide](BOOTSTRAP_CONTEXT_GUIDE.md)

-   :material-cog:{ .lg .middle } **Provider Setup**

    ---

    Configure AI providers

    [:octicons-arrow-right-24: Provider Setup](PROVIDER_SETUP.md)

</div>

## Resources

- [GitHub Repository](https://github.com/rcconsult/ppxai)
- [Releases](https://github.com/rcconsult/ppxai/releases)
- [Issue Tracker](https://github.com/rcconsult/ppxai/issues)
- [Changelog](https://github.com/rcconsult/ppxai/blob/master/CHANGELOG.md)
