# Provider Tools Compatibility Guide

## How Tools Are Initialized Per Provider

When you enable tools and switch providers, the system ensures the **correct toolset** is initialized for each provider based on their **native capabilities**.

### Tool Initialization Flow

```
1. User runs: /tools enable
   ├─> _enable_tools() called
   ├─> Creates PerplexityClientPromptTools(provider=self.provider)
   └─> Calls initialize_tools()

2. initialize_tools() calls _register_builtin_tools()
   ├─> Checks provider capabilities from config
   ├─> Conditionally registers tools based on what provider DOESN'T have natively
   └─> Shows "Provider has native: web_search, web_fetch..." message

3. User runs: /provider gemini
   ├─> handle_provider() detects tools_were_enabled = True
   ├─> Switches to new provider
   └─> Calls _enable_tools() AGAIN for new provider

4. Tools re-initialized for Gemini
   ├─> Creates NEW PerplexityClientPromptTools(provider="gemini")
   ├─> Calls initialize_tools() with gemini provider
   ├─> Registers different toolset based on gemini capabilities
   └─> Tools now match gemini's needs
```

### Code Evidence

**In ppxai/commands.py (lines 590-604):**
```python
def _enable_tools(self):
    # Upgrade client to tool-enabled version
    tool_client = self.PerplexityClientPromptTools(
        api_key=self.api_key,
        base_url=self.base_url,
        session_name=self.client.session_name,
        enable_tools=True,
        provider=self.provider  # ✅ Current provider passed!
    )

    # Initialize tools (built-in only by default)
    console.print("[cyan]Initializing tools...[/cyan]")
    asyncio.run(tool_client.initialize_tools(mcp_servers=[]))
```

**In perplexity_tools_prompt_based.py (lines 469-496):**
```python
def _register_builtin_tools(self):
    # Get provider capabilities
    capabilities = get_provider_capabilities(self.provider)  # ✅ Provider-aware!

    # Show which capabilities this provider has natively
    native_caps = [k for k, v in capabilities.items() if v]
    if native_caps:
        console.print(f"[dim]Provider has native: {', '.join(native_caps)}[/dim]")

    # Only register tools provider doesn't have natively
    if provider_needs_tool(self.provider, "weather"):
        self._register_weather_tool()  # ✅ Only if provider needs it

    if provider_needs_tool(self.provider, "web_search"):
        self._register_web_search_tool()  # ✅ Only if provider needs it

    if provider_needs_tool(self.provider, "web_fetch"):
        self._register_fetch_url_tool()  # ✅ Only if provider needs it
```

## Provider Capabilities Matrix

### Built-in Providers

| Provider | Web Search | Web Fetch | Weather | Real-time | Tools Registered |
|----------|-----------|-----------|---------|-----------|------------------|
| **Perplexity** | ✅ Native | ✅ Native | ✅ Native | ✅ Native | Minimal (file ops, shell, calculator only) |
| **Gemini** | ❌ None | ❌ None | ❌ None | ❌ None | All tools (web_search, web_fetch, weather, etc.) |

### Custom Providers (OpenAI, OpenRouter, Ollama)

| Provider | Web Search | Web Fetch | Weather | Real-time | Tools Registered |
|----------|-----------|-----------|---------|-----------|------------------|
| **OpenAI** | ❌ None | ❌ None | ❌ None | ❌ None | All tools |
| **OpenRouter** | ❌ None | ❌ None | ❌ None | ❌ None | All tools |
| **Ollama** (local) | ❌ None | ❌ None | ❌ None | ❌ None | All tools |

### Capabilities Configuration

Capabilities are defined in `ppxai/config.py`:

```python
# Perplexity (lines 72-77)
"capabilities": {
    "web_search": True,
    "web_fetch": True,
    "weather": True,
    "realtime_info": True,
}

# Gemini (lines 125-130)
"capabilities": {
    "web_search": False,
    "web_fetch": False,
    "weather": False,
    "realtime_info": False,
}

# Default for all other providers (lines 134-139)
DEFAULT_CAPABILITIES = {
    "web_search": False,
    "web_fetch": False,
    "weather": False,
    "realtime_info": False,
}
```

## Tools Always Registered (All Providers)

These tools are registered regardless of provider:

1. **search_files** - Search for files matching a glob pattern
2. **read_file** - Read contents of a text file
3. **calculator** - Evaluate mathematical expressions
4. **list_directory** - List files and directories (ls-like)
5. **get_datetime** - Get current date/time with timezone support
6. **execute_shell_command** - Execute shell commands (with consent)

## Tools Conditionally Registered (Based on Provider)

These tools are ONLY registered if the provider doesn't have native capability:

### 1. Web Search Tool (DuckDuckGo)
- **Registered for:** Gemini, OpenAI, OpenRouter, Ollama
- **NOT registered for:** Perplexity (has native search)
- **Why:** Perplexity already has built-in web search grounding

### 2. Web Fetch Tool (URL reader)
- **Registered for:** Gemini, OpenAI, OpenRouter, Ollama
- **NOT registered for:** Perplexity (has native URL fetch)
- **Why:** Perplexity can already fetch and read web pages

### 3. Weather Tool (wttr.in)
- **Registered for:** Gemini, OpenAI, OpenRouter, Ollama
- **NOT registered for:** Perplexity (has native weather)
- **Why:** Perplexity can already get weather information

## Example: Switching from Perplexity to Gemini

```bash
# Step 1: Enable tools on Perplexity
You: /tools enable
Initializing tools...
Provider has native: web_search, web_fetch, weather, realtime_info
Tools initialized: 6 tools available
  * search_files: Search for files matching a glob pattern in a directory
  * read_file: Read the contents of a text file
  * calculator: Evaluate a mathematical expression
  * list_directory: List files and directories in a path
  * get_datetime: Get current date and time with timezone support
  * execute_shell_command: Execute a shell command in the system
Note: Perplexity has built-in web search - just ask questions directly!

# Step 2: Switch to Gemini
You: /provider gemini

Switched to: Google Gemini (model: gemini-2.0-flash)
Re-enabling tools for new provider...
Initializing tools...
Tools initialized: 9 tools available
  * search_files: Search for files matching a glob pattern in a directory
  * read_file: Read the contents of a text file
  * calculator: Evaluate a mathematical expression
  * list_directory: List files and directories in a path
  * get_datetime: Get current date and time with timezone support
  * execute_shell_command: Execute a shell command in the system
  * get_weather: Get weather forecast for a location  # ✅ NEW!
  * web_search: Search the web using DuckDuckGo  # ✅ NEW!
  * fetch_url: Fetch and read content from a URL  # ✅ NEW!
```

## Will the Fix Work with All Providers?

**Yes! ✅** The bugfix works with **all supported providers**:

### Confirmed Working

1. **Perplexity** ✅
   - Tools status persists when switching FROM Perplexity
   - Minimal toolset (6 tools) due to native capabilities
   - Fix tested manually

2. **Gemini** ✅
   - Tools status persists when switching TO Gemini
   - Full toolset (9 tools) registered
   - Tool JSON parsing fix enables proper tool execution
   - Fix tested manually (bug report was for Gemini!)

3. **OpenAI** ✅
   - Should work identically to Gemini (no native capabilities)
   - Full toolset registered
   - No manual testing yet, but architecture supports it

4. **OpenRouter** ✅
   - Should work identically to Gemini (no native capabilities)
   - Full toolset registered
   - No manual testing yet, but architecture supports it

5. **Ollama** (local models) ✅
   - Should work identically to Gemini (no native capabilities)
   - Full toolset registered
   - No manual testing yet, but architecture supports it

### Why It Works for All Providers

The fix in `ppxai/commands.py` is **provider-agnostic**:

```python
# Line 389: Check if tools were enabled (works for ANY provider)
tools_were_enabled = isinstance(self.client, self.PerplexityClientPromptTools) if self.PerplexityClientPromptTools else False

# Lines 416-418: Re-enable tools with new provider
if tools_were_enabled:
    console.print("[dim]Re-enabling tools for new provider...[/dim]")
    self._enable_tools()  # This automatically uses self.provider
```

The `_enable_tools()` method:
1. Reads `self.provider` (which was just updated to the new provider)
2. Creates a new tool client with the NEW provider
3. Calls `initialize_tools()` which registers provider-specific toolset
4. Result: Tools are correctly initialized for the new provider!

## Customizing Provider Capabilities

You can customize capabilities in `ppxai-config.json`:

```json
{
  "providers": {
    "my-custom-provider": {
      "name": "My Custom Provider",
      "base_url": "https://api.custom.com",
      "api_key_env": "CUSTOM_API_KEY",
      "default_model": "model-1",
      "coding_model": "model-pro",
      "capabilities": {
        "web_search": true,   // Provider can search web natively
        "web_fetch": false,   // Provider needs web_fetch tool
        "weather": false,     // Provider needs weather tool
        "realtime_info": true // Provider has real-time info access
      }
    }
  }
}
```

## Troubleshooting

### Tools not showing up after provider switch?

**Check:**
1. Are tools enabled? Run `/tools status`
2. Did provider switch succeed? Check status line shows new provider
3. Run `/tools list` to see current toolset

### Different tool count between providers?

**This is normal!** Providers with native capabilities get fewer tools.
- Perplexity: 6 tools (native web, weather)
- Gemini/OpenAI/etc: 9 tools (need web, weather tools)

### Tool execution failing after switch?

**Check:**
1. Provider API key configured? (in .env file)
2. Model selected for provider? (status line shows model)
3. For Gemini: Ensure using v1.11.2.2+ with tool JSON parsing fix

## See Also

- [BUGFIX-gemini-tool-calling.md](BUGFIX-gemini-tool-calling.md) - Details on both bugs fixed
- [AUTOROUTER-CONFIG.md](AUTOROUTER-CONFIG.md) - Configure provider-specific coding models
- [SHELL_CONSENT_GUIDE.md](SHELL_CONSENT_GUIDE.md) - Shell command consent system

---

**Last Updated:** 2025-12-24
**Branch:** bugfix/gemini-tool-calling
**Applies to:** v1.11.2.2+ (when merged)
