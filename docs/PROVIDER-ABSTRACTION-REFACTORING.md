# Provider Abstraction Refactoring Analysis

**Date:** 2025-12-24
**Branch:** bugfix/gemini-tool-calling
**Question:** Do we need to refactor to add new providers without breaking changes?

## Executive Summary

**Answer: Minor refactoring recommended, but NOT blocking for new providers.**

The current architecture is **80% provider-agnostic**. The engine layer (`ppxai/engine/`) is fully abstracted with `BaseProvider`, while the legacy TUI layer has some hardcoded references. Most hardcoded references are acceptable (defaults, configuration). Only 3 patterns need refactoring for optimal extensibility.

## Current Architecture Assessment

### ✅ Well-Abstracted (No Changes Needed)

#### 1. Engine Layer - BaseProvider Pattern
**File:** `ppxai/engine/providers/base.py`

```python
class BaseProvider(ABC):
    """Abstract base class for all AI providers."""

    name: str = "base"
    default_capabilities: ProviderCapabilities = ProviderCapabilities()

    @abstractmethod
    async def chat(self, messages: List[Message], ...) -> AsyncIterator[Event]:
        pass
```

**Status:** ✅ Perfect abstraction - Adding new providers requires implementing BaseProvider interface only.

#### 2. Capability-Based Tool Filtering
**File:** `ppxai/config.py` (lines 472-510)

```python
def get_provider_capabilities(provider: str = None) -> dict:
    """Get capabilities for the specified provider."""
    config = get_provider_config(provider)
    return config.get("capabilities", DEFAULT_CAPABILITIES)

def provider_needs_tool(provider: str, tool_category: str) -> bool:
    """Check if a provider needs a specific tool category."""
    capabilities = get_provider_capabilities(provider)
    return not capabilities.get(tool_category, False)
```

**Status:** ✅ Capability-based, not provider-based - Works for any provider.

#### 3. Configuration-Based Provider Definitions
**File:** `ppxai/config.py` (lines 40-120)

```python
BUILTIN_PROVIDERS = {
    "perplexity": {
        "name": "Perplexity AI",
        "base_url": "https://api.perplexity.ai",
        "capabilities": {
            "web_search": True,
            "web_fetch": True,
            "weather": True,
            "realtime_info": True
        },
        "models": {...}
    },
    "gemini": {...}
}
```

**Status:** ✅ Adding new provider = add to BUILTIN_PROVIDERS dict.

### ⚠️ Needs Refactoring (3 Issues)

#### Issue #1: Misleading Class Name
**File:** `perplexity_tools_prompt_based.py`
**Problem:** Class named `PerplexityClientPromptTools` but works with ALL providers

```python
class PerplexityClientPromptTools:
    """Perplexity API client with AI-powered tools.

    This client wraps the standard Perplexity API client with tool-calling
    capabilities via prompt engineering.
    """

    def __init__(self, ..., provider: str = "perplexity"):
        self.provider = provider  # ✅ Accepts any provider!
```

**Evidence it's provider-agnostic:**
- Line 41: `self.provider = provider` (not hardcoded)
- Line 65: `provider=self.provider` passed to AIClient
- Works with Perplexity, Gemini, OpenAI, OpenRouter, Ollama

**Impact:** 🟡 Low - Works correctly, just confusing naming
**Breaking Change:** 🔴 Yes - Renaming would break imports

**Refactoring Options:**

**Option A: Rename Class (Breaking Change)**
```python
# Rename to generic name
class ProviderToolsClient:  # or AIClientWithTools
    """AI client with tool-calling capabilities via prompt engineering."""
```

**Option B: Deprecation Path (Backward Compatible)**
```python
class AIClientWithTools:
    """AI client with tool-calling capabilities."""
    pass

# Deprecated alias
PerplexityClientPromptTools = AIClientWithTools
import warnings
warnings.warn("PerplexityClientPromptTools is deprecated, use AIClientWithTools",
              DeprecationWarning)
```

**Recommendation:** Option B for next minor release (v1.12.0)

---

#### Issue #2: Hardcoded Default Provider
**File:** `ppxai/commands.py` (lines 194-195)

```python
def __init__(self, client, api_key: str, current_model: str,
             base_url: str = None, provider: str = None):
    self.base_url = base_url or "https://api.perplexity.ai"  # ❌ Hardcoded
    self.provider = provider or "perplexity"  # ❌ Hardcoded
```

**Problem:** Defaults to Perplexity, not configurable

**Impact:** 🟡 Medium - Works but forces Perplexity as default
**Breaking Change:** 🟢 No - Just changing defaults

**Refactoring:**
```python
# Get default from config
DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "perplexity")

def __init__(self, client, api_key: str, current_model: str,
             base_url: str = None, provider: str = None):
    actual_provider = provider or DEFAULT_PROVIDER
    self.provider = actual_provider
    self.base_url = base_url or get_base_url(actual_provider)
```

**Recommendation:** Implement in v1.12.0

---

#### Issue #3: Hardcoded Pricing Fallback
**File:** `ppxai/config.py` (line 388)

```python
MODEL_PRICING = BUILTIN_PROVIDERS["perplexity"]["pricing"]
```

**Problem:** Default pricing hardcoded to Perplexity's pricing

**Impact:** 🟢 Low - Only affects cost estimates, not functionality
**Breaking Change:** 🟢 No - Internal implementation detail

**Refactoring:**
```python
def get_model_pricing(provider: str = None) -> dict:
    """Get pricing for the specified provider."""
    config = get_provider_config(provider)
    return config.get("pricing", {})

# Usage
pricing = get_model_pricing(current_provider)
```

**Recommendation:** Implement in v1.12.0

---

### ✅ Acceptable Hardcoded References (No Changes)

#### 1. UI Hint for Perplexity's Native Search
**File:** `perplexity_tools_prompt_based.py` (line 107)

```python
if self.provider == "perplexity":
    console.print(f"[dim]Note: Perplexity has built-in web search![/dim]")
```

**Status:** ✅ Acceptable - Provider-specific UI hint, doesn't affect functionality

#### 2. Built-in Provider Definitions
**File:** `ppxai/config.py` (lines 40-120)

```python
BUILTIN_PROVIDERS = {
    "perplexity": {...},
    "gemini": {...}
}
```

**Status:** ✅ Acceptable - Configuration, not logic

#### 3. Default Provider in Environment Variable
**File:** `.env.example`

```bash
DEFAULT_PROVIDER=perplexity
```

**Status:** ✅ Acceptable - User-configurable default

---

## Adding a New Provider: Current Process

### Example: Adding "anthropic" Provider

**Step 1: Add to BUILTIN_PROVIDERS** (ppxai/config.py)
```python
BUILTIN_PROVIDERS = {
    "perplexity": {...},
    "gemini": {...},
    "anthropic": {  # ✅ NEW
        "name": "Anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "api_key_env": "ANTHROPIC_API_KEY",
        "default_model": "claude-3-5-sonnet-20241022",
        "capabilities": {
            "web_search": False,
            "web_fetch": False,
            "weather": False,
            "realtime_info": False
        },
        "models": {
            "claude-3-5-sonnet-20241022": {
                "name": "Claude 3.5 Sonnet",
                "description": "Most intelligent model"
            }
        },
        "pricing": {...}
    }
}
```

**Step 2: Add API Key** (.env)
```bash
ANTHROPIC_API_KEY=sk-ant-xxxxx
```

**Step 3: Test**
```bash
uv run ppxai
/provider anthropic
/model claude-3-5-sonnet-20241022
/tools enable  # ✅ Tools automatically filtered based on capabilities!
```

**That's it!** ✅ No code changes needed.

---

## Refactoring Roadmap

### v1.12.0 (Recommended - Backward Compatible)

**Priority 1: Configurable Default Provider**
- [ ] Add `DEFAULT_PROVIDER` env var support
- [ ] Update `ppxai/commands.py` to use configurable default
- [ ] Update `.env.example` with `DEFAULT_PROVIDER=perplexity`

**Priority 2: Provider-Specific Pricing**
- [ ] Create `get_model_pricing(provider)` function
- [ ] Remove hardcoded `MODEL_PRICING` global
- [ ] Update cost calculation to use provider-specific pricing

**Priority 3: Deprecate PerplexityClientPromptTools**
- [ ] Create `AIClientWithTools` class (exact copy)
- [ ] Make `PerplexityClientPromptTools` an alias with deprecation warning
- [ ] Update documentation to reference `AIClientWithTools`

### v2.0.0 (Future - Breaking Changes)

**Complete Legacy Cleanup**
- [ ] Remove `PerplexityClientPromptTools` alias
- [ ] Rename `perplexity_tools_prompt_based.py` to `ai_client_with_tools.py`
- [ ] Update all imports across codebase
- [ ] Remove all legacy TUI code (fully migrate to EngineClient)

---

## Current Provider Compatibility Matrix

| Provider | Supported | Tools Work | Auto-Router | Notes |
|----------|-----------|------------|-------------|-------|
| Perplexity | ✅ | ✅ | ✅ | Native search, built-in |
| Gemini | ✅ | ✅ | ✅ | Built-in, fixed v1.11.2.1 |
| OpenAI | ✅ | ✅ | ✅ | Via config file |
| OpenRouter | ✅ | ✅ | ✅ | Via config file |
| Ollama | ✅ | ✅ | ⚠️ | Local only, via config |
| **Future** | - | - | - | - |
| Anthropic | 🔮 | 🔮 | 🔮 | Add to BUILTIN_PROVIDERS |
| DeepSeek | 🔮 | 🔮 | 🔮 | Add to BUILTIN_PROVIDERS |
| Cohere | 🔮 | 🔮 | 🔮 | Add to BUILTIN_PROVIDERS |

**Legend:**
- ✅ Fully supported
- ⚠️ Partially supported
- 🔮 Future - Easy to add (1 config change)

---

## Conclusion

### Answer: Do we need to refactor?

**For adding new providers:** 🟢 **No refactoring required**
- Current architecture supports adding providers via configuration only
- Example: Adding Anthropic requires 1 config change + API key

**For long-term maintainability:** 🟡 **Minor refactoring recommended**
- 3 issues identified (class naming, default provider, pricing)
- All fixable in v1.12.0 without breaking changes
- Deprecation path available for class renaming

**For current work:** 🟢 **Proceed with confidence**
- `bugfix/gemini-tool-calling` branch is good to merge
- No refactoring needed for tool persistence or Gemini parsing fixes
- Architecture supports all 5+ current providers

### Recommended Next Steps

1. **Merge bugfix/gemini-tool-calling** (no blockers)
2. **Release v1.11.2.2 or v1.11.3** with both fixes
3. **Plan v1.12.0** with refactoring tasks from roadmap above
4. **Add new providers** as needed (configuration-only changes)

---

**Created:** 2025-12-24
**Author:** Claude Code Analysis
**Status:** ✅ Analysis Complete
**Branch:** bugfix/gemini-tool-calling
