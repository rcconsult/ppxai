# Gemini Models: Multi-Criteria Evaluation Impact

**Date:** 2026-02-08
**Version:** ppxai v1.15.3
**Category:** Code Editing (apply_patch tests)

---

## Executive Summary

Multi-criteria evaluation reveals **significant quality issues** across all Gemini models that were masked by binary scoring. Even the "perfect" gemini-3-flash-preview had hidden anti-patterns.

### Impact Summary

| Model | Binary Score | Quality Score | Change | Status |
|-------|--------------|---------------|--------|--------|
| **gemini-3-flash-preview** | 100.0% ✅ | **57.1%** ⚠️ | **▼42.9%** | Anti-patterns detected |
| **gemini-2.5-flash** | 71.4% | **28.6%** ⚠️ | **▼42.9%** | Severe anti-patterns |
| **gemini-3-pro-preview** | 28.6% | **28.6%** | = | No change |
| **gemini-2.5-pro** | 64.3% | **0.0%** ❌ | **▼64.3%** | Complete failure |

**Key Finding:** ALL Gemini models exhibit quality issues. Only gemini-3-pro-preview's score remained stable because it was already failing due to wrong tool selection, not anti-patterns.

---

## Detailed Test Results

### gemini-3-flash-preview: 100% → 57.1% (▼42.9%)

**Test Breakdown:**

| Test | Binary | Quality | Tool Correctness | Tool Success | Quality Score | Anti-Patterns |
|------|--------|---------|------------------|--------------|---------------|---------------|
| patch_simple | PASS | **PASS** ✅ | ✓ | ✓ | 1.0 | None |
| patch_indentation | PASS | **FAIL** ❌ | ✓ | ✓ | 0.45 | duplicate_code_in_content, 4x duplicate_tool_calls |
| patch_multiline | PASS | **PASS** ✅ | ✓ | ✓ | 0.7 | duplicate_code_in_content |

**Analysis:**
- **patch_simple:** Clean response, no issues
- **patch_indentation:** Made **4 tool calls** instead of 1, plus duplicate code in response
  - Quality: 0.75 - 0.3 (2 anti-patterns × 0.15) = 0.45 < 0.7 threshold → FAIL
- **patch_multiline:** Barely passed with 0.7 score (exactly at threshold)
  - One anti-pattern: duplicate_code_in_content

**Key Issue:** Unnecessary tool calls and response verbosity

---

### gemini-2.5-flash: 71.4% → 28.6% (▼42.9%)

**Test Breakdown:**

| Test | Binary | Quality | Tool Correctness | Tool Success | Quality Score | Anti-Patterns |
|------|--------|---------|------------------|--------------|---------------|---------------|
| patch_simple | PASS | **FAIL** ❌ | ✓ | ✓ | 0.0 | tool_json_in_content, duplicate_tool_calls, hallucinated_tools |
| patch_indentation | FAIL | **FAIL** ❌ | ✗ | ✗ | 0.0 | Called read_file instead of apply_patch |
| patch_multiline | PASS | **PASS** ✅ | ✓ | ✓ | 1.0 | None |

**Analysis:**
- **patch_simple:** **3 anti-patterns detected!**
  - Outputs tool JSON in content while making tool calls
  - Makes 2 duplicate tool calls
  - Mentions tools that weren't called
  - Quality: 0.4 - 0.45 (3 × 0.15) = 0.0 → FAIL
- **patch_indentation:** Wrong tool (read_file instead of apply_patch)
- **patch_multiline:** Clean response, perfect execution

**Key Issue:** Severe anti-patterns in simple tests, but clean on complex multiline patch

---

### gemini-3-pro-preview: 28.6% → 28.6% (No Change)

**Test Breakdown:**

| Test | Binary | Quality | Tool Correctness | Tool Success | Quality Score | Anti-Patterns |
|------|--------|---------|------------------|--------------|---------------|---------------|
| patch_simple | PASS | **PASS** ✅ | ✓ | ✓ | N/A | N/A |
| patch_indentation | FAIL | **FAIL** ❌ | ✗ | ✗ | 0.0 | Wrong tool |
| patch_multiline | FAIL | **FAIL** ❌ | ✗ | ✗ | 0.0 | Hallucinated tool name: "google:apply_patch" |

**Analysis:**
- Score unchanged because failures are due to **wrong tool selection**, not anti-patterns
- Model calls non-existent tools like "google:apply_patch" (namespace hallucination)
- Clean responses when using correct tools

**Key Issue:** Tool selection problems, not response quality

---

### gemini-2.5-pro: 64.3% → 0.0% (▼64.3%)

**Test Breakdown:**

| Test | Binary | Quality | Tool Correctness | Tool Success | Quality Score | Anti-Patterns |
|------|--------|---------|------------------|--------------|---------------|---------------|
| patch_simple | ? | **FAIL** ❌ | ✓ | ✗ | 0.0 | duplicate_code_in_content, duplicate_tool_calls |
| patch_indentation | ? | **FAIL** ❌ | ✓ | ✗ | 0.0 | tool_json_in_content, hallucinated_tools |
| patch_multiline | ? | **FAIL** ❌ | ✓ | ✗ | 0.0 | tool_json_in_content, hallucinated_tools |

**Analysis:**
- **All tests failed** - tools called correctly but produced empty/incomplete patches
- **Every response has anti-patterns:**
  - tool_json_in_content (2 tests)
  - hallucinated_tools (2 tests)
  - duplicate_code_in_content (1 test)
  - duplicate_tool_calls (1 test)

**Key Issue:** Complete breakdown - both tool execution AND response quality

---

## Anti-Pattern Comparison

### Frequency by Model

| Model | tool_json_in_content | duplicate_code_in_content | duplicate_tool_calls | hallucinated_tools |
|-------|---------------------|--------------------------|---------------------|-------------------|
| gemini-3-flash-preview | 0 | 2 | 1 | 0 |
| gemini-2.5-flash | 1 | 0 | 1 | 1 |
| gemini-3-pro-preview | 0 | 0 | 0 | 1 |
| gemini-2.5-pro | 2 | 1 | 1 | 2 |

**Pattern:** Pro models (especially 2.5-pro) have more severe anti-patterns than flash models.

---

## Key Insights

### 1. Binary Scoring Was Highly Misleading

**gemini-3-flash-preview:**
- Binary: "Perfect 100% score! Best model!"
- Reality: Makes 4 duplicate tool calls, outputs duplicate code, barely passes multiline (0.7 threshold)

**gemini-2.5-pro:**
- Binary: "64.3% - decent performance"
- Reality: 0% - complete failure with severe anti-patterns

### 2. Quality Issues Are Widespread

**Every Gemini model tested exhibits quality issues:**
- gemini-3-flash-preview: Duplicate tool calls, verbose responses
- gemini-2.5-flash: Tool JSON in content, hallucinated tools
- gemini-3-pro-preview: Tool namespace hallucination
- gemini-2.5-pro: All anti-patterns, complete breakdown

### 3. Flash Models Cleaner Than Pro Models

**Flash models:**
- gemini-3-flash-preview: 57.1% (highest Gemini score)
- gemini-2.5-flash: 28.6%

**Pro models:**
- gemini-3-pro-preview: 28.6%
- gemini-2.5-pro: 0.0%

Flash models have fewer severe anti-patterns, though still not clean.

### 4. Anti-Pattern Distribution

**Most common issues:**
1. **duplicate_code_in_content** (4 occurrences) - Models explain code instead of just calling tools
2. **hallucinated_tools** (4 occurrences) - Models mention tools they didn't call
3. **tool_json_in_content** (3 occurrences) - Models output tool JSON in response
4. **duplicate_tool_calls** (3 occurrences) - Models make 2-4 calls instead of 1

### 5. Comparison with Perplexity Models

**Gemini flash models vs Perplexity:**

| Model | Quality Score | Cleanest Test |
|-------|---------------|---------------|
| gemini-3-flash-preview | 57.1% | patch_simple (1.0) |
| perplexity/sonar-reasoning-pro | 28.6% | patch_simple (0.7) |
| gemini-2.5-flash | 28.6% | patch_multiline (1.0) |
| perplexity/sonar | 0.0% | N/A |
| perplexity/sonar-pro | 0.0% | N/A |
| gemini-2.5-pro | 0.0% | N/A |

**gemini-3-flash-preview is the cleanest model tested so far** (57.1%), but still has significant issues.

---

## Recommendations

### 1. Model Selection for Code Editing

**Best:** gemini-3-flash-preview (57.1%)
- Most consistent
- Fewest severe anti-patterns
- 2/3 tests passed quality validation
- **Warning:** Still makes duplicate tool calls and verbose responses

**Acceptable:** gemini-2.5-flash (28.6%)
- Can produce perfect patches (patch_multiline: 1.0)
- Inconsistent - severe anti-patterns on simple tests
- Only use if gemini-3-flash unavailable

**Avoid:**
- gemini-3-pro-preview (28.6%) - tool namespace hallucination
- gemini-2.5-pro (0.0%) - complete breakdown

### 2. AGENTS.md Hints Need Refinement

Current hints reduce binary scores but don't address anti-patterns:
- "Call tools directly without explanation" → Still get duplicate code in content
- "CRITICAL: use apply_patch" → Still get duplicate tool calls

**Needed:**
- "Make EXACTLY ONE tool call - do NOT call the same tool multiple times"
- "Do NOT output code in your response when using apply_patch"
- "Do NOT output tool call JSON in your response text"

### 3. Quality Validation Is Essential

**Binary benchmarks are insufficient:**
- gemini-3-flash-preview: 100% → 57.1% (hidden issues)
- gemini-2.5-pro: 64.3% → 0.0% (complete failure masked)

**All future benchmarks must use multi-criteria evaluation.**

---

## Conclusion

Multi-criteria evaluation reveals that **ALL Gemini models have quality issues** that binary scoring completely missed. The "perfect" gemini-3-flash-preview (100% binary) actually has duplicate tool calls and verbose responses (57.1% quality).

**Key Takeaway:**
- gemini-3-flash-preview is the best Gemini model but far from perfect
- Quality validation is CRITICAL - binary scoring is dangerously misleading
- Pro models have severe issues and should be avoided for code editing
- Even "good" models need prompt refinement to eliminate anti-patterns

**Next Steps:**
1. Create targeted AGENTS.md hints to address specific anti-patterns
2. Re-run benchmarks after hint updates
3. Expand quality validation to other test categories
4. Test other model families (GPT-4, Claude) with quality validation
