# GPT-OSS & DGX Spark vLLM Tuning Plan (v1.15.3)

**Created:** 2026-02-09
**Status:** COMPLETED 2026-02-09
**Models:** GPT-OSS 120B (`custom`), Qwen3-Coder-30B-A3B FP8 (`asusai-vllm`)
**Scope:** 2 vLLM endpoints only (Ollama models deferred)
**Objective:** Apply the same evidence-based tuning that achieved +25.2% avg improvement across Gemini/Perplexity

---

## Results Summary

### Qwen3-Coder FP8 (asusai-vllm) - Best: 75.0% (+18.8%)

| Phase | Overall | Code Edit | Tool Call | Hallucin. | Reasoning | Error Rec |
|-------|---------|-----------|-----------|-----------|-----------|-----------|
| Phase 1 (baseline) | **56.2%** | 71.4% | 64.3% | 33.3% | 33.3% | 66.7% |
| Phase 2 (hints+fix) | **68.8%** | 71.4% | 85.7% | 33.3% | 100% | 100% |
| Phase 3 (freq=0.0) | **75.0%** | 71.4% | **100%** | 33.3% | **100%** | **100%** |

**Optimal config:** `frequency_penalty: 0.0`, 10 model hints, 9 provider hints

### GPT-OSS 120B (custom) - Best: 68.8% (+25.0%)

| Phase | Overall | Code Edit | Tool Call | Hallucin. | Reasoning | Error Rec |
|-------|---------|-----------|-----------|-----------|-----------|-----------|
| Phase 1 (baseline) | **43.8%** | 0% | 42.9% | 16.7% | 66.7% | 66.7% |
| Phase 2 (hints+fix) | **68.8%** | 28.6% | 50.0% | 55.6% | **100%** | **100%** |
| Phase 3 (freq=0.0) | **65.6%** | 0% | 78.6% | 55.6% | 66.7% | 66.7% |

**Optimal config:** `frequency_penalty: 0.1` (0.0 didn't help), 10 model hints, 9 provider hints

### Key Findings

1. **Charmap encoding bug** caused 7+ test crashes on Windows (cp1252 can't encode Unicode)
   - Fixed with `sys.stdout.reconfigure(encoding='utf-8', errors='replace')` in benchmark.py
   - This alone recovered multiple lost test passes
2. **AGENTS.md hints** addressed 8 anti-patterns: hallucinated tools, wrong parameter names, JSON in content, explains before tool, claims success on failure, duplicate calls, large payload truncation, missing imports
3. **frequency_penalty=0.0** is optimal for Qwen3-Coder (100% tool_calling), neutral/slightly negative for GPT-OSS
4. **Hallucination resistance** remains the weakest category (33.3% for both) - not improvable via hints alone; would need system prompt or model-level changes
5. **High variance** across runs (especially GPT-OSS) means single-run scores have ±10-15% noise
6. **Harmony parser is NOT the issue** for GPT-OSS code_editing failures (verified 2026-02-09)
   - vLLM nightly (Jan 20, 2026) fixed the Harmony parser - all tool calls parse correctly
   - All 3 code_editing tests show `finish_reason: "tool_calls"` (native tool calls work)
   - No HarmonyError or "unexpected tokens" in any debug logs
   - Failures are **model behavioral**: hallucinated param names (`file_path`/`unified_diff` instead of `path`/`patch`), redundant duplicate tool calls (2-3 per task), wrong tool choice (write_file instead of apply_patch), and hallucinated file state ("already present")

### Qwen3-Next-80B-A3B Testing (2026-02-10)

| Variant | Status | Score | Notes |
|---------|--------|-------|-------|
| NVFP4 | **BROKEN** | N/A | CUTLASS MoE kernel crash on SM12.1, `--enforce-eager` also fails |
| FP8 | Works | **54.7%** | TRITON FP8 MoE backend, 74.89 GiB loaded, 29.81 GiB KV cache |
| FP8 + hints | Works | **54.7%** | 13 targeted hints had **0% effect** — identical results |

**FP8 Category Breakdown:** code_editing 0%, hallucination_resistance 16.7%, tool_calling 85.7%, reasoning 100%, error_recovery 100%

**Key Finding #7:** General-purpose models (Qwen3-Next) are not improvable via AGENTS.md hints for coding tasks. The model fundamentally lacks apply_patch discipline — it reads files then outputs code in text, makes duplicate tool calls with alternate param names (`path` + `filepath`), and hallucates tools (`run_command`, `list_directory`). Code-specialized models (Qwen3-Coder) respond to hints because they already have the tool-calling foundation.

**Decision:** Restored Qwen3-Coder-30B FP8 (81.2%) as DGX Spark production model. Qwen3-Next cached for potential future NVFP4 kernel fix or Qwen3-Coder-Next testing.

### Qwen3-Coder-Next-FP8 Testing (2026-02-12)

**Architecture:** 80B total / 3B active, 512 experts (10 active + 1 shared), Gated DeltaNet + Gated Attention hybrid, `Qwen3NextForCausalLM`, 256K native context.

**vLLM Setup:** `qwen3_coder` tool call parser (confirmed available in vLLM 0.16.0rc1), `--entrypoint vllm` override required (same as production container), 74.89 GiB GPU memory, TRITON FP8 MoE backend, FLASHINFER attention.

**Three benchmark runs** tested different parser and parameter combinations:

| Run | Date | Parser | Temp | Top P | Overall | Passed | Duration |
|-----|------|--------|------|-------|---------|--------|----------|
| 1 | Feb 10 | hermes | 0.2 | 0.9 | **60.9%** | 18/26 | 818s |
| 2 | Feb 12 | qwen3_coder | 1.0 | 0.95 | **57.8%** | 17/26 | 630s |
| 3 | Feb 12 | qwen3_coder | 0.2 | 0.9 | **54.7%** | 16/26 | 927s |

**Per-category breakdown (all 3 runs):**

| Category | Run 1 (hermes) | Run 2 (qwen3_coder, t=1.0) | Run 3 (qwen3_coder, t=0.2) | Variance |
|----------|---------------|---------------------------|---------------------------|----------|
| code_editing | 57.1% | 57.1% | **100%** | High |
| error_recovery | 66.7% | **100%** | 33.3% | **Extreme** |
| format_compliance | 100% | 100% | 100% | None |
| hallucination_resistance | 33.3% | 33.3% | 16.7% | Moderate |
| instruction_following | 57.1% | 28.6% | 28.6% | High |
| reasoning | 100% | 66.7% | 100% | High |
| tool_calling | 64.3% | 64.3% | 64.3% | **None** |

**Consistent failures (all 3 runs):** `respects_tool_failure`, `repeated_failure_acknowledgment`, `contradiction_detection` (hallucination_resistance), `large_payload` (tool_calling — timeout or truncation), `constraint_respect` (instruction_following), `patch_indentation` or `do_not_explain` (alternating).

**Key Finding #8:** Qwen3-Coder-Next FP8 is **not competitive** with Qwen3-Coder-30B FP8 (81.2%):
- **20+ points below production** across all 3 runs (54.7%–60.9%)
- **Extreme variance** in error_recovery (33%–100%) and code_editing (57%–100%) — unreliable
- **Persistent weaknesses** in hallucination_resistance (16.7%–33.3%) and tool_calling (stuck at 64.3%)
- **qwen3_coder parser didn't help** — scores were lower (57.8%, 54.7%) vs hermes (60.9%)
- **Temperature insensitive** — t=1.0 and t=0.2 both underperform, different failure modes
- 24 AGENTS.md hints loaded (Qwen/Qwen3-Coder* + *Qwen3-Next* patterns merged) — no meaningful improvement

**Decision:** Qwen3-Coder-Next is not viable for production. Stopped test container, restored Qwen3-Coder-30B FP8 (container 913d32a3acdd). Model cached for future re-evaluation if Qwen releases improved checkpoint.

### Model Evaluation Summary (as of 2026-02-12)

| Model | Type | Active | Best Score | Speed | Verdict |
|-------|------|--------|------------|-------|---------|
| **Qwen3-Coder-30B FP8** | MoE | 3B | **81.2%** | ~50 t/s | **PRODUCTION** |
| Qwen3-Coder-30B + eagle3 | MoE+spec | 3B | 70.3% | ~67 t/s | Reverted (quality loss) |
| GPT-OSS 120B (remote) | Dense | 120B | 68.8% | cloud | Good with hints |
| Qwen3-Coder-Next FP8 | MoE | 3B | 60.9% | ~43 t/s | Not competitive (high variance) |
| Qwen3-Next-80B Thinking FP8 | MoE | 3B | 57.8% | ~12 t/s | Slow, same flaws |
| Qwen3-Next-80B FP8 | MoE | 3B | 54.7% | ~50 t/s | Hints had 0% effect |
| Qwen2.5-Coder-32B BF16 | Dense | 32B | aborted | ~4 t/s | Too slow (dense on single GPU) |

### Changes Made

1. **AGENTS.md** - Added 38+13 hints (custom: 7, asusai-vllm: 9, gpt-oss*: 8, Qwen/Qwen3-Coder*: 10, *Qwen3-Next*: 13, qwen2.5-coder*: 4)
2. **ppxai-config.json** - Set `frequency_penalty: 0.0` for asusai-vllm; added Qwen3-Next FP8 + NVFP4 + Qwen3-Coder-Next FP8 model entries
3. **benchmark.py** - UTF-8 stdout/stderr encoding fix for Windows
4. **engine_runner.py** - (encoding fix reverted, handled at benchmark.py level)

---

## CRITICAL: Config File Usage

The benchmark runner uses `ppxai.config.find_config_file()` which searches:
1. `PPXAI_CONFIG_FILE` environment variable
2. `./ppxai-config.json` (project-local — the repo config)
3. `~/.ppxai/ppxai-config.json` (user config)

The `custom` and `asusai-vllm` providers are defined **only in the user config** at `~/.ppxai/ppxai-config.json`. The repo config does NOT contain these providers.

**All benchmark commands MUST set `PPXAI_CONFIG_FILE`:**

```bash
# Windows cmd
set PPXAI_CONFIG_FILE=%USERPROFILE%\.ppxai\ppxai-config.json

# Windows PowerShell
$env:PPXAI_CONFIG_FILE = "$env:USERPROFILE\.ppxai\ppxai-config.json"

# Linux/macOS
export PPXAI_CONFIG_FILE="$HOME/.ppxai/ppxai-config.json"
```

**Verify before running benchmarks:**
```bash
set PPXAI_CONFIG_FILE=%USERPROFILE%\.ppxai\ppxai-config.json && set UV_NATIVE_TLS=true && .uv\uv run python -c "from ppxai.config import initialize, PROVIDERS; initialize(); print([p for p in PROVIDERS])"
```

Expected output should include `custom` and `asusai-vllm`.

---

## Current State (from `~/.ppxai/ppxai-config.json`)

### Provider Configurations

| Setting | `custom` (GPT-OSS 120B) | `asusai-vllm` (Qwen3-Coder FP8) |
|---------|-------------------------|----------------------------------|
| **Base URL** | `https://your-gpt-oss-host/v1` | `http://your-vllm-host:8000/v1` |
| **API key env** | `CUSTOM_API_KEY` | `OLLAMA_API_KEY` |
| **Model ID** | `openai/gpt-oss-120b` | `Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8` |
| **Context limit** | 131,072 | 131,072 |
| **Max tokens** | 8,192 | 8,192 |
| **Temperature** | 0.2 | 0.2 |
| **Top P** | 0.9 | 0.9 |
| **Frequency penalty** | 0.1 | 0.1 |
| **Presence penalty** | 0.05 | — |
| **Native tool calling** | Yes (Harmony parser) | Yes (qwen3_coder parser) |
| **vLLM parser flag** | `--tool-call-parser openai` | `--tool-call-parser qwen3_coder` |

### System Prompts

**`custom` — Already tuned (8 rules):**
```
You are a helpful AI coding assistant. Be concise and direct.

CRITICAL TOOL RULES:
1. NEVER say 'I'll use the X tool' and then output JSON - just call the tool directly
2. Do NOT output tool calls as JSON in your response - use native tool calling
3. If you need a tool, call it immediately without explanation
4. Only explain AFTER the tool returns its result
5. After display_file: confirm 'File opened: <filename>'
6. For pip/npm: warn 'May take time (timeout: 120s)'
7. Prefer read_file over cat/type commands
8. Use replace_block/insert_text/apply_patch for editing

On Windows: Use PowerShell syntax. Bash heredocs (<<EOF) and $() don't work.
```

**`asusai-vllm` — Generic, not tuned:**
```
You are an expert coding assistant running on a local NVIDIA GB10 GPU via vLLM. Be concise and precise. When using tools, execute them directly and report results briefly. Focus on code quality, correctness, and best practices.
```

### AGENTS.md Hints

| Target | Current Hints | Gemini/Perplexity Equivalent |
|--------|--------------|------------------------------|
| `custom` provider | 2 generic | Gemini: 10, Perplexity: 6 |
| `gpt-oss*` model | 2 generic | gemini-3-flash*: 7, sonar*: 7 |
| `asusai-vllm` provider | **0** | — |
| `Qwen/Qwen3-Coder*` model | **0** | — |

---

## Baseline Benchmarks (Binary, from 2026-02-06)

| Provider | Model | Overall | Tool Call | Code Edit | Hallucination | Error Rec | Key Failures |
|----------|-------|---------|-----------|-----------|---------------|-----------|--------------|
| **custom** | GPT-OSS 120B | **82.8%** | 78.6% | 71.4% | 77.8% | 100% | large_payload (0 chars), patch_multiline (missing import), respects_tool_failure |
| **asusai-vllm** | Qwen3-Coder FP8 | **81.2%** | 100% | 100% | — | 100% | (from DGX doc, not quality-validated) |

**Critical gap:** Neither model has been run through multi-criteria quality validation (anti-pattern detection). Binary scores may be misleading — Gemini/Perplexity showed avg -51.2% gap.

### GPT-OSS 120B Specific Failures

| Test | Category | Error | Weight |
|------|----------|-------|--------|
| `respects_tool_failure` | hallucination | Model didn't acknowledge the failures | 2.0 |
| `large_payload` | tool_calling | Content truncated: got 0 chars, expected ~3500 | 1.5 |
| `patch_multiline` | code_editing | Missing json import | 1.0 |
| `dependency_ordering` | reasoning | Didn't prioritize running tests first | 1.0 |

---

## Tuning Plan

### Phase 1: Multi-Criteria Quality Baseline (1 hour)

Re-run both models with quality validation and `--debug` to capture anti-patterns.

**Commands (Windows cmd):**
```bash
set PPXAI_CONFIG_FILE=%USERPROFILE%\.ppxai\ppxai-config.json && set UV_NATIVE_TLS=true

# GPT-OSS 120B
.uv\uv run python benchmarks\llm-eval\benchmark.py --provider custom --model openai/gpt-oss-120b --debug --verbose

# Qwen3-Coder-30B FP8 (DGX vLLM)
.uv\uv run python benchmarks\llm-eval\benchmark.py --provider asusai-vllm --model Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8 --debug --verbose
```

**PowerShell:**
```powershell
$env:PPXAI_CONFIG_FILE = "$env:USERPROFILE\.ppxai\ppxai-config.json"
$env:UV_NATIVE_TLS = "true"

.uv\uv run python benchmarks\llm-eval\benchmark.py --provider custom --model openai/gpt-oss-120b --debug --verbose
.uv\uv run python benchmarks\llm-eval\benchmark.py --provider asusai-vllm --model "Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8" --debug --verbose
```

**What to look for in debug logs:**
- `tool_json_in_content` — tool JSON in response text instead of native calls
- `duplicate_tool_calls` — same tool called multiple times
- `hallucinated_tools` — mentioning tools that weren't called
- `explained_before_tool` — "I'll use X tool" before calling
- `duplicate_code_in_content` — code blocks that duplicate tool output

---

### Phase 2: Evidence-Based AGENTS.md Hints (30 min)

After Phase 1 reveals anti-patterns, add targeted hints to `AGENTS.md`.

**Proposed hints (refine based on Phase 1 results):**

```yaml
provider_hints:
  custom:
    - "You have native tool calling - use tools directly without XML formatting."
    - "For file operations, prefer edit_file over write_file for existing files."
    - "CRITICAL: After tool failures, acknowledge the error - do NOT claim success."
    - "Do NOT output tool call JSON in your response text - use native tool calling only."
    - "For large file writes, ensure complete content - truncated output fails silently."
    - "When tools return errors, report the actual error to the user."
  asusai-vllm:
    - "You are running on NVIDIA GB10 with native tool calling via vLLM."
    - "Execute tools directly - never describe what you would do."
    - "CRITICAL: After tool failures, acknowledge the error - do NOT claim success."
    - "Do NOT output tool call JSON in your response text."
    - "For code modifications, ALWAYS use apply_patch with unified diff format."
    - "Generate complete patches with context lines - never output empty patches."

model_hints:
  "gpt-oss*":
    - "You are a coding specialist - prioritize working code over explanations."
    - "Execute tools immediately rather than describing what you would do."
    - "CRITICAL: Check tool_result before claiming success - if 'Error:', acknowledge it."
    - "For apply_patch: include ALL necessary imports (json, os, sys, etc.)."
    - "For large payloads: generate complete content, truncation breaks functionality."
    - "Make ONE tool call per action - do NOT make duplicate or redundant calls."
  "Qwen/Qwen3-Coder*":
    - "You excel at code editing - use apply_patch confidently."
    - "Include all necessary imports and context in patches."
    - "CRITICAL: Acknowledge tool failures honestly - never claim success after errors."
    - "Make ONE tool call per action - avoid duplicate calls."
    - "For complex patches: include ALL affected lines with 3+ context lines."
```

**A/B test command:**
```bash
set PPXAI_CONFIG_FILE=%USERPROFILE%\.ppxai\ppxai-config.json && set UV_NATIVE_TLS=true
.uv\uv run python benchmarks\llm-eval\benchmark.py --provider custom --model openai/gpt-oss-120b --debug --verbose
.uv\uv run python benchmarks\llm-eval\benchmark.py --provider asusai-vllm --model Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8 --debug --verbose
```

---

### Phase 3: Generation Parameter Tuning (2 hours)

**Key lesson from Gemini tuning:** `frequency_penalty` completely broke Gemini code editing (caused 0% score). Both models currently use `frequency_penalty: 0.1`.

All parameter changes are made in `~/.ppxai/ppxai-config.json`.

#### GPT-OSS 120B (`custom`)

Edit: `providers.custom.models["openai/gpt-oss-120b"].generation_params`

| Exp | Temp | Top P | Freq Pen | Pres Pen | Max Tokens | Rationale |
|-----|------|-------|----------|----------|------------|-----------|
| **Baseline** | 0.2 | 0.9 | 0.1 | 0.05 | 8192 | Current user config |
| **No penalties** | 0.2 | 0.9 | **0.0** | **0.0** | 8192 | Test if penalties break patches (Gemini lesson) |
| **Higher tokens** | 0.2 | 0.9 | 0.0 | 0.0 | **16384** | Large payload truncation was 0 chars |
| **Conservative** | 0.1 | 0.85 | 0.0 | 0.0 | 8192 | Most deterministic |

#### Qwen3-Coder-30B FP8 (`asusai-vllm`)

Edit: `providers["asusai-vllm"].generation_params` (provider-level, applies to default model)

| Exp | Temp | Top P | Freq Pen | Max Tokens | Rationale |
|-----|------|-------|----------|------------|-----------|
| **Baseline** | 0.2 | 0.9 | 0.1 | 8192 | Current |
| **No freq_penalty** | 0.2 | 0.9 | **0.0** | 8192 | Test Gemini-like breakage |
| **Conservative** | 0.1 | 0.9 | 0.0 | 8192 | Most deterministic |
| **Higher tokens** | 0.2 | 0.9 | 0.0 | **16384** | Prevent truncation |

**Workflow per experiment:**
1. Edit `~/.ppxai/ppxai-config.json` — update `generation_params`
2. Run: `set PPXAI_CONFIG_FILE=%USERPROFILE%\.ppxai\ppxai-config.json && set UV_NATIVE_TLS=true && .uv\uv run python benchmarks\llm-eval\benchmark.py --provider <provider> --model <model> --debug`
3. Record result
4. Next experiment

---

### Phase 4: System Prompt Optimization (30 min)

#### `custom` — Add hallucination resistance (rules 9-10)

Edit: `providers.custom.system_prompt` in `~/.ppxai/ppxai-config.json`

```
You are a helpful AI coding assistant. Be concise and direct.

CRITICAL TOOL RULES:
1. NEVER say 'I'll use the X tool' and then output JSON - just call the tool directly
2. Do NOT output tool calls as JSON in your response - use native tool calling
3. If you need a tool, call it immediately without explanation
4. Only explain AFTER the tool returns its result
5. After display_file: confirm 'File opened: <filename>'
6. For pip/npm: warn 'May take time (timeout: 120s)'
7. Prefer read_file over cat/type commands
8. Use replace_block/insert_text/apply_patch for editing
9. CRITICAL: Check tool results before claiming success - if a tool returns 'Error:', acknowledge it
10. NEVER fabricate or invent tool output - only report what the tool actually returned

On Windows: Use PowerShell syntax. Bash heredocs (<<EOF) and $() don't work.
```

#### `asusai-vllm` — Add tool result verification

Edit: `providers["asusai-vllm"].system_prompt` in `~/.ppxai/ppxai-config.json`

```
You are an expert coding assistant running on a local NVIDIA GB10 GPU via vLLM. Be concise and precise. Execute tools directly and report results briefly. Focus on code quality, correctness, and best practices. CRITICAL: Check tool results before claiming success - if a tool fails, acknowledge the failure honestly. Never fabricate tool output.
```

---

### Phase 5: Validation & Documentation (1 hour)

1. Run each model **3 times** with final config for statistical stability
2. Compare progression: baseline → hints → hints+params → hints+params+prompt
3. Create `docs/GPT-OSS-DGX-TUNING-ANALYSIS.md` with results
4. Update `ppxai-config.example.json` with optimized settings
5. Commit AGENTS.md with validated hints
6. Sync optimized settings back to `~/.ppxai/ppxai-config.json`

---

## Success Criteria

| Model | Current (Binary) | Target | Minimum Acceptable |
|-------|-----------------|--------|---------------------|
| GPT-OSS 120B | 82.8% | 90%+ | 85%+ |
| Qwen3-Coder-30B FP8 | 81.2% | 90%+ | 85%+ |

### Category Targets

| Category | GPT-OSS 120B Current → Target | Qwen3-Coder FP8 Current → Target |
|----------|-------------------------------|----------------------------------|
| **Tool Calling** | 78.6% → 85%+ | 100% → Maintain |
| **Code Editing** | 71.4% → 85%+ | 100% → **Maintain (CRITICAL)** |
| **Hallucination** | 77.8% → 85%+ | Unknown → 80%+ |
| **Error Recovery** | 100% → Maintain | 100% → Maintain |

---

## Key Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Breaking Qwen3-Coder code editing (100%) | **HIGH** | Conservative tuning, revert immediately on any drop |
| `frequency_penalty` regression | **HIGH** | Test 0.0 first, before any other changes |
| DGX connectivity from Windows | MEDIUM | Verify `curl http://your-vllm-host:8000/v1/models` before starting |
| Config not loaded (wrong file) | MEDIUM | Always set `PPXAI_CONFIG_FILE`, verify providers visible |

---

## Timeline

| Phase | Duration | Cumulative |
|-------|----------|------------|
| Phase 1: Quality baseline (2 models) | 1 hour | 1 hour |
| Phase 2: AGENTS.md hints | 30 min | 1.5 hours |
| Phase 3: Parameter tuning (4 exp × 2 models) | 2 hours | 3.5 hours |
| Phase 4: System prompt optimization | 30 min | 4 hours |
| Phase 5: Validation + documentation | 1 hour | 5 hours |

**Total Estimated Time:** 5 hours

---

## Quick Reference: All Commands

```bash
# Set env (cmd) - DO THIS FIRST
set PPXAI_CONFIG_FILE=%USERPROFILE%\.ppxai\ppxai-config.json
set UV_NATIVE_TLS=true

# Verify providers visible
.uv\uv run python -c "from ppxai.config import initialize, PROVIDERS; initialize(); print([p for p in PROVIDERS])"

# GPT-OSS 120B benchmark
.uv\uv run python benchmarks\llm-eval\benchmark.py --provider custom --model openai/gpt-oss-120b --debug --verbose

# Qwen3-Coder FP8 benchmark
.uv\uv run python benchmarks\llm-eval\benchmark.py --provider asusai-vllm --model Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8 --debug --verbose

# Compare results for a provider/model
.uv\uv run python benchmarks\llm-eval\benchmark.py --provider custom --model openai/gpt-oss-120b --compare

# Check DGX connectivity
curl http://your-vllm-host:8000/v1/models
```
