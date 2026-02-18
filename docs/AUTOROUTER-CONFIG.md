# Autorouter Configuration Guide

## Overview

The autorouter automatically switches to a provider's best coding model when you use coding commands. This ensures you get the most capable model for tasks like code generation, debugging, and conversion.

Works with **ppxai** (Rich TUI), **ppxaide** (Textual TUI), and the VSCode extension.

## How It Works

When you use coding commands with autoroute enabled (default):
- `/generate` - Code generation
- `/test` - Generate unit tests
- `/docs` - Generate documentation
- `/implement` - Implement features
- `/debug` - Debug errors
- `/explain` - Explain code
- `/convert` - Convert between languages

The system automatically switches from your current model to the provider's designated `coding_model`.

## Default Coding Models

Each provider has a pre-configured coding model optimized for development tasks:

| Provider | Default Coding Model | Why This Model? |
|----------|---------------------|-----------------|
| **Perplexity** | `sonar-pro` | Advanced reasoning for complex coding tasks |
| **Gemini** | `gemini-2.5-pro` | Most capable model for complex reasoning |
| **OpenAI** | `gpt-4o` | Latest flagship with strong coding ability |
| **OpenRouter** | `anthropic/claude-sonnet-4` | Balanced performance for development |
| **Ollama** | `codellama` | Specialized local coding model |

## Customizing Coding Models

You can customize which model is used for coding tasks by editing your `ppxai-config.json`:

### Example: Use Gemini 3 Pro Preview for Coding

```json
{
  "providers": {
    "gemini": {
      "name": "Google Gemini",
      "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
      "api_key_env": "GEMINI_API_KEY",
      "default_model": "gemini-2.5-flash",
      "coding_model": "gemini-3-pro-preview",  // Changed from gemini-2.5-pro
      "models": {
        // ... model definitions ...
      }
    }
  }
}
```

### Example: Use o1 for OpenAI Coding Tasks

```json
{
  "providers": {
    "openai": {
      "name": "OpenAI ChatGPT",
      "base_url": "https://api.openai.com/v1",
      "api_key_env": "OPENAI_API_KEY",
      "default_model": "gpt-4o-mini",
      "coding_model": "o1",  // Use advanced reasoning model for coding
      "models": {
        // ... model definitions ...
      }
    }
  }
}
```

### Example: Disable Autorouting (Use Same Model)

```json
{
  "providers": {
    "gemini": {
      "name": "Google Gemini",
      "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
      "api_key_env": "GEMINI_API_KEY",
      "default_model": "gemini-2.5-flash-lite",
      "coding_model": "gemini-2.5-flash-lite",  // Same as default, no switching
      "models": {
        // ... model definitions ...
      }
    }
  }
}
```

## Managing Autorouting

You can control autorouting behavior using the `/autoroute` command:

```bash
# Check current status
/autoroute

# Enable autorouting (default)
/autoroute on

# Disable autorouting (use current model for all tasks)
/autoroute off
```

When autorouting is disabled, all commands use your currently selected model.

## Common Use Cases

### Use Case 1: Cost Optimization

**Scenario:** Use a cheap model for chat, but auto-route to a powerful model for coding.

```json
{
  "providers": {
    "gemini": {
      "default_model": "gemini-2.5-flash-lite",  // $0.075/$0.30 per million tokens
      "coding_model": "gemini-2.5-pro"            // $1.25/$5.00 per million tokens
    }
  }
}
```

**Result:** Chat costs are low, but coding tasks get the most capable model.

### Use Case 2: Consistent Model

**Scenario:** Always use the same model, never auto-route.

```json
{
  "providers": {
    "openai": {
      "default_model": "gpt-4o",
      "coding_model": "gpt-4o"  // Same as default
    }
  }
}
```

Then disable autorouting:
```bash
/autoroute off
```

### Use Case 3: Specialized Coding Model

**Scenario:** Use Ollama with a specialized coding model.

```json
{
  "providers": {
    "ollama": {
      "default_model": "llama3.2",      // General chat
      "coding_model": "codellama"        // Specialized for code
    }
  }
}
```

## Configuration File Locations

ppxai searches for configuration in this order:

1. `PPXAI_CONFIG_FILE` environment variable
2. `./ppxai-config.json` (project-specific)
3. `~/.ppxai/ppxai-config.json` (user-specific)
4. Built-in defaults (if no config file found)

## Built-in Provider Defaults

If you don't create a `ppxai-config.json`, these defaults are used:

```json
{
  "perplexity": {
    "default_model": "sonar-pro",
    "coding_model": "sonar-pro"
  },
  "gemini": {
    "default_model": "gemini-2.5-flash",
    "coding_model": "gemini-2.5-pro"
  }
}
```

## Troubleshooting

### Autorouting Uses Wrong Model

**Problem:** Using Gemini provider, but `/convert` auto-routes to Perplexity's `sonar-pro`.

**Solution:** This was a bug fixed in v1.11.3. Ensure you're on the latest version:
```bash
ppxai --version
```

If on an older version, the autorouter would use the global `MODEL_PROVIDER` instead of the current session provider.

### Want to See Which Model Will Be Used

```bash
# Check current autoroute status and coding model
/autoroute

# Output shows:
# Auto-routing is currently: enabled
# Auto-routing uses gemini-2.5-pro for coding commands
# Use /autoroute on or /autoroute off to change
```

## See Also

- [ppxai-config.example.json](../ppxai-config.example.json) - Full configuration example
- [README.md](../README.md) - General usage guide
- [CLAUDE.md](../CLAUDE.md) - Development documentation
