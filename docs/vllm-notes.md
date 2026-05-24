# vLLM Tool Calling — ppxai Quick Reference

This is a ppxai-side cheat sheet. For deeper guides see:
- [docs/vllm-tool-calling-guide.md](vllm-tool-calling-guide.md) — full ppxai-specific guide
- [docs/prompt-based-tool-calling.md](prompt-based-tool-calling.md) — general developer guide
- [examples/prompt_based_tools.py](../examples/prompt_based_tools.py) — standalone example

## Tool call parsers: Hermes vs Harmony

vLLM supports multiple tool calling formats via `--tool-call-parser`. Different model families use different parsers.

| Model Family | Parser | vLLM Flag | Stability |
|--------------|--------|-----------|-----------|
| GPT-OSS | Harmony | `--tool-call-parser openai` | ⚠️ Intermittent |
| Qwen3 | Hermes | `--tool-call-parser hermes` | Stable |
| Qwen2.5 | Hermes | `--tool-call-parser hermes` | Stable |
| Nous Hermes | Hermes | `--tool-call-parser hermes` | Stable |

Always use the correct parser for your model family. Wrong parser → tool calling fails completely.

## GPT-OSS (Harmony format)

Harmony format is **mandatory** for GPT-OSS — the model is trained on Harmony's response format with control tokens (`<|recipient|>`, `<|thinking|>`, `<|call|>`, ...). If vLLM doesn't parse them, they leak into responses causing `HarmonyError`.

vLLM with GPT-OSS can hit `HarmonyError: unexpected tokens remaining in message header` when using native tool calling. Known vLLM/Harmony issue ([vLLM #23567](https://github.com/vllm-project/vllm/issues/23567)).

**ppxai supports two modes:**

| Mode | Config | vLLM flags | Reliability |
|------|--------|------------|-------------|
| Native | `native_tool_calling: true` | `--enable-auto-tool-choice --tool-call-parser openai` | ⚠️ HarmonyError risk |
| Prompt-based | `native_tool_calling: false` | None required | Stable (recommended) |

**Key insight:** vLLM only triggers Harmony parsing when `request.tools` is provided. With `native_tool_calling: false`, ppxai doesn't send `tools`, so vLLM returns plain text that ppxai parses client-side. This bypasses the unstable Harmony parser.

Implementation:
- Tool prompt injection: `ppxai/engine/tools/manager.py:get_tools_prompt()`
- Multi-strategy parser: `ppxai/engine/tools/parser.py:parse_tool_call()`
- GPT-OSS nested unwrapping: `ppxai/engine/tools/parser.py:_normalize_tool_call()`
- Parameter aliasing: `ppxai/engine/tools/manager.py:PARAM_ALIAS_GROUPS`

Production setup:
- vLLM 0.11.x nightly with LMCache
- `--tool-call-parser openai`
- Model: `openai/gpt-oss-120b`
- ppxai default: `native_tool_calling: true`

For developers hitting HarmonyError: set `native_tool_calling: false`.

## Qwen3 / Qwen2.5 (Hermes format)

Generally more stable than Harmony.

vLLM server:
```bash
vllm serve Qwen/Qwen3-... \
  --enable-auto-tool-choice \
  --tool-call-parser hermes \
  --max-model-len 32768
```

ppxai config:
```json
{
  "providers": {
    "custom": {
      "base_url": "http://localhost:8000/v1",
      "native_tool_calling": true,
      "models": {
        "Qwen/Qwen3-...": { "max_tokens": 8192, "temperature": 0.2 }
      }
    }
  }
}
```

Known issues:
- Same truncation issues as GPT-OSS if `max_tokens` too low
- Unicode whitespace in code
- May still exhibit "I'll use X tool" behavior

Fallback: if native tool calling fails, set `native_tool_calling: false`.

## Known issue: "I'll use X tool" followed by JSON text

GPT-OSS sometimes outputs tool calls as JSON text instead of using native tool calling:

````
I'll use the apply_patch tool.
```json
{"tool": "apply_patch", "arguments": {...}}
```
````

Root causes:
1. vLLM's Harmony parser intermittently fails to capture tool calls.
2. Model explains what it will do before calling the tool (learned behavior).
3. Long tool calls (e.g. apply_patch with large diffs) may be truncated if no `max_tokens` is set.

Mitigation:
1. Add `max_tokens: 8192` (or higher) to model config.
2. System prompt: "NEVER say 'I'll use X tool' then output JSON — call tools directly."
3. AGENTS.md hint: "Do NOT output tool call JSON in your response text."
4. The fallback parser (`ppxai/engine/tools/parser.py`) attempts to extract tool calls from text responses.

Example config:
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
