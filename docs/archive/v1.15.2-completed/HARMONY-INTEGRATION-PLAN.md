# Harmony Format Integration Plan for ppxai

**Created:** 2026-01-26
**Status:** Planning
**Related:** [vllm-tool-calling-guide.md](vllm-tool-calling-guide.md)

## Background

GPT-OSS requires the Harmony response format—it's not optional. The model outputs special control tokens (`<|recipient|>`, `<|thinking|>`, `<|call|>`, etc.) that must be properly parsed.

### Current State

| Component | Status | Notes |
|-----------|--------|-------|
| Prompt-based tool calling | ✅ Working | Bypasses vLLM parser, ppxai parses JSON |
| Native tool calling | ✅ Working | Requires vLLM with PR #30205 fix |
| Reasoning extraction | ❌ Not implemented | `analysis` channel discarded |
| Token filtering | ❌ Not implemented | Raw tokens may leak to user |

### vLLM Harmony Fix Status

The Harmony parsing issue has been fixed in vLLM (PR #30205). If your vLLM deployment includes this fix, native tool calling works correctly.

With the Harmony fix available, **Phases 2-5 are now optional enhancements**, not critical fixes.

---

## Proposed Changes

### Phase 1: Documentation Updates (v1.14.x) ✅

**Status:** Completed in this session

1. ✅ Update `docs/vllm-tool-calling-guide.md` with Harmony format explanation
2. ✅ Update `CLAUDE.md` with critical finding about mandatory Harmony format
3. ✅ Document recommended configuration (`native_tool_calling: false`)

### Phase 2: Default Configuration Change (v1.15.x)

**Goal:** Make prompt-based tool calling the default for GPT-OSS

**Files to modify:**
- `ppxai-config.json` - Set `native_tool_calling: false` for vLLM/GPT-OSS
- `ppxai-config.example.json` - Update example with recommended config

**Change:**
```json
{
  "providers": {
    "custom": {
      "capabilities": {
        "native_tool_calling": false  // Changed from true
      }
    }
  }
}
```

**Risk:** Low - prompt-based mode is already implemented and tested

### Phase 3: Harmony Token Filtering (v1.15.x)

**Goal:** Strip leaked Harmony control tokens from responses

**Problem:** Even with prompt-based mode, some Harmony tokens may appear in responses if the model's training bleeds through.

**Implementation:**
```python
# ppxai/engine/providers/base.py or new harmony.py

HARMONY_TOKENS = [
    '<|start|>', '<|end|>',
    '<|recipient|>', '<|thinking|>',
    '<|call|>', '<|analysis|>',
    '<|final|>', '<|commentary|>',
]

def filter_harmony_tokens(text: str) -> str:
    """Remove Harmony control tokens from response text."""
    for token in HARMONY_TOKENS:
        text = text.replace(token, '')
    return text.strip()
```

**Files to modify:**
- `ppxai/engine/providers/openai_compat.py` - Add post-processing
- `ppxai/engine/tools/parser.py` - Filter before parsing

**Risk:** Medium - Need to ensure we don't break valid content

### Phase 4: Reasoning Channel Extraction (v1.16.x)

**Goal:** Extract chain-of-thought from Harmony's `analysis` channel and display as "thinking" tokens (like DeepSeek R1)

**Status:** Optional enhancement - all clients already support reasoning chunks

#### Client Readiness Assessment

| Component | Status | Implementation |
|-----------|--------|----------------|
| **Engine Types** | ✅ Ready | `EventType.REASONING_CHUNK` in `types.py:16` |
| **Provider** | ✅ Ready | Emits `REASONING_CHUNK` for `reasoning_content` field (`openai_compat.py:279-282`) |
| **TUI** | ✅ Ready | Shows "💭 Thinking..." header, dim italic content (`event_handler.py:315-322`) |
| **VSCode** | ✅ Ready | Collapsible reasoning section (`main.js:1027-1055`) |
| **Web App** | ✅ Ready | Collapsible reasoning section (`app.js:1856-1899`) |

**Key Finding:** All clients already handle `REASONING_CHUNK` events. Only the engine needs modification to parse Harmony format.

#### Harmony Response Structure

```
<|start|>
<|analysis|>
Let me think about this step by step...
1. First, I need to understand the question
2. Then, I'll formulate a response
<|final|>
Here is my answer to your question.
<|end|>
```

#### Implementation (Engine Only)

**Only 1 new file + 1 modification required:**

```
ppxai/engine/harmony.py           # NEW: Harmony parser (~80 lines)
ppxai/engine/providers/openai_compat.py  # MODIFY: Detect & parse Harmony
```

**1. New File: `ppxai/engine/harmony.py`**

```python
"""Harmony response format parser for GPT-OSS models."""

import re
from dataclasses import dataclass
from typing import Optional

HARMONY_TOKENS = [
    '<|start|>', '<|end|>',
    '<|analysis|>', '<|final|>', '<|commentary|>',
    '<|recipient|>', '<|thinking|>', '<|call|>',
]

@dataclass
class HarmonyResponse:
    analysis: Optional[str] = None   # Chain-of-thought (reasoning)
    final: Optional[str] = None      # User-facing response
    commentary: Optional[str] = None # Tool calls
    raw: str = ""

def parse_harmony_response(text: str) -> HarmonyResponse:
    """Parse Harmony-formatted response into channels."""
    result = HarmonyResponse(raw=text)

    # Extract analysis (reasoning)
    analysis_match = re.search(
        r'<\|analysis\|>(.*?)(?:<\|(?:final|commentary|end)\|>)',
        text, re.DOTALL
    )
    if analysis_match:
        result.analysis = analysis_match.group(1).strip()

    # Extract final (response content)
    final_match = re.search(
        r'<\|final\|>(.*?)(?:<\|(?:commentary|end)\|>)',
        text, re.DOTALL
    )
    if final_match:
        result.final = final_match.group(1).strip()

    # Extract commentary (tool calls)
    commentary_match = re.search(
        r'<\|commentary\|>(.*?)<\|end\|>',
        text, re.DOTALL
    )
    if commentary_match:
        result.commentary = commentary_match.group(1).strip()

    return result

def filter_harmony_tokens(text: str) -> str:
    """Remove Harmony control tokens from text."""
    for token in HARMONY_TOKENS:
        text = text.replace(token, '')
    return text.strip()

def is_harmony_format(text: str) -> bool:
    """Check if text contains Harmony control tokens."""
    return any(token in text for token in ['<|analysis|>', '<|final|>', '<|start|>'])
```

**2. Modify: `openai_compat.py` (streaming section)**

```python
# In the streaming loop, after collecting chunks:
from .harmony import parse_harmony_response, is_harmony_format, filter_harmony_tokens

# Check if response is Harmony format
full_text = ''.join(full_response)
if is_harmony_format(full_text):
    harmony = parse_harmony_response(full_text)

    # Emit reasoning if present
    if harmony.analysis:
        yield Event(EventType.REASONING_CHUNK, harmony.analysis)

    # Use final channel as content
    final_content = harmony.final or filter_harmony_tokens(full_text)
else:
    final_content = full_text
```

#### Effort Estimate

| Task | Lines | Complexity |
|------|-------|------------|
| Create `harmony.py` | ~80 | Low |
| Modify `openai_compat.py` | ~20 | Low |
| Add tests (`test_harmony.py`) | ~100 | Medium |
| **Total** | **~200** | **Low-Medium** |

#### Risk Assessment

| Risk | Level | Mitigation |
|------|-------|------------|
| False positive Harmony detection | Low | Only check for `<|analysis|>` token |
| Streaming vs buffered parsing | Medium | May need to buffer for complete channel extraction |
| Token leakage edge cases | Low | Filter function as fallback |

**Risk:** Low-Medium - Isolated engine change, clients already ready

### Phase 5: vLLM Configuration Detection (v1.16.x)

**Goal:** Auto-detect vLLM's Harmony parser state and adapt

**Implementation:**
```python
# ppxai/engine/providers/openai_compat.py

async def detect_vllm_harmony_support(base_url: str) -> bool:
    """Check if vLLM endpoint has working Harmony parser."""
    try:
        # Send test message with tool
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "test"}],
            tools=[{"type": "function", "function": {"name": "test"}}],
            max_tokens=10
        )
        # If no HarmonyError, native mode works
        return True
    except Exception as e:
        if 'HarmonyError' in str(e):
            return False
        raise
```

**Risk:** Low - Detection is optional enhancement

---

## Implementation Priority

**Note:** With vLLM PR #30205 deployed, phases 2-5 are optional enhancements.

| Phase | Priority | Effort | Target | Status |
|-------|----------|--------|--------|--------|
| Phase 1: Docs | ✅ Done | Low | v1.14.2 | Complete |
| Phase 2: Config default | Low | Low | v1.15.0 | Optional (native works) |
| Phase 3: Token filtering | Low | Low | v1.15.0 | Optional (edge case) |
| Phase 4: Reasoning | Medium | Low | v1.16.0 | **Clients ready, engine only** |
| Phase 5: Auto-detect | Low | Medium | v1.16.0 | Optional |

**Recommendation:** Phase 4 is the most valuable enhancement—~200 lines of engine code to display GPT-OSS chain-of-thought. All UI work is already done.

---

## Testing Plan

### Unit Tests
```python
# tests/test_harmony.py

def test_filter_harmony_tokens():
    text = "<|start|>Hello<|end|>"
    assert filter_harmony_tokens(text) == "Hello"

def test_parse_harmony_response():
    text = """<|start|>
<|analysis|>Thinking...
<|final|>Answer here
<|end|>"""
    result = parse_harmony_response(text)
    assert result.analysis == "Thinking..."
    assert result.final == "Answer here"

def test_parse_harmony_with_tool():
    text = """<|start|>
<|analysis|>I need to search
<|commentary|>{"tool": "web_search", "arguments": {"query": "test"}}
<|end|>"""
    result = parse_harmony_response(text)
    assert "web_search" in result.commentary
```

### Integration Tests
- Test with actual vLLM endpoint
- Verify reasoning displays in TUI/VSCode/Web
- Confirm tool calls still work with Harmony parsing

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Harmony format changes | High | Pin to specific vLLM/openai-harmony versions |
| Token filtering breaks content | Medium | Comprehensive test suite, opt-in flag |
| Performance overhead | Low | Parsing is O(n), minimal impact |
| User confusion about reasoning | Low | Clear UI labeling, documentation |

---

## References

- [OpenAI Harmony GitHub](https://github.com/openai/openai-harmony)
- [vLLM Issue #22337](https://github.com/vllm-project/vllm/issues/22337)
- [vLLM Issue #23567](https://github.com/vllm-project/vllm/issues/23567)
- [ppxai vLLM Guide](vllm-tool-calling-guide.md)
