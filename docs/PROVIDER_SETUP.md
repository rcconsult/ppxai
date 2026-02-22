# Provider Setup Guide

This guide shows how to configure ppxai with different AI providers using the hybrid configuration system (`.env` for secrets + `ppxai-config.json` for provider settings).

## Table of Contents

- [OpenAI ChatGPT](#openai-chatgpt)
- [Google Gemini](#google-gemini)
- [Perplexity AI](#perplexity-ai)
- [OpenRouter (Claude, Llama, etc.)](#openrouter)
- [Local Models (vLLM, Ollama)](#local-models)
- [Multiple Providers](#multiple-providers)

---

## OpenAI ChatGPT

### `.env`
```bash
# OpenAI API Key
OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Optional: Set OpenAI as default provider
MODEL_PROVIDER=openai

# Optional: SSL verification (for corporate proxies)
SSL_VERIFY=true
```

### `ppxai-config.json`
```json
{
  "version": "1.0",
  "default_provider": "openai",
  "providers": {
    "openai": {
      "name": "OpenAI ChatGPT",
      "base_url": "https://api.openai.com/v1",
      "api_key_env": "OPENAI_API_KEY",
      "default_model": "gpt-4o",
      "coding_model": "gpt-4o",
      "models": {
        "gpt-4o": {
          "name": "GPT-4o",
          "description": "Latest flagship model - best for complex tasks"
        },
        "gpt-4o-mini": {
          "name": "GPT-4o Mini",
          "description": "Fast and affordable for simple tasks"
        },
        "gpt-4-turbo": {
          "name": "GPT-4 Turbo",
          "description": "Previous generation, 128k context"
        },
        "o1-preview": {
          "name": "o1 Preview",
          "description": "Reasoning model for complex problems"
        },
        "o1-mini": {
          "name": "o1 Mini",
          "description": "Faster reasoning model"
        }
      },
      "pricing": {
        "gpt-4o": {"input": 2.50, "output": 10.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-4-turbo": {"input": 10.00, "output": 30.00},
        "o1-preview": {"input": 15.00, "output": 60.00},
        "o1-mini": {"input": 3.00, "output": 12.00}
      },
      "capabilities": {
        "web_search": false,
        "realtime_info": false
      }
    }
  }
}
```

---

## Google Gemini

Google's Gemini API supports OpenAI-compatible endpoints, making it easy to use with ppxai.

### `.env`
```bash
# Google Gemini API Key
GEMINI_API_KEY=AIzaSy-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Optional: Set Gemini as default
MODEL_PROVIDER=gemini
```

### `ppxai-config.json`
```json
{
  "version": "1.0",
  "default_provider": "gemini",
  "providers": {
    "gemini": {
      "name": "Google Gemini",
      "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
      "api_key_env": "GEMINI_API_KEY",
      "default_model": "gemini-2.5-flash",
      "coding_model": "gemini-2.5-flash",
      "options": {
        "enable_grounding": true
      },
      "models": {
        "gemini-2.5-flash": {
          "name": "Gemini 2.5 Flash",
          "description": "Fast model with best price/performance"
        },
        "gemini-2.5-flash-lite": {
          "name": "Gemini 2.5 Flash Lite",
          "description": "Cost-efficient for high-volume tasks"
        },
        "gemini-1.5-pro": {
          "name": "Gemini 1.5 Pro",
          "description": "Best for complex reasoning, 2M context"
        },
        "gemini-1.5-flash": {
          "name": "Gemini 1.5 Flash",
          "description": "Fast and versatile, 1M context"
        }
      },
      "pricing": {
        "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
        "gemini-2.5-flash-lite": {"input": 0.075, "output": 0.30},
        "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
        "gemini-1.5-flash": {"input": 0.075, "output": 0.30}
      },
      "capabilities": {
        "web_search": true,
        "realtime_info": true
      }
    }
  }
}
```

### Gemini Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enable_grounding` | boolean | `true` | Enable Google Search Grounding for real-time web search with citations |

**Note**: The OpenAI-compatible endpoint is `https://generativelanguage.googleapis.com/v1beta/openai`. For native Google Search Grounding with citations (similar to Perplexity), install `pip install ppxai[gemini]` which uses the native Gemini SDK.

**v1.13.3+**: When tools are enabled, both grounding AND tool prompts work together - grounding provides web search capabilities while tools provide other features like file editing, shell commands, etc.

---

## Perplexity AI

Perplexity is the default provider and has built-in web search capabilities.

### `.env`
```bash
# Perplexity API Key
PERPLEXITY_API_KEY=pplx-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Optional: Perplexity is default, but you can be explicit
MODEL_PROVIDER=perplexity
```

### `ppxai-config.json`
```json
{
  "version": "1.0",
  "default_provider": "perplexity",
  "providers": {
    "perplexity": {
      "name": "Perplexity AI",
      "base_url": "https://api.perplexity.ai",
      "api_key_env": "PERPLEXITY_API_KEY",
      "default_model": "sonar",
      "coding_model": "sonar-pro",
      "models": {
        "sonar": {
          "name": "Sonar",
          "description": "Fast search model, low cost ($0.20/M tokens)"
        },
        "sonar-pro": {
          "name": "Sonar Pro",
          "description": "Advanced search with citations (upgrade for complex queries)"
        },
        "sonar-reasoning-pro": {
          "name": "Sonar Reasoning Pro",
          "description": "Extended thinking for complex queries"
        },
        "sonar-deep-research": {
          "name": "Sonar Deep Research",
          "description": "Multi-step research for comprehensive answers"
        }
      },
      "pricing": {
        "sonar": {"input": 1.00, "output": 1.00},
        "sonar-pro": {"input": 3.00, "output": 15.00},
        "sonar-reasoning-pro": {"input": 2.00, "output": 8.00},
        "sonar-deep-research": {"input": 2.00, "output": 8.00}
      },
      "capabilities": {
        "web_search": true,
        "realtime_info": true
      }
    }
  }
}
```

---

## OpenRouter

OpenRouter provides access to many models including Claude, Llama, Mistral, and more through a single API.

### `.env`
```bash
# OpenRouter API Key
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

MODEL_PROVIDER=openrouter
```

### `ppxai-config.json`
```json
{
  "version": "1.0",
  "default_provider": "openrouter",
  "providers": {
    "openrouter": {
      "name": "OpenRouter",
      "base_url": "https://openrouter.ai/api/v1",
      "api_key_env": "OPENROUTER_API_KEY",
      "default_model": "anthropic/claude-sonnet-4",
      "coding_model": "anthropic/claude-sonnet-4",
      "models": {
        "anthropic/claude-sonnet-4": {
          "name": "Claude Sonnet 4",
          "description": "Anthropic's balanced model"
        },
        "anthropic/claude-opus-4": {
          "name": "Claude Opus 4",
          "description": "Anthropic's most capable model"
        },
        "anthropic/claude-haiku": {
          "name": "Claude Haiku",
          "description": "Fast and affordable"
        },
        "meta-llama/llama-3.1-405b-instruct": {
          "name": "Llama 3.1 405B",
          "description": "Meta's largest open model"
        },
        "meta-llama/llama-3.1-70b-instruct": {
          "name": "Llama 3.1 70B",
          "description": "Excellent open-source model"
        },
        "mistralai/mistral-large": {
          "name": "Mistral Large",
          "description": "Mistral's flagship model"
        },
        "google/gemini-pro-1.5": {
          "name": "Gemini Pro 1.5",
          "description": "Google's model via OpenRouter"
        }
      },
      "pricing": {
        "anthropic/claude-sonnet-4": {"input": 3.00, "output": 15.00},
        "anthropic/claude-opus-4": {"input": 15.00, "output": 75.00},
        "anthropic/claude-haiku": {"input": 0.25, "output": 1.25},
        "meta-llama/llama-3.1-405b-instruct": {"input": 3.00, "output": 3.00},
        "meta-llama/llama-3.1-70b-instruct": {"input": 0.50, "output": 0.50},
        "mistralai/mistral-large": {"input": 2.00, "output": 6.00},
        "google/gemini-pro-1.5": {"input": 2.50, "output": 7.50}
      },
      "capabilities": {
        "web_search": false,
        "realtime_info": false
      }
    }
  }
}
```

**Note**: OpenRouter is a great way to access Claude models since Anthropic's native API uses a different format that isn't OpenAI-compatible.

---

## Local Models

### vLLM

For self-hosted models using vLLM.

### `.env`
```bash
# vLLM typically doesn't require a real API key
LOCAL_VLLM_API_KEY=dummy-key

MODEL_PROVIDER=local-vllm
```

### `ppxai-config.json`
```json
{
  "version": "1.0",
  "default_provider": "local-vllm",
  "providers": {
    "local-vllm": {
      "name": "Local vLLM",
      "base_url": "http://localhost:8000/v1",
      "api_key_env": "LOCAL_VLLM_API_KEY",
      "default_model": "meta-llama/Llama-3-70b",
      "coding_model": "meta-llama/Llama-3-70b",
      "models": {
        "meta-llama/Llama-3-70b": {
          "name": "Llama 3 70B",
          "description": "Self-hosted Llama model"
        }
      },
      "pricing": {
        "meta-llama/Llama-3-70b": {"input": 0.0, "output": 0.0}
      },
      "capabilities": {
        "web_search": false,
        "realtime_info": false
      }
    }
  }
}
```

### Ollama

For local models using Ollama.

### `.env`
```bash
# Ollama doesn't require an API key
OLLAMA_API_KEY=ollama

MODEL_PROVIDER=ollama
```

### `ppxai-config.json`
```json
{
  "version": "1.0",
  "default_provider": "ollama",
  "providers": {
    "ollama": {
      "name": "Ollama (Local)",
      "base_url": "http://localhost:11434/v1",
      "api_key_env": "OLLAMA_API_KEY",
      "default_model": "llama3.1",
      "coding_model": "codellama",
      "models": {
        "llama3.1": {
          "name": "Llama 3.1",
          "description": "Latest Llama model"
        },
        "llama3.1:70b": {
          "name": "Llama 3.1 70B",
          "description": "Larger Llama model"
        },
        "codellama": {
          "name": "Code Llama",
          "description": "Optimized for coding tasks"
        },
        "mistral": {
          "name": "Mistral 7B",
          "description": "Fast and capable"
        },
        "mixtral": {
          "name": "Mixtral 8x7B",
          "description": "Mixture of experts model"
        }
      },
      "pricing": {
        "llama3.1": {"input": 0.0, "output": 0.0},
        "llama3.1:70b": {"input": 0.0, "output": 0.0},
        "codellama": {"input": 0.0, "output": 0.0},
        "mistral": {"input": 0.0, "output": 0.0},
        "mixtral": {"input": 0.0, "output": 0.0}
      },
      "capabilities": {
        "web_search": false,
        "realtime_info": false
      }
    }
  }
}
```

---

## Multiple Providers

You can configure multiple providers and switch between them using the `/provider` command.

### `.env`
```bash
# Multiple API keys
PERPLEXITY_API_KEY=pplx-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
GEMINI_API_KEY=AIzaSy-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Default to Perplexity (has web search)
MODEL_PROVIDER=perplexity
```

### `ppxai-config.json`
```json
{
  "version": "1.0",
  "default_provider": "perplexity",
  "providers": {
    "perplexity": {
      "name": "Perplexity AI",
      "base_url": "https://api.perplexity.ai",
      "api_key_env": "PERPLEXITY_API_KEY",
      "default_model": "sonar",
      "coding_model": "sonar-pro",
      "models": {
        "sonar": {"name": "Sonar", "description": "Fast search, low cost"},
        "sonar-pro": {"name": "Sonar Pro", "description": "Advanced search"}
      },
      "capabilities": {"web_search": true, "realtime_info": true}
    },
    "openai": {
      "name": "OpenAI ChatGPT",
      "base_url": "https://api.openai.com/v1",
      "api_key_env": "OPENAI_API_KEY",
      "default_model": "gpt-5-mini",
      "coding_model": "gpt-5.1-codex",
      "models": {
        "gpt-5-mini": {"name": "GPT-5 Mini", "description": "Balanced performance, low cost"},
        "gpt-5.2": {"name": "GPT-5.2", "description": "Flagship model for complex tasks"}
      },
      "capabilities": {"web_search": false, "realtime_info": false}
    },
    "gemini": {
      "name": "Google Gemini",
      "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
      "api_key_env": "GEMINI_API_KEY",
      "default_model": "gemini-2.5-flash",
      "coding_model": "gemini-2.5-flash",
      "models": {
        "gemini-2.5-flash": {"name": "Gemini 2.5 Flash", "description": "Fast multimodal"},
        "gemini-1.5-pro": {"name": "Gemini 1.5 Pro", "description": "2M context"}
      },
      "capabilities": {"web_search": true, "realtime_info": true}
    },
    "openrouter": {
      "name": "OpenRouter (Claude)",
      "base_url": "https://openrouter.ai/api/v1",
      "api_key_env": "OPENROUTER_API_KEY",
      "default_model": "anthropic/claude-sonnet-4",
      "coding_model": "anthropic/claude-sonnet-4",
      "models": {
        "anthropic/claude-sonnet-4": {"name": "Claude Sonnet 4", "description": "Balanced"},
        "anthropic/claude-opus-4": {"name": "Claude Opus 4", "description": "Most capable"}
      },
      "capabilities": {"web_search": false, "realtime_info": false}
    }
  }
}
```

### Switching Providers

In ppxai, use the `/provider` command to switch between configured providers:

```
You: /provider
Current provider: perplexity

Available providers:
1. perplexity - Perplexity AI (configured)
2. openai - OpenAI ChatGPT (configured)
3. gemini - Google Gemini (configured)
4. openrouter - OpenRouter (configured)

Select provider [1-4]:
```

---

## Configuration File Locations

ppxai searches for `ppxai-config.json` in this order:

1. `PPXAI_CONFIG_FILE` environment variable (if set)
2. `./ppxai-config.json` (current directory - project-specific)
3. `~/.ppxai/ppxai-config.json` (home directory - user-specific)
4. Built-in defaults (Perplexity only)

This allows you to:
- Share project-specific configs with your team (commit to git)
- Have personal configs in your home directory
- Override with environment variable for testing

---

## Troubleshooting

### API Key Not Found
```
Error: OPENAI_API_KEY not found in environment variables.
```
**Solution**: Make sure your `.env` file is in the same directory where you run ppxai, or set the environment variable directly.

### Invalid Model
```
Error: Invalid model 'gpt-5'. Permitted models can be found in the documentation.
```
**Solution**: Check the provider's documentation for available model names. Model names must match exactly.

### Connection Refused (Local Models)
```
Error: Connection refused at localhost:8000
```
**Solution**: Make sure your local model server (vLLM, Ollama) is running before starting ppxai.

### SSL Certificate Errors
```
[SSL: CERTIFICATE_VERIFY_FAILED]
```
**Solution**: If you're behind a corporate proxy, add `SSL_VERIFY=false` to your `.env` file (not recommended for production).

---

## Advanced Features

### Premium Web Search for Custom Providers

When using custom providers (vLLM, Ollama, etc.) that don't have native web search, ppxai can use Perplexity or Gemini for web search tool calls:

```bash
# .env - Add one of these for premium web search
PERPLEXITY_API_KEY=pplx-xxxxx  # Uses Perplexity Sonar API
GEMINI_API_KEY=AIza-xxxxx      # Uses Gemini with Google Search Grounding
```

Priority: Perplexity > Gemini > DuckDuckGo (free fallback)

### SSL Verification

For corporate environments with SSL inspection:

```bash
# .env
SSL_VERIFY=false  # Disables SSL certificate verification
```

This setting is respected by:
- All OpenAI-compatible API calls
- Premium web search (Perplexity, Gemini)
- URL fetching tools

**⚠️ Security Warning**: Only use `SSL_VERIFY=false` in trusted corporate environments where SSL inspection is required.

---

## Provider-Specific Hints (v1.14.0+)

You can provide provider-specific instructions via `AGENTS.md` bootstrap files. This is especially useful when switching between providers mid-session.

### Creating AGENTS.md

Create an `AGENTS.md` file in your project root:

```markdown
---
provider_hints:
  local:
    - "Complete tasks fully without stopping on empty responses."
    - "Use tools proactively - don't ask for permission."
  ollama:
    - "Keep responses concise - limited context window."
  gemini:
    - "Use Google Search grounding for current information."
  perplexity:
    - "Use your native web search - don't use web_search tool."
    - "Cite sources as markdown links inline."
model_hints:
  "deepseek-r1*":
    - "Show reasoning before taking actions."
  "qwen2.5-coder*":
    - "Focus on code quality and correctness."
---

# Project Instructions

Your project-specific instructions here...
```

### How It Works

- **Provider hints** apply when using that provider (e.g., `ollama` hints for Ollama)
- **`local` hints** apply to all local providers: `ollama`, `vllm`, `lmstudio`
- **Model hints** match against model names using glob patterns (`*` = any characters)
- Hints are dynamically applied when you switch provider/model with `/provider` or `/model`

### Combining with System Prompts

Bootstrap context works alongside `system_prompt` in `ppxai-config.json`:

```json
{
  "system_prompt": "You are a helpful coding assistant.",
  "system_prompt_mode": "prepend"
}
```

Modes:
- `prepend` (default): Config prompt appears before bootstrap content
- `append`: Config prompt appears after bootstrap content
- `replace`: Config prompt replaces bootstrap (not recommended)

### Debugging Hints

Use `/context hints` to see which hints are active for your current provider/model:

```
/context hints
```

See [Bootstrap Context Guide](BOOTSTRAP_CONTEXT_GUIDE.md) for full documentation.

---

## Generation Parameters (v1.15.0+)

Fine-tune model behavior with generation parameters at the provider or model level. These parameters control response determinism, creativity, and repetition.

### Available Parameters

| Parameter | Range | Coding Recommendation | Description |
|-----------|-------|----------------------|-------------|
| `temperature` | 0.0-2.0 | 0.1-0.3 | Lower = more deterministic, reduces hallucinations |
| `top_p` | 0.0-1.0 | 0.9 | Nucleus sampling, controls diversity |
| `frequency_penalty` | -2.0-2.0 | 0.1-0.2 | Reduces token repetition |
| `presence_penalty` | -2.0-2.0 | 0.0 | Encourages new topics (keep at 0 for focused coding) |
| `seed` | integer | (optional) | For reproducibility (if supported by provider) |

### Provider-Level Configuration

Apply parameters to all models from a provider:

```json
{
  "providers": {
    "custom": {
      "name": "Internal Code AI",
      "base_url": "https://your-server/v1",
      "api_key_env": "CUSTOM_API_KEY",
      "default_model": "your-model",
      "generation_params": {
        "temperature": 0.2,
        "top_p": 0.9,
        "frequency_penalty": 0.15,
        "presence_penalty": 0.0
      }
    }
  }
}
```

### Model-Level Configuration

Override provider defaults for specific models:

```json
{
  "providers": {
    "ollama": {
      "name": "Ollama Local",
      "base_url": "http://localhost:11434/v1",
      "api_key_env": "OLLAMA_API_KEY",
      "default_model": "qwen2.5-coder:3b",
      "generation_params": {
        "temperature": 0.2,
        "top_p": 0.9
      },
      "models": {
        "qwen2.5-coder:3b": {
          "name": "Qwen2.5 Coder 3B",
          "description": "Best coding model",
          "context_limit": 32768,
          "generation_params": {
            "temperature": 0.1,
            "frequency_penalty": 0.2
          }
        },
        "deepseek-r1:8b": {
          "name": "DeepSeek R1 8B",
          "description": "Reasoning model",
          "generation_params": {
            "temperature": 0.6
          }
        }
      }
    }
  }
}
```

**Priority**: Model-level params > Provider-level params > ppxai defaults

### Recommended Settings by Use Case

| Use Case | Temperature | Top P | Freq Penalty | Notes |
|----------|-------------|-------|--------------|-------|
| **Code generation** | 0.1-0.2 | 0.9 | 0.15 | Deterministic, avoid repetition |
| **Code review** | 0.2-0.3 | 0.9 | 0.1 | Slightly more flexible analysis |
| **Creative writing** | 0.7-1.0 | 0.95 | 0.0 | Allow diversity |
| **Reasoning tasks** | 0.5-0.7 | 0.9 | 0.0 | DeepSeek R1, o1 models |
| **Web search/research** | 0.3 | 0.9 | 0.1 | Balance accuracy and readability |

### Using Comments in Config

You can add documentation comments (ignored by ppxai):

```json
{
  "generation_params": {
    "temperature": 0.2,
    "top_p": 0.9,
    "frequency_penalty": 0.15,
    "__comment_temperature": "0.0-2.0: Lower = more deterministic (coding: 0.1-0.3)",
    "__comment_top_p": "0.0-1.0: Nucleus sampling (coding: 0.9)",
    "__comment_frequency_penalty": "-2.0-2.0: Reduces repetition (coding: 0.1-0.2)"
  }
}
```

Keys starting with `__comment` are automatically filtered out before API calls.

### Verifying Parameters

Check that parameters are being applied:

```bash
# Enable debug logging
ppxaide --debug

# Look for generation_params in the debug output
```

Or check the TUI debug log at `~/.ppxai/logs/tui-debug.log`.
