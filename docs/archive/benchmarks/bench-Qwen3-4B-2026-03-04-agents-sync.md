# Benchmark: Qwen3-4B after AGENTS.md sync — 2026-03-04

## Context

Re-ran benchmark after syncing AGENTS.md across Linux `~/.ppxai/`, Windows host, and repo:
- `local` provider hints: replaced 3 generic hints with 11 Qwen3-4B-specific operational hints
- Added `Qwen3-4B*` model hints (new — not previously in repo)

## Results

| Run | Score | Tests passed |
|-----|-------|-------------|
| With AGENTS.md | **76.1%** | 27/36 |
| Without AGENTS.md | **75.1%** | 27/36 |
| Delta | **+1.0%** | — |

Previous best single-run: **81.5%** (run #8, post prompt-based tuning)

## Category Breakdown — With AGENTS.md

| Category | Score | vs Without |
|----------|-------|-----------|
| error_recovery | 100.0% | = |
| format_compliance | 100.0% | = |
| instruction_following | 100.0% | = |
| reasoning | 100.0% | = |
| code_editing | 81.8% | = |
| tool_calling | 78.6% | **-21.4%** |
| agentic_tool_loops | 67.6% | = |
| efficiency | 58.0% | = |
| hallucination_resistance | 55.6% | **+22.2%** |

## Key Findings

### AGENTS.md helps: hallucination_resistance +22.2%
- `contradiction_detection`: FAIL without → PASS with
- Likely driven by: "When a tool fails, explicitly acknowledge it" and "Do NOT re-read files you already read"

### AGENTS.md hurts: tool_calling -21.4%
- `multi_tool_sequence`: **PASS without → FAIL with**
- Likely cause: `"Make ONE tool call per step"` in `Qwen3-4B*` model hints conflicts with tests
  requiring consecutive multi-tool chains in a single turn
- Also: `patch_multiline` PASS without → FAIL with (possible hint interference)
- Offsetting gain: `patch_apply_verify` PARTIAL(50%) without → PASS with (apply+verify hint works)

## Action Items

1. **Review `Qwen3-4B*` hint**: `"Make ONE tool call per step"` is too restrictive — it prevents
   multi-tool sequences. Consider replacing with:
   `"Do NOT duplicate the same tool call — but chain DIFFERENT tool calls for multi-step tasks."`

2. **Re-run after hint fix** to confirm tool_calling regression resolves.

3. **Variance note**: Single-run scores for Qwen3-4B vary significantly (~76–82%) due to model
   temperature and prompt sensitivity. The running average over 12 runs remains at 81.5%.
