# Release Notes: v1.11.2.1 (Patch Release)

**Release Date**: 2025-12-23
**Type**: Patch (Critical Bugfix)
**Status**: Released
**Priority**: High

## Overview

This is a critical patch release that fixes an autorouter bug discovered in v1.11.2. Users experiencing 404 errors when using coding commands with non-Perplexity providers (especially Gemini) should upgrade immediately.

## What's Fixed

### Critical: Autorouter Provider Mismatch Bug 🔧

**Problem**: When using a non-Perplexity provider (e.g., Gemini, OpenAI) and running coding commands (`/convert`, `/generate`, `/test`, etc.), the autorouter would incorrectly try to switch to Perplexity's `sonar-pro` model instead of the current provider's coding model, causing 404 errors.

**Symptoms**:
```
User: /convert @file.R to Python
Auto-routed to sonar-pro for coding task
Error: models/sonar-pro is not found for API version v1main [404]
```

**Root Cause**: Seven coding command handlers were missing the provider parameter when calling `send_coding_task()`, causing fallback to a stale global `MODEL_PROVIDER` variable that doesn't update when users switch providers during a session.

**Solution**: All coding command handlers now correctly pass the current session's provider to `send_coding_task()`, ensuring provider-specific coding models are used:
- Perplexity → `sonar-pro`
- Gemini → `gemini-2.5-pro`
- OpenAI → `gpt-4o`
- OpenRouter → `anthropic/claude-sonnet-4`
- Ollama → `codellama`

## Files Changed

**Core Fix**:
- `ppxai/commands.py` - Fixed 7 command handlers:
  - `handle_generate()` (line 424)
  - `handle_test()` (line 437)
  - `handle_docs()` (line 450)
  - `handle_implement()` (line 461)
  - `handle_debug()` (line 471)
  - `handle_explain()` (line 484)
  - `handle_convert()` (line 512)

**Testing**:
- `tests/test_commands.py` - Added `test_send_coding_task_gemini()` regression test

**Documentation**:
- `docs/AUTOROUTER-CONFIG.md` - NEW: Comprehensive autorouter configuration guide
- `ppxai-config.example.json` - Added `coding_model` documentation

**Version**:
- `pyproject.toml` - Version 1.11.2 → 1.11.2.1
- `vscode-extension/package.json` - Version 1.11.2 → 1.11.2.1

## Testing

All tests pass (308/308):
```bash
✓ test_send_coding_task_perplexity
✓ test_send_coding_task_custom
✓ test_send_coding_task_gemini  (NEW - regression test)
✓ test_send_coding_task_no_autoroute_perplexity
✓ test_send_coding_task_no_autoroute_custom
✓ test_send_coding_task_invalid_type_perplexity
✓ test_send_coding_task_invalid_type_custom
```

## Upgrade Instructions

### From v1.11.2

**Via uv** (recommended):
```bash
uv pip install --upgrade ppxai
```

**Via pip**:
```bash
pip install --upgrade ppxai
```

**VSCode Extension**:
1. Download `ppxai-1.11.2.1.vsix` from GitHub releases
2. Install: `code --install-extension ppxai-1.11.2.1.vsix`
3. Restart VSCode

### Verify Installation

```bash
ppxai --version
# Should show: ppxai 1.11.2.1
```

## Impact

- ✅ **Fixes**: 404 errors when using coding commands with Gemini, OpenAI, OpenRouter providers
- ✅ **Improves**: Autorouting now works correctly for all providers
- ✅ **Adds**: Comprehensive documentation for autorouter customization
- ✅ **Backward Compatible**: No breaking changes, drop-in replacement

## Who Should Upgrade?

**Upgrade immediately if**:
- ❗ You use Gemini, OpenAI, or OpenRouter providers
- ❗ You use coding commands (`/convert`, `/generate`, `/test`, etc.)
- ❗ You experienced 404 errors with coding commands

**Upgrade at convenience if**:
- ✓ You only use Perplexity provider (not affected by this bug)
- ✓ You have autorouting disabled (`/autoroute off`)

## New Feature: Autorouter Configuration

This release adds comprehensive documentation for customizing autorouter behavior. You can now configure which model is used for coding tasks per provider.

**Example**: Use Gemini 3 Pro Preview for coding:
```json
{
  "providers": {
    "gemini": {
      "default_model": "gemini-2.0-flash",
      "coding_model": "gemini-3-pro-preview"
    }
  }
}
```

See [docs/AUTOROUTER-CONFIG.md](AUTOROUTER-CONFIG.md) for complete guide.

## Known Issues

None. This patch release resolves all known issues from v1.11.2.

## What's Next?

After this patch release, development will continue on v1.11.3+ for agentic workflow features:
- `@git` context provider
- `@tree` context provider
- `/agent` command for autonomous multi-step tasks

See [docs/v1.11.0-agentic-workflow-plan.md](v1.11.0-agentic-workflow-plan.md) for details.

## Links

- **GitHub Release**: https://github.com/rcconsult/ppxai/releases/tag/v1.11.2.1
- **Bug Report**: [bug-tui-20251223.txt](../bug-tui-20251223.txt)
- **Autorouter Guide**: [AUTOROUTER-CONFIG.md](AUTOROUTER-CONFIG.md)
- **Changelog**: [CHANGELOG.md](../CHANGELOG.md)

---

**Release created**: 2025-12-23
**Supersedes**: v1.11.2 (2025-12-22)
**Next planned**: v1.11.3 (agentic workflow features)
