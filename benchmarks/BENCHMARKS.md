# ppxai Benchmark System

**Version:** v1.15.5
**Last Updated:** 2026-02-14

---

## Overview

The ppxai benchmark suite evaluates AI models on capabilities critical for coding assistants:

- **Tool calling reliability** - Can the model correctly invoke tools?
- **Code editing accuracy** - Does `apply_patch` work correctly?
- **Format compliance** - Does the model follow instructions and output formats?
- **Error recovery** - Can the model self-correct and handle failures?
- **Multi-step reasoning** - Does the model plan complex tasks?
- **Instruction following** - Does the model respect constraints?
- **Hallucination resistance** - Does the model claim false success?

**Key Features:**
- ✅ Provider-agnostic (works with Perplexity, Gemini, OpenAI, vLLM, Ollama, etc.)
- ✅ Historical tracking (compare runs over time)
- ✅ Category-level analysis (see where models excel/struggle)
- ✅ Ranking system (compare models head-to-head)
- ✅ Tool calling method detection (native vs prompt-based)
- ✅ Debug mode with detailed logs

---

## Quick Start

### Run a Benchmark

```bash
cd benchmarks/llm-eval

# Benchmark any provider
python benchmark.py --provider perplexity --model sonar-pro
python benchmark.py --provider gemini --model gemini-3-flash-preview
python benchmark.py --provider openai --model gpt-4o

# Custom providers (vLLM, Ollama, etc.)
python benchmark.py --provider custom --model openai/gpt-oss-120b
```

### View Results

```bash
# List all benchmarks
python benchmark.py --list-results

# Compare two models
python benchmark.py --compare perplexity/sonar-pro gemini/gemini-3-flash-preview

# Show ranking
python benchmark.py --ranking

# Show history for a model
python benchmark.py --history perplexity/sonar-pro
```

---

## Test Categories

### 1. Tool Calling (6 tests)

**What it measures:** Accuracy of tool invocation and parameter passing

| Test | Description | Weight |
|------|-------------|--------|
| `simple_tool_call` | Basic single tool invocation | 1.0 |
| `complex_args` | Tool call with multiple arguments | 1.0 |
| `large_payload` | Tool call with large JSON (truncation test) | 1.5 |
| `multi_tool_sequence` | Multi-turn tool usage with dependencies | 1.5 |
| `no_explain_before_tool` | Calls tool without "I'll use X" preamble | 1.0 |
| `no_json_in_content` | Tool calls not leaked as JSON in content | 1.0 |

**Good score:** 80%+
**Poor score:** <50%

**Common failures:**
- Model explains what it will do instead of calling tool directly
- Tool JSON appears in response content (prompt-based method leakage)
- Parameters are malformed or missing

---

### 2. Code Editing (3 tests)

**What it measures:** Accuracy of `apply_patch` tool for code modifications

| Test | Description | Weight |
|------|-------------|--------|
| `patch_simple` | Simple apply_patch with exact content | 1.0 |
| `patch_indentation` | apply_patch preserves indentation | 1.5 |
| `patch_multiline` | apply_patch with multi-line changes | 1.0 |

**Good score:** 90%+
**Poor score:** <70%

**Common failures:**
- Indentation errors (tabs vs spaces)
- Incomplete hunks (missing lines)
- Unicode normalization issues (NBSP, thin space)

---

### 3. Hallucination Resistance (5 tests)

**What it measures:** Does the model claim false success after tool failures?

| Test | Description | Weight | Tags |
|------|-------------|--------|------|
| `respects_tool_failure` | Acknowledges tool failures, doesn't claim success | 2.0 | critical, gate |
| `no_phantom_tool_calls` | Doesn't claim actions it didn't take | 1.5 | gate |
| `repeated_failure_acknowledgment` | Doesn't ignore repeated failures | 2.0 | critical, gate |
| `contradiction_detection` | Doesn't contradict tool results | 2.0 | critical, gate |
| `multi_turn_consistency` | Maintains accuracy over multiple turns | 1.5 | gate |

**Good score:** 80%+
**Poor score:** <60%

**Common failures (GPT-OSS specific):**
- Claims "File created successfully" after write_file returned error
- Says "I've read the file" when read_file failed
- Ignores repeated error messages

**Note:** These tests are critical "gate" tests - models that fail multiple tests in this category are not production-ready for agentic workflows.

---

### 4. Format Compliance (3 tests)

**What it measures:** Can the model follow formatting instructions?

| Test | Description | Weight |
|------|-------------|--------|
| `json_output` | Outputs valid JSON when requested | 1.0 |
| `markdown_code_blocks` | Proper markdown code block formatting | 1.0 |
| `no_hallucinated_paths` | Doesn't hallucinate file paths | 1.0 |

**Good score:** 90%+
**Poor score:** <70%

---

### 5. Instruction Following (3 tests)

**What it measures:** Does the model respect explicit constraints?

| Test | Description | Weight |
|------|-------------|--------|
| `do_not_explain` | Follows "do not explain" instruction | 1.0 |
| `constraint_respect` | Respects explicit constraints | 1.5 |
| `format_specification` | Follows specific output format | 1.0 |

**Good score:** 85%+
**Poor score:** <60%

---

### 6. Reasoning (3 tests)

**What it measures:** Multi-step planning and dependency analysis

| Test | Description | Weight |
|------|-------------|--------|
| `multi_step_planning` | Plans multi-step tasks | 1.0 |
| `dependency_ordering` | Understands task dependencies | 1.0 |
| `edge_case_handling` | Recognizes edge cases | 1.0 |

**Good score:** 75%+
**Poor score:** <50%

---

### 7. Error Recovery (3 tests)

**What it measures:** Self-correction and graceful degradation

| Test | Description | Weight |
|------|-------------|--------|
| `tool_error_recovery` | Recovers from tool errors | 1.0 |
| `self_correction` | Corrects mistakes when pointed out | 1.0 |
| `graceful_degradation` | Handles limited capabilities gracefully | 1.0 |

**Good score:** 80%+
**Poor score:** <55%

---

## Understanding Scores

### Overall Score Calculation

Scores are **weighted averages** based on test importance:

```
overall_score = (sum of passed_weight) / (sum of total_weight) * 100
```

Example:
```
Tool Calling:
  simple_tool_call (1.0): PASS → 1.0
  complex_args (1.0):     FAIL → 0.0
  large_payload (1.5):    PASS → 1.5

  Category score = (1.0 + 0.0 + 1.5) / (1.0 + 1.0 + 1.5) * 100 = 71.4%
```

### Interpreting Scores

| Overall Score | Assessment | Recommendation |
|---------------|------------|----------------|
| **90-100%** | Excellent | Production-ready for complex agentic workflows |
| **75-89%** | Good | Suitable for most coding tasks with monitoring |
| **60-74%** | Fair | Usable for simple tasks, may need fallbacks |
| **<60%** | Poor | Not recommended for production use |

### Category-Specific Benchmarks

| Category | Excellent | Good | Fair | Poor |
|----------|-----------|------|------|------|
| Tool Calling | 90%+ | 75-89% | 60-74% | <60% |
| Code Editing | 95%+ | 85-94% | 70-84% | <70% |
| Hallucination Resistance | 90%+ | 75-89% | 60-74% | <60% |
| Format Compliance | 95%+ | 85-94% | 75-84% | <75% |
| Instruction Following | 90%+ | 75-89% | 60-74% | <60% |
| Reasoning | 80%+ | 65-79% | 50-64% | <50% |
| Error Recovery | 85%+ | 70-84% | 55-69% | <55% |

---

## Tool Calling Methods

ppxai supports **two different tool calling architectures**:

### Native Tool Calling

**How it works:**
1. ppxai sends `tools` parameter with function schemas
2. Provider's LLM decides which tools to call
3. API response includes structured `tool_calls` array
4. ppxai executes tools and sends results back

**Providers:** Gemini, OpenAI, OpenRouter, vLLM (with `--enable-auto-tool-choice`)

**Advantages:**
- ✅ More reliable (provider-optimized)
- ✅ Structured responses
- ✅ Faster (no parsing needed)

**Metadata:**
```json
{
  "provider": "gemini",
  "model": "gemini-3-flash-preview",
  "metadata": {
    "tool_calling_method": "native"
  }
}
```

---

### Prompt-Based Tool Calling

**How it works:**
1. ppxai injects tool descriptions into system prompt
2. LLM outputs tool calls as JSON text
3. ppxai parses JSON from response content
4. ppxai executes tools and continues conversation

**Providers:** Perplexity (all Sonar models)

**Advantages:**
- ✅ Works with any text-generation API
- ✅ No special API support required

**Disadvantages:**
- ⚠️ Less reliable (JSON parsing can fail)
- ⚠️ May include extra explanation text
- ⚠️ Prone to formatting errors

**Metadata:**
```json
{
  "provider": "perplexity",
  "model": "sonar-pro",
  "metadata": {
    "tool_calling_method": "prompt_based"
  }
}
```

**Reference:** [docs/TOOL_CALLING.md](../docs/TOOL_CALLING.md)

---

## Running Benchmarks

### Basic Usage

```bash
# Run all tests
python benchmark.py --provider perplexity --model sonar-pro

# Run specific categories
python benchmark.py --provider gemini --model gemini-3-flash-preview \
  --categories tool_calling,code_editing

# With custom timeout
python benchmark.py --provider openai --model gpt-4o \
  --timeout 180

# With retries
python benchmark.py --provider custom --model openai/gpt-oss-120b \
  --retries 2
```

### Debug Mode

```bash
# Save detailed logs to debug/ directory
python benchmark.py --provider perplexity --model sonar-pro --debug

# Output structure:
# debug/
#   SUMMARY.json                    # Overall results
#   test_001_tool_calling_simple_tool_call.json
#   test_002_tool_calling_complex_args.json
#   ...
```

### Verbose Output

```bash
# Show error summaries for failed tests
python benchmark.py --provider perplexity --model sonar-pro --verbose
```

---

## Analyzing Results

### List All Results

```bash
python benchmark.py --list-results
```

Output:
```
Provider/Model                           Latest Score  Runs  Last Run
--------------------------------------------------------------------------------
custom/openai/gpt-oss-120b                      89.1%     1  2026-02-05T13:53:31
gemini/gemini-3-flash-preview                  100.0%     1  2026-02-08T17:29:31
perplexity/sonar-pro                            50.0%     2  2026-02-08T12:15:20
```

---

### Compare Two Models

```bash
python benchmark.py --compare \
  custom/openai/gpt-oss-120b \
  gemini/gemini-3-flash-preview
```

Output:
```
Category                  gpt-oss-120b    gemini-3-flash      Delta
---------------------------------------------------------------------------
tool_calling                    95.0%              100.0%      -5.0%
code_editing                   100.0%              100.0%       0.0%
hallucination_resistance        85.0%               95.0%     -10.0%
format_compliance               90.0%              100.0%     -10.0%
instruction_following           88.0%               92.0%      -4.0%
reasoning                       75.0%               80.0%      -5.0%
error_recovery                  80.0%               85.0%      -5.0%
---------------------------------------------------------------------------
OVERALL                         89.1%              100.0%     -10.9%
```

---

### Show Ranking

```bash
python benchmark.py --ranking
```

Output:
```
Rank   Provider/Model                           Score   Runs
--------------------------------------------------------------
1      gemini/gemini-3-flash-preview           100.0%      1
2      custom/openai/gpt-oss-120b               89.1%      1
3      asusai-vllm/Qwen3-Coder-30B-A3B          81.3%      1
4      asusai-vllm/Qwen3-Coder-Next             60.9%      3
5      perplexity/sonar-pro                     50.0%      2
```

---

### Show History for a Model

```bash
python benchmark.py --history perplexity/sonar-pro
```

Output:
```
History for: perplexity/sonar-pro

Run  Timestamp            Score   Passed   Duration
----------------------------------------------------
1    2026-02-08           50.0%   14/28    245.3s
2    2026-02-09           52.0%   15/28    238.1s
```

---

## Result Files

Benchmark results are stored in `benchmarks/llm-eval/results/`:

### Individual Result Files

**Format:** `{provider}_{model}_{date}_{hash}.json`

**Example:** `perplexity_sonar-pro_2026-02-08_a755ae49.json`

```json
{
  "provider": "perplexity",
  "model": "sonar-pro",
  "timestamp": "2026-02-08T12:15:20.123456",
  "overall_score": 50.0,
  "tests_passed": 14,
  "tests_total": 28,
  "duration_seconds": 245.3,
  "category_scores": {
    "tool_calling": 45.0,
    "code_editing": 70.0,
    "hallucination_resistance": 40.0,
    "format_compliance": 60.0,
    "instruction_following": 55.0,
    "reasoning": 50.0,
    "error_recovery": 45.0
  },
  "test_results": [
    {
      "name": "simple_tool_call",
      "category": "tool_calling",
      "passed": true,
      "details": {},
      "weight": 1.0
    },
    ...
  ],
  "metadata": {
    "runner": "engine",
    "timeout": 120,
    "retries": 1,
    "sdk_versions": {
      "openai": "2.11.0",
      "google-genai": "1.56.0"
    },
    "model_fingerprint": "93f925383017",
    "tool_calling_method": "prompt_based"
  }
}
```

### Index File

**File:** `benchmarks/llm-eval/results/index.json`

Tracks all benchmark runs for quick lookups:

```json
{
  "pairs": {
    "perplexity/sonar-pro": [
      {
        "filename": "perplexity_sonar-pro_2026-02-08_a755ae49.json",
        "timestamp": "2026-02-08T12:15:20.123456",
        "overall_score": 50.0
      }
    ]
  },
  "runs": [
    {
      "pair": "perplexity/sonar-pro",
      "filename": "perplexity_sonar-pro_2026-02-08_a755ae49.json",
      "timestamp": "2026-02-08T12:15:20.123456",
      "overall_score": 50.0
    }
  ]
}
```

---

## Benchmark History

### Current Results (v1.15.4)

| Model | Provider | Overall | Tool Calling | Code Editing | Hallucination | Tool Method |
|-------|----------|---------|--------------|--------------|---------------|-------------|
| GPT-OSS-120B | custom | 89.1% | 95.0% | 100.0% | 85.0% | native |
| Gemini 3 Flash | gemini | 100.0% | 100.0% | 100.0% | 95.0% | native |
| Qwen3-Coder-30B | vllm | 81.3% | 90.0% | 95.0% | 75.0% | native |
| Sonar Pro | perplexity | 50.0% | 45.0% | 70.0% | 40.0% | prompt_based |

**Key insights:**
- Native tool calling scores ~30% higher than prompt-based on average
- Gemini 3 Flash is currently the top performer (100% overall)
- GPT-OSS-120B excels at code editing (100%) but has hallucination issues (85%)
- Perplexity Sonar Pro struggles with tool calling reliability (45%)

---

## Troubleshooting

### Test Timeouts

**Symptom:** Tests fail with "Timeout" error

**Solutions:**
```bash
# Increase timeout (default: 120s)
python benchmark.py --provider perplexity --model sonar-pro --timeout 300

# For slow models/providers, use 5+ minutes
python benchmark.py --provider custom --model meta-llama/llama-3.1-405b --timeout 600
```

---

### API Authentication Errors

**Symptom:** "401 Unauthorized" or "API key not found"

**Solutions:**
```bash
# Check .env file has correct API keys
cat ~/.ppxai/.env | grep PERPLEXITY_API_KEY
cat ~/.ppxai/.env | grep GEMINI_API_KEY

# Reload config
python -c "from ppxai.config import reload_config; reload_config()"
```

---

### Tool Calling Failures

**Symptom:** All tool_calling tests fail

**Check:** Tool calling method compatibility
```bash
# Verify provider capabilities
python -c "
from ppxai.config import initialize, PROVIDERS
initialize()
print(PROVIDERS['perplexity']['capabilities'])
"
```

**Perplexity Sonar models** use prompt-based tool calling (lower scores expected)
**Gemini/OpenAI** use native tool calling (higher scores expected)

---

### Inconsistent Results

**Symptom:** Same model scores differently across runs

**Causes:**
1. **Model updates** - Providers update models server-side
2. **Temperature** - Non-zero temperature adds randomness
3. **Load balancing** - Different backend instances may behave differently

**Solutions:**
```bash
# Run multiple times and average
for i in {1..3}; do
  python benchmark.py --provider gemini --model gemini-3-flash-preview
done

# Check model fingerprint in metadata
# Different fingerprints = different model behavior
```

---

### Low Scores on Custom Providers

**Symptom:** vLLM/Ollama models score poorly on tool_calling

**Check:** vLLM tool calling configuration
```bash
# vLLM requires --enable-auto-tool-choice flag
vllm serve openai/gpt-oss-120b \
  --enable-auto-tool-choice \
  --tool-call-parser openai

# Ollama only supports tool calling with Qwen models
ollama run qwen2.5-coder:32b
```

**Reference:** [docs/vllm-tool-calling-guide.md](../docs/vllm-tool-calling-guide.md)

---

## Development

### Adding New Tests

1. **Define test in `test_cases.py`:**
```python
def test_my_new_test(client: MockClient) -> Tuple[bool, Dict[str, Any]]:
    """Test description."""
    # Send message, check tool calls
    response = client.chat([{"role": "user", "content": "..."}], tools=TOOLS)

    # Validate
    passed = len(response.get("tool_calls", [])) > 0
    details = {"some_metric": 123}

    return passed, details

# Register test
ALL_TESTS.append(
    TestCase(
        name="my_new_test",
        category="tool_calling",
        description="Brief description",
        test_fn=test_my_new_test,
        weight=1.0,
        tags=["critical"]  # optional
    )
)
```

2. **Run test:**
```bash
python benchmark.py --provider perplexity --model sonar-pro --categories tool_calling
```

---

### Adding New Categories

Edit `test_cases.py`:
```python
def get_categories() -> list[str]:
    return [
        "tool_calling",
        "code_editing",
        # ... existing categories ...
        "my_new_category",  # ADD
    ]
```

---

## Files

| File | Purpose |
|------|---------|
| `benchmark.py` | Main CLI entry point |
| `engine_runner.py` | ppxai EngineClient integration |
| `test_cases.py` | Test definitions (~1,283 lines) |
| `results.py` | Historical storage and ranking |
| `response_quality.py` | Anti-pattern detection |
| `results/` | Stored benchmark results (JSON) |
| `docs/archive/legacy/` | Pre-v1.15 benchmarks (archived) |

---

## See Also

- **Tool Calling Guide:** [docs/TOOL_CALLING.md](../docs/TOOL_CALLING.md)
- **vLLM Setup:** [docs/vllm-tool-calling-guide.md](../docs/vllm-tool-calling-guide.md)
- **Prompt-Based Tools:** [docs/prompt-based-tool-calling.md](../docs/prompt-based-tool-calling.md)
- **DGX Spark Setup:** [docs/DGX-SPARK-SETUP.md](../docs/DGX-SPARK-SETUP.md)
- **Test Definitions:** [benchmarks/llm-eval/test_cases.py](llm-eval/test_cases.py)

---

**Last Updated:** 2026-02-14
**Version:** v1.15.5
