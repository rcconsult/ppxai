# ASUS DGX Spark (GB10) Ollama Setup Guide

**Last Updated:** 2026-02-06
**Hardware:** ASUS Ascent GX10 / DGX Spark
**Provider ID:** `asusai`

## Hardware Specifications

| Component | Details |
|-----------|---------|
| GPU | NVIDIA GB10 Blackwell |
| GPU Memory | 128GB unified LPDDR5x (shared CPU/GPU) |
| CPU | 20-core ARM (Cortex-X925 + Cortex-A725) |
| RAM | 119GB total (shared with GPU) |
| Storage | 916GB NVMe |
| Architecture | aarch64 |
| OS | Ubuntu 24.04.3 LTS |
| Kernel | 6.14.0-1015-nvidia |
| NVIDIA Driver | 580.126.09 |
| Docker | 29.1.3 |

## Step 1: Docker + NVIDIA Container Runtime

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

> **Note:** The GB10 reports `[N/A]` for memory total because it uses unified memory shared with the CPU, not dedicated VRAM.

## Step 2: Pull and Run Ollama Container

```bash
docker run -d \
  --name ollama \
  --runtime=nvidia \
  --gpus all \
  -v ollama_data:/root/.ollama \
  -p 11434:11434 \
  --restart unless-stopped \
  ollama/ollama
```

Key flags:
- `--runtime=nvidia` - Uses NVIDIA Container Runtime for GPU access
- `--gpus all` - Exposes all GPUs to the container
- `-v ollama_data:/root/.ollama` - Persistent named volume for model storage
- `--restart unless-stopped` - Auto-restart on reboot (survives power cycles)

Verify container is running:
```bash
docker exec ollama ollama --version
# Expected: ollama version is 0.15.x
```

## Step 3: Pull Models

```bash
# Primary coding model (recommended)
docker exec ollama ollama pull qwen2.5-coder:32b

# Fast coding model for quick iteration
docker exec ollama ollama pull qwen2.5-coder:7b

# MoE model - 30B params, only 3B active per token (fast inference)
docker exec ollama ollama pull qwen3:30b-a3b
```

## Step 4: Create Extended Context Variants

The default context window is 32K tokens. For large codebases, create extended variants via Ollama Modelfiles.

### qwen2.5-coder:32b with 64K context

```bash
docker exec ollama bash -c 'cat > /tmp/Modelfile-qwen25-64k << EOF
FROM qwen2.5-coder:32b
PARAMETER num_ctx 65536
EOF
ollama create qwen2.5-coder:32b-64k -f /tmp/Modelfile-qwen25-64k'
```

### qwen3:30b-a3b with 96K context

The MoE architecture (only 3B active params per token) allows larger context windows within the same memory budget.

```bash
docker exec ollama bash -c 'cat > /tmp/Modelfile-qwen3-96k << EOF
FROM qwen3:30b-a3b
PARAMETER num_ctx 98304
EOF
ollama create qwen3:30b-a3b-96k -f /tmp/Modelfile-qwen3-96k'
```

### Verify all models

```bash
docker exec ollama ollama list
```

Expected output:
```
NAME                     ID              SIZE      MODIFIED
qwen3:30b-a3b-96k        d77825500758    18 GB     ...
qwen2.5-coder:32b-64k    427a4814ca5c    19 GB     ...
qwen3:30b-a3b            ad815644918f    18 GB     ...
qwen2.5-coder:32b        b92d6a0bd47e    19 GB     ...
qwen2.5-coder:7b         dae161e27b0e    4.7 GB    ...
```

## Step 5: ppxai Configuration

### API key (`.env`)

```bash
# Ollama uses a dummy key (no authentication required)
OLLAMA_API_KEY=ollama
```

### Provider config (`ppxai-config.json`)

Add the `asusai` provider to the `providers` section:

```json
{
  "asusai": {
    "name": "ASUS DGX Spark (GB10)",
    "base_url": "http://<dgx-spark-ip>:11434/v1",
    "api_key_env": "OLLAMA_API_KEY",
    "default_model": "qwen2.5-coder:32b",
    "coding_model": "qwen2.5-coder:32b",
    "system_prompt": "You are an expert coding assistant running on a local NVIDIA GB10 GPU via Ollama. Be concise and precise. When using tools, execute them directly and report results briefly. Focus on code quality, correctness, and best practices.",
    "generation_params": {
      "temperature": 0.2,
      "top_p": 0.9,
      "frequency_penalty": 0.1
    },
    "models": {
      "qwen2.5-coder:32b": {
        "name": "Qwen2.5 Coder 32B",
        "description": "High-quality coding model: ~19GB, excellent tool calling, strong reasoning (recommended)",
        "context_limit": 32768,
        "max_tokens": 8192
      },
      "qwen2.5-coder:32b-64k": {
        "name": "Qwen2.5 Coder 32B (64K ctx)",
        "description": "Extended context variant: 64K context window for large codebases, ~19GB",
        "context_limit": 65536,
        "max_tokens": 8192
      },
      "qwen3:30b-a3b": {
        "name": "Qwen3 30B-A3B (MoE)",
        "description": "MoE model: 30B total / 3B active per token, ~18GB, efficient for long contexts",
        "context_limit": 32768,
        "max_tokens": 8192
      },
      "qwen3:30b-a3b-96k": {
        "name": "Qwen3 30B-A3B (96K ctx)",
        "description": "Extended context MoE: 96K context window, only 3B active params per token, ideal for large projects",
        "context_limit": 98304,
        "max_tokens": 8192
      },
      "qwen2.5-coder:7b": {
        "name": "Qwen2.5 Coder 7B",
        "description": "Fast coding model: ~4.7GB, good for quick iteration and testing",
        "context_limit": 32768,
        "max_tokens": 4096
      }
    },
    "pricing": {
      "qwen2.5-coder:32b": { "input": 0.0, "output": 0.0 },
      "qwen2.5-coder:32b-64k": { "input": 0.0, "output": 0.0 },
      "qwen3:30b-a3b": { "input": 0.0, "output": 0.0 },
      "qwen3:30b-a3b-96k": { "input": 0.0, "output": 0.0 },
      "qwen2.5-coder:7b": { "input": 0.0, "output": 0.0 }
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

### Tool provider overrides (optional)

Simplify tool descriptions for local models:

```json
{
  "tools": {
    "provider_overrides": {
      "asusai": {
        "list_directory": "Show all files in a folder",
        "search_files": "Find files by pattern like *.py"
      }
    }
  }
}
```

## Step 6: Verify Connectivity

```bash
# From the client machine (WSL/Linux)
curl http://<dgx-spark-ip>:11434/v1/models

# Quick test via ppxai
uv run ppxai
# Then: /provider asusai
# Then: /model qwen2.5-coder:32b
# Then: Hello, write a Python hello world
```

## Benchmark Results (2026-02-06)

### Latency (3 iterations, via ppxai Engine)

| Model | TTFT (mean) | Throughput | Notes |
|-------|------------|------------|-------|
| qwen2.5-coder:32b | 7,849ms | 6.3 tok/s | Dense, all 32B params active |
| qwen2.5-coder:32b-64k | 1,300ms | 8.6 tok/s | Fast TTFT after warmup (258ms) |
| qwen3:30b-a3b | 6,970ms | 22.6 tok/s | MoE, 3.6x faster than dense |
| qwen3:30b-a3b-96k | 7,910ms | 20.2 tok/s | 96K ctx, similar to base |

### LLM-Eval (Agentic Coding Quality, 26 tests)

| Model | Score | Passed | Best Categories |
|-------|-------|--------|-----------------|
| qwen2.5-coder:32b-64k | 57.8% | 17/26 | Reasoning 100%, Error Recovery 100%, Format 100% |
| qwen2.5-coder:32b | 51.6% | 15/26 | Reasoning, Error Recovery |
| qwen3:30b-a3b | 46.9% | 14/26 | Reasoning 100%, but Code Editing 0% |

### Key Findings

- **qwen2.5-coder:32b** is the best coding model for quality - trained specifically for code
- **qwen3:30b-a3b** is 3.6x faster on throughput but weaker on coding tasks (MoE trades quality for speed)
- **64K context variant** shows similar or slightly better quality than base (same weights, just larger context window)
- **Cold start TTFT** is ~8-10s for first request (model loading); subsequent requests are much faster
- All models run at 100% GPU offload on the GB10's unified memory

## Model Selection Guide

| Use Case | Recommended Model |
|----------|-------------------|
| Code editing and refactoring | `qwen2.5-coder:32b` |
| Large codebase analysis | `qwen2.5-coder:32b-64k` |
| Quick iteration and testing | `qwen2.5-coder:7b` |
| Long conversations, general tasks | `qwen3:30b-a3b-96k` |
| Fast responses, speed over quality | `qwen3:30b-a3b` |

## Troubleshooting

### Container won't start with GPU

```bash
# Check NVIDIA runtime is available
docker info | grep Runtime
# Should show: nvidia

# Check GPU is visible
nvidia-smi
```

### Model loading is slow (first request)

The first request after pulling a model or container restart triggers model loading into GPU memory. This takes 5-10 seconds. Subsequent requests reuse the loaded model.

To pre-warm a model:
```bash
docker exec ollama ollama run qwen2.5-coder:32b "hello" --nowordwrap
```

### Models not persisting after container restart

Ensure you're using a named volume (`ollama_data`), not a bind mount. Named volumes persist across container recreations:
```bash
docker volume ls | grep ollama
# Should show: local     ollama_data
```

### Connection refused from WSL/remote

Check the container is binding to all interfaces:
```bash
docker exec ollama printenv OLLAMA_HOST
# Should show: 0.0.0.0:11434
```

If not set, the container image sets this by default. Check firewall:
```bash
curl http://<dgx-spark-ip>:11434/api/tags
```

### SSL issues from WSL

If `.env` has `SSL_CERT_FILE` pointing to a Windows path (e.g., `C:\Users\...\.ppxai\cacert.pem`), it won't exist on WSL. The benchmark scripts handle this automatically by cleaning up invalid `SSL_CERT_FILE` entries. For manual runs, unset it:

```bash
unset SSL_CERT_FILE
```

## Running Benchmarks

### Latency benchmark

```bash
export PATH="/path/to/ppxai/.uv:$PATH"
PPXAI_CONFIG_FILE=~/.ppxai/ppxai-config.json SSL_VERIFY=false \
  uv run python scripts/benchmark.py \
    --provider asusai \
    --model "qwen2.5-coder:32b" \
    --iterations 3
```

### LLM-Eval benchmark

```bash
cd benchmarks/llm-eval
PPXAI_CONFIG_FILE=~/.ppxai/ppxai-config.json SSL_VERIFY=false \
  uv run python benchmark.py \
    --provider asusai \
    --model "qwen2.5-coder:32b" \
    --engine \
    --timeout 120 \
    -v
```

> **Important:** Run latency benchmarks first (3 iterations to warm up cold starts), then llm-eval after. Do not run both simultaneously to avoid GPU contention.

## References

- [Ollama Docker Guide](https://github.com/ollama/ollama/blob/main/docs/docker.md)
- [Ollama Modelfile Reference](https://github.com/ollama/ollama/blob/main/docs/modelfile.md)
- [ppxai Provider Setup Guide](PROVIDER_SETUP.md)
- [ppxai Ollama Limitations](ollama-limitations.md)
- [ppxai vLLM Tool Calling Guide](vllm-tool-calling-guide.md)
