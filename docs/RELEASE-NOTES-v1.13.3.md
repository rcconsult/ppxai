# Release Notes - v1.13.3

**Release Date:** 2026-01-06

This release fixes critical issues with Gemini provider tools, improves error handling across all UIs, and adds better Windows compatibility.

## Highlights

- 🔧 **Gemini tools + grounding now work together** - Previously tools would break Gemini's native web search
- 🪟 **Windows compatibility fixes** - UTF-8 BOM handling, console encoding
- 📊 **Better error display** - Tool errors now show actual messages instead of `[object Object]`
- 🛠️ **vLLM GPT-OSS 120B support** - Properly unwraps nested tool call structures

## Fixed - Gemini Provider

### Tools + Grounding Working Together

**Problem**: When tools were enabled with Gemini, the model couldn't use its native Google Search Grounding. System messages (containing tool prompts) were being silently dropped.

**Root Cause**: The `_convert_messages()` method was skipping all system messages instead of passing them via Gemini's `system_instruction` config parameter.

**Solution**:
- System messages are now collected and passed via `system_instruction` in the API config
- Both grounding AND system_instruction work simultaneously
- Grounding provides native web search with citations
- System instruction enables prompt-based tool calling

**Impact**: Users can now use Gemini with tools enabled AND still get web search with citations.

### New Provider Options

Added `options` section in JSON config for provider-specific settings:

```json
"gemini": {
  "options": {
    "enable_grounding": true
  }
}
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enable_grounding` | boolean | `true` | Enable Google Search Grounding |

## Fixed - Error Display

### Tool Errors Now Show Actual Messages

**Before**: Tool errors displayed as `[object Object]` or generic "Unknown error"

**After**: Errors now show the actual error message:
```
Tool error (execute_shell_command): Command timed out after 30s
```

**Affected UIs**:
- VSCode extension
- Desktop Web App
- TUI

## Fixed - vLLM Compatibility

### GPT-OSS 120B Nested Tool Calls

vLLM with certain models (like GPT-OSS 120B) returns tool calls in a nested structure:

```json
{"function_call": {"name": "tool", "arguments": {...}}}
```

The tool parser now properly unwraps this structure to extract the tool call.

## Fixed - Windows Compatibility

### UTF-8 BOM in Config Files

PowerShell's `Out-File` cmdlet writes files with a UTF-8 BOM (Byte Order Mark). The config parser now handles this gracefully instead of failing with JSON parse errors.

### Console Encoding

The logger now handles Windows console encoding issues that could cause crashes when logging certain characters.

## Fixed - File Editing Tools

### UX Improvements

- `apply_patch` can create new files via `*** Add File:` syntax
- `insert_text` can create new files when `line_number=1`
- Support for AI-generated search-replace diff format (GPT-OSS 120B style)

## Test Results

```
579 passed in 15.23s
```

All tests pass on Windows and Linux.

## Upgrade Instructions

### From v1.13.2

This is a drop-in replacement. No configuration changes required.

```bash
# Update via pip
pip install --upgrade ppxai

# Or update via uv
uv pip install --upgrade ppxai
```

### Gemini Users

If you were experiencing issues with tools not working, they should now work correctly. Both tools and native web search (grounding) are enabled by default.

To disable grounding (use only ppxai tools for web search):

```json
"gemini": {
  "options": {
    "enable_grounding": false
  }
}
```

### VSCode Extension

Download the new VSIX from the GitHub release:
```bash
code --install-extension ppxai-1.13.3.vsix
```

## Files Changed

| Category | Files |
|----------|-------|
| Gemini Provider | `ppxai/engine/providers/gemini.py` |
| Engine Client | `ppxai/engine/client.py` |
| Config | `ppxai-config.example.json` |
| Tool Parsing | `ppxai/engine/tool_parsing.py` |
| Error Handling | `ppxai/server/http.py`, `vscode-extension/src/httpClient.ts` |
| Windows Compat | `ppxai/config.py`, `ppxai/common/logger.py` |
| Documentation | `docs/PROVIDER_SETUP.md` |

## Known Issues

**Accepted (not blocking)**:
- Perplexity/Gemini may use shell commands with curl for weather queries instead of native web search when tools are enabled. This works but is suboptimal. See ROADMAP.md for future fix.

## Contributors

- @rcconsult - All changes

---

**Full Changelog:** [v1.13.2...v1.13.3](https://github.com/rcconsult/ppxai/compare/v1.13.2...v1.13.3)
