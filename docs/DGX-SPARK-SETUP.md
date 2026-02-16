# ASUS DGX Spark (GB10) Setup Guide

**Last Updated:** 2026-02-16
**Purpose:** Feasibility study testbed for evaluating local LLM coding assistants
**Hardware:** ASUS Ascent GX10 / DGX Spark
**Host IP:** `<dgx-spark-ip>`
**Provider ID:** `asusai-vllm` (vLLM)
**HF Cache:** `/opt/hf/cache` (287GB, `root:users`, 775)
**Launch Script:** `/opt/hf/launch-vllm.sh`

## Hardware Specifications

| Component | Details |
|-----------|---------|
| GPU | NVIDIA GB10 Blackwell (SM 12.1, CUDA 13.0) |
| GPU Memory | 128GB unified LPDDR5x (shared CPU/GPU) |
| CPU | 20-core ARM (Cortex-X925 + Cortex-A725) |
| RAM | 119GB total (shared with GPU) |
| Storage | 916GB NVMe |
| Architecture | aarch64 |
| OS | Ubuntu 24.04.3 LTS |
| Kernel | 6.14.0-1015-nvidia |
| NVIDIA Driver | 580.126.09 |
| Docker | 29.1.3 |

> **Note:** The GB10 reports `[N/A]` for `nvidia-smi` memory queries because it uses unified memory shared with the CPU, not dedicated VRAM. All 128GB is available for model weights + KV cache.

## Prerequisites

The DGX Spark ships with Docker and NVIDIA Container Toolkit pre-installed. Verify:

```bash
docker --version
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
```

Expected output:
```
Docker version 29.1.3, build f52814d
NVIDIA GB10, [N/A], 580.126.09
```

---

## Option A: vLLM (Recommended for Coding Agents)

vLLM provides native tool calling, FP8 quantization with Blackwell tensor cores, and high throughput for MoE models.

### Why vLLM

vLLM was selected over Ollama based on benchmark evaluation:

| Feature | vLLM |
|---------|------|
| Throughput (MoE) | **43.8 tok/s** |
| TTFT (warm) | **117ms** |
| Native tool calling | Yes (parser-based) |
| FP8 quantization | Native HW support |
| KV cache control | Configurable |
| Code editing quality | **100%** (Qwen3-Coder) |

### Step A1: Docker Image

The official vLLM images do not support the GB10 (Blackwell SM 12.1 + driver 580.x). Use the community image:

```bash
docker pull hellohal2064/vllm-dgx-spark-gb10:latest
```

| Image | Version | Notes |
|-------|---------|-------|
| `hellohal2064/vllm-dgx-spark-gb10:latest` | vLLM 0.16.0rc1 | Built for driver 580.x, aarch64, SM 12.1 |
| `vllm/vllm-openai:latest` | - | **Does NOT work** — missing SM 12.1 support |
| `vllm/vllm-openai:v0.8.x` | - | **Does NOT work** — pre-Blackwell builds |

> **Security note:** The community image is a rebuild of vLLM with Blackwell-compatible CUDA libraries. Verify the image digest and review the Dockerfile if security is a concern. HuggingFace models are downloaded with SHA-256 verification.

### Step A2: Run vLLM Container (Recommended Model)

Use the launch script at `/opt/hf/launch-vllm.sh`:

```bash
sudo bash /opt/hf/launch-vllm.sh              # Start with default model
sudo bash /opt/hf/launch-vllm.sh stop          # Stop the running container
sudo bash /opt/hf/launch-vllm.sh status        # Show container status
sudo bash /opt/hf/launch-vllm.sh logs          # Tail container logs
```

Or run manually:

```bash
docker run -d \
  --name vllm-testbed \
  --gpus all \
  -v /opt/hf/cache:/root/.cache/huggingface \
  -p 8000:8000 \
  --restart unless-stopped \
  --entrypoint vllm \
  hellohal2064/vllm-dgx-spark-gb10:latest \
  serve Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8 \
  --tool-call-parser qwen3_coder \
  --enable-auto-tool-choice \
  --max-model-len 131072
```

Key flags:
- `--gpus all` — GPU access via NVIDIA Container Runtime
- `-v /opt/hf/cache:/root/.cache/huggingface` — Persistent model cache at `/opt/hf/cache` (owned by `root:users`, 775)
- `--enable-auto-tool-choice --tool-call-parser qwen3_coder` — Native tool calling for Qwen3-Coder models
- `--max-model-len 131072` — 131K context window (820K token KV cache)

First-time startup downloads the model (~31 GiB, takes 4-5 minutes on a fast connection). Subsequent starts load from cache in ~3 minutes (model loading + CUDA graph compilation).

### Step A3: Verify vLLM

```bash
# Check container health
docker ps --format 'table {{.Names}}\t{{.Status}}'

# Check loaded model
curl -s http://localhost:8000/v1/models | python3 -m json.tool

# Quick inference test
curl -s http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8", "messages": [{"role": "user", "content": "Write a Python hello world"}], "max_tokens": 100}' | python3 -m json.tool
```

Expected model loading stats (from container logs):
```
Model weights:  ~30 GiB
KV cache:       73.57 GiB (803,616 tokens)
MoE backend:    TRITON Fp8
Attention:      FLASHINFER
```

### Step A4: Tool Call Parser Selection (Critical)

The tool call parser must match the model family. Using the wrong parser causes silent failures — tool calls either don't parse or responses contain `<think>` blocks that corrupt output.

| Model Family | Parser | Flag |
|-------------|--------|------|
| **Qwen3-Coder** | `qwen3_coder` | `--tool-call-parser qwen3_coder` |
| Qwen3 (base) | `hermes` | `--tool-call-parser hermes` |
| Llama 4 | `llama4_json` | `--tool-call-parser llama4_json` |
| GPT-OSS (Harmony) | `openai` | `--tool-call-parser openai` |

**Impact of parser choice on benchmark results:**

The base Qwen3-30B-A3B model was tested with `hermes` parser and scored **60.9%** on LLM-eval with **0% code editing**. The same-architecture Qwen3-Coder model with `qwen3_coder` parser scored **81.2%** with **100% code editing**.

Key differences:
- **`hermes`** parser with base Qwen3: Model emits `<think>` blocks that pollute responses. JSON output tests fail because responses start with `<think>` instead of JSON. Code editing patches arrive empty.
- **`qwen3_coder`** parser with Qwen3-Coder: No thinking tokens, clean output, native tool call format parsed correctly.

> **Can re-testing base Qwen3 with `qwen3_coder` parser improve results?** Unlikely. The `qwen3_coder` parser expects Qwen3-Coder's specific output format. The base Qwen3 model uses thinking mode and a different chat template. The poor code editing (0%) is caused by the model itself not generating proper patches, not just parser mismatch. The thinking tokens consuming the response budget is a model behavior, not a parser issue.

### Step A5: Switching Models

To load a different model, stop the container and start a new one:

```bash
sudo bash /opt/hf/launch-vllm.sh stop
# Edit MODEL= in /opt/hf/launch-vllm.sh, then:
sudo bash /opt/hf/launch-vllm.sh
```

Only one model can be loaded at a time (the GB10's unified memory is shared). Pre-downloaded models are cached in `/opt/hf/cache/` and load without re-downloading.

---

## ppxai Configuration

### API key (`.env`)

```bash
# vLLM uses a dummy key (no authentication required)
VLLM_API_KEY=dummy
```

### vLLM provider config (`ppxai-config.json`)

```json
{
  "asusai-vllm": {
    "name": "ASUS DGX Spark vLLM (GB10)",
    "base_url": "http://<dgx-spark-ip>:8000/v1",
    "api_key_env": "VLLM_API_KEY",
    "default_model": "Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8",
    "coding_model": "Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8",
    "system_prompt": "You are an expert coding assistant running on a local NVIDIA GB10 GPU via vLLM. Be concise and precise. When using tools, execute them directly and report results briefly. Focus on code quality, correctness, and best practices.",
    "generation_params": {
      "temperature": 0.2,
      "top_p": 0.9,
      "frequency_penalty": 0.0
    },
    "models": {
      "Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8": {
        "name": "Qwen3 Coder 30B-A3B FP8 (MoE)",
        "description": "Code-specialized MoE: 30.5B total / 3.3B active, FP8, native tool calling via qwen3_coder parser, 820K token KV cache",
        "context_limit": 131072,
        "max_tokens": 8192
      }
    },
    "pricing": {
      "Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8": { "input": 0.0, "output": 0.0 }
    },
    "capabilities": {
      "web_search": true,
      "web_fetch": true,
      "weather": true,
      "realtime_info": true,
      "native_tool_calling": true
    }
  }
}
```

> **Note:** `frequency_penalty: 0.0` is a tuning result — Qwen3-Coder scored 75% → 81.2% when reduced from 0.1 to 0.0. vLLM is the only supported runtime for this testbed.

## Verify Connectivity

```bash
# vLLM (port 8000)
curl http://<dgx-spark-ip>:8000/v1/models

# Quick test via ppxai
uv run ppxai
# Then: /provider asusai-vllm
# Then: Hello, write a Python hello world
```

---

## Benchmark Results (2026-02-12)

All benchmarks run via ppxai Engine on the DGX Spark GB10.

### Latency (3 iterations per prompt level, 9 total runs)

| Runtime | Model | TTFT (mean) | TTFT (warm) | Throughput | KV Cache |
|---------|-------|-------------|-------------|------------|----------|
| **vLLM** | **Qwen3-Coder-30B-A3B FP8** | **174ms** | **117ms** | **43.8 tok/s** | **803K tokens** |
| vLLM | Qwen3-30B-A3B FP8 | 175ms | ~120ms | 45.1 tok/s | ~800K tokens |
| vLLM | Qwen3-32B NVFP4 | 231ms | 176ms | 9.4 tok/s | 313K tokens |
| vLLM | Llama-3.3-70B NVFP4 | 535ms | ~300ms | 3.4 tok/s | - |

### LLM-Eval (Agentic Coding Quality, 26 tests)

| Runtime | Model | Score | Passed | Tool Call | Code Edit | Error Rec | Format |
|---------|-------|-------|--------|-----------|-----------|-----------|--------|
| **vLLM** | **Qwen3-Coder-30B-A3B FP8** | **81.2%** | **22/26** | **100%** | **100%** | **100%** | **100%** |
| vLLM | Qwen3-30B-A3B FP8 | 60.9% | 17/26 | 78.6% | 0% | 100% | 66.7% |

### Comparison with Cloud Providers

| Provider | Model | Score | Throughput | Cost |
|----------|-------|-------|------------|------|
| Perplexity | sonar-pro | 100% | ~60 tok/s | $3-15/M tokens |
| **DGX Spark** | **Qwen3-Coder-30B-A3B FP8** | **81.2%** | **43.8 tok/s** | **Free (local)** |
| Google | Gemini 2.5 Flash | 81.2% | ~45 tok/s | $0.15-0.60/M tokens |
| Google | Gemini 3 Pro Preview | 70.3% | - | $1.25-5.0/M tokens |

---

## Model Testing Log

### Models That Work Well

| Model | Quant | Size | Speed | Quality | Notes |
|-------|-------|------|-------|---------|-------|
| **Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8** | FP8 | ~30 GiB | 50 tok/s | **81.2%** | **Best overall.** MoE (3.3B active), code-specialized, native tool calling via `qwen3_coder` parser. No thinking tokens. TRITON Fp8 MoE backend. |
| RedHatAI/Qwen3-30B-A3B-FP8-dynamic | FP8 | ~9 GiB | 45.1 tok/s | 60.9% | Fast MoE baseline. Same architecture as Coder but general-purpose. `<think>` blocks pollute output. `hermes` parser. 0% code editing. |
| RedHatAI/Qwen3-32B-NVFP4 | NVFP4 | ~19 GiB | 9.4 tok/s | - | Dense model, works but slow. Blackwell FP4 tensor cores active. 76 GiB KV cache. LLM-eval killed due to speed. |

### Models Evaluated But Not Competitive

| Model | Quant | Size | Speed | Quality | Notes |
|-------|-------|------|-------|---------|-------|
| Qwen/Qwen3-Coder-30B + eagle3 speculator | FP8+spec | ~31 GiB | 67 tok/s | 70.3% | +34% speed but -4.7% quality. tool_calling dropped 100% → 64.3%. Speculator trained for base Qwen3, not Coder variant. **Reverted.** |
| Qwen/Qwen3-Coder-Next-FP8 | FP8 | ~75 GiB | 43 tok/s | 60.9% | Hybrid MoE (80B/3B, Gated DeltaNet). High variance across 3 runs (54.7%–60.9%). tool_calling stuck at 64.3%. Not competitive with Coder-30B. |
| Qwen/Qwen3-Next-80B-A3B-Instruct-FP8 | FP8 | ~75 GiB | 50 tok/s | 54.7% | General-purpose hybrid MoE. Hints had 0% effect. code_editing 0%, hallucination_resistance 16.7%. |
| Qwen/Qwen3-Next-80B-A3B-Thinking-FP8 | FP8 | ~77 GiB | 12 tok/s | 57.8% | Thinking variant with `<think>` blocks. Extremely slow (37 min benchmark). Only +3.1% over Instruct. Same core weaknesses. |
| Qwen/Qwen2.5-Coder-32B-Instruct (vLLM) | BF16 | ~62 GiB | 4-5 tok/s | aborted | Dense 32B, all params active. 10x slower than MoE. Speed alone disqualifies for interactive use. |

### Models That Failed

| Model | Quant | Issue | Root Cause |
|-------|-------|-------|------------|
| **RedHatAI/Qwen3-Next-80B-A3B-Instruct-NVFP4** | NVFP4 | **CRASH** during profiling | `RuntimeError: Could not construct fused moe op with Activation: uint8, Weight: int64, Output: bfloat16`. The flashinfer CUTLASS MoE backend doesn't support NVFP4 quantized MoE weight types. Model loads all 10 shards (44 GiB) but crashes during the first dummy inference. |
| **RedHatAI/Llama-4-Scout-17B-16E-Instruct-NVFP4** | NVFP4 | **OOM** (silent kill) | Model is 17B params × 16 experts = ~70 GiB. Loads all 14 shards successfully, then EngineCore process is silently killed by Linux OOM killer during profiling/CUDA graph compilation. 70 GiB model + profiling overhead exceeds 128 GB unified memory. |
| **RedHatAI/Llama-3.3-70B-Instruct-NVFP4** | NVFP4 | Works but **unusably slow** | 3.4 tok/s. Dense 70B model with all params active per token. NVFP4 saves memory but doesn't help throughput for dense architectures. |

### Key Technical Findings

**NVFP4 MoE is broken on vLLM 0.16.0rc1:**
The flashinfer CUTLASS MoE kernel does not support the NVFP4 weight type combination (`uint8 activation + int64 weight + bfloat16 output`). This affects all MoE models with NVFP4 quantization. Dense NVFP4 models (like Qwen3-32B) work because they use a different kernel path. The TRITON Fp8 MoE backend works correctly with FP8 quantized MoE models.

**FP8 MoE is the sweet spot for GB10:**
MoE architecture (only 3.3B of 30.5B params active per token) + FP8 quantization (native Blackwell tensor core support via TRITON backend) = best throughput. Dense models can't compete regardless of quantization because all params are active.

**Tool call parser matters more than expected:**
Using `hermes` parser with base Qwen3 → 60.9% score, 0% code editing. Using `qwen3_coder` parser with Qwen3-Coder → 81.2% score, 100% code editing. The parser must match the model's output format. Base Qwen3 emits `<think>` tokens that hermes doesn't strip, corrupting JSON output and code patches.

**Memory budget rule of thumb:**
Model weights + KV cache + CUDA graphs + profiling overhead must fit in 128 GB. Safe limit is ~35 GiB for model weights (leaving ~73 GiB for KV cache and ~20 GiB headroom). Models over ~60 GiB risk OOM during profiling even if weights load successfully.

---

## Model Selection Guide

| Use Case | Recommended Model | Notes |
|----------|-------------------|-------|
| **Coding agent (best quality + speed)** | `Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8` | 81.2% benchmark, 50 tok/s, 131K context |
| General-purpose fast responses | `RedHatAI/Qwen3-30B-A3B-FP8-dynamic` | 60.9%, same speed, no code editing |
| Dense model experimentation | `RedHatAI/Qwen3-32B-NVFP4` | Slow (9.4 tok/s) but Blackwell FP4 |

---

## Troubleshooting

### vLLM container exits immediately (crash loop)

```bash
docker logs vllm-testbed 2>&1 | tail -30
```

Common causes:
- **flashinfer MoE error** — NVFP4 MoE models crash. Use FP8 MoE or dense NVFP4 instead.
- **OOM kill** — Model too large. Check `dmesg | grep -i oom` on the host.
- **Wrong tool parser** — `KeyError: invalid tool call parser`. Check available parsers in the error message.

### Model loading is slow (first request)

First request after container start triggers model loading (3-5 minutes for ~30 GiB). Pre-warm:
```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8", "messages": [{"role": "user", "content": "hello"}], "max_tokens": 5}'
```

### Connection refused from WSL/remote

```bash
# Check container is binding to all interfaces
docker exec vllm-testbed printenv | grep HOST
# Should show: 0.0.0.0
```

### SSL issues from WSL

If `.env` has `SSL_CERT_FILE` pointing to a Windows path, it won't exist on WSL. The benchmark scripts handle this automatically. For manual runs:
```bash
unset SSL_CERT_FILE
```

---

## Running Benchmarks

### Latency benchmark

```bash
PPXAI_CONFIG_FILE=~/.ppxai/ppxai-config.json SSL_VERIFY=false \
  uv run python scripts/benchmark.py \
    --provider asusai-vllm \
    --model "Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8" \
    --iterations 3
```

### LLM-Eval benchmark

```bash
cd benchmarks/llm-eval
PPXAI_CONFIG_FILE=~/.ppxai/ppxai-config.json SSL_VERIFY=false \
  uv run python benchmark.py \
    --provider asusai-vllm \
    --model "Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8" \
    --engine \
    --timeout 120 \
    -v
```

> **Important:** Run latency benchmarks first (3 iterations to warm up), then LLM-eval. Do not run both simultaneously — GPU contention skews results.

---

## vLLM Docker Image Details

### Community Image: `hellohal2064/vllm-dgx-spark-gb10:latest`

| Property | Value |
|----------|-------|
| vLLM Version | 0.16.0rc1.dev122+g6595a2380 |
| CUDA | 13.1 |
| Python | 3.12 |
| Base | Ubuntu 24.04 (aarch64) |
| Architecture | aarch64 + SM 12.1 (Blackwell) |

### Available Tool Call Parsers (vLLM 0.16.0rc1)

```
qwen3_coder, hermes, openai, llama3_json, llama4_json, llama4_pythonic,
mistral, deepseek_v3, deepseek_v31, deepseek_v32, granite, jamba,
internlm, minimax, pythonic, xlam, qwen3_xml, kimi_k2, ...
```

### MoE Backend Selection

vLLM automatically selects the MoE backend based on quantization:

| Quantization | Backend | Status on GB10 |
|-------------|---------|-----------------|
| **FP8** | TRITON Fp8 | **Works** |
| NVFP4 | flashinfer CUTLASS | **Crashes** (MoE only) |
| NVFP4 | - | Works for dense models |
| BF16 | TRITON/flashinfer | Works |

---

## References

- [vLLM Documentation](https://docs.vllm.ai/)
- [Qwen3-Coder-30B-A3B-Instruct-FP8 Model Card](https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8)
- [ppxai Provider Setup Guide](PROVIDER_SETUP.md)
- [ppxai vLLM Tool Calling Guide](vllm-tool-calling-guide.md)
