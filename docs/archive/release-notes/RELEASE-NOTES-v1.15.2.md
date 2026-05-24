# Release Notes: v1.15.2

**Release Date:** 2026-02-06
**Branch:** feature/1-15-2
**Focus:** Gemini Native Tool Calling, display_file VSCode Fix, LLM Benchmark Suite

---

## Overview

v1.15.2 brings **native tool calling for Gemini**, fixes the **VSCode display_file integration**, and introduces a comprehensive **LLM benchmark suite** for evaluating agentic coding capabilities. This release also includes critical Unicode normalization fixes for `apply_patch` and enhanced truncated tool call detection.

---

## Major Features

### 1. Gemini Native Tool Calling

**What Changed:**
- Gemini provider now uses native `function_declarations` instead of prompt-based tool calling
- Full streaming support with `TOOL_CALL` events
- Backward compatible - prompt-based mode still works with `native_tool_calling: false`

**Technical Details:**
- `ppxai/engine/providers/gemini.py` - Complete rewrite with `_convert_tools_to_gemini()` and `_parse_function_call()`
- Tools converted from OpenAI format to Gemini `function_declarations`
- Default capabilities now include `native_tool_calling=True`

**Limitation:**
- Multi-tool use (GoogleSearch + function_declarations) requires Live API
- Standard `generate_content` API cannot mix grounding with tools
- When tools enabled, grounding automatically disabled

**Workaround for Web Search:**
- `web_search` tool now available for Gemini in agent mode
- Uses premium web search (Perplexity → Gemini grounding API → DuckDuckGo fallback)
- Separate grounding-only API call when agent needs web data

**Configuration:**
```json
{
  "providers": {
    "gemini": {
      "native_tool_calling": true  // Default in v1.15.2
    }
  }
}
```

**Files Updated:**
- `ppxai/engine/providers/gemini.py` - Native tool calling implementation
- `ppxai/engine/tools/builtin/web_premium.py` - Removed Gemini from exclusion list

---

### 2. VSCode display_file Fix (EventBus Architecture)

**What Changed:**
- Fixed display_file tool in VSCode extension - files now open in editor tab instead of chat
- Completed incomplete EventBus refactoring

**Root Cause:**
- EventBus infrastructure existed (handlers, event types, subscribers) but wasn't connected
- `handleStreamEvent()` never called `processStreamEvent()` to emit typed events
- Events went through old switch-case logic instead of EventBus

**Fix Applied:**
- Made `handleStreamEvent()` call `processStreamEvent(event, this._eventBus)` at the start
- Added display_file case to `processStreamEvent()` in `stream.ts`
- Added `stream:display_file` event type to EventBus interface
- Added subscriber in `chatPanel.ts` to open files in `ViewColumn.Beside`

**Flow:**
```
Server emits DISPLAY_FILE → SSE → mapServerEvent() → StreamEvent
→ handleStreamEvent() → processStreamEvent() → eventBus.emit('stream:display_file')
→ subscriber opens file in VSCode editor
```

**Files Updated:**
- `vscode-extension/src/chatPanel.ts` - Wired EventBus in handleStreamEvent()
- `vscode-extension/src/handlers/stream.ts` - Added processDisplayFile()
- `vscode-extension/src/handlers/eventBus.ts` - Added stream:display_file event type
- `vscode-extension/src/httpClient.ts` - Added display_file case to mapServerEvent()

**Lesson Learned:**
Incomplete refactoring can leave both old (switch-case) and new (EventBus) code paths, causing events to bypass proper handlers. Always complete architectural transitions fully.

---

### 3. LLM Benchmark Suite

**What's New:**
- Comprehensive benchmark suite in `benchmarks/llm-eval/`
- 6 test categories, 21+ test cases for evaluating agentic coding capabilities
- Tests load generation params from `ppxai-config.json` for reproducible evaluation

**Test Categories:**
1. **hallucination_resistance** - Gate tests for basic reliability (must pass 100%)
   - File existence verification
   - Tool result validation
   - Success claim detection
   - Command output fabrication
2. **tool_calling** - Native tool execution accuracy
3. **file_editing** - apply_patch, replace_block, insert_text
4. **code_generation** - Generate working code from descriptions
5. **multi_step_tasks** - Complex multi-step agent workflows
6. **error_recovery** - Handle failures and retry

**Usage:**
```bash
# Run all benchmarks
uv run pytest benchmarks/llm-eval/ -v

# Run specific category
uv run pytest benchmarks/llm-eval/test_hallucination_resistance.py -v

# Run with specific model
BENCHMARK_PROVIDER=ollama BENCHMARK_MODEL=qwen2.5-coder:32b pytest benchmarks/
```

**Configuration:**
Benchmarks read generation params from `ppxai-config.json`:
```json
{
  "providers": {
    "ollama": {
      "models": {
        "qwen2.5-coder:32b": {
          "generation_params": {
            "temperature": 0.2,
            "top_p": 0.9
          }
        }
      }
    }
  }
}
```

**Files Added:**
- `benchmarks/llm-eval/test_hallucination_resistance.py` - Gate tests
- `benchmarks/llm-eval/test_tool_calling.py` - Tool execution tests
- `benchmarks/llm-eval/test_file_editing.py` - File operation tests
- `benchmarks/llm-eval/conftest.py` - Shared fixtures and helpers

---

## Critical Fixes

### 4. Unicode Whitespace Normalization in apply_patch

**Problem:**
LLM models output Unicode whitespace characters (NBSP `\xa0`, NNBSP `\u202f`, Thin Space) that break exact string matching in `apply_patch` tool.

**Solution:**
5-level fuzzy matching in `_replace_hunk()`:
1. **Exact match** - Try unmodified strings first
2. **CRLF normalization** - Convert `\r\n` → `\n`
3. **Unicode normalization** - Replace Unicode spaces with regular spaces
4. **Strip + normalize** - Remove leading/trailing whitespace then normalize
5. **Collapse whitespace** - Replace multiple spaces/tabs with single space

**Impact:**
- apply_patch now works reliably with GPT-4o, Claude, Gemini outputs
- No more "pattern not found" errors from invisible Unicode differences

**Files Updated:**
- `ppxai/engine/tools/builtins.py` - Enhanced `_replace_hunk()` with 5-level matching
- 20 new tests in `tests/test_unicode_normalization.py`

---

### 5. Truncated Tool Call Detection

**Problem:**
GPT-OSS sometimes says "I'll use X tool" then outputs incomplete JSON when `max_tokens` not set, or when vLLM's Harmony parser fails.

**Solution:**
- Detection in `validator.py` - recognizes "I'll use X tool" with incomplete JSON
- Auto-retry with targeted guidance when truncation detected
- System prompt instructs models to call tools directly, never output JSON in text

**Mitigation:**
Add `max_tokens: 8192` to model config to prevent truncation:
```json
{
  "models": {
    "openai/gpt-oss-120b": {
      "max_tokens": 8192,
      "generation_params": { "temperature": 0.2 }
    }
  }
}
```

**Files Updated:**
- `ppxai/engine/tools/validator.py` - Truncated tool call detection
- Enhanced system prompt in tool manager
- 20 new tests for truncation detection

---

## Additional Improvements

### Configuration & Settings

- **Generation params from config** - Gemini and Perplexity providers now load `temperature`, `top_p`, etc. from `ppxai-config.json`
- **Config loader fix** - Now includes all config sections (`server`, `session`, `tui`, `paths`)
- **`server.idle_timeout`** - Config now properly read (was always using 300s default)

### ppxaide TUI

- **Streaming cancellation** - Ctrl+C during streaming gracefully cancels the response
- **SIGINT handler** - Graceful shutdown on Ctrl+C for Linux/macOS
- **Double Ctrl+C to quit** - Prevents accidental exits
- **Autocomplete fix** - Preserves command prefix for subcommands (`/provider ` + TAB works)
- **Trace logging mode** - `--trace` flag for verbose per-event logging (separate from `--debug`)

### Web App

- **`/context reload` fix** - Shows correct message instead of false "not found"
- **Clipboard button fix** - Now uses correct global reference (`window.ppxai`)
- **`display_file` event** - Now handled properly (opens split preview in Monaco editor)

### Status & Terminal

- **`/status` command** - Shows terminal override indicators when `PPXAI_TERMINAL` or `PPXAI_IMAGE_PROTOCOL` env vars set
- **Terminal detection** - Better handling of WezTerm, Windows Terminal, iTerm2

---

## Technical Improvements

### Code Quality

- **Refactored StatusBar helpers** - Extracted `_format_cwd_display()`, `_update_checkpoint_badge()`
- **EventBus logging** - Now tied to `--trace` mode instead of `--debug`
- **Widget query errors** - Use specific `NoMatches` exception instead of bare `except:`

### Testing

- **20 new tests** for Unicode whitespace normalization
- **20 new tests** for truncated tool call detection
- **Benchmark test ordering** - `hallucination_resistance` runs first as gate tests
- **Total test count:** 1,105 passing tests

---

## Breaking Changes

None. This release is fully backward compatible with v1.15.1.

---

## Upgrade Notes

### From v1.15.1

No action required. Just update binaries and VSCode extension.

### Recommended Configuration for GPT-OSS

If using vLLM with GPT-OSS models, add `max_tokens` to prevent truncation:

```json
{
  "providers": {
    "gpt-oss": {
      "models": {
        "openai/gpt-oss-120b": {
          "max_tokens": 8192,
          "generation_params": {
            "temperature": 0.2,
            "top_p": 0.9
          }
        }
      }
    }
  }
}
```

---

## Installation

### Pre-built Binaries

Download from [GitHub Releases](https://github.com/rcconsult/ppxai/releases/tag/v1.15.2):

- `ppxai-{platform}` - Rich TUI
- `ppxaide-{platform}` - Textual TUI
- `ppxai-server-{platform}` - HTTP server for VSCode
- `ppxai-desktop-{platform}` - Desktop Web App
- `ppxai-1.15.2.vsix` - VSCode extension
- `ppxai-*-macos-arm64.dmg` - macOS app bundle installer

### One-Line Install

**Linux / macOS:**
```bash
curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash
```

**Windows (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/rcconsult/ppxai/master/scripts/install.ps1 | iex
```

### VSCode Extension

```bash
code --install-extension ppxai-1.15.2.vsix
```

---

## Documentation

- [Installation Guide](../docs/installation.md)
- [Provider Setup](../docs/provider-setup.md)
- [Agent Mode Guide](../docs/agent-mode-guide.md)
- [Architecture](../docs/architecture.md)
- [vLLM Tool Calling Guide](../docs/vllm-tool-calling-guide.md)

---

## Contributors

This release represents 20 commits with 132 files changed.

Key features developed on the `feature/1-15-2` branch from 2026-01-30 to 2026-02-06.

---

## What's Next?

See [TODO-v1.16.0.md](../TODO-v1.16.0.md) for the next release plan:

- **Phase 0:** Command-based navigation (`/ls`, `/tree`) for all clients
- **Phase 1:** ppxaide interactive file tree (NvChad-style)
- **Phase 2:** Web App file tree sidebar

---

**Full Changelog:** [v1.15.1...v1.15.2](https://github.com/rcconsult/ppxai/compare/v1.15.1...v1.15.2)
