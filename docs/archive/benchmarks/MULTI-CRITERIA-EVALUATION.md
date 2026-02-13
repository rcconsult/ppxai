# Multi-Criteria Evaluation System

**Version:** v1.15.3
**Date:** 2026-02-08
**Status:** Production

## Overview

The multi-criteria evaluation system validates LLM benchmark responses beyond binary pass/fail, detecting anti-patterns and measuring response quality.

## Motivation

### Problem: Binary Scoring Masks Quality Issues

Binary pass/fail benchmarks only check if the correct tool was called with valid arguments. This misses critical quality issues:

**Case Study: Perplexity sonar-pro**
- **Binary score:** 100% (all tests passed)
- **Reality:** Serious anti-patterns in every response
  - Outputs tool JSON in content while making tool calls
  - Hallucinating tool names
  - Making 5+ duplicate tool calls

The model technically "passed" but exhibited poor response quality that would confuse users and waste tokens.

## Solution: Quality Metrics

### QualityMetrics Class

```python
@dataclass
class QualityMetrics:
    tool_correctness: bool      # Did the right tool get called?
    tool_success: bool           # Did the tool execute successfully?
    response_quality: float      # Response cleanliness (0.0-1.0)
    anti_patterns: List[str]     # Detected anti-patterns
    quality_notes: List[str]     # Detailed observations

    @property
    def overall_score(self) -> float:
        """Score with anti-pattern penalties."""
        if not (self.tool_correctness and self.tool_success):
            return 0.0
        penalty = len(self.anti_patterns) * 0.15  # 15% per pattern
        return max(0.0, self.response_quality - penalty)

    @property
    def passed(self) -> bool:
        """Pass threshold: 70%"""
        return self.overall_score >= 0.7
```

### Anti-Pattern Detection

| Anti-Pattern | Penalty | Description |
|--------------|---------|-------------|
| **tool_json_in_content** | -30% | Model outputs tool JSON in response while also making tool calls |
| **explained_before_tool** | -20% | Model explains what it will do instead of calling tool directly |
| **duplicate_code_in_content** | -15% | Model outputs code in response when tool call should handle it |
| **duplicate_tool_calls** | -10% | Model makes unnecessary redundant tool calls |
| **hallucinated_tools** | -20% | Model mentions tools in content that weren't actually called |

### Positive Indicators

| Indicator | Bonus | Description |
|-----------|-------|-------------|
| **Clean tool-only response** | +10% | Tool call with no unnecessary text |
| **No anti-patterns** | Note | Explicitly noted in quality_notes |

## Scoring Algorithm

1. **Base Quality Score (0.0-1.0)**
   - Starts at 1.0
   - Reduced by specific anti-pattern weights
   - Bonus for clean responses

2. **Anti-Pattern Penalty**
   - Each anti-pattern: -15%
   - Applied after base quality calculation

3. **Overall Score**
   ```
   if not (tool_correctness and tool_success):
       return 0.0
   else:
       return max(0.0, quality - (anti_patterns × 0.15))
   ```

4. **Pass Threshold**
   - Score >= 0.7 (70%) = PASS
   - Score < 0.7 = FAIL

## Example: Perplexity sonar-pro

### Before Quality Validation (Binary Scoring)

```json
{
  "name": "patch_indentation",
  "passed": true,
  "details": {
    "patch_length": 225
  }
}
```
**Result:** PASS (100%)

### After Quality Validation

```json
{
  "name": "patch_indentation",
  "passed": false,
  "details": {
    "patch_length": 225,
    "tool_correctness": true,
    "tool_success": true,
    "response_quality": 0.5,
    "anti_patterns": [
      "tool_json_in_content",
      "hallucinated_tools"
    ],
    "quality_notes": [
      "Model output tool JSON in response text while also making tool calls",
      "Model mentioned tools in content that weren't actually called"
    ],
    "overall_score": 0.2,
    "passed": false
  }
}
```
**Result:** FAIL (20% score)
**Calculation:** 0.5 - (2 × 0.15) = 0.2

## Impact Analysis

### Perplexity Models (code_editing category)

| Model | Binary Score | Quality Score | Change | Anti-Patterns |
|-------|--------------|---------------|--------|---------------|
| sonar-pro | 100.0% | 0.0% | ▼100% | tool_json_in_content, hallucinated_tools, 5x duplicate_tool_calls |
| sonar | 57.1% | 0.0% | ▼57.1% | tool_json_in_content, hallucinated_tools, 6x duplicate_tool_calls |
| sonar-reasoning-pro | 28.6% | 28.6% | = | duplicate_code_in_content only |

**Key Insight:** sonar-reasoning-pro has the cleanest responses despite lowest score. It fails due to calling wrong tools or incomplete patches, not anti-patterns.

## Integration Guide

### Test Case Updates

```python
from response_quality import validate_response_quality, QualityMetrics

async def test_apply_patch_simple(client) -> tuple[bool, dict]:
    response = await client.chat(...)

    # Validate response quality
    quality = validate_response_quality(response, expected_tool="apply_patch")

    tool_calls = response.get("tool_calls", [])
    if not tool_calls:
        quality.tool_success = False
        return False, {"error": "No tool call", **quality.to_dict()}

    # Existing validation logic...
    if validation_fails:
        quality.tool_success = False
        return False, {"error": "...", **quality.to_dict()}

    # Return quality-based pass/fail
    return quality.passed, {"patch_length": len(patch), **quality.to_dict()}
```

### Key Changes

1. **Call validator first** with expected tool name
2. **Set `quality.tool_success = False`** when validation fails
3. **Return `quality.passed`** instead of `True/False`
4. **Include `**quality.to_dict()`** in all result dicts

## Files Modified

- `benchmarks/llm-eval/response_quality.py` (NEW) - Core validation logic
- `benchmarks/llm-eval/test_cases.py` - Updated code_editing tests:
  - `test_apply_patch_simple`
  - `test_apply_patch_indentation`
  - `test_apply_patch_multiline`

## Future Work

1. **Expand to Other Categories**
   - Tool Calling: Already has anti-pattern tests (test_no_explain_before_tool, test_tool_call_json_in_content)
   - Format Compliance: Could validate JSON/markdown quality
   - Instruction Following: Could check for constraint violations

2. **Model-Specific Tuning**
   - Different penalty weights per model family
   - Adaptive thresholds based on model capabilities

3. **Response Improvement Feedback**
   - Suggest specific fixes for detected anti-patterns
   - Link to model-specific hints in AGENTS.md

## References

- **Implementation:** `benchmarks/llm-eval/response_quality.py`
- **Integration:** `benchmarks/llm-eval/test_cases.py`
- **Results:** `benchmarks/llm-eval/results/perplexity_*_2026-02-08_*.json`
- **Discovery:** `docs/PERPLEXITY-BENCHMARK-ANALYSIS.md`
