# Gemini SDK Rollback Status

**Date:** 2026-02-08
**Action:** Rolled back to google-genai 1.56.0 (from 1.62.0)
**Workarounds:** Kept in place (gemini.py empty parts filtering)

---

## Rollback Details

### Executed Commands
```bash
cp uv.lock.backup uv.lock
uv sync
```

### Version Changes
| Package | Before (1.62.0) | After Rollback |
|---------|-----------------|----------------|
| google-genai | 1.62.0 | **1.56.0** ✅ |
| protobuf | 6.33.5 | (removed, 1.56.0 uses older version) |
| google-ai-generativelanguage | 0.10.0 | (removed, 1.56.0 uses older version) |

### Verification
```bash
$ uv run python -c "from google import genai; print('google-genai OK')"
google-genai OK
```

---

## Workarounds Kept

Despite rollback, we kept the empty parts filtering in `gemini.py`:

**Rationale:**
- Won't hurt with SDK 1.56.0
- Provides extra safety if SDK has undocumented issues
- Logs warnings when empty parts are detected (helpful for debugging)
- Code is clean and well-documented

**File:** `ppxai/engine/providers/gemini.py`
- Lines 125-163: `_filter_empty_parts()` method
- Lines 193-194: Applied in streaming path
- Lines 259-261: Applied in non-streaming path
- Lines 340-342: Applied in sync_simple path

---

## Expected Results

### Baseline (Feb 7, SDK 1.56.0, no workarounds)
- **Overall:** 76.6%
- **Code editing:** 57.1%
- **Tool calling:** 85.7%
- **Hallucination resistance:** 55.6%

### Target (Feb 8, SDK 1.56.0, with workarounds)
- **Overall:** 76.6%+ (at least maintain)
- **Code editing:** 57.1%+ (restore from 0%)
- **Tool calling:** 85.7%+ (maintain)
- **Hallucination resistance:** 55.6%+ (maintain or improve)

### Regression (Feb 8, SDK 1.62.0, with workarounds)
- **Overall:** 64.1%
- **Code editing:** 0% (all tests failed)
- **Tool calling:** 85.7% (no change)
- **Hallucination resistance:** 33.3%

---

## Current Benchmark Run

**Command:**
```bash
uv run python benchmarks/llm-eval/benchmark.py \
  --provider gemini \
  --model gemini-2.5-flash \
  --timeout 120
```

**Status:** Running (26 tests total)
**Expected Duration:** ~3-5 minutes

---

## Next Steps

### If Rollback Succeeds (Expected)
1. ✅ Confirm code editing restored to 57.1%
2. ✅ Document final SDK version decision (stay on 1.56.0)
3. ✅ Proceed with Gemini tuning experiments (GEMINI-TUNING-PLAN.md)
4. ✅ File GitHub issue with googleapis/python-genai about v1.57.0+ regression

### If Rollback Fails (Unexpected)
1. ❌ Investigate root cause (not SDK version?)
2. ❌ Check model version (gemini-2.5-flash stable unchanged?)
3. ❌ Consider deeper investigation before tuning

---

## References

- [GEMINI-SDK-REGRESSION-ANALYSIS.md](GEMINI-SDK-REGRESSION-ANALYSIS.md)
- [GEMINI-SDK-WORKAROUNDS-APPLIED.md](GEMINI-SDK-WORKAROUNDS-APPLIED.md)
- [GEMINI-TUNING-PLAN.md](GEMINI-TUNING-PLAN.md)
- [Issue #1789 - Empty Finish Messages](https://github.com/googleapis/python-genai/issues/1789)
- [Issue #1818 - AFC Persistence](https://github.com/googleapis/python-genai/issues/1818)

---

## Timeline

| Time | Action | Result |
|------|--------|--------|
| Feb 7 | Baseline benchmark (SDK 1.56.0) | 76.6% ✅ |
| Feb 8 05:30 | Upgrade to SDK 1.62.0 | Regression to 64.1% ❌ |
| Feb 8 14:00 | Applied workarounds | Still 0% code editing ❌ |
| Feb 8 15:00 | Rollback to SDK 1.56.0 | ⏳ Testing now |

---

## Status: ⏳ AWAITING BENCHMARK RESULTS
