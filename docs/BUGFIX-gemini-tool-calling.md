# Bugfix: Gemini Tool Calling & Provider Tools Persistence

**Branch:** `bugfix/gemini-tool-calling`
**Date:** 2025-12-24
**Status:** ✅ Fixed and Tested

## Issues Fixed

### Bug #1: Tools Status Not Persisting When Switching Providers

**Symptom:**
```
1. Run TUI: uv run ppxai
2. Select Perplexity provider
3. Enable tools: /tools enable
4. Status shows: [Perplexity AI | Sonar Pro | Tools: ON] ✅
5. Switch provider: /provider gemini
6. Status shows: [Google Gemini | ... | Tools: OFF] ❌ BUG!
```

**Expected:** Tools should remain `ON` after switching providers
**Actual:** Tools reset to `OFF`

**Root Cause:**
In `ppxai/commands.py`, the `handle_provider()` method (lines 346-410) creates a new `AIClient` when switching providers but does NOT check if tools were enabled on the previous client or re-enable them.

**Fix:**
```python
# Line 389: Check if tools are currently enabled before switching
tools_were_enabled = isinstance(self.client, self.PerplexityClientPromptTools) if self.PerplexityClientPromptTools else False

# ... provider switching logic ...

# Lines 416-418: Re-enable tools if they were enabled before switching
if tools_were_enabled:
    console.print("[dim]Re-enabling tools for new provider...[/dim]")
    self._enable_tools()
```

**Files Changed:**
- `ppxai/commands.py` (lines 388-420)

**Testing:**
- Manual TUI test confirmed fix works
- test_provider_switching_fix_documented() documents expected behavior

---

### Bug #2: Gemini Tool Call JSON Parsing Failing on Nested Braces

**Symptom:**
When using Gemini models with tools enabled, tool calls are **shown as raw JSON** to the user instead of being executed:

```
You: /convert @/tmp/hello_world.R to Python and run it

A: (streaming...)
Of course. Here is the Python version...

{
  "tool": "execute_shell_command",
  "arguments": {
    "command": "printf 'print(\"Hello\")' > /tmp/hello.py && python3 /tmp/hello.py",
    "working_dir": "/tmp"
  }
}
```

**Expected:** Tool should be executed silently, final result shown
**Actual:** JSON is rendered to user, tool not executed

**Root Cause:**
In `perplexity_tools_prompt_based.py`, the `_parse_tool_call()` method uses a regex pattern that fails on nested JSON:

```python
# OLD (BROKEN): Only matches up to first '}'
raw_json_pattern = r'\{\s*"tool"\s*:\s*"[^"]+"\s*[^}]*\}'

# This matches: {"tool": "execute_shell_command", "arguments": {
# But stops at the first '}' inside arguments!
```

When parsing this JSON:
```json
{
  "tool": "execute_shell_command",
  "arguments": {
    "command": "...",
    "working_dir": "/tmp"
  }
}
```

The regex only captures:
```json
{
  "tool": "execute_shell_command",
  "arguments": {
```

Which fails JSON.parse() → tool not detected → JSON shown to user

**Fix:**
```python
# Lines 1055-1070: NEW - Extract JSON with nested braces support
first_brace = text.find('{')
last_brace = text.rfind('}')

if first_brace != -1 and last_brace != -1 and first_brace < last_brace:
    json_candidate = text[first_brace:last_brace+1]
    try:
        data = json.loads(json_candidate)
        # Check if it's a tool call
        if isinstance(data, dict) and "tool" in data:
            normalized = normalize_tool_call(data)
            if normalized:
                return normalized
    except json.JSONDecodeError:
        pass
```

**Files Changed:**
- `perplexity_tools_prompt_based.py` (lines 1054-1083)

**Testing:**
- ✅ test_parse_gemini_nested_json_tool_call() - Tests Gemini format
- ✅ test_parse_tool_call_in_code_block() - Tests code blocks still work
- ✅ test_parse_tool_call_simple_no_nested_args() - Tests simple calls work
- All 3 automated tests passing

---

## Commits

1. **5ffdc4c** - fix: Two critical TUI bugfixes - tools status persistence + Gemini tool parsing
2. **398aef5** - test: Add regression tests for provider tools bugfixes

## Test Results

```bash
$ uv run pytest tests/test_provider_tools_bugfixes.py -v

tests/test_provider_tools_bugfixes.py::TestProviderSwitchingToolsPersistence::test_provider_switching_fix_documented PASSED
tests/test_provider_tools_bugfixes.py::TestGeminiToolCallParsing::test_parse_gemini_nested_json_tool_call PASSED
tests/test_provider_tools_bugfixes.py::TestGeminiToolCallParsing::test_parse_tool_call_in_code_block PASSED
tests/test_provider_tools_bugfixes.py::TestGeminiToolCallParsing::test_parse_tool_call_simple_no_nested_args PASSED

============================== 4 passed in 0.94s ==============================
```

## Manual Testing

**Test Scenario (both bugs):**
1. Start TUI: `uv run ppxai`
2. Select Perplexity provider
3. Enable tools: `/tools enable`
4. Verify: Status shows `[Perplexity AI | Sonar Pro | Tools: ON]`
5. Switch provider: `/provider gemini`
6. ✅ **Bug #1 Fixed:** Status shows `[Google Gemini | ... | Tools: ON]`
7. Test tool execution: `/convert @/tmp/hello_world.R to Python and run it`
8. ✅ **Bug #2 Fixed:** Tool executes, no raw JSON shown

## Impact

**Before Fixes:**
- ❌ Tools disabled after provider switch (confusing UX)
- ❌ Gemini tool calls show raw JSON (broken functionality)
- ❌ Users think tools don't work with Gemini

**After Fixes:**
- ✅ Tools persist across provider switches
- ✅ Gemini tool calls execute correctly
- ✅ Consistent tool experience across all providers

## Next Steps

1. Merge `bugfix/gemini-tool-calling` to `master`
2. Consider releasing as v1.11.2.2 or v1.11.3
3. Update CHANGELOG.md with both fixes
4. Test with all providers (Perplexity, Gemini, OpenAI, OpenRouter)

---

**Created:** 2025-12-24
**Branch:** bugfix/gemini-tool-calling
**Commits:** 2
**Tests Added:** 4
**Files Changed:** 3
