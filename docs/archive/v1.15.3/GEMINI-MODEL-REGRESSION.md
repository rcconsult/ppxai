# Gemini Model Regression Analysis

**Date:** 2026-02-08
**Model:** gemini-2.5-flash
**Issue:** Code editing regression - model stopped generating apply_patch tool calls

---

## Summary

The gemini-2.5-flash model has experienced a **model behavior regression** between Feb 7-8, 2026. Code editing performance dropped from 57.1% to 0%, with the model no longer generating `apply_patch` tool calls.

**Root Cause:** Model API change by Google (not SDK or ppxai code).

---

## Evidence

### Feb 7, 2026 - Baseline (57.1% code editing)
- **SDK:** google-genai 1.56.0
- **Code:** No workarounds
- **Results:**
  - patch_simple: ✅ PASS (patch_length: 144)
  - patch_indentation: ❌ FAIL (subtract method not found)
  - patch_multiline: ✅ PASS (patch_length: 277)

### Feb 8, 2026 - After Regression (0% code editing)
- **SDK:** google-genai 1.56.0 (same as Feb 7)
- **Code:** No workarounds (same as Feb 7)
- **Results:**
  - patch_simple: ❌ FAIL (Wrong tool: read_file - didn't use apply_patch)
  - patch_indentation: ❌ FAIL (empty patch - no apply_patch call)
  - patch_multiline: ❌ FAIL (empty patch - no apply_patch call)

---

## Analysis

### What Changed
- **SDK:** ✅ Identical (1.56.0)
- **ppxai Code:** ✅ Identical (no commits to gemini.py)
- **Benchmark Code:** ✅ Identical (no test changes)
- **Model Behavior:** ❌ CHANGED (stopped using apply_patch)

### Behavior Comparison

| Test | Feb 7 Behavior | Feb 8 Behavior |
|------|----------------|----------------|
| patch_simple | Generated apply_patch (144 chars) | Called read_file instead |
| patch_indentation | Generated empty patch (failure) | Generated empty patch (failure) |
| patch_multiline | Generated apply_patch (277 chars) | Generated empty patch (no tool call) |

---

## Timeline of Investigation

1. **Feb 7 23:33** - Baseline benchmark: 76.6% overall, 57.1% code editing ✅
2. **Feb 8 05:30** - Upgraded SDK to 1.62.0: Regression to 64.1% overall ❌
3. **Feb 8 14:00** - Applied workarounds (Issue #1789): Still 0% code editing ❌
4. **Feb 8 15:00** - Rolled back SDK to 1.56.0 + workarounds: Still 0% code editing ❌
5. **Feb 8 16:00** - Removed workarounds, clean SDK 1.56.0: Still 0% code editing ❌
6. **Feb 8 16:34** - **FINDING:** Model behavior changed, not SDK

---

## Other Score Changes

| Category | Feb 7 | Feb 8 | Change |
|----------|-------|-------|--------|
| Overall | 76.6% | 54.7% | -21.9% |
| Code Editing | 57.1% | 0% | -57.1% |
| Hallucination Resistance | 55.6% | 16.7% | -38.9% |
| Instruction Following | 100% | 57.1% | -42.9% |
| Tool Calling | 85.7% | 85.7% | ✅ Same |
| Reasoning | 100% | 100% | ✅ Same |
| Error Recovery | 100% | 100% | ✅ Same |

Tool calling, reasoning, and error recovery remain stable. The regression is specific to:
1. Code editing (apply_patch tool)
2. Hallucination resistance (contradictions, failure acknowledgment)
3. Instruction following (constraint respect)

---

## Hypothesis

Google updated the gemini-2.5-flash model between Feb 7-8, 2026, potentially:
- Changing the function calling training data
- Adjusting the system prompt or instruction following
- Modifying the tool selection strategy

The model is now **less likely to use specialized tools** like apply_patch, preferring simpler tools like read_file instead.

---

## Impact

**HIGH SEVERITY** - Code editing is a core use case for agentic coding assistants. A 57% drop in this category makes gemini-2.5-flash significantly less useful.

---

## Recommendations

### Short-Term
1. **Switch to gemini-2.5-pro** - More stable, better instruction following
2. **Test gemini-3-* models** - Evaluate gemini-3-flash-preview and gemini-3-pro-preview
3. **Document the regression** - Alert users to avoid gemini-2.5-flash for code editing
4. **Add model version tracking** - Track which model version was tested

### Long-Term
1. **Report to Google AI** - File issue with Gemini API team
2. **Monitor for updates** - Re-test gemini-2.5-flash weekly to detect fixes
3. **Add model version fingerprinting** - Track model behavior changes over time
4. **Implement fallback strategies** - Switch models when specific capabilities degrade

---

## Next Steps

Per [GEMINI-TUNING-PLAN.md](GEMINI-TUNING-PLAN.md):

1. ✅ Document model regression (this file)
2. ⏳ Run gemini-2.5-pro benchmark
3. ⏳ Run gemini-3-flash-preview benchmark
4. ⏳ Run gemini-3-pro-preview benchmark
5. ⏳ Compare results and identify best model for code editing

---

## References

- [GEMINI-SDK-REGRESSION-ANALYSIS.md](GEMINI-SDK-REGRESSION-ANALYSIS.md) - Initial SDK investigation
- [GEMINI-SDK-ROLLBACK-STATUS.md](GEMINI-SDK-ROLLBACK-STATUS.md) - Rollback details
- [GEMINI-TUNING-PLAN.md](GEMINI-TUNING-PLAN.md) - Model testing plan

---

## Status

✅ Root cause identified: Model API change by Google
⏳ Workaround: Use gemini-2.5-pro or gemini-3-* models instead
⚠️ **Do not use gemini-2.5-flash for code editing tasks until this is resolved**
