# Bootstrap Context Guide

**Version:** v1.14.2+
**Last Updated:** January 23, 2026

## Overview

Bootstrap context allows you to define project-specific instructions that are automatically loaded when starting **ppxai** (Rich TUI) or **ppxaide** (Textual TUI). These instructions become part of the system prompt, guiding AI behavior for your specific project.

**Key Features:**
- **Hierarchical scopes** (v1.14.2) - Global, project, and subdirectory contexts that merge automatically
- Auto-discovery of `AGENTS.md` or `CLAUDE.md` files
- Provider-specific hints (different instructions for Ollama vs Gemini)
- Model-specific hints with pattern matching
- **Include directive** (v1.14.2) - Compose AGENTS.md from multiple files
- **Hint templates** (v1.14.2) - Define reusable hint sets
- Dynamic prompt assembly when switching provider/model
- Debugging commands to see active hints

## Quick Start

Create an `AGENTS.md` file in your project root:

```markdown
---
provider_hints:
  local:
    - "Complete tasks fully without stopping on empty responses."
  ollama:
    - "Keep responses concise - limited context window."
model_hints:
  "deepseek-r1*":
    - "Show reasoning before taking actions."
---

# Project Instructions

This is a Python 3.11+ project using pytest for testing.
Always use type hints and follow PEP 8 style guidelines.
```

When you start ppxai or ppxaide in this directory, these instructions are automatically loaded.

## File Format

### Basic Structure

```markdown
---
# YAML front matter (optional)
provider_hints:
  <provider_id>:
    - "hint 1"
    - "hint 2"
model_hints:
  "<pattern>":
    - "hint 1"
---

# Markdown content below
Your project instructions here...
```

### File Discovery

ppxai searches for bootstrap files in **hierarchical order** (v1.14.2+):

1. **Global scope** - `~/.ppxai/AGENTS.md` (user-wide defaults)
2. **Project scope** - `{git_root}/AGENTS.md` (repository-specific)
3. **Subdirectory scope** - `{cwd}/AGENTS.md` (directory-specific overrides)

Within each scope, it looks for these files in order:
1. `AGENTS.md` (default, compatible with Claude Code)
2. `CLAUDE.md` (fallback)

Files from all scopes are **merged** - hints are additive, base instructions concatenate with source markers.

You can customize the file list via configuration:

```json
{
  "bootstrap": {
    "files": ["AGENTS.md", "CLAUDE.md", "INSTRUCTIONS.md"]
  }
}
```

### Viewing Active Context

Use `/context show` to see which bootstrap files are loaded:

```
/context show

Bootstrap Context

Sources: (2 files)
1. /Users/you/.ppxai/AGENTS.md
   [🌐 global] 1.4 KB
2. /Users/you/project/AGENTS.md
   [📁 project] 3.9 KB

Total: 5.3 KB (~1,325 tokens)

Hints Defined:
  Provider: local, ollama, perplexity
  Model: deepseek*, qwen*
```

## Provider Hints

Provider hints are instructions that apply when using a specific AI provider.

### Syntax

```yaml
provider_hints:
  ollama:
    - "Hint for Ollama"
  gemini:
    - "Hint for Gemini"
  perplexity:
    - "Hint for Perplexity"
```

### The `local` Provider

The special `local` key applies to all local model providers:
- `ollama`
- `vllm`
- `lmstudio`

```yaml
provider_hints:
  local:
    - "Complete tasks fully - don't stop after tool calls."
    - "Use tools proactively without asking permission."
  ollama:
    - "Keep responses concise."  # Additional Ollama-specific hint
```

When using Ollama, you get both `local` hints AND `ollama` hints.

### Common Provider Hints

| Provider | Recommended Hints |
|----------|------------------|
| `local` | "Complete tasks fully", "Use tools proactively" |
| `ollama` | "Keep responses concise", "Prefer smaller focused tool calls" |
| `gemini` | "Use Google Search grounding for current information" |
| `perplexity` | "Use native web search - don't use web_search tool" |
| `custom` | "Use tools directly without XML formatting" |

## Model Hints

Model hints apply to specific models matched by pattern.

### Syntax

```yaml
model_hints:
  "deepseek-r1*":
    - "Show your reasoning process before taking actions."
  "qwen2.5-coder*":
    - "Focus on code quality and correctness."
  "gpt-4*":
    - "You can handle complex multi-step reasoning."
```

### Pattern Matching

Patterns use glob-style matching:
- `*` matches any characters
- Matching is case-insensitive

| Pattern | Matches |
|---------|---------|
| `deepseek-r1*` | `deepseek-r1`, `deepseek-r1:7b`, `deepseek-r1-lite` |
| `qwen2.5-coder*` | `qwen2.5-coder:3b`, `qwen2.5-coder:7b` |
| `gpt-4*` | `gpt-4`, `gpt-4o`, `gpt-4-turbo` |
| `llama*` | `llama3.1`, `llama3.2:3b`, `llama-3.1-70b` |

### Common Model Hints

| Model Pattern | Recommended Hints |
|---------------|------------------|
| `deepseek-r1*` | "Show reasoning before actions" |
| `qwen2.5-coder*` | "Focus on code quality", "Use edit_file for surgical changes" |
| `sonar*` | "Use real-time web access", "Cite sources with markdown links" |
| Small models (<3B) | "Keep responses focused", "Avoid complex multi-step reasoning" |

## Prompt Assembly

When you send a message, ppxai assembles the system prompt in this order:

1. **Bootstrap base instructions** - Content below the YAML `---`
2. **Provider hints** - Matching provider (including `local` inheritance)
3. **Model hints** - All patterns that match current model
4. **Config system prompt** - From `ppxai-config.json` (if any)
5. **Tool prompt** - If tools are enabled

### Example Assembly

With this `AGENTS.md`:
```markdown
---
provider_hints:
  local:
    - "Complete tasks fully."
  ollama:
    - "Keep responses concise."
model_hints:
  "qwen2.5*":
    - "Focus on code quality."
---

# My Project
Python 3.11+ with pytest.
```

Using `ollama` provider with `qwen2.5-coder:3b` model:

```
# My Project
Python 3.11+ with pytest.

## Provider Guidance
- Complete tasks fully.
- Keep responses concise.

## Model Guidance
- Focus on code quality.
```

## Debugging Commands

### `/context hints`

Shows detailed breakdown of active hints:

```
━━━ Active Bootstrap Hints ━━━
  Source: /path/to/project/AGENTS.md
  Provider: ollama
  Model: qwen2.5-coder:3b

Provider Hints: (2 active)
  (includes inherited 'local' hints)
  • [local] Complete tasks fully.
  • [ollama] Keep responses concise.

Model Hints: (1 active)
  Matched patterns: qwen2.5*
  • [qwen2.5*] Focus on code quality.

Total active hints: 3
```

### `/status`

Shows bootstrap context in status output:

```
━━━ ppxai Status ━━━
  Version: v1.14.0
  Provider: Ollama (Local)
  Model: qwen2.5-coder:3b
  Bootstrap: AGENTS.md (1,234 chars) (3+ provider, 1 model hints active)
```

The `+` indicates inherited `local` hints.

### Debug Logging

Enable debug logging to see hint transitions:

```
/debug-log on
```

When you switch provider/model, you'll see logs like:
```
[DEBUG] Model hints transition: qwen2.5-coder:3b -> deepseek-r1:7b
[DEBUG]   Previous: qwen2.5* (1 hint)
[DEBUG]   New: deepseek-r1* (2 hints)
```

## Configuration

### Enable/Disable Bootstrap

```json
{
  "bootstrap": {
    "enabled": true
  }
}
```

Set to `false` to disable bootstrap context loading entirely.

### Custom File List

```json
{
  "bootstrap": {
    "files": ["AGENTS.md", "CLAUDE.md", "AI-INSTRUCTIONS.md"]
  }
}
```

Files are checked in order; first match wins.

### Empty List Disables

```json
{
  "bootstrap": {
    "files": []
  }
}
```

An empty list disables bootstrap context (equivalent to `enabled: false`).

## Include Directive (v1.14.2+)

Compose your AGENTS.md from multiple files using include directives:

```markdown
---
provider_hints:
  local:
    - "Follow project conventions."
---

# Project Instructions

<!-- include: ./docs/coding-standards.md -->
<!-- include: ./docs/api-conventions.md -->
```

**Features:**
- Paths are relative to the AGENTS.md file location
- Max include depth: 5 levels (prevents infinite loops)
- Cycle detection: circular includes are detected and reported
- Missing files: shown as `<!-- include failed: path/to/file.md (not found) -->`

**Use Cases:**
- Share coding standards across multiple projects
- Keep domain-specific instructions in separate files
- Include generated documentation

## Hint Templates (v1.14.2+)

Define reusable hint sets in `~/.ppxai/hint-templates.yaml`:

```yaml
templates:
  tool-heavy:
    - "Use tools proactively without asking."
    - "Execute multiple tool calls in sequence."
    - "Don't stop on empty responses - continue working."

  concise:
    - "Keep responses brief and focused."
    - "Use bullet points for lists."

  reasoning:
    - "Show your reasoning process before taking actions."
    - "Explain trade-offs when making decisions."
```

Reference templates in AGENTS.md:

```yaml
provider_hints:
  ollama:
    - template: tool-heavy
    - template: concise
    - "Custom project-specific hint"
  gemini:
    - template: reasoning
```

**Benefits:**
- Consistent hints across projects
- Easy to update hints in one place
- Mix templates with custom hints

## Best Practices

### For Small Models (< 3B parameters)

```yaml
provider_hints:
  local:
    - "Keep responses concise and focused."
    - "Complete one task at a time."
    - "If a tool returns empty, explain what you tried."
model_hints:
  "qwen2.5-coder:0.5b":
    - "Focus on simple, direct tool calls."
    - "Avoid complex multi-step reasoning."
```

### For Large Models (7B+ parameters)

```yaml
provider_hints:
  local:
    - "Use tools proactively - don't ask for permission."
    - "Chain multiple tool calls when needed."
model_hints:
  "qwen2.5-coder:7b":
    - "You can handle complex file refactoring tasks."
```

### For Cloud Providers

```yaml
provider_hints:
  perplexity:
    - "Use your native web search for current information."
    - "Cite sources as markdown links inline."
  gemini:
    - "Use Google Search grounding when available."
    - "You have 1M token context - include full file contents."
```

### Project-Specific Instructions

Put project context in the markdown body below the YAML:

```markdown
---
provider_hints:
  local:
    - "Follow project conventions."
---

# Project: My App

## Code Style
- Python 3.11+, type hints required
- Use dataclasses for data structures
- pytest for testing, 80% coverage minimum

## Architecture
- `src/` contains source code
- `tests/` contains test files
- Use dependency injection for testability

## Important Files
- `src/config.py` - Configuration system
- `src/main.py` - Entry point
```

## Interaction with System Prompts

Bootstrap context works alongside `system_prompt` in `ppxai-config.json`:

1. Bootstrap context is added first
2. Config `system_prompt` is added according to `system_prompt_mode`:
   - `prepend` (default): Config prompt before bootstrap
   - `append`: Config prompt after bootstrap
   - `replace`: Config prompt replaces bootstrap (not recommended)

For most cases, let bootstrap handle project-specific instructions and use config `system_prompt` only for global preferences.

## Troubleshooting

### "No bootstrap context loaded"

**Cause:** No `AGENTS.md` or `CLAUDE.md` found in working directory.

**Solution:**
1. Create an `AGENTS.md` file in your project root
2. Or set working directory with `/cd /path/to/project`

### Hints not applying

**Cause:** Provider or model doesn't match any patterns.

**Solution:**
1. Run `/context hints` to see what's active
2. Check provider ID matches (e.g., `ollama` not `Ollama`)
3. Check model patterns (case-insensitive, use `*` for wildcards)

### Too many hints cluttering context

**Cause:** Multiple overlapping patterns matching.

**Solution:**
1. Use more specific patterns
2. Consolidate hints under `local` for all local providers
3. Remove redundant hints

## API Reference

### EngineClient Methods

```python
# Get bootstrap loading status
status = engine.get_bootstrap_status()
# Returns: {"loaded": True, "sources": [...], "char_count": 1234, ...}

# Get active hints for current provider/model
hints = engine.get_active_hints()
# Returns: {"loaded": True, "provider_hints": [...], "model_hints": [...], ...}
```

### HTTP Endpoints

```
GET /context/hints
Returns active hints for current session
```

## Related Documentation

- [Context Injection Guide](context-injection.md) - `@file`, `@git`, `@tree` runtime injection
- [Provider Setup Guide](provider-setup.md) - Configure AI providers
- [Ollama Limitations](ollama-limitations.md) - Small model behavior
- [Session Agent Guide](session-agent-guide.md) - Autonomous task execution

---

**Feedback:** Report issues at [GitHub Issues](https://github.com/rcconsult/ppxai/issues)
