# Gemini SDK Workarounds Applied (v1.62.0)

**Date:** 2026-02-08
**SDK Version:** google-genai 1.62.0 (with workarounds)
**Based on:** GitHub Issues #1789, #1818, Spring AI #4556

---

## Summary

Applied workarounds to mitigate SDK v1.57.0+ regressions without full rollback to v1.56.0.

---

## Changes Made

### 1. Added Empty Parts Filtering

**File:** `ppxai/engine/providers/gemini.py`

**New Method:** `_filter_empty_parts()`

```python
def _filter_empty_parts(self, parts: List[Any], context: str = "") -> List[Any]:
    """Filter out empty parts to work around SDK v1.57.0+ regression.

    Issue: https://github.com/googleapis/python-genai/issues/1789
    SDK versions 1.57.0+ removed validation on empty text parts, causing
    incomplete responses (e.g., patches missing imports) to pass through.
    """
    if not parts:
        return parts

    filtered_parts = []
    empty_count = 0

    for part in parts:
        # Keep function call parts always
        if hasattr(part, 'function_call') and part.function_call:
            filtered_parts.append(part)
            continue

        # Filter text parts: must have text AND non-whitespace content
        if hasattr(part, 'text') and part.text and part.text.strip():
            filtered_parts.append(part)
        else:
            empty_count += 1

    if empty_count > 0:
        logger.warning(
            f"Gemini SDK workaround: Filtered {empty_count} empty parts from "
            f"{context} response (Issue #1789)"
        )

    return filtered_parts
```

### 2. Applied Filter to All Response Paths

**Streaming Response (lines 234-243):**
```python
# Before:
if content.parts:
    for part in content.parts:
        if hasattr(part, 'text') and part.text:

# After:
filtered_parts = self._filter_empty_parts(content.parts, "streaming")
if filtered_parts:
    for part in filtered_parts:
        if hasattr(part, 'text') and part.text and part.text.strip():
```

**Non-Streaming Response (lines 308-313):**
```python
# Before:
for part in response.candidates[0].content.parts:
    if hasattr(part, 'text') and part.text:

# After:
filtered_parts = self._filter_empty_parts(
    response.candidates[0].content.parts, "non-streaming"
)
for part in filtered_parts:
    if hasattr(part, 'text') and part.text and part.text.strip():
```

**Sync Simple Response (lines 395-400):**
```python
# Before:
for part in response.candidates[0].content.parts:
    if hasattr(part, 'text') and part.text:

# After:
filtered_parts = self._filter_empty_parts(
    response.candidates[0].content.parts, "sync_simple"
)
for part in filtered_parts:
    if hasattr(part, 'text') and part.text and part.text.strip():
```

### 3. Added Logger Import

```python
from ...common.logger import get_logger

logger = get_logger("gemini")
```

---

## Addressed Issues

### Issue #1789: Empty Finish Messages
**Problem:** SDK returns empty messages when function calls are malformed
**Workaround:** Filter parts before processing, log warnings when empty parts detected

### Issue #1818: AFC Persistence
**Status:** Not applicable (ppxai doesn't use Automatic Function Calling)

### Spring AI #4556: Empty Assistant Messages
**Problem:** API returns multiple candidates with empty text
**Workaround:** Same filtering logic prevents empty parts from propagating

---

## Expected Benefits

1. **Code Editing:** Incomplete patches (missing imports) should now be caught
2. **Tool Selection:** Empty responses won't bypass validation
3. **Logging:** Warnings when empty parts are filtered (helps debugging)
4. **Robustness:** All response paths protected (streaming, non-streaming, sync)

---

## Testing

**Verification Benchmark:**
```bash
uv run python benchmarks/llm-eval/benchmark.py \
  --provider gemini \
  --model gemini-2.5-flash \
  --categories code_editing \
  --timeout 120
```

**Expected Results:**
- Code editing: 0% → closer to historical 57.1%
- Fewer incomplete patches
- Warning logs when empty parts are encountered

---

## Rollback Plan

If workarounds don't improve results, revert to SDK v1.56.0:

```bash
cp uv.lock.backup uv.lock
uv sync
```

---

## References

- [Issue #1789 - Empty Finish Messages](https://github.com/googleapis/python-genai/issues/1789)
- [Issue #1818 - AFC Persistence](https://github.com/googleapis/python-genai/issues/1818)
- [Spring AI #4556 - Empty Assistant Messages](https://github.com/spring-projects/spring-ai/issues/4556)
- [docs/GEMINI-SDK-REGRESSION-ANALYSIS.md](GEMINI-SDK-REGRESSION-ANALYSIS.md)

---

## Status

✅ Workarounds applied
⏳ Verification benchmark running
❓ Results pending
