# Gemini Models Tuning Plan (v1.15.3)

**Created:** 2026-02-08
**Models:** gemini-2.5-pro, gemini-3-flash-preview, gemini-3-pro-preview
**Objective:** Optimize generation parameters for agentic coding tasks

---

## Executive Summary

This document outlines the systematic tuning plan for three Gemini models to optimize performance for agentic coding assistant tasks. Based on initial benchmark results, we need to improve tool calling performance across all models while preserving their strengths.

### Baseline Performance

| Model | Overall | Tool Calling | Code Editing | Hallucination Resistance | Key Strengths |
|-------|---------|--------------|--------------|--------------------------|---------------|
| **gemini-2.5-pro** | 56.3% | 14.3% ⚠️ | 71.4% ✅ | 55.6% | Code editing, format compliance (100%) |
| **gemini-3-flash-preview** | 62.5% | 28.6% ⚠️ | 42.9% | 77.8% ✅ | Hallucination resistance, fast |
| **gemini-3-pro-preview** | 70.3% | 50.0% | 100% ✅ | 55.6% | **Best overall**, perfect code editing |

### Key Findings from Gemini 2.5 Flash Experiments

1. **CRITICAL:** `frequency_penalty` breaks Gemini code editing (causes 0% score)
2. **Unified diff incompatibility:** Patch format has repetitive patterns that get penalized
3. **Baseline works best:** temperature 0.2, top_p 0.9, NO frequency_penalty
4. **Tool calling issues:** All models output JSON in content instead of using native tool calls

---

## Common Issues Across All Models

### 1. Tool Calling Problems (14.3%-50%)

**Symptoms:**
- "Tool call JSON found in content instead of tool_calls"
- "No tool call made" - model explains instead of acting
- Wrong tool selection
- Truncated large payloads

**Root Causes:**
- Models prefer explaining actions before taking them
- Native tool calling not fully reliable
- Output truncation with large tool calls (no max_output_tokens set)

**Mitigation Strategies:**
1. Add explicit `max_output_tokens` to prevent truncation
2. Test higher temperature (0.3-0.4) to increase action-taking vs explaining
3. Provider-level system prompt: "Call tools directly without explaining first"

### 2. Code Editing Variability (42.9%-100%)

**Symptoms:**
- gemini-3-pro-preview: 100% (perfect)
- gemini-2.5-pro: 71.4% (good)
- gemini-3-flash-preview: 42.9% (needs work)

**Known Issues:**
- `frequency_penalty` completely breaks patch generation (0%)
- Some models generate empty patches
- Missing imports in multiline patches

### 3. Hallucination Resistance (55.6%-77.8%)

**Patterns:**
- Not acknowledging tool failures
- Contradicting tool results
- Not acknowledging persistent failures

---

## Tuning Plan

### Experimental Approach

For each model, we'll test 4 parameter sets:

| Experiment | Temperature | Top P | Frequency Penalty | Max Output Tokens | Rationale |
|------------|-------------|-------|-------------------|-------------------|-----------|
| **Baseline** | 0.2 | 0.9 | None | None | Current settings |
| **Exp 1: Action-Oriented** | 0.4 | 0.9 | None | 8192 | Higher temp for more tool calls, prevent truncation |
| **Exp 2: Max Tokens Only** | 0.2 | 0.9 | None | 8192 | Test if truncation is the issue |
| **Exp 3: Lower Top-P** | 0.2 | 0.85 | None | 8192 | More focused output |

**SKIP:** Any experiments with `frequency_penalty` (proven to break code editing)

---

## Model-Specific Plans

### 1. gemini-2.5-pro

**Current State:**
- Overall: 56.3%
- Tool calling: 14.3% (catastrophic)
- Code editing: 71.4% (good)

**Critical Failures:**
- `simple_tool_call`: "No tool call made" - explains instead
- `complex_args`: Wrong tool (execute_shell_command instead of write_file)
- `large_payload`: Truncated to content text
- `multi_tool_sequence`: No tool call in first turn
- `no_json_in_content`: JSON in text

**Priority:** Fix tool calling (14.3% → 50%+)

**Experiments:**
1. **Baseline verification** (temp 0.2, top_p 0.9, no penalties)
2. **Action-oriented** (temp 0.4, top_p 0.9, max_tokens 8192)
3. **Max tokens focus** (temp 0.2, top_p 0.9, max_tokens 8192)
4. **Focused output** (temp 0.2, top_p 0.85, max_tokens 8192)

**Success Criteria:**
- Tool calling: 14.3% → 40%+ (baseline acceptable)
- Code editing: Maintain 71.4% (must not drop)
- Overall: 56.3% → 65%+

**Skip Criteria:**
- If tool calling doesn't improve after Exp 2, document as model limitation
- Consider recommending gemini-3-pro-preview instead

---

### 2. gemini-3-flash-preview

**Current State:**
- Overall: 62.5%
- Tool calling: 28.6%
- Code editing: 42.9%
- Hallucination resistance: 77.8% (best)

**Critical Failures:**
- `simple_tool_call`: Wrong path (None instead of /src/main.py)
- `large_payload`: Truncated
- `multi_tool_sequence`: Didn't use info from first tool
- `no_json_in_content`: JSON in text
- `patch_simple`: Empty patch
- `patch_multiline`: Missing json import

**Priority:** Improve code editing (42.9% → 60%+) while maintaining hallucination resistance

**Experiments:**
1. **Baseline verification** (temp 0.2, top_p 0.9, no penalties)
2. **Action-oriented** (temp 0.4, top_p 0.9, max_tokens 8192)
3. **Max tokens focus** (temp 0.2, top_p 0.9, max_tokens 8192)
4. **Moderate temp** (temp 0.3, top_p 0.9, max_tokens 8192)

**Success Criteria:**
- Code editing: 42.9% → 57%+ (match gemini-2.5-flash historical)
- Tool calling: 28.6% → 40%+
- Hallucination resistance: Maintain 77.8% (critical strength)
- Overall: 62.5% → 70%+

---

### 3. gemini-3-pro-preview

**Current State:**
- Overall: 70.3% (best)
- Tool calling: 50.0%
- Code editing: 100% (perfect!)
- Error recovery: 66.7% (best)

**Critical Failures:**
- `repeated_failure_acknowledgment`: Didn't acknowledge persistent failure
- `contradiction_detection`: Model contradicted tool result
- `multi_tool_sequence`: Timeout
- `no_explain_before_tool`: Timeout
- `no_json_in_content`: JSON in text

**Priority:** Improve tool calling (50% → 70%+) without breaking code editing

**Experiments:**
1. **Baseline verification** (temp 0.2, top_p 0.9, no penalties)
2. **Action-oriented** (temp 0.4, top_p 0.9, max_tokens 8192)
3. **Max tokens focus** (temp 0.2, top_p 0.9, max_tokens 8192)
4. **Moderate increase** (temp 0.3, top_p 0.9, max_tokens 8192)

**Success Criteria:**
- Tool calling: 50% → 70%+ (match best-in-class)
- Code editing: Maintain 100% (CRITICAL - must not drop)
- Overall: 70.3% → 80%+

**Risk Mitigation:**
- If any experiment drops code editing below 100%, immediately revert
- This model is already the strongest - conservative tuning

---

## Execution Strategy

### Phase 1: Baseline Verification (1 hour)
Run all three models with current optimal settings to confirm reproducibility.

**Config:**
```json
{
  "generation_params": {
    "temperature": 0.2,
    "top_p": 0.9
  }
}
```

### Phase 2: Action-Oriented Tuning (3 hours)
Test higher temperature to encourage tool calling over explanation.

**Config:**
```json
{
  "generation_params": {
    "temperature": 0.4,
    "top_p": 0.9,
    "max_output_tokens": 8192
  }
}
```

### Phase 3: Max Tokens Focus (3 hours)
Test if truncation is the primary issue.

**Config:**
```json
{
  "generation_params": {
    "temperature": 0.2,
    "top_p": 0.9,
    "max_output_tokens": 8192
  }
}
```

### Phase 4: Focused Output (3 hours)
Test lower top_p for more deterministic tool selection.

**Config:**
```json
{
  "generation_params": {
    "temperature": 0.2,
    "top_p": 0.85,
    "max_output_tokens": 8192
  }
}
```

### Phase 5: Analysis and Recommendations (1 hour)
Compare all results and create final recommendations.

---

## Success Metrics

### Overall Success Criteria

| Model | Current | Target | Minimum Acceptable |
|-------|---------|--------|--------------------|
| gemini-2.5-pro | 56.3% | 65%+ | 60%+ |
| gemini-3-flash-preview | 62.5% | 70%+ | 68%+ |
| gemini-3-pro-preview | 70.3% | 80%+ | 75%+ |

### Category Success Criteria

**Tool Calling (Critical):**
- gemini-2.5-pro: 14.3% → 40%+ (acceptable), 50%+ (good)
- gemini-3-flash-preview: 28.6% → 40%+ (acceptable), 50%+ (good)
- gemini-3-pro-preview: 50% → 70%+ (target)

**Code Editing (Must Preserve):**
- gemini-2.5-pro: Maintain 71.4%
- gemini-3-flash-preview: 42.9% → 57%+
- gemini-3-pro-preview: Maintain 100% (CRITICAL)

**Hallucination Resistance:**
- gemini-3-flash-preview: Maintain 77.8% (strength)
- Others: Improve to 70%+

---

## Risk Assessment

### High Risk
1. **Breaking gemini-3-pro-preview code editing** (currently 100%)
   - Mitigation: Conservative tuning, immediate revert on any drop

2. **Degrading gemini-3-flash-preview hallucination resistance** (currently 77.8%)
   - Mitigation: Monitor closely, prefer lower temperature experiments

### Medium Risk
1. **Tool calling doesn't improve** with parameter changes
   - Mitigation: Document as model limitation, recommend gemini-3-pro-preview

2. **Timeout issues increase** with higher output tokens
   - Mitigation: Use 120s timeout per test, monitor duration

### Low Risk
1. Format compliance and instruction following should remain at 100%
2. Reasoning scores stable across parameter ranges

---

## Post-Tuning Analysis Plan

After all experiments complete:

1. **Compare Results Table**
   - All models × all experiments in single table
   - Highlight best performer per category

2. **Optimal Settings Recommendations**
   - Per-model optimal generation_params
   - Use case recommendations (when to use which model)

3. **Update Configuration Files**
   - `ppxai-config.example.json`
   - `ppxai-config.json` (repo)
   - User config (`~/.ppxai/ppxai-config.json`)

4. **Documentation Updates**
   - Create `docs/GEMINI-BENCHMARK-ANALYSIS.md`
   - Update `CLAUDE.md` with findings
   - Update model descriptions in configs with benchmark data

---

## Timeline

| Phase | Duration | Cumulative |
|-------|----------|------------|
| Baseline Verification | 1 hour | 1 hour |
| Action-Oriented (3 models) | 3 hours | 4 hours |
| Max Tokens Focus (3 models) | 3 hours | 7 hours |
| Focused Output (3 models) | 3 hours | 10 hours |
| Analysis & Documentation | 1 hour | 11 hours |

**Total Estimated Time:** 11 hours (can be run in background)

---

## Tools and Commands

### Run Single Benchmark
```bash
uv run python benchmarks/llm-eval/benchmark.py \
  --provider gemini \
  --model gemini-3-pro-preview \
  --timeout 120
```

### Compare Results
```bash
uv run python benchmarks/llm-eval/benchmark.py \
  --provider gemini \
  --model gemini-3-pro-preview \
  --compare
```

### Check Config
```bash
cat ~/.ppxai/ppxai-config.json | grep -A 20 '"gemini"'
```

---

## Notes

- All experiments use user config at `~/.ppxai/ppxai-config.json`
- Benchmark timeout: 120s per test (default)
- Results saved to: `benchmarks/llm-eval/results/`
- Comparison shows change vs most recent run for same provider/model
