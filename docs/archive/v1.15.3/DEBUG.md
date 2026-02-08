# LLM-Eval Debug Mode

## Overview

The `--debug` flag enables comprehensive debug logging for benchmark runs, capturing detailed request/response data and test execution details. This helps identify why specific models fail certain tests and find opportunities for improvement.

## Usage

```bash
# Run full benchmark with debug logging
python benchmark.py --provider gemini --model gemini-2.5-pro --debug

# Run specific categories with debug logging
python benchmark.py --provider perplexity --model sonar-reasoning-pro --categories tool_calling --debug

# Combine with verbose mode for console output
python benchmark.py --provider openai --model gpt-4o --debug --verbose
```

## Debug Output Structure

Debug logs are saved to: `debug/{provider}_{model}_{timestamp}/`

```
debug/gemini_gemini-2.5-pro_20260208_005607/
├── SUMMARY.json                              # Quick overview of results
├── request_001.json                          # First LLM request/response
├── request_002.json                          # Second LLM request/response
├── ...
├── test_001_tool_calling_simple_tool_call.json
├── test_002_tool_calling_complex_args.json
└── ...
```

## File Types

### SUMMARY.json
Quick reference showing:
- Overall score and category breakdown
- List of failed tests with error messages
- Links to detailed test logs

**Example:**
```json
{
  "provider": "gemini",
  "model": "gemini-2.5-pro",
  "overall_score": 64.3,
  "tests_passed": 4,
  "tests_total": 6,
  "failed_tests": [
    {
      "name": "multi_tool_sequence",
      "category": "tool_calling",
      "error": "No tool call in first turn",
      "log_file": "test_004_tool_calling_multi_tool_sequence.json"
    }
  ]
}
```

### test_XXX_*.json
Detailed test execution data:
- Test metadata (name, category, weight)
- Attempt history (with retries)
- Pass/fail status and error details

**Example:**
```json
{
  "test_number": 4,
  "test_name": "multi_tool_sequence",
  "category": "tool_calling",
  "weight": 1.5,
  "attempts": [
    {
      "attempt": 1,
      "passed": false,
      "details": {
        "error": "No tool call in first turn"
      }
    }
  ],
  "final_result": {
    "passed": false,
    "details": {
      "error": "No tool call in first turn"
    }
  }
}
```

### request_XXX.json
Complete request/response cycle:
- Full message history
- Tools provided to the model
- Complete system prompt with tool definitions
- LLM response (content, tool_calls, finish_reason)

**Example:**
```json
{
  "request_id": 4,
  "provider": "gemini",
  "model": "gemini-2.5-pro",
  "messages": [
    {
      "role": "system",
      "content": "You are a coding assistant..."
    },
    {
      "role": "user",
      "content": "First read /src/config.json..."
    }
  ],
  "tools_provided": 6,
  "tools": ["read_file", "write_file", "apply_patch", ...],
  "last_message": "You have access to the following tools...",
  "response": {
    "content": "I have read `/src/config.json`...",
    "tool_calls": [],
    "finish_reason": "stop"
  }
}
```

## Common Failure Patterns

### Hallucination (claims without tool calls)
**Symptom:** Response content describes tool execution results without actual tool_calls
```json
{
  "content": "I have read /src/config.json and found...",
  "tool_calls": [],
  "finish_reason": "stop"
}
```
**Root Cause:** Model "thinks" about what it would do instead of calling tools
**Common in:** Reasoning models (sonar-reasoning-pro, gemini-2.5-pro)

### Tool JSON in Content
**Symptom:** Tool call JSON appears in response text instead of tool_calls array
```json
{
  "content": "I'll use the read_file tool.\n```json\n{\"tool\": \"read_file\", \"arguments\": {...}}```",
  "tool_calls": []
}
```
**Root Cause:** Model formats tool call as code block instead of using native format
**Fix Opportunity:** Enhanced parser to extract tool calls from code blocks

### Missing Tool Calls
**Symptom:** Model explains what it will do without making the call
```json
{
  "content": "I'll read the config file first, then the main entry file.",
  "tool_calls": []
}
```
**Root Cause:** Model lacks understanding of when to use tools vs when to explain
**Fix Opportunity:** Stronger system prompt emphasizing "call tools directly, no explanation"

### Timeout Errors
**Symptom:** Test times out (>120s default)
```json
{
  "error": "Timeout",
  "attempt": 1
}
```
**Root Cause:** Model stuck in reasoning loop or slow API response
**Fix Opportunity:** Increase timeout or optimize prompt

## Analysis Workflow

1. **Start with SUMMARY.json** - Identify which tests failed and error categories
2. **Check test_XXX logs** - Understand test expectations and failure details
3. **Review request_XXX logs** - See exact prompts sent and responses received
4. **Identify patterns** - Group failures by type (hallucination, timeout, format issues)
5. **Propose fixes** - System prompt improvements, parser enhancements, config tuning

## Example Analysis Session

```bash
# Run debug benchmark
python benchmark.py --provider gemini --model gemini-2.5-pro --categories tool_calling --debug

# Output shows:
# Debug logs saved to: debug/gemini_gemini-2.5-pro_20260208_005607
# Summary: debug/gemini_gemini-2.5-pro_20260208_005607/SUMMARY.json

# Check summary
cat debug/gemini_gemini-2.5-pro_20260208_005607/SUMMARY.json

# Review failed test
cat debug/gemini_gemini-2.5-pro_20260208_005607/test_004_tool_calling_multi_tool_sequence.json

# See actual LLM response
cat debug/gemini_gemini-2.5-pro_20260208_005607/request_004.json

# Analysis:
# - Model claimed to read files without calling read_file tool
# - Response shows hallucination pattern
# - Opportunity: Add anti-hallucination guidance to system prompt
```

## Tips

1. **Focus on Failed Tests** - SUMMARY.json lists only failures for quick access
2. **Match Request IDs** - request_XXX.json files correspond to test execution order
3. **Compare Models** - Run debug for multiple models to see behavioral differences
4. **Track Improvements** - Re-run after prompt/config changes to validate fixes
5. **Share Logs** - Debug directories can be zipped and shared for collaboration

## Cleanup

Debug directories can grow large with many requests. Clean up old runs periodically:

```bash
# Remove all debug logs
rm -rf debug/

# Keep only recent runs (last 7 days)
find debug/ -type d -mtime +7 -exec rm -rf {} +
```
