# Release Notes: v1.11.3

**Release Date:** December 24, 2025
**Type:** Patch Release (Consolidates v1.11.2.1 + v1.11.2.2)
**Branch:** bugfix/gemini-tool-calling → master

**⚠️ Version Consolidation:** This release combines v1.11.2.1 and v1.11.2.2 into v1.11.3 due to VSCode extension versioning constraints. VSCode extensions only support 3-part semantic versioning (`major.minor.patch`), not 4-part versions like `1.11.2.2`. The VSCode extension build failed with "Invalid extension version '1.11.2.2'" error.

---

## Overview

v1.11.3 is a foundation refactoring release that combines two critical patches: provider abstraction improvements and autorouter fixes. This release improves extensibility for adding new AI providers and fixes critical bugs.

**Key Changes (from v1.11.2.2 - Provider Abstraction):**
- ✅ Configurable default provider (no more hardcoded "perplexity")
- ✅ Provider-specific pricing function
- ✅ AIClientWithTools alias for better naming
- ✅ Fixed: Tools status persists when switching providers (Bug #1)
- ✅ Fixed: Gemini tool call JSON parsing with nested braces (Bug #2)

**Key Changes (from v1.11.2.1 - Autorouter Fix):**
- ✅ Fixed: Provider mismatch in autorouter causing 404 errors
- ✅ All 7 coding command handlers now pass current provider parameter

---

## What's New

### 1. Configurable Default Provider

**Before:** Default provider was hardcoded to "perplexity" in `ppxai/commands.py`

```python
# ❌ OLD - Hardcoded default
self.provider = provider or "perplexity"
self.base_url = base_url or "https://api.perplexity.ai"
```

**After:** Default provider is now configurable via environment variable or falls back to first available provider

```python
# ✅ NEW - Configurable default
from ppxai.config import get_default_provider, get_base_url
actual_provider = provider or get_default_provider()
self.provider = actual_provider
self.base_url = base_url or get_base_url(actual_provider)
```

**Configuration:**
```bash
# .env
DEFAULT_PROVIDER=gemini  # Or perplexity, openai, etc.
```

**Fallback Order:**
1. `DEFAULT_PROVIDER` environment variable
2. First available provider from config
3. Falls back to "perplexity"

**Files Changed:**
- `ppxai/config.py` - Added `get_default_provider()` function
- `ppxai/commands.py` - Use configurable default instead of hardcoded
- `.env.example` - Document `DEFAULT_PROVIDER` option

---

### 2. Provider-Specific Pricing Function

**Before:** `MODEL_PRICING` global hardcoded to Perplexity pricing

```python
# ❌ OLD - Hardcoded to perplexity
MODEL_PRICING = BUILTIN_PROVIDERS["perplexity"]["pricing"]
```

**After:** New `get_model_pricing(provider)` function for any provider

```python
# ✅ NEW - Provider-specific pricing
from ppxai.config import get_model_pricing

# Get pricing for current provider
pricing = get_model_pricing(provider)

# Or get pricing for specific provider
perplexity_pricing = get_model_pricing("perplexity")
gemini_pricing = get_model_pricing("gemini")
```

**Files Changed:**
- `ppxai/config.py` - Added `get_model_pricing(provider)` function
- Backward compatible: `MODEL_PRICING` global still exists

---

### 3. AIClientWithTools Alias

**Issue:** Class named `PerplexityClientPromptTools` but works with ALL providers (confusing!)

**Solution:** Added `AIClientWithTools` alias with updated documentation

```python
# Both names now supported for backward compatibility
from perplexity_tools_prompt_based import PerplexityClientPromptTools  # ✅ Works (legacy)
from perplexity_tools_prompt_based import AIClientWithTools            # ✅ Works (recommended)

# They're the same class
assert AIClientWithTools is PerplexityClientPromptTools  # True
```

**Documentation Updated:**
```python
class PerplexityClientPromptTools:
    """
    AI client with prompt-based tool support (works with ALL providers).

    NOTE: Despite the name "PerplexityClient", this class works with ALL AI providers
    (Perplexity, Gemini, OpenAI, OpenRouter, Ollama, etc.) - the name is historical.

    For new code, consider using the AIClientWithTools alias (v1.11.3+).
    """
```

**Files Changed:**
- `perplexity_tools_prompt_based.py` - Updated docstring and added alias

---

## Bug Fixes (from bugfix/gemini-tool-calling)

### Bug #1: Tools Status Not Persisting When Switching Providers

**Symptom:**
```
1. Enable tools on Perplexity: /tools enable
2. Status shows: [Perplexity AI | Sonar Pro | Tools: ON] ✅
3. Switch provider: /provider gemini
4. Status shows: [Google Gemini | ... | Tools: OFF] ❌ BUG!
```

**Root Cause:** `handle_provider()` didn't check if tools were enabled before switching

**Fix:** Added tools persistence logic in `ppxai/commands.py` (lines 388-420)

```python
# BUGFIX: Check if tools are currently enabled before switching
tools_were_enabled = isinstance(self.client, self.PerplexityClientPromptTools) \
    if self.PerplexityClientPromptTools else False

# ... provider switching logic ...

# BUGFIX: Re-enable tools if they were enabled before switching
if tools_were_enabled:
    console.print("[dim]Re-enabling tools for new provider...[/dim]")
    self._enable_tools()
```

**Impact:**
- ✅ Tools now persist across provider switches
- ✅ Consistent UX across all providers

---

### Bug #2: Gemini Tool Call JSON Parsing Failing on Nested Braces

**Symptom:**
```json
You: /convert @/tmp/hello_world.R to Python and run it

Gemini: (shows raw JSON instead of executing!)
{
  "tool": "execute_shell_command",
  "arguments": {
    "command": "printf 'print(\"Hello\")' > /tmp/hello.py && python3 /tmp/hello.py",
    "working_dir": "/tmp"
  }
}
```

**Root Cause:** Regex pattern `r'\{\s*"tool"\s*:\s*"[^"]+"\s*[^}]*\}'` only matched to first `}`, breaking on nested `arguments` object

**Fix:** Extract JSON using first/last brace positions in `perplexity_tools_prompt_based.py` (lines 1054-1083)

```python
# BUGFIX: Extract JSON with nested braces (Gemini compatibility)
first_brace = text.find('{')
last_brace = text.rfind('}')

if first_brace != -1 and last_brace != -1 and first_brace < last_brace:
    json_candidate = text[first_brace:last_brace+1]
    try:
        data = json.loads(json_candidate)
        if isinstance(data, dict) and "tool" in data:
            normalized = normalize_tool_call(data)
            if normalized:
                return normalized
    except json.JSONDecodeError:
        pass
```

**Impact:**
- ✅ Gemini tool calls now execute correctly
- ✅ Handles nested JSON in tool arguments
- ✅ Works with all providers (Perplexity, OpenAI, OpenRouter, Ollama)

---

## Test Results

**All Tests Passing:** 4/4 new regression tests + existing test suite

```bash
$ uv run pytest tests/test_provider_tools_bugfixes.py -v

tests/test_provider_tools_bugfixes.py::TestProviderSwitchingToolsPersistence::test_provider_switching_fix_documented PASSED
tests/test_provider_tools_bugfixes.py::TestGeminiToolCallParsing::test_parse_gemini_nested_json_tool_call PASSED
tests/test_provider_tools_bugfixes.py::TestGeminiToolCallParsing::test_parse_tool_call_in_code_block PASSED
tests/test_provider_tools_bugfixes.py::TestGeminiToolCallParsing::test_parse_tool_call_simple_no_nested_args PASSED

============================== 4 passed in 0.94s ==============================
```

**Manual Testing:**
1. ✅ Tools persist when switching Perplexity → Gemini
2. ✅ Gemini tool calls execute correctly (no raw JSON)
3. ✅ Works with all providers (Perplexity, Gemini, OpenAI, OpenRouter)

---

## Documentation Added

1. **[BUGFIX-gemini-tool-calling.md](BUGFIX-gemini-tool-calling.md)** - Comprehensive bug analysis
2. **[PROVIDER-TOOLS-COMPATIBILITY.md](PROVIDER-TOOLS-COMPATIBILITY.md)** - How tools work across providers
3. **[PROVIDER-ABSTRACTION-REFACTORING.md](PROVIDER-ABSTRACTION-REFACTORING.md)** - Refactoring analysis and recommendations

---

## Files Changed

**Configuration & Defaults:**
- `ppxai/config.py` - Added `get_default_provider()` and `get_model_pricing(provider)`
- `ppxai/commands.py` - Use configurable default provider
- `.env.example` - Document `DEFAULT_PROVIDER` option

**Bug Fixes:**
- `ppxai/commands.py` - Tools persistence when switching providers (lines 388-420)
- `perplexity_tools_prompt_based.py` - Gemini JSON parsing fix (lines 1054-1083)

**Class Naming:**
- `perplexity_tools_prompt_based.py` - Updated docstring, added `AIClientWithTools` alias

**Version Updates:**
- `pyproject.toml` - v1.11.3
- `ppxai/__init__.py` - v1.11.3
- `vscode-extension/package.json` - v1.11.3 (version + activitybar title)
- `ROADMAP.md` - Current Release v1.11.3, Last Updated Dec 24 2025
- `README.md` - VSIX filename references updated

**Tests:**
- `tests/test_provider_tools_bugfixes.py` - 4 new regression tests

**Documentation:**
- `docs/BUGFIX-gemini-tool-calling.md` - Bug analysis
- `docs/PROVIDER-TOOLS-COMPATIBILITY.md` - Provider tools guide
- `docs/PROVIDER-ABSTRACTION-REFACTORING.md` - Refactoring analysis
- `docs/RELEASE-NOTES-v1.11.3.md` - This file

---

## Migration Guide

### For Users

**No breaking changes!** Everything works as before.

**Optional:** Set a custom default provider:
```bash
# .env
DEFAULT_PROVIDER=gemini  # Start with Gemini instead of Perplexity
```

**Benefit:** Tools now work correctly with Gemini and persist across provider switches!

### For Developers

**Recommended:** Use new functions instead of hardcoded defaults:

```python
# ✅ GOOD - Use new functions
from ppxai.config import get_default_provider, get_model_pricing

provider = get_default_provider()  # Configurable!
pricing = get_model_pricing(provider)  # Provider-specific!

# ⚠️ OK but discouraged - Old globals still work
from ppxai.config import MODEL_PRICING  # Hardcoded to perplexity
```

**Recommended:** Use `AIClientWithTools` alias for new code:

```python
# ✅ GOOD - Clear name
from perplexity_tools_prompt_based import AIClientWithTools

client = AIClientWithTools(api_key, base_url, provider="gemini")

# ⚠️ OK but confusing - Legacy name
from perplexity_tools_prompt_based import PerplexityClientPromptTools

client = PerplexityClientPromptTools(api_key, base_url, provider="gemini")  # Works but confusing!
```

---

## Known Issues

None. All issues from v1.11.2.1 resolved.

---

## Upgrade Instructions

### From v1.11.2.1:

```bash
# Pull latest
git pull origin master
git checkout v1.11.3

# Update dependencies (no changes, but good practice)
uv sync

# Run tests to verify
uv run pytest tests/ -v

# Optional: Set custom default provider
echo "DEFAULT_PROVIDER=gemini" >> .env
```

### VSCode Extension:

```bash
# Download new VSIX
curl -L -o ppxai-1.11.3.vsix \
  https://github.com/rcconsult/ppxai/releases/download/v1.11.3/ppxai-1.11.3.vsix

# Install
code --install-extension ppxai-1.11.3.vsix
```

---

## What's Next

**v1.12.0 (Minor Release)** - Full deprecation path:
- Deprecation warnings for `PerplexityClientPromptTools` (suggests `AIClientWithTools`)
- Enhanced provider abstraction (remove remaining hardcoded references)
- Improved error messages with provider context

**v1.11.3+ (Agentic Workflow)** - Planned features:
- @git context provider
- @tree context provider
- /agent command for autonomous tasks

---

**Commits:**
1. `5ffdc4c` - fix: Two critical TUI bugfixes - tools status persistence + Gemini tool parsing
2. `398aef5` - test: Add regression tests for provider tools bugfixes
3. `3fb37e0` - docs: Add provider abstraction refactoring analysis
4. `[current]` - feat: v1.11.2.2 - Foundation refactoring for provider abstraction

**Released:** December 24, 2025
**Branch:** bugfix/gemini-tool-calling → master
**Tag:** v1.11.2.2
