# Release Plan: v1.13.x Series

**Created:** January 3, 2026
**Last Updated:** January 3, 2026
**Status:** v1.13.0 Released
**Branch:** `master`

---

## Theme: Session Bootstrap

**Tagline:** Reproducible starting point for every session

## Overview

The v1.13.x series introduces "Session Bootstrap" - the ability to automatically load project-specific context (instructions, rules, coding standards) from AGENTS.md or CLAUDE.md files. This enables:

- **Teams:** Share project context via version control
- **Consistency:** Same AI behavior across all team members
- **Zero friction:** Works automatically, no configuration needed

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     User Message                             │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                   EngineClient                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  _bootstrap_context: str (cached)                    │   │
│  │  _bootstrap_sources: List[str]                       │   │
│  │                                                       │   │
│  │  load_bootstrap_context() ──────────────────────────┼───┤
│  │  get_bootstrap_status() → {loaded, sources, chars}  │   │
│  │  _build_system_messages() ──────────┐               │   │
│  └─────────────────────────────────────┼───────────────┘   │
│                                        │                     │
│                                        ▼                     │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              System Prompt                           │   │
│  │  ┌───────────────────────────────────────────────┐  │   │
│  │  │ PROJECT CONTEXT:                               │  │   │
│  │  │ {bootstrap_context from AGENTS.md}             │  │   │
│  │  │                                                 │  │   │
│  │  │ ---                                             │  │   │
│  │  │                                                 │  │   │
│  │  │ TOOLS:                                          │  │   │
│  │  │ {tool_prompt from ToolManager}                  │  │   │
│  │  └───────────────────────────────────────────────┘  │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                 ContextInjector                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  find_bootstrap_files() → List[Path]                 │   │
│  │                                                       │   │
│  │  Search order:                                        │   │
│  │  1. ~/.ppxai/AGENTS.md (global)                      │   │
│  │  2. {project_root}/AGENTS.md                         │   │
│  │  3. {cwd}/AGENTS.md                                  │   │
│  │                                                       │   │
│  │  Priority: AGENTS.md > CLAUDE.md                     │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## Release Schedule

### v1.13.0 - Custom Provider Parity ✅ RELEASED

**Released:** January 3, 2026

**Actual v1.13.0 Scope:**
- Premium web search tool for custom providers (vLLM, Ollama)
- Priority fallback: Perplexity Sonar → Gemini Grounding → DuckDuckGo
- SSL_VERIFY environment variable for corporate proxy support
- `native_tool_calling` capability for vLLM endpoints
- `ToolUsage` dataclass for per-tool usage tracking
- Enhanced tool parsing with dispatcher pattern
- 525 tests passing (119 new tests)

See [RELEASE-NOTES-v1.13.0.md](RELEASE-NOTES-v1.13.0.md) for full details.

---

### v1.13.1 - Installation & Server Control (Planned)

**Goal:** Frictionless installation and VSCode server management

#### Features

| Feature | Description |
|---------|-------------|
| `install.sh` | curl+bash installer for TUI and server binaries |
| VSCode Server Badge | Click to start/stop ppxai-server from extension |
| Terminal Integration | Server runs in VSCode terminal with output visible |
| Installation Guide | Comprehensive docs/INSTALLATION.md |

#### Installation Script (`install.sh`)

```bash
# One-line install
curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash

# Options
--version VERSION    # Specific version (default: latest)
--with-extension     # Also download VSCode VSIX
--server-only        # Only ppxai-server
--install-dir DIR    # Custom directory (default: ~/.local/bin)
```

#### VSCode Server Control

- **Server Badge** - Shows connection status (Connected/Disconnected/Connecting)
- **Click to Toggle** - Start or stop server directly from the UI
- **Terminal Output** - Server runs in named terminal for visibility
- **Auto-Reconnect** - Re-initializes after server starts

#### New Commands (package.json)

```json
"ppxai.startServer"  - Start ppxai-server in terminal
"ppxai.stopServer"   - Stop ppxai-server
"ppxai.toggleServer" - Toggle server state
"ppxai.serverStatus" - Show server status
```

#### Files Changed

| File | Changes |
|------|---------|
| `install.sh` | NEW - curl+bash installer |
| `docs/INSTALLATION.md` | NEW - Installation guide |
| `extension.ts` | Server terminal management, commands |
| `chatPanel.ts` | Server badge, status updates |
| `httpClient.ts` | `getBaseUrl()` method |
| `package.json` | Server control commands |
| `README.md` | Updated quick start with curl+bash |

---

### v1.13.2 - AGENTS.md Support (Core)

**Goal:** Load project context from working directory

| Feature | File | Description |
|---------|------|-------------|
| `find_bootstrap_files()` | `ppxai/engine/context.py` | Discover AGENTS.md/CLAUDE.md |
| `load_bootstrap_context()` | `ppxai/engine/client.py` | Load and cache content |
| `_build_system_messages()` | `ppxai/engine/client.py` | Inject into system prompt |
| `get_bootstrap_status()` | `ppxai/engine/client.py` | Status API for UI |

**Test Cases:**
```python
# tests/test_bootstrap_context.py

def test_finds_agents_md_in_working_dir():
    """AGENTS.md in cwd should be discovered."""
    with temp_dir() as d:
        (d / "AGENTS.md").write_text("Project rules")
        injector = ContextInjector(working_dir=str(d))
        files = injector.find_bootstrap_files()
        assert len(files) == 1
        assert files[0].name == "AGENTS.md"

def test_finds_claude_md_as_fallback():
    """CLAUDE.md used when no AGENTS.md exists."""
    with temp_dir() as d:
        (d / "CLAUDE.md").write_text("Claude instructions")
        injector = ContextInjector(working_dir=str(d))
        files = injector.find_bootstrap_files()
        assert len(files) == 1
        assert files[0].name == "CLAUDE.md"

def test_agents_md_takes_priority():
    """When both exist, AGENTS.md wins."""
    with temp_dir() as d:
        (d / "AGENTS.md").write_text("Agents rules")
        (d / "CLAUDE.md").write_text("Claude rules")
        injector = ContextInjector(working_dir=str(d))
        files = injector.find_bootstrap_files()
        assert len(files) == 1
        assert files[0].name == "AGENTS.md"

def test_context_injected_into_system_prompt():
    """Bootstrap context appears in messages sent to LLM."""
    with temp_dir() as d:
        (d / "AGENTS.md").write_text("Always use TypeScript")
        engine = EngineClient(working_dir=str(d))
        messages = engine._build_system_messages()
        assert "Always use TypeScript" in messages[0].content

def test_context_cached_between_chat_calls():
    """Context is loaded once, not on every chat."""
    with temp_dir() as d:
        (d / "AGENTS.md").write_text("Rules")
        engine = EngineClient(working_dir=str(d))
        engine.load_bootstrap_context()
        # Modify file - should NOT be reflected
        (d / "AGENTS.md").write_text("New rules")
        assert "Rules" in engine._bootstrap_context
        assert "New rules" not in engine._bootstrap_context

def test_no_bootstrap_file_is_fine():
    """Missing bootstrap files should not cause errors."""
    with temp_dir() as d:
        engine = EngineClient(working_dir=str(d))
        engine.load_bootstrap_context()
        assert engine._bootstrap_context is None
        assert engine._bootstrap_sources == []
```

### v1.13.3 - File Precedence

**Goal:** Support global, project, and subdirectory contexts

| Feature | Description |
|---------|-------------|
| Global context | Load from `~/.ppxai/AGENTS.md` |
| Project context | Load from git root AGENTS.md |
| Subdirectory context | Load from cwd AGENTS.md |
| Merge strategy | Concatenate with separator |

**Precedence Order:**
```
1. ~/.ppxai/AGENTS.md          (global defaults)
2. {git_root}/AGENTS.md        (project-specific)
3. {cwd}/AGENTS.md             (subdirectory overrides)
```

**Merge Behavior:**
```python
def _merge_contexts(self, files: List[Path]) -> str:
    """Merge multiple context files."""
    contents = []
    for f in files:
        content = f.read_text(errors='replace')
        source = str(f)
        contents.append(f"<!-- Source: {source} -->\n{content}")
    return "\n\n---\n\n".join(contents)
```

**Test Cases:**
```python
def test_global_context_loaded():
    """~/.ppxai/AGENTS.md is loaded."""

def test_project_root_detected():
    """Git root is correctly identified."""

def test_precedence_order():
    """Global + Project + Subdir are concatenated in order."""

def test_missing_intermediate_is_fine():
    """Works if only global and subdir exist, no project."""
```

### v1.13.4 - `/context` Commands

**Goal:** User control over loaded context

| Command | Description |
|---------|-------------|
| `/context show` | Display loaded sources and content preview |
| `/context reload` | Refresh from disk |
| `/context edit` | Open context file in editor |
| `/context clear` | Temporarily disable context |

**Files to Modify:**

| File | Changes |
|------|---------|
| `ppxai/commands.py` | Add `handle_context_command()` |
| `ppxai/common/commands.py` | Add to COMMANDS list |
| `ppxai/server/http.py` | Add `/context` endpoints |
| `vscode-extension/src/httpClient.ts` | Add context API |

**HTTP Endpoints:**
```
GET  /context         → {loaded, sources, char_count, preview}
POST /context/reload  → {success, sources}
POST /context/clear   → {success}
```

**TUI Output Example:**
```
/context show
Bootstrap Context:
  Sources:
    1. ~/.ppxai/AGENTS.md (1.2 KB)
    2. /project/AGENTS.md (3.4 KB)

  Total: 4.6 KB (~1,200 tokens)

  Preview:
  ─────────────────────────────
  <!-- Source: ~/.ppxai/AGENTS.md -->
  # Global Defaults
  - Use TypeScript for all new code
  - Follow ESLint rules
  ...
```

### v1.13.5 - Context Enhancements

**Goal:** Advanced context features

| Feature | Description |
|---------|-------------|
| Token count display | Show in status bar |
| Conditional sections | Provider-specific rules |
| Include directive | Reference other files |

**Conditional Syntax:**
```markdown
<!-- if provider:gemini -->
Use Google Search Grounding for real-time information.
Always cite sources from grounding results.
<!-- endif -->

<!-- if provider:perplexity -->
Cite sources using [1], [2] notation from citations array.
<!-- endif -->

<!-- if tools:enabled -->
Prefer using tools over asking the user for information.
<!-- endif -->
```

**Include Directive:**
```markdown
# Project Rules

<!-- include: ./docs/coding-standards.md -->
<!-- include: ./docs/api-conventions.md -->

## Additional Notes
...
```

## Implementation Checklist

### v1.13.0 ✅ RELEASED
- [x] Premium web search tool
- [x] SSL_VERIFY environment variable
- [x] `native_tool_calling` capability
- [x] `ToolUsage` dataclass
- [x] Enhanced tool parsing
- [x] 525 tests passing

### v1.13.1 (Current)
- [x] Create `install.sh` curl+bash installer
- [x] Add `--with-extension` option to download VSIX
- [x] Add VSCode server status badge
- [x] Add server start/stop via terminal
- [x] Add server control commands (start, stop, toggle, status)
- [x] Create `docs/INSTALLATION.md`
- [x] Update README.md quick start
- [ ] Test installation on clean machine
- [ ] Test VSCode server control

### v1.13.2
- [ ] Add `find_bootstrap_files()` to ContextInjector
- [ ] Add `_bootstrap_context` to EngineClient
- [ ] Add `load_bootstrap_context()` method
- [ ] Add `get_bootstrap_status()` method
- [ ] Modify `_build_system_messages()` to include context
- [ ] Call `load_bootstrap_context()` in `__init__`
- [ ] Call `load_bootstrap_context()` in `set_working_dir()`
- [ ] Create `tests/test_bootstrap_context.py`
- [ ] Update `/status` to show bootstrap info
- [ ] Test in TUI
- [ ] Test in VSCode extension

### v1.13.3
- [ ] Add global path search (`~/.ppxai/`)
- [ ] Add git root detection
- [ ] Implement merge strategy
- [ ] Add source tracking for each file
- [ ] Add tests for precedence

### v1.13.4
- [ ] Add `/context` command handler
- [ ] Implement `show` subcommand
- [ ] Implement `reload` subcommand
- [ ] Implement `edit` subcommand
- [ ] Implement `clear` subcommand
- [ ] Add tab autocomplete
- [ ] Add HTTP endpoints
- [ ] Update VSCode extension

### v1.13.5
- [ ] Add token counting
- [ ] Implement conditional parsing
- [ ] Implement include directive
- [ ] Add context size to status bar

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Large context files | Warn if > 50KB, truncate if > 100KB |
| Circular includes | Track visited files, max depth = 3 |
| Performance on startup | Cache aggressively, lazy load if needed |
| Security (code injection) | Context is instructions only, not executed |

## Success Metrics

- [ ] Existing CLAUDE.md in ppxai project is automatically loaded
- [ ] `/status` shows loaded context
- [ ] Context visible in system prompt sent to LLM
- [ ] No performance regression (< 50ms added to startup)
- [ ] Works identically in TUI and VSCode

---

## Future: Premium Web Search Tools (v1.13.4+)

**Status:** Research Complete (January 3, 2026)

### Overview

Upgrade the fallback web search tools to use premium APIs when available, providing higher-quality results with proper citations for providers without native web search (e.g., custom vLLM endpoints).

### Current Architecture

```
Provider with native search (Perplexity, Gemini)
    └── Uses built-in web search, tools excluded

Provider without native search (Custom vLLM, OpenAI)
    └── Falls back to DuckDuckGo scraping (free, no API key)
        └── Falls back to HTML scraping if ddg package fails
```

### Proposed Architecture

```
Provider without native search (Custom vLLM, OpenAI)
    ├── IF PERPLEXITY_API_KEY set → Use Perplexity Sonar API
    ├── ELIF GEMINI_API_KEY set → Use Gemini + Google Search Grounding
    └── ELSE → Free DuckDuckGo (existing fallback)
```

### Research Findings

#### 1. Perplexity Search via Sonar API

**Discovery:** Perplexity's "online" models (`sonar`, `sonar-pro`) have built-in web search. The same API key used for chat works for search.

**API Format:** Standard OpenAI-compatible chat completion

```python
# POST https://api.perplexity.ai/chat/completions
{
  "model": "sonar",  # Cheapest online model
  "messages": [{"role": "user", "content": "search query"}]
}

# Response includes:
# - choices[0].message.content  → Answer with synthesized info
# - citations                   → List of source URLs
```

**Pricing (per 1M tokens):**
| Model | Input | Output |
|-------|-------|--------|
| sonar | $0.20 | $0.20 |
| sonar-pro | $3.00 | $15.00 |

**Implementation Effort:** Low - Reuse existing OpenAI SDK

**Source:** [OpenWebUI Perplexity Tool](https://openwebui.com/t/abhiactually/perplexity)

#### 2. Google Search via Gemini API + Search Grounding

**Discovery:** Gemini API supports "Grounding with Google Search" - a tool that lets any Gemini model access real-time Google Search results.

**API Format:** Gemini-native with `google_search` tool

```python
from google import genai

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
response = client.models.generate_content(
    model="gemini-2.0-flash",
    contents="What is the weather in NYC?",
    config={
        "tools": [{"google_search": {}}]
    }
)

# Response includes groundingMetadata:
# - webSearchQueries: ["weather NYC"]
# - groundingChunks: [{uri, title}, ...]
# - groundingSupports: [{text, groundingChunkIndices}, ...]
```

**Pricing (as of Jan 2026):**
- Gemini 3 models: **$14 per 1,000 search queries** (per-query billing)
- Gemini 2.5 and older: **$35 per 1,000 prompts** (per-prompt billing)
- Token costs: Same as regular Gemini usage

**Advantage:** Users with only a Gemini API key get premium web search without a separate Perplexity account.

**Implementation Effort:** Medium - Requires Gemini SDK or REST API

**Sources:**
- [Grounding with Google Search - Gemini API](https://ai.google.dev/gemini-api/docs/google-search)
- [Google Developers Blog - Grounding Announcement](https://developers.googleblog.com/en/gemini-api-and-ai-studio-now-offer-grounding-with-google-search/)

### Proposed Configuration

```json
// ppxai-config.json
{
  "tools": {
    "web_search": {
      "preferred": "auto",       // "perplexity" | "gemini" | "duckduckgo" | "auto"
      "perplexity_model": "sonar",  // Cheapest online model
      "gemini_model": "gemini-2.0-flash"  // For grounding calls
    }
  }
}
```

**"auto" Selection Logic:**
1. If `PERPLEXITY_API_KEY` set → Use Perplexity Sonar (fastest, best citations)
2. Elif `GEMINI_API_KEY` set → Use Gemini + Google Search Grounding
3. Else → Free DuckDuckGo fallback

### Implementation Plan

#### File: `ppxai/engine/tools/builtin/web_premium.py` (NEW)

```python
"""Premium web search tools using external APIs."""

import os
from typing import Optional, Tuple, List

async def web_search_perplexity(query: str, num_results: int = 5) -> Tuple[str, List[str]]:
    """Search web using Perplexity Sonar API.

    Returns:
        Tuple of (answer_text, list_of_citation_urls)
    """
    from openai import AsyncOpenAI

    api_key = os.getenv("PERPLEXITY_API_KEY")
    if not api_key:
        raise ValueError("PERPLEXITY_API_KEY not set")

    client = AsyncOpenAI(
        api_key=api_key,
        base_url="https://api.perplexity.ai"
    )

    response = await client.chat.completions.create(
        model="sonar",
        messages=[{"role": "user", "content": query}]
    )

    content = response.choices[0].message.content
    # Perplexity returns citations in response object
    citations = getattr(response, 'citations', [])[:num_results]

    return content, citations


async def web_search_gemini(query: str, num_results: int = 5) -> Tuple[str, List[str]]:
    """Search web using Gemini + Google Search Grounding.

    Returns:
        Tuple of (answer_text, list_of_citation_urls)
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not set")

    # Use REST API for simplicity (avoids extra google-genai dependency)
    import httpx

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

    payload = {
        "contents": [{"parts": [{"text": query}]}],
        "tools": [{"google_search": {}}]
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            params={"key": api_key},
            json=payload
        )
        resp.raise_for_status()
        data = resp.json()

    # Extract content and grounding metadata
    content = data["candidates"][0]["content"]["parts"][0]["text"]
    grounding = data["candidates"][0].get("groundingMetadata", {})

    citations = []
    for chunk in grounding.get("groundingChunks", [])[:num_results]:
        if "web" in chunk:
            citations.append(chunk["web"]["uri"])

    return content, citations


def get_premium_search_provider() -> Optional[str]:
    """Determine which premium search provider is available.

    Returns:
        "perplexity", "gemini", or None if no premium provider available
    """
    if os.getenv("PERPLEXITY_API_KEY"):
        return "perplexity"
    elif os.getenv("GEMINI_API_KEY"):
        return "gemini"
    return None


async def web_search_premium(query: str, num_results: int = 5) -> str:
    """Search web using best available premium provider.

    Falls back gracefully if premium providers unavailable.
    """
    provider = get_premium_search_provider()

    try:
        if provider == "perplexity":
            content, citations = await web_search_perplexity(query, num_results)
        elif provider == "gemini":
            content, citations = await web_search_gemini(query, num_results)
        else:
            # Fall back to existing DuckDuckGo
            from . import web
            return web.web_search(query, num_results)

        # Format result with sources
        result = f"{content}\n\nSources:\n"
        for url in citations:
            result += f"- {url}\n"
        return result

    except Exception as e:
        # Fall back to DuckDuckGo on any error
        from . import web
        return web.web_search(query, num_results)


def register_tools(manager, provider=None):
    """Register premium web search if API keys available."""
    # Skip for providers with native search
    if provider in ["perplexity", "gemini"]:
        return

    premium_provider = get_premium_search_provider()

    if premium_provider:
        description = f"Search the web using {premium_provider.title()} AI"
        manager.register_function(
            name="web_search",
            func=web_search_premium,
            description=description,
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "num_results": {"type": "integer", "default": 5}
                },
                "required": ["query"]
            },
            provider_excluded=["perplexity", "gemini"]
        )
    else:
        # Fall back to existing free search
        from . import web
        web.register_tools(manager, provider)
```

### Cost Comparison

| Provider | Cost per Search | Quality | Citations |
|----------|-----------------|---------|-----------|
| DuckDuckGo | Free | Basic | No |
| Perplexity Sonar | ~$0.001 | Excellent | Yes |
| Gemini Grounding | $0.014 | Excellent | Yes |

### Implementation Checklist

**Core Premium Search:**
- [ ] Create `ppxai/engine/tools/builtin/web_premium.py`
- [ ] Add `web_search_perplexity()` function
- [ ] Add `web_search_gemini()` function
- [ ] Add `get_premium_search_provider()` helper
- [ ] Update `__init__.py` to call premium registration first
- [ ] Add config support for `tools.web_search.preferred`
- [ ] Add tests with mocked API responses
- [ ] Update `/tools status` to show search provider
- [ ] Document in CLAUDE.md

**Usage Metrics Integration:**
- [ ] Add `ToolUsage` dataclass to `ppxai/engine/types.py`
- [ ] Extend `UsageStats` with `tool_calls` dict
- [ ] Track tool usage in `EngineClient._execute_tool()`
- [ ] Return usage from premium search functions
- [ ] Update `usage_persistence.py` to store tool usage
- [ ] Update `/usage` command to show tool breakdown
- [ ] Update `/usage report` to aggregate tool costs
- [ ] Add tool pricing config section to `ppxai-config.json`
- [ ] Update HTTP `/usage` endpoint with tool data
- [ ] Update VSCode extension usage badge
- [ ] Add tests for tool usage tracking and cost calculation

### Test Cases

```python
# tests/test_web_premium.py

def test_perplexity_search_priority():
    """Perplexity used when API key set."""
    with patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"}):
        assert get_premium_search_provider() == "perplexity"

def test_gemini_search_fallback():
    """Gemini used when only Gemini key set."""
    with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True):
        assert get_premium_search_provider() == "gemini"

def test_duckduckgo_when_no_keys():
    """DuckDuckGo used when no API keys."""
    with patch.dict(os.environ, {}, clear=True):
        assert get_premium_search_provider() is None

def test_perplexity_citations_extracted():
    """Perplexity response includes citations."""
    # Mock Perplexity API response with citations

def test_gemini_grounding_metadata_extracted():
    """Gemini grounding chunks converted to citations."""
    # Mock Gemini response with groundingMetadata

def test_fallback_on_api_error():
    """Falls back to DuckDuckGo on API failure."""
    # Mock Perplexity returning error
```

### User Experience

**Before (Custom vLLM with tools):**
```
> What's the current weather in NYC?
[web_search] Searching: "weather NYC"
[Result from DuckDuckGo HTML scraping - no sources]
```

**After (Custom vLLM with Perplexity key):**
```
> What's the current weather in NYC?
[web_search via Perplexity] Searching: "weather NYC"
Current weather in NYC is 45°F, partly cloudy...

Sources:
- https://weather.com/weather/today/l/New+York+NY
- https://www.accuweather.com/en/us/new-york/10007
```

### Usage Metrics Updates

Premium web search calls need to be tracked separately from main model usage since they:
1. Use different providers (may use Perplexity for search while main model is vLLM)
2. Have different pricing structures (per-query vs per-token)
3. Should be visible in `/usage` reports for cost awareness

#### Data Model Changes

```python
# ppxai/engine/types.py - Extend UsageStats

@dataclass
class UsageStats:
    # Existing fields
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    # NEW: Tool usage tracking
    tool_calls: Dict[str, ToolUsage] = field(default_factory=dict)

@dataclass
class ToolUsage:
    """Track usage for a specific tool."""
    call_count: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    provider: str = ""  # "perplexity", "gemini", "duckduckgo"
```

#### `/usage` Command Output

```
/usage

Session Usage:
  Main Model: custom/openai/gpt-oss-120b
    Tokens: 12.5K in / 3.2K out
    Cost: $0.00 (self-hosted)

  Tools:
    web_search (via Perplexity):
      Calls: 5
      Tokens: 1.2K in / 2.8K out
      Cost: $0.0012

  Total Session Cost: $0.0012
```

#### `/usage report` Output

```
/usage report 24h

Usage Report (Last 24 hours):

  By Provider:
    custom (vLLM): 45.2K tokens, $0.00
    perplexity (web_search): 8.5K tokens, $0.0034

  By Tool:
    web_search: 12 calls, $0.0034
    shell: 8 calls (free)
    read_file: 23 calls (free)

  Total: $0.0034
```

#### Implementation Changes

| File | Changes |
|------|---------|
| `ppxai/engine/types.py` | Add `ToolUsage` dataclass |
| `ppxai/engine/client.py` | Track tool usage in `_execute_tool()` |
| `ppxai/usage_persistence.py` | Store/aggregate tool usage data |
| `ppxai/commands.py` | Update `/usage` command formatting |
| `ppxai/server/http.py` | Include tool usage in `/usage` endpoint |
| `vscode-extension/` | Display tool costs in usage badge |

#### Pricing Configuration

```json
// ppxai-config.json
{
  "tools": {
    "web_search": {
      "preferred": "auto",
      "perplexity_model": "sonar",
      "gemini_model": "gemini-2.0-flash",
      "pricing": {
        "perplexity": {"input": 0.20, "output": 0.20},
        "gemini_grounding": {"per_query": 14.00}
      }
    }
  }
}
```

#### Test Cases

```python
# tests/test_usage_tools.py

def test_tool_usage_tracked():
    """Premium search usage appears in stats."""
    engine = EngineClient()
    engine.set_provider("custom")
    engine.enable_tools()

    # Simulate web search call
    await engine._execute_tool("web_search", {"query": "test"})

    stats = engine.get_usage_stats()
    assert "web_search" in stats.tool_calls
    assert stats.tool_calls["web_search"].call_count == 1

def test_tool_cost_calculation():
    """Tool costs calculated correctly."""
    usage = ToolUsage(
        call_count=5,
        tokens_in=1000,
        tokens_out=2000,
        provider="perplexity"
    )
    # Perplexity: $0.20/1M in, $0.20/1M out
    expected_cost = (1000 * 0.20 / 1_000_000) + (2000 * 0.20 / 1_000_000)
    assert usage.calculate_cost() == pytest.approx(expected_cost)

def test_gemini_grounding_per_query_billing():
    """Gemini grounding uses per-query pricing."""
    usage = ToolUsage(
        call_count=3,
        provider="gemini"
    )
    # Gemini: $14/1000 queries = $0.014 per query
    expected_cost = 3 * 0.014
    assert usage.calculate_cost() == pytest.approx(expected_cost)

def test_usage_report_includes_tools():
    """Usage report shows tool breakdown."""
    report = get_usage_report("24h")
    assert "tools" in report
    assert "web_search" in report["tools"]
```

---

## References

- [Claude Code CLAUDE.md format](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/memory)
- [v1.11.0 Agentic Workflow Plan](v1.11.0-agentic-workflow-plan.md)
- [ROADMAP.md v1.13.x section](../ROADMAP.md)
- [OpenWebUI Perplexity Tool](https://openwebui.com/t/abhiactually/perplexity)
- [Grounding with Google Search - Gemini API](https://ai.google.dev/gemini-api/docs/google-search)
- [Google Developers Blog - Grounding Announcement](https://developers.googleblog.com/en/gemini-api-and-ai-studio-now-offer-grounding-with-google-search/)
- [Gemini API Pricing](https://ai.google.dev/gemini-api/docs/pricing)
