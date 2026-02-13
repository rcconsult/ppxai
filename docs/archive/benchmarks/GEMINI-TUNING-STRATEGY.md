# Gemini Tuning Strategy

**Date:** 2026-02-08
**Context:** After discovering gemini-2.5-flash model regression, we need a comprehensive tuning strategy

---

## Executive Summary

Based on the regression analysis, we have three tuning levers:
1. **Generation Parameters** (temperature, max_tokens, top_p, etc.)
2. **System Prompts** (provider-specific instructions)
3. **AGENTS.md Hints** (dynamic provider/model-specific guidance)

**Current Status:**
- ✅ Generation params: Configured per provider/model in `ppxai-config.json`
- ⚠️ System prompts: Generic, not optimized for code editing
- ⚠️ AGENTS.md hints: Generic gemini hints, no model-specific tuning

---

## 1. Debug Logging Analysis

### What --debug Captures

Running benchmarks with `--debug` creates detailed logs in `benchmarks/llm-eval/debug/`:

```bash
python benchmark.py --provider gemini --model gemini-3-flash-preview --categories code_editing --debug
```

**Captures:**
- `request_NNN.json` - Full request details:
  - System prompt used
  - User message
  - Tool definitions (if native) or tool prompt (if prompt-based)
  - Complete API response
  - Tool calls made
  - Finish reason
- `test_NNN_category_name.json` - Test outcomes:
  - Attempts per test
  - Pass/fail status
  - Test-specific details (patch_length, tool names, etc.)
- `SUMMARY.json` - Aggregate results

**Example Request Log:**
```json
{
  "request_id": 1,
  "provider": "gemini",
  "model": "gemini-3-flash-preview",
  "messages": [
    {
      "role": "system",
      "content": "You are a coding assistant. Use apply_patch to modify files."
    },
    {
      "role": "user",
      "content": "Here is /src/hello.py:\n..."
    }
  ],
  "tools_provided": 6,
  "tools": ["read_file", "write_file", "apply_patch", ...],
  "response": {
    "content": "...",
    "tool_calls": [...],
    "finish_reason": "tool_calls"
  }
}
```

### Why Workaround Logs Weren't Visible

**Problem:** The `logger.warning()` calls in gemini.py didn't appear in benchmark output.

**Root Cause:** The benchmark runner doesn't configure Python logging. Logger messages go nowhere unless:
1. `PPXAI_LOG_LEVEL=DEBUG` environment variable is set
2. Python logging is configured (not done in benchmark.py)

**Evidence:**
```python
# In gemini.py (lines 185-189)
logger.warning(
    f"Gemini SDK workaround: Filtered {empty_count}/{len(parts)} empty parts "
    f"from {context} response (Issue #1789)"
)
```

This warning never appeared because the benchmark doesn't import/configure the ppxai logger.

**Solution:** Add logging configuration to benchmark runner:
```python
# In engine_runner.py __init__
if debug or os.getenv("PPXAI_LOG_LEVEL"):
    from ppxai.common.logger import configure_logging
    configure_logging("DEBUG")
```

---

## 2. Current Tuning Configuration

### Generation Parameters (ppxai-config.json)

```json
{
  "providers": {
    "gemini": {
      "models": {
        "gemini-3-flash-preview": {
          "generation_params": {
            "temperature": 0.2,
            "max_output_tokens": 8192
          }
        }
      }
    }
  }
}
```

**Status:** ✅ Configured and working

### System Prompts (ppxai-config.json)

Currently using default system prompt from `ppxai/config/__init__.py`:

```python
DEFAULT_SYSTEM_PROMPTS = {
    "global": "You are a helpful AI assistant...",
    "gemini": "You are a helpful AI assistant...",  # Same as global
}
```

**Status:** ⚠️ Generic, not optimized for code editing

### AGENTS.md Hints (AGENTS.md)

Current gemini hints:
```yaml
provider_hints:
  gemini:
    - "Use Google Search grounding for current information when available."
    - "You have a 1M token context - feel free to include full file contents."
```

**Status:** ⚠️ No code editing guidance, no model-specific hints

---

## 3. Tuning Strategy

### Phase 1: Enhanced AGENTS.md Hints ✅ RECOMMENDED

Add model-specific hints for code editing:

```yaml
provider_hints:
  gemini:
    - "Use Google Search grounding for current information when available."
    - "You have a 1M token context - feel free to include full file contents."
    - "For code modifications, ALWAYS use apply_patch with unified diff format."
    - "Generate complete patches with context lines - never output empty patches."
    - "Call tools directly without explanation - don't say 'I'll use X tool'."

model_hints:
  "gemini-3-flash*":
    - "You excel at code editing - use apply_patch confidently."
    - "Include all necessary imports in patches."
    - "Verify tool exists before calling - don't hallucinate tools."

  "gemini-2.5-flash*":
    - "CRITICAL: Always use apply_patch for file modifications, not read_file."
    - "Generate patches immediately - don't explain what you'll do first."

  "gemini-2.5-pro*":
    - "Focus on tool selection accuracy - prefer specialized tools like apply_patch."
    - "For file operations, prefer apply_patch over write_file for existing files."
```

**Why This Works:**
- Dynamic - applies hints based on current provider/model
- Non-invasive - doesn't require code changes
- Testable - can A/B test with/without hints
- Per-user - users can customize in `~/.ppxai/AGENTS.md`

### Phase 2: Optimized System Prompts

Add gemini-specific system prompt to config:

```json
{
  "providers": {
    "gemini": {
      "system_prompt": "You are an expert coding assistant specializing in precise code modifications.\n\nKey capabilities:\n- Use apply_patch with unified diff format for file modifications\n- Call tools directly without explanation\n- Generate complete, valid patches with proper context\n- Focus on tool calling accuracy over verbose responses\n\nAvailable tools: read_file, write_file, apply_patch, run_command, search_code, get_diagnostics"
    }
  }
}
```

**Why This Works:**
- Sets clear expectations upfront
- Emphasizes tool calling behavior
- Reminds model of available tools (reduces hallucinations)

### Phase 3: Generation Parameter Tuning

Test different temperature/max_tokens combinations:

| Model | Temperature | Max Tokens | Hypothesis |
|-------|-------------|------------|------------|
| gemini-3-flash | 0.1 | 8192 | Lower temp = more deterministic tool calls |
| gemini-3-flash | 0.2 | 8192 | Baseline |
| gemini-3-flash | 0.3 | 8192 | Higher temp = more creative (may worsen) |
| gemini-2.5-flash | 0.1 | 8192 | See if lower temp restores code editing |
| gemini-2.5-pro | 0.1 | 8192 | See if lower temp improves tool calling |

**Why This Works:**
- Temperature affects sampling - lower = more consistent
- Max tokens prevents truncation of long patches

### Phase 4: Benchmark With Enhanced Prompts

Run A/B test:

**Control (current):**
```bash
python benchmark.py --provider gemini --model gemini-3-flash-preview
```

**Treatment (with hints):**
1. Add hints to AGENTS.md (Phase 1)
2. Run benchmark
3. Compare results

**Expected Improvement:**
- gemini-3-flash-preview: 71.4% → 85%+ (reduce hallucinated tools)
- gemini-2.5-flash: 0% → 30%+ (encourage apply_patch usage)
- gemini-2.5-pro: 0% → 20%+ (improve tool selection)

---

## 4. Implementation Plan

### Step 1: Update AGENTS.md ✅

Add enhanced hints (see Phase 1 above).

### Step 2: Benchmark Baseline (No Hints)

```bash
# Rename current AGENTS.md to disable hints
mv AGENTS.md AGENTS.md.backup

# Run benchmark
python benchmark.py --provider gemini --model gemini-3-flash-preview --debug

# Restore AGENTS.md
mv AGENTS.md.backup AGENTS.md
```

### Step 3: Benchmark with Hints

```bash
# With enhanced AGENTS.md
python benchmark.py --provider gemini --model gemini-3-flash-preview --debug
```

### Step 4: Compare Results

Look for:
- Reduced hallucinated tool calls
- Higher code editing scores
- More consistent apply_patch usage

### Step 5: System Prompt Tuning (If Hints Insufficient)

If Phase 1 (hints) doesn't improve scores enough:
1. Add optimized system prompt to config (Phase 2)
2. Re-run benchmarks
3. Measure incremental improvement

### Step 6: Generation Parameter Sweep (Fine-Tuning)

Once hints + system prompt are optimized:
1. Test temperature variations (0.1, 0.2, 0.3)
2. Test max_tokens variations (4096, 8192, 16384)
3. Find optimal combination

---

## 5. Why AGENTS.md Hints Are Preferred

### Advantages

1. **Dynamic:** Applied per provider/model automatically
2. **User-Customizable:** Users can add their own hints in `~/.ppxai/AGENTS.md`
3. **Hierarchical:** Global → project → subdir hints merge additively
4. **Non-Invasive:** No code changes required
5. **Testable:** Easy to A/B test with/without hints
6. **Documented:** Clear what guidance was given

### Disadvantages

1. **Not in Benchmark:** Current benchmark doesn't load AGENTS.md
2. **Requires Bootstrap:** Only works when bootstrap context is loaded
3. **User Awareness:** Users must know to check AGENTS.md

### Solution

Add AGENTS.md loading to benchmark runner:

```python
# In engine_runner.py
from ppxai.engine.bootstrap import BootstrapContext

class EngineBenchmarkRunner:
    def __init__(self, provider, model, ...):
        # ... existing code ...

        # Load AGENTS.md if present
        agents_md = Path("AGENTS.md")
        if agents_md.exists():
            self.bootstrap_context = BootstrapContext.from_file(agents_md)
        else:
            self.bootstrap_context = None

    def _prepare_messages(self, test_prompt):
        system_prompt = "You are a coding assistant..."

        # Add AGENTS.md hints if loaded
        if self.bootstrap_context:
            hints_prompt = self.bootstrap_context.get_prompt_for(
                self.provider, self.model
            )
            if hints_prompt:
                system_prompt = f"{hints_prompt}\n\n{system_prompt}"

        return [{"role": "system", "content": system_prompt}, ...]
```

---

## 6. Expected Outcomes

### With Enhanced AGENTS.md Hints

| Model | Current | Target | Improvement |
|-------|---------|--------|-------------|
| gemini-3-flash-preview | 71.4% | 85%+ | +14% (reduce hallucinations) |
| gemini-3-pro-preview | 28.6% | 50%+ | +21% (encourage apply_patch) |
| gemini-2.5-flash | 0% | 30%+ | +30% (restore basic function) |
| gemini-2.5-pro | 0% | 20%+ | +20% (improve tool selection) |

### With System Prompt + Hints

| Model | Hints Only | + System Prompt | Total Improvement |
|-------|------------|-----------------|-------------------|
| gemini-3-flash | 85% | 90%+ | +19% from baseline |
| gemini-3-pro | 50% | 60%+ | +31% from baseline |

### With Full Tuning (Hints + Prompt + Params)

| Model | Baseline | Fully Tuned | Total Improvement |
|-------|----------|-------------|-------------------|
| gemini-3-flash | 71.4% | 95%+ | +24% |
| gemini-3-pro | 28.6% | 70%+ | +41% |

---

## 7. Monitoring & Iteration

### Track Over Time

1. **Model Version Fingerprinting:**
   - Hash of first 3 test responses
   - Detect when Google updates models

2. **Weekly Benchmarks:**
   - Re-run benchmarks weekly
   - Detect regressions early

3. **A/B Testing:**
   - Control: No hints
   - Treatment: With hints
   - Measure delta

### Iterate on Hints

If scores don't improve:
1. Review debug logs for failure patterns
2. Refine hints to address specific issues
3. Re-test

---

## 8. Next Steps

1. ✅ Document tuning strategy (this file)
2. ⏳ Update AGENTS.md with enhanced hints
3. ⏳ Add AGENTS.md loading to benchmark runner
4. ⏳ Run A/B test: baseline vs hints
5. ⏳ Add logging configuration to benchmark
6. ⏳ Implement model version fingerprinting
7. ⏳ Document results in GEMINI-COMPREHENSIVE-BENCHMARK-ANALYSIS.md

---

## References

- [GEMINI-COMPREHENSIVE-BENCHMARK-ANALYSIS.md](GEMINI-COMPREHENSIVE-BENCHMARK-ANALYSIS.md) - Full regression analysis
- [GEMINI-MODEL-REGRESSION.md](GEMINI-MODEL-REGRESSION.md) - Initial findings
- [AGENTS.md](../AGENTS.md) - Current provider/model hints
- [ppxai/engine/bootstrap.py](../ppxai/engine/bootstrap.py) - Hint loading logic
- [ppxai/engine/chat.py](../ppxai/engine/chat.py) - Prompt assembly
