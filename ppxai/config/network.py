"""Is a configured URL a loopback hop?

httpx sends requests for `127.0.0.1` and `localhost` to `HTTP_PROXY` when it
is set (docs/lessons/loopback-http-hops-must-not-read-proxy-env.md). A client
whose URL comes from config -- an OpenAI-compatible provider's `base_url`, the
vision sidecar's endpoint, the `/doctor` model probe -- can point either way:
a local vLLM, Ollama or LM Studio, or an SSH forward, is loopback and must
skip the proxy; a hosted API is outbound and must keep it. So these clients
pass `trust_env=not is_loopback_url(url)` rather than a blanket setting.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit


def is_loopback_url(url: str | None) -> bool:
    """True when `url`'s host is `localhost` or a loopback address
    (127.0.0.0/8, ::1). False for anything else, including no URL."""
    if not url:
        return False
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return False
    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
