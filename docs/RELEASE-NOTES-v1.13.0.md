# Release Notes - v1.13.0

**Release Date:** January 3, 2026

## Summary

Major release focused on custom provider support: Premium web search for vLLM/Ollama, native tool calling, comprehensive usage tracking, and enhanced tool parsing. This release validates that custom providers work as reliably as Perplexity and Gemini.

## What's New

### Premium Web Search Tool
- **Custom Provider Support** - vLLM, Ollama, and other custom providers can now use premium web search
- **Priority Fallback Chain** - Perplexity Sonar > Gemini Grounding > DuckDuckGo (free)
- **Automatic Detection** - Tool checks available API keys and uses best available option
- **Citation Integration** - Web search results formatted consistently across all providers

### SSL Proxy Support
- **SSL_VERIFY Environment Variable** - Disable SSL verification for corporate proxies
- **Corporate Network Compatible** - Works behind SSL-inspecting firewalls
- **Per-Request Control** - SSL verification status passed to httpx client

### Tool Usage Tracking
- **ToolUsage Dataclass** - New type for tracking per-tool usage (calls, tokens, cost)
- **`/usage` Command Enhancement** - Shows tool usage breakdown with provider info
- **Cost Attribution** - Separate tracking for model costs vs tool costs (Perplexity Sonar, Gemini Grounding)
- **Per-Query Pricing** - Supports both token-based (Perplexity) and query-based (Gemini) pricing

### Native Tool Calling for Custom Providers
- **`native_tool_calling` Capability** - Enable OpenAI-style function calling for vLLM endpoints
- **vLLM Integration** - Works with `--enable-auto-tool-choice` flag
- **Tool Choice Parameter** - Automatic `tool_choice: "auto"` when tools enabled
- **Streaming Tool Calls** - Full support for streaming responses with tool calls

### Enhanced Tool Parsing
- **vLLM Inference** - Infer tool names from argument patterns (for models without explicit tool names)
- **Dispatcher Pattern** - Match JSON arguments against registered tool schemas
- **Robust Error Handling** - Better recovery from malformed tool responses
- **440+ New Lines** - Comprehensive tool parsing test coverage

### `/tools status` Enhancement
- **Web Search Provider Display** - Shows which web search backend is active
- **Premium vs Free Indicator** - Clearly indicates Perplexity/Gemini (premium) or DuckDuckGo (free)

### Documentation Updates
- Updated test counts from 406 to 525 tests across README.md and ROADMAP.md
- Fixed Gemini `web_search` capability flag (was false, now true)
- Replaced deprecated `sonar-reasoning` with `sonar-reasoning-pro` and `sonar-deep-research`
- Added "Advanced Features" section to PROVIDER_SETUP.md

## Installation

```bash
pip install ppxai[gemini]
# or
uv pip install ppxai[gemini]
```

For SSL proxy support:
```bash
# .env
SSL_VERIFY=false
```

For native tool calling with vLLM:
```json
// ppxai-config.json
{
  "providers": {
    "vllm-local": {
      "capabilities": {
        "native_tool_calling": true
      }
    }
  }
}
```

## Technical Details

### New Files
- `ppxai/engine/tools/builtin/web_premium.py` - Premium web search with Perplexity/Gemini fallback
- `tests/test_engine_tool_parsing.py` - 440+ lines of tool parsing tests
- `tests/test_web_premium.py` - Premium web search tests

### Modified Files
- `ppxai/engine/types.py` - Added `ToolUsage` dataclass, `native_tool_calling` capability
- `ppxai/engine/providers/openai_compat.py` - Native tool calling support for custom providers
- `ppxai/engine/client.py` - Tool usage tracking integration
- `ppxai/commands.py` - Tool usage display in `/usage`, web search provider in `/tools status`
- `ppxai/usage.py` - Tool usage storage in session records

### Provider Capabilities
```python
ProviderCapabilities(
    web_search=True,           # Native web search (Perplexity, Gemini)
    native_tool_calling=True,  # OpenAI-style function calling (vLLM)
    streaming=True,            # Streaming responses
    citations=True             # Citation formatting
)
```

## Test Results

- **525 tests passing** (119 new tests since v1.12.5)
- **Custom provider tool calling** - 8 integration tests
- **Tool parsing** - 440+ lines of test coverage
- **Premium web search** - Integration validated with mocked APIs
- **vLLM inference** - Dispatcher pattern tests for tool name inference

## Files Changed

| File | Changes |
|------|---------|
| `ppxai/engine/types.py` | Added `ToolUsage`, `native_tool_calling` capability |
| `ppxai/engine/providers/openai_compat.py` | Native tool calling, streaming tool calls |
| `ppxai/engine/client.py` | Tool usage tracking integration |
| `ppxai/engine/tools/builtin/web_premium.py` | Premium web search tool |
| `ppxai/commands.py` | Tool usage display, web search provider status |
| `ppxai/usage.py` | Tool usage storage in sessions |
| `tests/test_engine_tool_parsing.py` | 440+ lines of tool parsing tests |
| `tests/test_custom_endpoint_integration.py` | 8 custom provider tests |
| `tests/test_web_premium.py` | Premium web search tests |
| `README.md` | Test count update (406 -> 525) |
| `ROADMAP.md` | v1.13.0 section, test count update |
| `docs/PROVIDER_SETUP.md` | Gemini capabilities, Advanced Features |

## Compatibility

- Python 3.10+
- Requires `ppxai[gemini]` for Gemini Grounding fallback
- Works with all custom OpenAI-compatible endpoints
- vLLM with `--enable-auto-tool-choice` for native tool calling
- No breaking changes

## Upgrade

```bash
pip install --upgrade ppxai[gemini]
```

Or download from [GitHub Releases](https://github.com/rcconsult/ppxai/releases/tag/v1.13.0).
