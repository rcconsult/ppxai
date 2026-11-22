"""GET /files/remote-image — a web image the user allowed, fetched by the server.

The web UI loads an answer's image by itself only when this server serves it
(`web/shared/image-policy.js`, and `img-src 'self' data: blob:` on the page).
An image from another host stays a link until the user allows web images for
the conversation; then the page asks this route for it, so the CSP never has
to name another host.

What the route fetches is limited, because an image URL may have been
written after a prompt injection:

- HTTPS only, no user name or password in the URL;
- every address the host resolves to must be a public one (no loopback,
  private, link-local, CGNAT, multicast or reserved range), and the
  connection goes to the address that was checked, so a second DNS answer
  cannot swap in a local one; each redirect is checked the same way;
- at most 3 redirects, 10 s, 10 MB, and only raster image types (an SVG
  could carry script if opened on this origin);
- the request carries no cookies, no referrer and a generic User-Agent.

`key` must match `REMOTE_IMAGE_KEY`, which only the served page knows
(`static.py` writes it into `index.html`). Without it, a model could write
`![x](/files/remote-image?url=...)` — a same-origin image that loads with no
click — and have the server send the URL for it.
"""

from __future__ import annotations

import asyncio
import hmac
import ipaddress
import logging
import secrets
import socket

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

router = APIRouter()

#: Written into the served page; a request without it is refused.
REMOTE_IMAGE_KEY = secrets.token_urlsafe(24)

MAX_BYTES = 10 * 1024 * 1024
TIMEOUT_S = 10.0
MAX_REDIRECTS = 3
IMAGE_TYPES = frozenset({
    "image/png", "image/jpeg", "image/gif", "image/webp", "image/avif",
    "image/bmp", "image/x-icon", "image/vnd.microsoft.icon",
})
_REDIRECTS = frozenset({301, 302, 303, 307, 308})
_USER_AGENT = "ppxai-image-fetch"


class RemoteImageError(Exception):
    """The URL or the answer is not one this route fetches."""


def is_public_address(address: str) -> bool:
    """True only for a globally routable unicast address."""
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


async def resolve_public(host: str, port: int) -> str:
    """One address for `host`, after checking that every address is public."""
    try:
        return _checked(str(ipaddress.ip_address(host)))
    except ValueError:
        pass
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise RemoteImageError(f"cannot resolve {host}") from exc
    addresses = [info[4][0] for info in infos]
    if not addresses:
        raise RemoteImageError(f"cannot resolve {host}")
    for address in addresses:
        _checked(address)
    return addresses[0]


def _checked(address: str) -> str:
    if not is_public_address(address):
        raise RemoteImageError(f"{address} is not a public address")
    return address


def check_url(url: httpx.URL) -> None:
    if url.scheme != "https":
        raise RemoteImageError("only https images are fetched")
    if url.userinfo:
        raise RemoteImageError("a URL with a user name or password is not fetched")
    if not url.host:
        raise RemoteImageError("the URL has no host")


async def fetch_remote_image(raw_url: str, client: httpx.AsyncClient) -> tuple[bytes, str]:
    """Fetch one image under the limits above; returns (bytes, content type)."""
    url = httpx.URL(raw_url)
    for _hop in range(MAX_REDIRECTS + 1):
        check_url(url)
        host = url.host
        port = url.port or 443
        address = await resolve_public(host, port)
        host_header = host if url.port in (None, 443) else f"{host}:{url.port}"
        request = client.build_request(
            "GET", url.copy_with(host=address),
            headers={"Host": host_header, "Accept": "image/*", "User-Agent": _USER_AGENT},
            extensions={"sni_hostname": host},
        )
        response = await client.send(request, stream=True)
        try:
            if response.status_code in _REDIRECTS:
                location = response.headers.get("location")
                if not location:
                    raise RemoteImageError("a redirect without a location")
                url = url.join(location)
                continue
            if response.status_code != 200:
                raise RemoteImageError(f"the host answered {response.status_code}")
            ctype = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if ctype not in IMAGE_TYPES:
                raise RemoteImageError(f"not a raster image ({ctype or 'no type'})")
            declared = response.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > MAX_BYTES:
                raise RemoteImageError("the image is larger than 10 MB")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_BYTES:
                    raise RemoteImageError("the image is larger than 10 MB")
            return bytes(body), ctype
        finally:
            await response.aclose()
    raise RemoteImageError(f"more than {MAX_REDIRECTS} redirects")


def _client() -> httpx.AsyncClient:
    # trust_env=False: no proxy and no netrc from the environment; the
    # address check means nothing if a proxy makes the connection.
    return httpx.AsyncClient(follow_redirects=False, trust_env=False,
                             timeout=httpx.Timeout(TIMEOUT_S))


@router.get("/files/remote-image")
async def remote_image(url: str = "", key: str = ""):
    if not key or not hmac.compare_digest(key, REMOTE_IMAGE_KEY):
        return JSONResponse(status_code=403, content={"detail": "missing or wrong key"})
    try:
        async with _client() as client:
            data, ctype = await asyncio.wait_for(fetch_remote_image(url, client), TIMEOUT_S)
    except RemoteImageError as exc:
        return JSONResponse(status_code=403, content={"detail": str(exc)})
    except (asyncio.TimeoutError, httpx.HTTPError, ValueError) as exc:
        logger.debug("remote image fetch failed: %s", exc)
        return JSONResponse(status_code=502, content={"detail": "the image could not be fetched"})
    return Response(content=data, media_type=ctype, headers={
        "Cache-Control": "private, max-age=3600",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
    })
