# LLM Agentic Coding Assistant Benchmark Suite

A benchmark suite for evaluating LLM models on capabilities critical for coding assistants.
Uses **ppxai Engine** for consistent tool handling across all providers.

## Features

- **6 Test Categories**: Tool calling, code editing, format compliance, instruction following, reasoning, error recovery
- **26 Test Cases**: Targeting real-world agentic coding scenarios
- **Engine-Based**: Uses ppxai's EngineClient for automatic tool registration
- **Historical Tracking**: Results stored per provider/model pair
- **Ranking System**: Compare across runs and models
- **Multi-Provider**: Supports Perplexity, Gemini, OpenAI, OpenRouter, vLLM, Ollama, and custom providers

## Quick Start

```bash
# Run against Perplexity
python benchmark.py --provider perplexity --model sonar-pro

# Run against Gemini
python benchmark.py --provider gemini --model gemini-2.5-flash

# Run against OpenAI
python benchmark.py --provider openai --model gpt-4o

# Run against custom provider (vLLM, Ollama, etc.)
python benchmark.py --provider custom --model openai/gpt-oss-120b
```

## Test Categories

### 1. Tool Calling (6 tests)
Tests reliability of native tool calling:
- Simple tool invocation
- Complex argument handling
- Large payload handling (truncation detection)
- Multi-tool sequences
- **GPT-OSS specific**: No "I'll use X tool" preamble
- **GPT-OSS specific**: Tool calls not leaked as JSON in content

### 2. Code Editing (3 tests)
Tests apply_patch and code modification accuracy:
- Simple exact replacements
- Indentation preservation (critical for Python)
- Multi-line additions with imports

### 3. Format Compliance (3 tests)
Tests output format adherence:
- Valid JSON output when requested
- Proper markdown code blocks with language tags
- No hallucinated file paths

### 4. Instruction Following (3 tests)
Tests constraint respect:
- "Do not explain" compliance
- Explicit constraint respect (naming, style, line limits)
- Specific output format adherence

### 5. Reasoning (3 tests)
Tests planning and problem-solving:
- Multi-step task planning
- Dependency ordering (run tests before commit)
- Edge case recognition

### 6. Error Recovery (3 tests)
Tests failure handling:
- Tool error recovery
- Self-correction when mistakes pointed out
- Graceful degradation with limited capabilities

## Usage

### Run Benchmark

```bash
# Full benchmark
python benchmark.py --provider perplexity --model sonar-pro

# Specific categories only
python benchmark.py --provider gemini --model gemini-2.5-flash --categories tool_calling,code_editing

# With verbose output (shows error details)
python benchmark.py --provider openai --model gpt-4o -v

# Custom timeout and retries
python benchmark.py --provider custom --model openai/gpt-oss-120b --timeout 120 --retries 2
```

### View Results

```bash
# List all stored results
python benchmark.py --list-results

# Show ranking across all models
python benchmark.py --ranking

# View history for a specific model
python benchmark.py --history "openai/gpt-4o"

# Compare two models
python benchmark.py --compare "openai/gpt-4o" "vllm/openai/gpt-oss-120b"
```

## Output Example

```
============================================================
LLM Agentic Coding Assistant Benchmark
============================================================
Provider: vllm
Model:    openai/gpt-oss-120b
Base URL: http://localhost:8000/v1
============================================================

Running 21 tests...

[1/21] tool_calling/simple_tool_call... ✓
[2/21] tool_calling/complex_args... ✓
[3/21] tool_calling/large_payload... ✗
[4/21] tool_calling/multi_tool_sequence... ✓
...

Overall Score: 76.2%
Tests Passed:  16/21
Duration:      45.3s

Category Scores:
----------------------------------------
  code_editing         ████████████████░░░░  80.0%
  error_recovery       ████████████████████ 100.0%
  format_compliance    ████████████████░░░░  80.0%
  instruction_following████████████░░░░░░░░  60.0%
  reasoning            ████████████████░░░░  80.0%
  tool_calling         ██████████░░░░░░░░░░  50.0%

============================================================
Comparison with Previous Runs
============================================================

Current:  76.2%
Previous: 71.4%
Change:   ↑ 4.8%

Category Changes:
  tool_calling         ↑ 8.3%
  instruction_following↓ 6.7%

============================================================
Overall Ranking (All Models)
============================================================

Rank   Provider/Model                           Score    Runs
--------------------------------------------------------------
1      openai/gpt-4o                            95.2%      3
2      anthropic/claude-3-opus                  91.4%      2
3      openai/gpt-4-turbo                       88.1%      5
4      vllm/openai/gpt-oss-120b                 76.2%      7 ← current
5      ollama/llama3.1:70b                      68.5%      2
```

## Results Storage

Results are stored in `./results/` directory:
- `index.json` - Index of all runs
- `{provider}_{model}_{date}_{hash}.json` - Individual run results

Each result includes:
- Overall and category scores
- Individual test results with pass/fail and error details
- Metadata (base URL, timeout, retries)
- Timestamp for historical tracking

## Adding Custom Tests

Add new tests in `test_cases.py`:

```python
async def test_my_custom_test(client) -> tuple[bool, dict]:
    """Test description."""
    response = await client.chat(
        messages=[
            {"role": "system", "content": "..."},
            {"role": "user", "content": "..."}
        ],
        tools=TOOLS,  # Optional
    )

    # Evaluate response
    if condition:
        return True, {"detail": "value"}
    return False, {"error": "What went wrong"}

# Register the test
ALL_TESTS.append(
    TestCase(
        name="my_custom_test",
        category="tool_calling",  # or other category
        description="What this tests",
        run=test_my_custom_test,
        weight=1.0,  # Relative scoring weight
        tags=["optional", "tags"],
    )
)
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | OpenAI API key |
| `PERPLEXITY_API_KEY` | Perplexity API key |
| `OPENROUTER_API_KEY` | OpenRouter API key |
| `ANTHROPIC_API_KEY` | Anthropic API key |

For local providers (ollama, vllm, lmstudio), no API key is required.

## Known Failure Modes Tested

Based on real-world experience with GPT-OSS/vLLM:

1. **Truncated Tool Calls**: Large JSON payloads get truncated mid-JSON
2. **"I'll use X tool" Pattern**: Model explains before calling instead of calling directly
3. **JSON in Content**: Tool calls leak into response content instead of `tool_calls`
4. **Indentation Issues**: Python indentation not preserved in patches
5. **Missing Constraints**: Explicit constraints (naming, line limits) ignored

## License

Part of the ppxai project. See main repository for license.
