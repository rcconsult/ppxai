# Ollama Local Model Limitations

**Document Version:** v1.14.0
**Last Updated:** January 19, 2026

## Overview

This document describes the practical limitations of running local LLMs via Ollama for coding assistant tasks, based on testing with RTX 3050 (6GB VRAM).

## Hardware Constraints

### GPU Memory (6GB VRAM)

| Model | Download Size | Runtime Size | GPU Fit | Performance |
|-------|---------------|--------------|---------|-------------|
| `qwen2.5-coder:0.5b` | 0.4GB | ~1GB | ✅ 100% GPU | ~120 tok/s |
| `qwen2.5-coder:3b` | 1.9GB | 3.4GB | ✅ 100% GPU | ~60 tok/s |
| `qwen3:4b` | 2.6GB | 6.3GB | ⚠️ 89% GPU | ~40 tok/s |
| `codellama:7b` | 3.8GB | ~5GB | ✅ 100% GPU | ~30 tok/s |
| `qwen2.5-coder:7b` | 4.7GB | 8.1GB | ❌ 100% CPU | ~5 tok/s |
| `mistral:v0.3` | 4.4GB | 7.6GB | ⚠️ 26% GPU / 74% CPU | ~10 tok/s |

**Key Insight:** Download size ≠ runtime size. Models expand significantly when loaded due to:
- KV cache allocation
- Activation memory
- CUDA overhead

**Recommendation:** For 6GB VRAM, stick to models with download size ≤ 3GB to ensure full GPU inference.

## Model Capability Limitations

### Tool Calling vs Response Synthesis

Small models (≤3B) exhibit a fundamental trade-off:

| Capability | 0.5B | 3B | 7B+ |
|------------|------|----|----|
| Tool selection accuracy | 70% | 83% | 90%+ |
| Parameter formatting | Good | Good | Excellent |
| Response synthesis | Poor | Weak | Good |
| Context understanding | Limited | Moderate | Good |

### Observed Behaviors

**Good at:**
- Selecting correct tool for simple queries (`ls`, `pwd`, `read_file`)
- Formatting JSON tool calls correctly
- Following tool calling format instructions

**Poor at:**
- Synthesizing tool results into coherent answers
- Understanding context from previous tool calls
- Answering follow-up questions about tool results
- Complex multi-step reasoning

### Example: Weather Query

```
User: "Show me the weather forecast for Lausanne"

3B Model Behavior:
1. ✅ Correctly calls web_search tool
2. ✅ Receives detailed weather data
3. ❌ Response: "I'm unable to process your current command..."
   (Fails to synthesize the tool result)

7B+ Model Behavior:
1. ✅ Correctly calls web_search tool
2. ✅ Receives detailed weather data
3. ✅ Response: "Today in Lausanne: 7°C, mostly cloudy..."
   (Properly synthesizes and presents the data)
```

## Workarounds

### 0. Bootstrap Context Hints (v1.14.0)

Use `AGENTS.md` to provide model-specific guidance that helps small models perform better:

```markdown
---
provider_hints:
  local:
    - "Complete tasks fully without stopping on empty responses."
    - "If a tool returns empty output, explain what you tried and continue."
  ollama:
    - "Keep responses concise - you have limited context window."
    - "Prefer smaller, focused tool calls over complex multi-step operations."
model_hints:
  "qwen2.5-coder:0.5b":
    - "Focus on simple, direct tool calls."
    - "Avoid complex multi-step reasoning."
  "qwen2.5-coder:3b":
    - "You can handle moderate complexity but keep responses focused."
---

# Project Instructions
...
```

**Benefits:**
- Hints are automatically applied when using Ollama
- `local` hints apply to all local providers (Ollama, vLLM, LMStudio)
- Model-specific hints refine behavior for each model size
- Use `/context hints` to verify which hints are active

See [Bootstrap Context Guide](BOOTSTRAP_CONTEXT_GUIDE.md) for full documentation.

### 1. Tool Loop Detection (v1.13.10)

Small models sometimes get stuck calling the same tool repeatedly without synthesizing results. ppxai v1.13.10 adds automatic loop detection:

```json
{
  "tools": {
    "agent": {
      "max_same_tool_calls": 3
    }
  }
}
```

When a model calls the same tool 3+ times consecutively, ppxai:
1. Stops the tool execution
2. Injects a message asking the model to synthesize
3. Forces the model to respond with available data

This prevents infinite loops like `get_weather → get_weather → get_weather → ...`

### 2. Use Cloud Providers for Complex Tasks

For queries requiring synthesis (research, explanations, complex reasoning):
```
/provider perplexity  # or gemini
```

Perplexity and Gemini have:
- Native web search (no tool overhead)
- Better reasoning capabilities
- Proper response synthesis

### 3. Use Ollama for Simple File Operations

Ollama works well for:
- Directory listing (`ls`, `pwd`)
- File reading/writing
- Simple code edits
- Running shell commands

### 4. Hybrid Workflow

```
# Local for file ops (fast, private)
/provider ollama
cd ~/project && ls

# Cloud for research (accurate, synthesized)
/provider perplexity
explain the authentication flow in this codebase
```

## Future: Multi-Model Orchestration

The ROADMAP includes plans for dual-model architecture:

```
User Query → Tool Router (0.5B, fast) → Decision
                                          ↓
                          [tool_needed?] ─┬─ Yes → Execute Tool → Response Generator (7B/cloud)
                                          └─ No  → Response Generator (7B/cloud)
```

**Benefits:**
- Small model handles tool selection (what it's good at)
- Larger model handles synthesis (what it's good at)
- Fits in 6GB VRAM: router (0.5GB) + generator (3-4GB)

**Status:** Research phase. See [ROADMAP.md](../ROADMAP.md#multi-model-orchestration-research) for details.

## Configuration Recommendations

### For 6GB VRAM (RTX 3050, RTX 3060, etc.)

```json
{
  "ollama": {
    "default_model": "qwen2.5-coder:3b",
    "models": {
      "qwen2.5-coder:3b": {
        "description": "Best balance for 6GB VRAM",
        "context_length": 32768
      }
    }
  }
}
```

### For 8GB+ VRAM

Can use 7B models with full GPU inference for better synthesis.

### For 12GB+ VRAM

Can run 7B models with larger context windows or consider 13B models.

## Benchmark Results

Tool routing accuracy benchmark (24 test cases):

| Model | Native Tool Calling | Content Parsing | Notes |
|-------|---------------------|-----------------|-------|
| qwen2.5-coder:0.5b | 12.5% | 62.5-70.8% | ✅ Recommended for routing |
| qwen2.5-coder:3b | 16.7% | 66.7-83.3% | ✅ Best overall for 6GB |
| qwen2.5:3b | - | 79.2% | ✅ Highest tool accuracy |
| mistral:v0.3 | 25% | 25% | ❌ Doesn't call tools, explains instead |

**Note:** "Content parsing" uses ppxai's JSON extraction from model output, which is more reliable than native tool calling for small models.

### Description Optimization

Small models benefit from minimal tool descriptions:

| Description Style | 0.5B Accuracy | 3B Accuracy |
|-------------------|---------------|-------------|
| Default (verbose) | 66.7% | 83.3% |
| Minimal (3-5 words) | 70.8% | 79.2% |
| Enhanced (detailed) | 62.5% | 75.0% |

ppxai v1.13.10 adds configurable tool descriptions per model in `ppxai-config.json`:

```json
{
  "tools": {
    "model_overrides": {
      "qwen2.5-coder:0.5b": {
        "shell": "Run command",
        "read_file": "Read file",
        "list_directory": "List directory"
      }
    }
  }
}
```

## Models Tested and Rejected

### Mistral 7B v0.3 (Q4_K_M)

Tested 2026-01-14. Despite having native tool calling support via special tokens, Mistral v0.3 **failed** for ppxai:

**Problems:**
1. **VRAM overflow**: 7.6GB runtime → 74% runs on CPU, only 26% on GPU
2. **Doesn't actually call tools**: Explains how to use tools instead of calling them
3. **25% accuracy**: 17/24 false negatives (missed tool calls)
4. **5.6s average latency**: ~7x slower than Qwen 3B due to CPU offload

**Example failure:**
```
Query: "run git status"
Expected: shell tool call
Got: "To execute npm install, you can use the shell function..."
```

### Other Models Tested

| Model | Status | Reason |
|-------|--------|--------|
| deepseek-coder:1.3b | ❌ | Returns 400 error with tools parameter |
| starcoder:3b | ❌ | Returns 400 error with tools parameter |
| codegemma:2b | ❌ | Returns 400 error with tools parameter |
| codellama:7b | ❌ | Returns 400 error with tools parameter |
| qwen3:4b | ⚠️ | Works but too large for 6GB (89% GPU) |

**Conclusion:** Only Qwen2.5 family models support tool calling via Ollama's OpenAI-compatible API on 6GB VRAM hardware.

## References

- [Ollama Documentation](https://ollama.ai/docs)
- [Qwen2.5-Coder Model Card](https://huggingface.co/Qwen/Qwen2.5-Coder-3B)
- [AWS Paper: Small LLMs for Tool Calling](../2512.15943v1.pdf) - Referenced in ROADMAP
- [ppxai Benchmark Script](../scripts/benchmark_tool_routing.py)
