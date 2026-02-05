"""
Benchmark runner - executes tests against LLM API.

Supports loading generation params from ppxai config for consistent benchmarking.
"""

import asyncio
import json
import os
import ssl
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from openai import AsyncOpenAI

from test_cases import ALL_TESTS, TestCase, get_categories
from results import BenchmarkResult


def load_ppxai_config() -> dict:
    """Load ppxai config from user's home directory."""
    config_paths = [
        Path.home() / ".ppxai" / "ppxai-config.json",
        Path.home() / ".config" / "ppxai" / "ppxai-config.json",
    ]

    for path in config_paths:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                continue

    return {}


def get_provider_config(config: dict, provider: str) -> dict:
    """Get provider configuration from ppxai config."""
    return config.get("providers", {}).get(provider, {})


def get_model_config(provider_config: dict, model: str) -> dict:
    """Get model-specific configuration from provider config."""
    return provider_config.get("models", {}).get(model, {})


def get_generation_params(config: dict, provider: str, model: str) -> dict:
    """
    Get generation params for a provider/model pair.

    Priority (highest to lowest):
    1. Model-specific generation_params
    2. Provider-level generation_params
    3. Empty dict (use API defaults)
    """
    provider_config = get_provider_config(config, provider)
    model_config = get_model_config(provider_config, model)

    # Start with provider-level params
    params = dict(provider_config.get("generation_params", {}))

    # Override with model-specific params
    params.update(model_config.get("generation_params", {}))

    # Add max_tokens if specified at model level
    if "max_tokens" in model_config:
        params["max_tokens"] = model_config["max_tokens"]

    return params


class LLMClient:
    """Wrapper for OpenAI-compatible API."""

    def __init__(
        self,
        provider: str,
        model: str,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: int = 60,
        ssl_verify: bool = True,
        ssl_cert_file: Optional[str] = None,
        generation_params: Optional[dict] = None,
    ):
        self.provider = provider
        self.model = model
        self.timeout = timeout
        self.generation_params = generation_params or {}

        # Determine base URL and API key
        if base_url:
            self.base_url = base_url
        else:
            self.base_url = self._default_base_url(provider)

        if api_key:
            self.api_key = api_key
        else:
            self.api_key = self._default_api_key(provider)

        # Configure SSL
        http_client = None
        if not ssl_verify:
            # Disable SSL verification (for corporate proxies)
            http_client = httpx.AsyncClient(verify=False)
        elif ssl_cert_file:
            # Use custom CA bundle
            http_client = httpx.AsyncClient(verify=ssl_cert_file)

        self.client = AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=timeout,
            http_client=http_client,
        )

    def _default_base_url(self, provider: str) -> str:
        """Get default base URL for provider."""
        defaults = {
            "openai": "https://api.openai.com/v1",
            "perplexity": "https://api.perplexity.ai",
            "openrouter": "https://openrouter.ai/api/v1",
            "ollama": "http://localhost:11434/v1",
            "vllm": "http://localhost:8000/v1",
            "lmstudio": "http://localhost:1234/v1",
        }
        return defaults.get(provider, "http://localhost:8000/v1")

    def _default_api_key(self, provider: str) -> str:
        """Get API key from environment."""
        env_vars = {
            "openai": "OPENAI_API_KEY",
            "perplexity": "PERPLEXITY_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
        }
        env_var = env_vars.get(provider, f"{provider.upper()}_API_KEY")
        key = os.environ.get(env_var, "")

        # For local providers, use dummy key
        if not key and provider in ("ollama", "vllm", "lmstudio", "local"):
            key = "not-needed"

        return key

    async def chat(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        verbose: bool = False,
        **kwargs,
    ) -> dict:
        """Send chat completion request."""
        try:
            params = {
                "model": self.model,
                "messages": messages,
            }

            # Add generation params from config
            if self.generation_params:
                params.update(self.generation_params)

            if tools:
                params["tools"] = tools
                params["tool_choice"] = "auto"

            response = await self.client.chat.completions.create(**params)

            if verbose:
                print(f"\n  [DEBUG] Raw response: {response}")

            # Extract response
            choice = response.choices[0]
            result = {
                "content": choice.message.content or "",
                "tool_calls": [],
                "finish_reason": choice.finish_reason,
            }

            if choice.message.tool_calls:
                result["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        }
                    }
                    for tc in choice.message.tool_calls
                ]

            return result

        except Exception as e:
            if verbose:
                print(f"\n  [DEBUG] Exception: {e}")
            return {
                "content": "",
                "tool_calls": [],
                "error": str(e),
            }


class BenchmarkRunner:
    """Runs benchmark tests against an LLM."""

    def __init__(
        self,
        provider: str,
        model: str,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: int = 60,
        retries: int = 1,
        verbose: bool = False,
        ssl_verify: bool = True,
        ssl_cert_file: Optional[str] = None,
        use_ppxai_config: bool = True,
        generation_params: Optional[dict] = None,
    ):
        self.provider = provider
        self.model = model
        self.timeout = timeout
        self.retries = retries
        self.verbose = verbose

        # Load generation params
        if generation_params:
            # Explicit params override everything
            self.generation_params = generation_params
        elif use_ppxai_config:
            # Load from ppxai config
            config = load_ppxai_config()
            self.generation_params = get_generation_params(config, provider, model)

            # Also get base_url and api_key from config if not provided
            if not base_url:
                provider_config = get_provider_config(config, provider)
                base_url = provider_config.get("base_url")

            if not api_key:
                provider_config = get_provider_config(config, provider)
                api_key_env = provider_config.get("api_key_env")
                if api_key_env:
                    api_key = os.environ.get(api_key_env, "")
        else:
            self.generation_params = {}

        self.client = LLMClient(
            provider=provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
            ssl_verify=ssl_verify,
            ssl_cert_file=ssl_cert_file,
            generation_params=self.generation_params,
        )

    def run(self, categories: Optional[list[str]] = None) -> BenchmarkResult:
        """Run benchmark synchronously."""
        return asyncio.run(self.run_async(categories))

    async def run_async(self, categories: Optional[list[str]] = None) -> BenchmarkResult:
        """Run benchmark tests."""
        start_time = time.time()

        # Filter tests by category if specified
        tests = ALL_TESTS
        if categories:
            tests = [t for t in tests if t.category in categories]

        test_results = []
        category_results = {}  # category -> list of (passed, weight)

        print(f"Running {len(tests)} tests...")
        print()

        for i, test in enumerate(tests, 1):
            print(f"[{i}/{len(tests)}] {test.category}/{test.name}...", end=" ", flush=True)

            passed = False
            details = {}

            for attempt in range(self.retries):
                try:
                    passed, details = await asyncio.wait_for(
                        test.run(self.client),
                        timeout=self.timeout,
                    )
                    if passed:
                        break
                except asyncio.TimeoutError:
                    details = {"error": "Timeout"}
                except Exception as e:
                    details = {"error": str(e)}

                if attempt < self.retries - 1:
                    print("(retry)", end=" ", flush=True)

            status = "PASS" if passed else "FAIL"
            print(status)

            if self.verbose and not passed:
                error = details.get("error", "Unknown error")
                print(f"      Error: {error[:80]}")

            # Record result
            test_results.append({
                "name": test.name,
                "category": test.category,
                "passed": passed,
                "details": details,
                "weight": test.weight,
            })

            # Track by category
            if test.category not in category_results:
                category_results[test.category] = []
            category_results[test.category].append((passed, test.weight))

        # Calculate scores
        total_weight = sum(t.weight for t in tests)
        passed_weight = sum(r["weight"] for r in test_results if r["passed"])
        overall_score = (passed_weight / total_weight * 100) if total_weight > 0 else 0

        category_scores = {}
        for category, results in category_results.items():
            cat_total = sum(w for _, w in results)
            cat_passed = sum(w for p, w in results if p)
            category_scores[category] = (cat_passed / cat_total * 100) if cat_total > 0 else 0

        duration = time.time() - start_time

        return BenchmarkResult(
            provider=self.provider,
            model=self.model,
            timestamp=datetime.utcnow().isoformat(),
            overall_score=overall_score,
            tests_passed=sum(1 for r in test_results if r["passed"]),
            tests_total=len(test_results),
            duration_seconds=duration,
            category_scores=category_scores,
            test_results=test_results,
            metadata={
                "base_url": self.client.base_url,
                "timeout": self.timeout,
                "retries": self.retries,
                "generation_params": self.generation_params,
            },
        )
