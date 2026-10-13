"""The OpenAI SDK half of the provider base (ADR 0016 §4).

`BaseProvider` used to import the OpenAI SDK for every provider: it built an
`OpenAI` client in `__init__`, used `openai.NOT_GIVEN` for the client
timeout and mapped `openai.*Error` classes to user messages. So a Gemini or
Anthropic session paid for the OpenAI SDK because the shared base class was
the OpenAI wire's. That half lives here now, used by the two providers that
speak through the SDK (`openai_compat`, `openai_native`); `BaseProvider`
keeps only what is wire-neutral.
"""

import re
from typing import Any

import httpx
import openai
from openai import OpenAI

from ...common.logger import get_logger
from ...config import get_provider_config
from ...config.network import is_loopback_url
from ...config.tls import tls_verify

logger = get_logger(__name__)


def client_timeout(provider_id: str | None) -> float | openai.NotGiven:
    """`providers.<id>.timeout_s` for the OpenAI SDK client, else its default.

    The SDK default is a 600 s read timeout with 2 retries, so an upstream
    that accepts a request and never answers held it for up to ~30 minutes
    (2026-09-28: kimi-k3 on NVIDIA). A per-provider value bounds each
    attempt. Unset, zero, negative or non-numeric keeps the SDK default.
    """
    if not provider_id:
        return openai.NOT_GIVEN
    raw = (get_provider_config(provider_id) or {}).get("timeout_s")
    if raw is None:
        return openai.NOT_GIVEN
    try:
        value = float(raw)
    except (TypeError, ValueError):
        logger.warning(f"providers.{provider_id}.timeout_s={raw!r} is not a number; ignored")
        return openai.NOT_GIVEN
    return value if value > 0 else openai.NOT_GIVEN


def build_openai_client(api_key: str, base_url: str, provider_id: str | None) -> OpenAI:
    """An `OpenAI` client for an OpenAI-compatible endpoint at `base_url`.

    TLS verification: env (SSL_VERIFY / SSL_CERT_FILE) then
    network.ssl.* in ppxai-config.json. Resolved in ONE place so this
    site cannot drift from the other outbound clients — it already had
    (see ppxai/config/tls.py). tls_verify() returns False (off) or an
    SSLContext — never True — so the client always carries an explicit
    policy; a `verify is True` fast path would be dead code.
    A loopback base_url (local vLLM/Ollama/LM Studio, an SSH forward)
    must not go through HTTP_PROXY; a hosted one keeps it.
    """
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        http_client=httpx.Client(verify=tls_verify(),
                                 trust_env=not is_loopback_url(base_url)),
        timeout=client_timeout(provider_id),
    )


class OpenAIWireMixin:
    """Error handling for providers that call through the OpenAI SDK.

    Listed before `BaseProvider` in the bases, so these run first and fall
    back to the wire-neutral `BaseProvider` versions for anything that is
    not an `openai` exception.
    """

    def _format_error(self, e: Exception) -> str:
        """Format exception into user-friendly error message.

        Provides clear, actionable messages for common errors while preserving
        technical details for debugging when needed.

        Args:
            e: The exception to format

        Returns:
            User-friendly error message
        """
        error_str = str(e)

        # Connection errors (no network, DNS failure, VPN required)
        if isinstance(e, openai.APIConnectionError):
            # Extract the root cause
            if "getaddrinfo failed" in error_str:
                return (
                    "Connection failed: Unable to resolve hostname.\n"
                    "Check that:\n"
                    "  - You have network connectivity\n"
                    "  - VPN is connected (if required for this endpoint)\n"
                    "  - The API endpoint URL is correct"
                )
            elif "Connection refused" in error_str:
                return (
                    "Connection refused: Server is not reachable.\n"
                    "Check that:\n"
                    "  - The server is running\n"
                    "  - The port number is correct\n"
                    "  - Firewall is not blocking the connection"
                )
            elif "timed out" in error_str.lower():
                return (
                    "Connection timed out: Server did not respond.\n"
                    "Check that:\n"
                    "  - The server is running and responsive\n"
                    "  - Network latency is acceptable"
                )
            else:
                return "Connection failed: Unable to reach the server."

        # Authentication errors
        if isinstance(e, openai.AuthenticationError):
            return (
                "Authentication failed: Invalid API key.\n"
                "Check that your API key is correct in .env or ppxai-config.json"
            )

        # Rate limiting
        if isinstance(e, openai.RateLimitError):
            return "Rate limit exceeded. Please wait before retrying."

        # Bad request (invalid parameters)
        if isinstance(e, openai.BadRequestError):
            # Extract just the error message, not the full JSON
            if "'message':" in error_str:
                match = re.search(r"'message':\s*'([^']+)'", error_str)
                if match:
                    return f"Invalid request: {match.group(1)}"
            return f"Invalid request: {error_str}"

        # API errors (server-side issues)
        if isinstance(e, openai.APIStatusError):
            # v1.18.3: provider-side throttle / quota — recognize NIM-style
            # "operation not allowed" 403 + generic 429 with cleaner messages
            # so users learn this is a provider quota block, not a model bug.
            if e.status_code == 403:
                if "operation not allowed" in error_str.lower():
                    return (
                        "Provider quota / permission error (403): "
                        "endpoint refused the call. On NVIDIA NIM free tier "
                        "this typically means the per-model rate limit was "
                        "exhausted — wait, switch model, or use paid tier."
                    )
                return f"Provider permission error (403): {error_str}"
            if e.status_code == 429:
                return (
                    f"Provider rate limit (429): {error_str}. "
                    f"Wait before retrying or switch to another model."
                )
            return f"API error ({e.status_code}): {error_str}"

        return super()._format_error(e)

    def _classify_throttle(self, e: Exception) -> dict[str, Any] | None:
        """Detect provider-side rate-limit / quota errors and return a
        structured payload for ``EventType.PROVIDER_THROTTLED``.

        Returns a dict with keys ``status_code``, ``provider``, ``message``,
        ``retry_after`` when the exception is a 429 ``RateLimitError`` or
        a 403 ``APIStatusError``; otherwise ``None`` so the caller falls
        back to ``EventType.ERROR``.

        v1.18.3: introduced alongside NVIDIA NIM provider work — free-tier
        NIM returns HTTP 403 ``{"message":"Operation not allowed"}`` when
        per-model quota exhausts, indistinguishable from a model failure
        until you know to look at the status code.
        """
        if not isinstance(e, openai.APIStatusError):
            return None
        status = getattr(e, "status_code", None)
        if status not in (403, 429):
            return None
        retry_after: float | None = None
        try:
            response = getattr(e, "response", None)
            if response is not None:
                header = response.headers.get("retry-after")
                if header:
                    retry_after = float(header)
        except (AttributeError, TypeError, ValueError):
            retry_after = None
        return {
            "status_code": int(status),
            "provider": self.provider_id or "",
            "message": self._format_error(e),
            "retry_after": retry_after,
        }
