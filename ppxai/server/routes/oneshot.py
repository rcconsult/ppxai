"""
v1 gateway: stateless single-turn completion (POST /v1/oneshot).

External agents (outlook-monitor classifier, routers, structured-extraction
pipelines, etc.) often want ppxai-server as a thin LLM gateway without
managing sessions per call. The `/chat` endpoint is session-scoped and
streams via SSE — overkill for "given this prompt, return one response."

`/v1/oneshot` is the gateway primitive:

    POST /v1/oneshot
    {
      "prompt": "Classify this email...",
      "provider": "nvidia",                 // optional
      "model": "qwen/qwen3.5-122b-a10b",    // optional
      "system": "You are a classifier...",  // optional
      "response_format": {"type": "json_object"},  // optional
      "max_tokens": 512,                    // optional
      "temperature": 0.0                    // optional
    }

    → 200 {"content": "...", "finish_reason": "stop", "model": "...",
           "provider": "...", "usage": {...}}

The `/v1/` prefix is the **stable API boundary** — semver-style guarantees
on the request/response shape, see [docs/API-GATEWAY.md] for the policy.
Internal endpoints (`/chat`, `/command/*`, `/files/*`) keep evolving and
are not part of the gateway contract.

Implementation notes:
- No `EngineClient` — we build the provider directly from config so the
  call has zero session-state side effects.
- v1 supports `OpenAICompatibleProvider` (covers `local`, `custom`,
  `openai`-compat NIM/vLLM/Ollama deployments). Native OpenAI / Perplexity
  / Gemini-native providers raise 400 with a clear message until they
  grow `oneshot()`.
- `response_format` forwards to the provider as-is. NVIDIA NIM, vLLM, and
  modern OpenAI-compatible endpoints accept the OpenAI shape
  (`{"type": "json_object"}` or
  `{"type": "json_schema", "json_schema": {...}}`).
- Per-model `extra_body` from config is still applied (so e.g. NIM
  `chat_template_kwargs.enable_thinking` carries through).
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...common.logger import get_logger
from ...config import (
    get_api_key,
    get_available_providers,
    get_base_url,
    get_default_model,
    get_default_provider,
    get_provider_config,
)
from ...engine.providers import create_provider
from ...engine.providers.openai_compat import OpenAICompatibleProvider
from ...engine.types import ProviderCapabilities

logger = get_logger("server")

router = APIRouter(prefix="/v1")


# ---------------------------------------------------------------------------
# Request / response shapes (stable wire contract)
# ---------------------------------------------------------------------------


class OneshotRequest(BaseModel):
    """Stateless single-turn completion request.

    The shape is part of the stable v1 gateway contract — see
    docs/API-GATEWAY.md. Adding optional fields is non-breaking;
    removing or repurposing fields requires a `/v2/oneshot`.
    """
    prompt: str = Field(..., min_length=1, description="User message content.")
    provider: Optional[str] = Field(
        None,
        description="Provider ID. Falls back to the server's default_provider.",
    )
    model: Optional[str] = Field(
        None,
        description="Model ID. Falls back to the provider's default_model.",
    )
    system: Optional[str] = Field(None, description="Optional system message.")
    response_format: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "OpenAI-shaped response_format dict, e.g. "
            '{"type": "json_object"} or '
            '{"type": "json_schema", "json_schema": {...}}.'
        ),
    )
    max_tokens: Optional[int] = Field(
        None, gt=0, description="Cap output tokens. Overrides per-model config."
    )
    temperature: Optional[float] = Field(
        None,
        ge=0.0,
        le=2.0,
        description="Sampling temperature. Overrides per-model config.",
    )


class OneshotUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class OneshotResponse(BaseModel):
    content: str
    finish_reason: Optional[str] = None
    model: str
    provider: str
    usage: Optional[OneshotUsage] = None


# ---------------------------------------------------------------------------
# Provider construction (stateless — no EngineClient)
# ---------------------------------------------------------------------------


def _build_provider(provider_name: str):
    """Construct a provider instance directly from config.

    Mirrors `engine/provider_ops.py::set_provider` minus the
    `EngineClient` mutation. Returns the provider or raises HTTPException
    with a friendly message that the caller can surface to clients.
    """
    # get_provider_config falls back to "perplexity" for unknown providers,
    # which would silently swap providers under the caller. Check membership
    # explicitly first.
    if provider_name not in get_available_providers():
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider: {provider_name!r}. "
            f"Configure it in ppxai-config.json.",
        )
    cfg = get_provider_config(provider_name)

    api_key = get_api_key(provider_name)
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail=f"No API key for provider {provider_name!r}. "
            f"Set it in ~/.ppxai/.env.",
        )

    base_url = get_base_url(provider_name)
    capabilities = ProviderCapabilities.from_dict(cfg.get("capabilities", {}))
    options = cfg.get("options", {})

    provider = create_provider(
        provider_name,
        api_key=api_key,
        base_url=base_url,
        models=cfg.get("models", {}),
        capabilities=capabilities,
        **options,
    )
    if provider is None:
        provider = OpenAICompatibleProvider(
            api_key=api_key,
            base_url=base_url,
            models=cfg.get("models", {}),
            capabilities=capabilities,
            provider_id=provider_name,
        )
    return provider


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.post("/oneshot", response_model=OneshotResponse)
async def oneshot(req: OneshotRequest) -> OneshotResponse:
    """Stateless single-turn completion. See module docstring."""
    provider_name = req.provider or get_default_provider()
    if not provider_name:
        raise HTTPException(
            status_code=400,
            detail="No provider specified and no default_provider configured.",
        )

    model = req.model or get_default_model(provider_name)
    if not model:
        raise HTTPException(
            status_code=400,
            detail=f"No model specified and no default_model for "
            f"provider {provider_name!r}.",
        )

    provider = _build_provider(provider_name)

    # v1 supports OpenAI-compatible providers (covers local/custom/openai-
    # compat NIM/vLLM/Ollama). Other providers grow oneshot() in subsequent
    # versions; until then, surface a clear 400.
    if not isinstance(provider, OpenAICompatibleProvider):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Provider {provider_name!r} doesn't support /v1/oneshot yet. "
                f"v1 supports OpenAI-compatible providers (local, custom, and "
                f"any provider routed through OpenAICompatibleProvider). "
                f"Use POST /chat with X-Session-Id for now."
            ),
        )

    try:
        result = provider.oneshot(
            prompt=req.prompt,
            model=model,
            system=req.system,
            response_format=req.response_format,
            max_tokens=req.max_tokens,
            temperature=req.temperature,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(
            f"/v1/oneshot provider call failed: {provider_name}/{model}: {e}"
        )
        raise HTTPException(
            status_code=502,
            detail=f"Provider call failed: {e}",
        )

    usage = None
    if result.get("usage") is not None:
        usage = OneshotUsage(**result["usage"])

    return OneshotResponse(
        content=result.get("content", ""),
        finish_reason=result.get("finish_reason"),
        model=result.get("model", model),
        provider=provider_name,
        usage=usage,
    )
