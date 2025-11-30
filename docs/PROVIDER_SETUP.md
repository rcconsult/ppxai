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
      "default_model": "gemini-2.0-flash",
      "coding_model": "gemini-2.0-flash",
      "models": {
        "gemini-2.0-flash": {
          "name": "Gemini 2.0 Flash",
          "description": "Latest fast model with multimodal support"
        },
        "gemini-2.0-flash-lite": {
          "name": "Gemini 2.0 Flash Lite",
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
        "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
        "gemini-2.0-flash-lite": {"input": 0.075, "output": 0.30},
        "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
        "gemini-1.5-flash": {"input": 0.075, "output": 0.30}
      },
      "capabilities": {
        "web_search": false,
        "realtime_info": false
      }
    }
  }
}
```

**Note**: The OpenAI-compatible endpoint is `https://generativelanguage.googleapis.com/v1beta/openai`. Some advanced Gemini features (like grounding with Google Search) may not be available through this endpoint.

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
      "default_model": "sonar-pro",
      "coding_model": "sonar-pro",
      "models": {
        "sonar": {
          "name": "Sonar",
          "description": "Lightweight search model"
        },
        "sonar-pro": {
          "name": "Sonar Pro",
          "description": "Advanced search with citations"
        },
        "sonar-reasoning": {
          "name": "Sonar Reasoning",
          "description": "Extended thinking for complex queries"
        }
      },
      "pricing": {
        "sonar": {"input": 1.00, "output": 1.00},
        "sonar-pro": {"input": 3.00, "output": 15.00},
        "sonar-reasoning": {"input": 1.00, "output": 5.00}
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
      "default_model": "sonar-pro",
      "coding_model": "sonar-pro",
      "models": {
        "sonar": {"name": "Sonar", "description": "Lightweight search"},
        "sonar-pro": {"name": "Sonar Pro", "description": "Advanced search"}
      },
      "capabilities": {"web_search": true, "realtime_info": true}
    },
    "openai": {
      "name": "OpenAI ChatGPT",
      "base_url": "https://api.openai.com/v1",
      "api_key_env": "OPENAI_API_KEY",
      "default_model": "gpt-4o",
      "coding_model": "gpt-4o",
      "models": {
        "gpt-4o": {"name": "GPT-4o", "description": "Latest flagship"},
        "gpt-4o-mini": {"name": "GPT-4o Mini", "description": "Fast and affordable"}
      },
      "capabilities": {"web_search": false, "realtime_info": false}
    },
    "gemini": {
      "name": "Google Gemini",
      "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
      "api_key_env": "GEMINI_API_KEY",
      "default_model": "gemini-2.0-flash",
      "coding_model": "gemini-2.0-flash",
      "models": {
        "gemini-2.0-flash": {"name": "Gemini 2.0 Flash", "description": "Fast multimodal"},
        "gemini-1.5-pro": {"name": "Gemini 1.5 Pro", "description": "2M context"}
      },
      "capabilities": {"web_search": false, "realtime_info": false}
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
