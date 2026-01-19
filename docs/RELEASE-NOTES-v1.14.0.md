# Release Notes - v1.14.0

**Release Date:** January 19, 2026

## Overview

v1.14.0 introduces **Bootstrap Context Support** - a system for loading project-specific instructions from `AGENTS.md` or `CLAUDE.md` files. This feature allows teams to share consistent AI behavior across sessions and provides dynamic prompt assembly based on the current provider and model.

## What's New

### AGENTS.md/CLAUDE.md Support

ppxai now automatically loads project instructions from bootstrap files on startup:

- **Auto-discovery** - Looks for `AGENTS.md`, then `CLAUDE.md` in the working directory
- **YAML front matter** - Provider and model-specific hints in structured header
- **Dynamic prompt assembly** - System prompt rebuilds automatically when switching provider/model
- **Configurable file aliases** - User-defined fallback list via `bootstrap.files` config

**Example `AGENTS.md`:**

```markdown
---
provider_hints:
  local:
    - "Complete tasks fully without stopping on empty responses."
    - "Use tools proactively - don't ask permission for read-only operations."
  ollama:
    - "Keep responses concise - Ollama has limited context."
  gemini:
    - "Use Google Search grounding for current information when available."
model_hints:
  "deepseek-r1*":
    - "Show your reasoning process before taking actions."
  "qwen2.5-coder*":
    - "Focus on code quality and correctness."
---

# Project Instructions

Python 3.11+, type hints required, pytest for testing.
```

### Provider/Model Hints System

The hints system provides targeted guidance based on which AI provider and model you're using:

- **Provider hints** - Instructions specific to a provider (e.g., `ollama`, `gemini`, `custom`)
- **Model hints** - Pattern-matched instructions (e.g., `deepseek-r1*` matches any DeepSeek R1 model)
- **`local` inheritance** - Ollama, vLLM, and LMStudio automatically inherit from `local` hints
- **Additive behavior** - Both provider AND model hints concatenate (not override)

### Debugging Visibility

New commands help you understand what hints are active for your current session:

- **`/context hints`** - Shows detailed breakdown of active provider/model hints
- **`/status`** - Now displays active hints count with inheritance indicator (e.g., `3+ provider hints active`)
- **Debug logging** - Enable with `/debug-log on` to see hint transitions when switching provider/model
- **`/context/hints` endpoint** - VSCode extension can query active hints via HTTP

### VSCode/Web Table Rendering Fix

Markdown tables in the VSCode extension and Web App now use word-wrap instead of horizontal scrollbars, making them more readable.

## Configuration

### Bootstrap Config Options

Add to your `ppxai-config.json`:

```json
{
  "bootstrap": {
    "enabled": true,
    "files": ["AGENTS.md", "CLAUDE.md", "INSTRUCTIONS.md"]
  }
}
```

- `enabled` (default: `true`) - Enable/disable bootstrap context loading
- `files` (default: `["AGENTS.md", "CLAUDE.md"]`) - List of filenames to search for (in order)

## Upgrade Notes

- No breaking changes from v1.13.10
- Existing sessions will continue to work without modification
- To use bootstrap context, create an `AGENTS.md` file in your project root

## Technical Details

### New Files

- `ppxai/engine/bootstrap.py` - Bootstrap context parsing and prompt assembly
- `tests/test_bootstrap_context.py` - Unit tests for bootstrap functionality

### API Changes

- `EngineClient.get_active_hints()` - Returns detailed breakdown of active hints
- `EngineClient.get_bootstrap_status()` - Returns bootstrap loading status
- `GET /context/hints` - New HTTP endpoint for querying active hints

### Architecture

```
Prompt Assembly Order:
1. [bootstrap base_instructions]      # Content below YAML ---
2. [matching provider_hints]          # If provider matches
3. [matching model_hints]             # If model regex matches
4. [config system_prompt]             # From ppxai-config.json
5. [tool_prompt]                      # If tools enabled
```

## Contributors

- Bootstrap context system implementation
- Provider/model hints with `local` inheritance
- `/context hints` command and debugging features
- CSS table word-wrap fix for VSCode/Web

## Full Changelog

See [CHANGELOG.md](../CHANGELOG.md) for complete details.
