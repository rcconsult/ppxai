"""
Image format and size validation for multimodal attachments.

Phase 2.6 (v1.17.4). Centralizes the accept/reject decision for image
bytes before they reach `file_preprocessing` or a provider API. Keeps
every client (`/attach`, server chat route, preprocessing pipeline,
future PDF/Excel rendering tools) consistent about which formats are
acceptable and what the per-provider size limits are.

Design goals:

1. **Single source of truth for accepted formats.** PNG, JPEG, WEBP, and
   GIF are the universal set — every major provider accepts them. Other
   formats (SVG, TIFF, BMP, HEIC, etc.) are rejected with a clear error
   rather than sent to a provider that will reject them silently or
   return an obscure API error.

2. **Provider-aware size limits.** Most providers cap image input at
   10 MB, Perplexity explicitly documents 50 MB for Sonar. The default
   is 10 MB (conservative); providers with higher limits are listed in
   `PROVIDER_IMAGE_LIMITS`. Preprocessing passes the provider name in
   and gets the right cap.

3. **MIME sniffing from magic bytes.** A file named `chart.png` that's
   actually a GIF must be classified correctly — the content hash is
   what ends up in `file_id`, not the filename. Lightweight magic-byte
   detection handles the common cases without a PIL dependency.

4. **Token cost estimation.** Matches Perplexity's documented formula
   `(width × height) / 750` so callers can show a "this attachment will
   cost ~N tokens" hint before sending. Uses `struct` to pull dimensions
   from PNG/JPEG/WEBP/GIF headers directly — no PIL round trip.

5. **Zero-deps module.** `ppxai/engine/image_validation.py` imports only
   stdlib so it can be used from `SessionFileStore`, `file_preprocessing`,
   `/attach`, and the server chat route without adding to the dependency
   graph. Tests exercise it in isolation.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

# Universal image formats every major provider accepts. Keys are MIME
# types, values are the magic-byte prefixes used by `sniff_media_type`.
ACCEPTED_IMAGE_FORMATS: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpeg",
    "image/webp": "webp",
    "image/gif": "gif",
}

# Default per-file size cap across all providers. 10 MB matches
# `ppxai/commands/attach.py::MAX_FILE_BYTES` so `/attach` and
# preprocessing agree on the same ceiling.
DEFAULT_IMAGE_SIZE_LIMIT = 10 * 1024 * 1024

# Per-provider size caps. Providers not in this map fall back to the
# conservative default. Sources: each provider's official docs as of
# April 2026.
PROVIDER_IMAGE_LIMITS: dict[str, int] = {
    "perplexity": 50 * 1024 * 1024,   # Sonar accepts up to 50 MB
    "openai": 20 * 1024 * 1024,       # GPT-4o/GPT-5 accept up to 20 MB
    "gemini": 20 * 1024 * 1024,       # Gemini 2.5/3 accept up to 20 MB
    "anthropic": 5 * 1024 * 1024,     # Claude caps at 5 MB
    # Default (10 MB) applies to "ollama", "local", custom providers.
}

# Token estimation constant from Perplexity documentation:
# https://docs.perplexity.ai/guides/image-guide — used as a rough
# universal estimate across providers since they all charge per-pixel.
_PIXELS_PER_TOKEN = 750


@dataclass
class ImageValidationResult:
    """Outcome of validating a candidate image attachment.

    A successful result carries the canonical `media_type` (which may
    differ from what the filename suggested), the image dimensions if
    they could be sniffed, and an estimated token cost for cost-aware
    UIs. A failed result carries only the reason — callers surface the
    reason to the user and refuse the attachment.
    """
    ok: bool
    media_type: str = ""
    width: int = 0
    height: int = 0
    size: int = 0
    estimated_tokens: int = 0
    reason: str = ""


def sniff_media_type(data: bytes) -> str | None:
    """Detect image MIME type from magic bytes.

    Returns the canonical MIME type string for the first 4 supported
    formats, or None if the bytes don't match any known format. Does
    NOT attempt to decode the full image — just checks the header.

    Args:
        data: Raw file bytes (at least the first 16 bytes must be
              present; shorter inputs return None).

    Returns:
        "image/png", "image/jpeg", "image/webp", "image/gif", or None.
    """
    if len(data) < 12:
        return None

    # PNG: 89 50 4E 47 0D 0A 1A 0A
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"

    # JPEG: FF D8 FF (followed by E0/E1/E2/... marker)
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"

    # WEBP: "RIFF" ???? "WEBP"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"

    # GIF: "GIF87a" or "GIF89a"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"

    return None


def _extract_png_dimensions(data: bytes) -> tuple[int, int] | None:
    """Extract (width, height) from a PNG header.

    PNG stores IHDR immediately after the 8-byte signature. IHDR layout:
    4-byte length, 4-byte "IHDR" tag, 4-byte width, 4-byte height, ...
    Width and height are big-endian 32-bit ints.
    """
    if len(data) < 24 or data[12:16] != b"IHDR":
        return None
    try:
        width, height = struct.unpack(">II", data[16:24])
    except struct.error:
        return None
    return width, height


def _extract_jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    """Extract (width, height) from a JPEG Start-Of-Frame marker.

    JPEGs have a sequence of markers after the SOI (FF D8). We walk
    marker segments looking for SOF0 (FF C0) or SOF2 (FF C2, progressive).
    The SOF payload is: 1-byte precision, 2-byte height, 2-byte width,
    ...  Using only stdlib struct rather than pulling PIL just for
    dimension sniffing.
    """
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    pos = 2
    while pos < len(data) - 9:
        if data[pos] != 0xFF:
            return None
        marker = data[pos + 1]
        # Skip marker padding (0xFF 0xFF ...)
        if marker == 0xFF:
            pos += 1
            continue
        # Standalone markers with no length field
        if marker in (0xD8, 0xD9):
            pos += 2
            continue
        # Read segment length
        if pos + 4 > len(data):
            return None
        length = struct.unpack(">H", data[pos + 2 : pos + 4])[0]
        # SOF0..SOF3, SOF5..SOF7, SOF9..SOF11, SOF13..SOF15 carry dimensions
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if pos + 9 > len(data):
                return None
            try:
                height = struct.unpack(">H", data[pos + 5 : pos + 7])[0]
                width = struct.unpack(">H", data[pos + 7 : pos + 9])[0]
            except struct.error:
                return None
            return width, height
        pos += 2 + length
    return None


def _extract_gif_dimensions(data: bytes) -> tuple[int, int] | None:
    """Extract (width, height) from a GIF header.

    GIFs store logical screen width/height at bytes 6-10 as
    little-endian 16-bit ints, right after the GIF87a/GIF89a signature.
    """
    if len(data) < 10:
        return None
    try:
        width, height = struct.unpack("<HH", data[6:10])
    except struct.error:
        return None
    return width, height


def _extract_webp_dimensions(data: bytes) -> tuple[int, int] | None:
    """Extract (width, height) from a WEBP header.

    WEBP comes in three chunk variants (VP8/VP8L/VP8X) with different
    dimension layouts. Handles all three to cover the common formats
    without pulling PIL. Spec: https://developers.google.com/speed/webp/docs/riff_container
    """
    if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    chunk = data[12:16]
    if chunk == b"VP8 ":
        # Lossy VP8: width/height at offset 26, 14-bit LE
        if len(data) < 30:
            return None
        w = struct.unpack("<H", data[26:28])[0] & 0x3FFF
        h = struct.unpack("<H", data[28:30])[0] & 0x3FFF
        return w, h
    if chunk == b"VP8L":
        # Lossless VP8L: 14-bit width/height packed after signature byte
        if len(data) < 25:
            return None
        b0, b1, b2, b3 = data[21], data[22], data[23], data[24]
        w = 1 + (((b1 & 0x3F) << 8) | b0)
        h = 1 + (((b3 & 0xF) << 10) | (b2 << 2) | ((b1 & 0xC0) >> 6))
        return w, h
    if chunk == b"VP8X":
        # Extended VP8X: 24-bit width/height minus 1
        if len(data) < 30:
            return None
        w = 1 + (data[24] | (data[25] << 8) | (data[26] << 16))
        h = 1 + (data[27] | (data[28] << 8) | (data[29] << 16))
        return w, h
    return None


def extract_dimensions(media_type: str, data: bytes) -> tuple[int, int] | None:
    """Dispatch dimension extraction based on detected media type.

    Returns None when dimensions cannot be recovered — callers should
    treat this as "unknown size" and skip token estimation rather than
    failing validation.
    """
    if media_type == "image/png":
        return _extract_png_dimensions(data)
    if media_type == "image/jpeg":
        return _extract_jpeg_dimensions(data)
    if media_type == "image/gif":
        return _extract_gif_dimensions(data)
    if media_type == "image/webp":
        return _extract_webp_dimensions(data)
    return None


def estimate_tokens(width: int, height: int) -> int:
    """Estimate the token cost of sending an image of given dimensions.

    Uses Perplexity's published formula as a reasonable cross-provider
    approximation — OpenAI and Gemini use different internal formulas
    but in the same order of magnitude. Returns 0 for invalid inputs
    rather than raising, so the caller can degrade gracefully.
    """
    if width <= 0 or height <= 0:
        return 0
    return max(1, (width * height) // _PIXELS_PER_TOKEN)


def get_size_limit(provider: str | None) -> int:
    """Return the per-file image size limit for a provider in bytes.

    Unknown providers fall back to the conservative default. Case
    insensitive. `None` returns the default, so callers that don't
    know the provider at validation time still get a sane limit.
    """
    if not provider:
        return DEFAULT_IMAGE_SIZE_LIMIT
    return PROVIDER_IMAGE_LIMITS.get(provider.lower(), DEFAULT_IMAGE_SIZE_LIMIT)


def validate_image(
    data: bytes,
    *,
    declared_media_type: str | None = None,
    provider: str | None = None,
    size_limit: int | None = None,
) -> ImageValidationResult:
    """Full validation pipeline for a candidate image attachment.

    Checks in order:
    1. Non-empty bytes.
    2. Magic-byte detection → canonical MIME type. If `declared_media_type`
       disagrees, the sniffed type wins (a PNG misnamed `photo.jpg` is
       still a PNG; providers care about content, not filename).
    3. Format is in `ACCEPTED_IMAGE_FORMATS`.
    4. Size under `size_limit` (or provider default if not specified).
    5. Optional dimension extraction for token cost estimation.

    Any failure returns `ok=False` with a human-readable `reason` the
    caller can surface directly. Successful returns carry the canonical
    media_type, dimensions when available, and the estimated token cost.

    Args:
        data: Raw image bytes.
        declared_media_type: What the caller thinks the file is (e.g.
                             from the HTTP Content-Type header or
                             filename extension). Used only as a hint;
                             the sniffed type is authoritative.
        provider: Provider name for per-provider size limit lookup
                  ("openai", "gemini", "perplexity", ...). Optional.
        size_limit: Explicit override for the size cap in bytes. Takes
                    precedence over provider-based lookup when both
                    are supplied (useful for testing).

    Returns:
        ImageValidationResult with `ok=True` on success.
    """
    if not data:
        return ImageValidationResult(
            ok=False,
            reason="Image data is empty.",
        )

    # 1. Format detection (magic bytes trump declared type).
    sniffed = sniff_media_type(data)
    if sniffed is None:
        return ImageValidationResult(
            ok=False,
            size=len(data),
            reason=(
                "Unrecognized image format. Accepted: "
                f"{', '.join(sorted(ACCEPTED_IMAGE_FORMATS.keys()))}."
                + (
                    f" (File declared as {declared_media_type})"
                    if declared_media_type
                    and declared_media_type not in ACCEPTED_IMAGE_FORMATS
                    else ""
                )
            ),
        )

    if sniffed not in ACCEPTED_IMAGE_FORMATS:
        # Defensive: sniff_media_type only returns accepted formats
        # today, but the guard future-proofs us in case the accepted
        # set ever diverges from the sniffer's capabilities.
        return ImageValidationResult(
            ok=False,
            media_type=sniffed,
            size=len(data),
            reason=(
                f"{sniffed} is not accepted by all providers. "
                f"Accepted: {', '.join(sorted(ACCEPTED_IMAGE_FORMATS.keys()))}."
            ),
        )

    # 2. Size cap.
    limit = size_limit if size_limit is not None else get_size_limit(provider)
    if len(data) > limit:
        mb = len(data) / (1024 * 1024)
        limit_mb = limit / (1024 * 1024)
        provider_suffix = f" for provider '{provider}'" if provider else ""
        return ImageValidationResult(
            ok=False,
            media_type=sniffed,
            size=len(data),
            reason=(
                f"Image is {mb:.1f} MB — exceeds the {limit_mb:.1f} MB limit"
                f"{provider_suffix}."
            ),
        )

    # 3. Dimensions + token estimate (best effort).
    dims = extract_dimensions(sniffed, data)
    width, height = dims if dims else (0, 0)
    tokens = estimate_tokens(width, height) if dims else 0

    return ImageValidationResult(
        ok=True,
        media_type=sniffed,
        width=width,
        height=height,
        size=len(data),
        estimated_tokens=tokens,
    )


__all__ = [
    "ACCEPTED_IMAGE_FORMATS",
    "DEFAULT_IMAGE_SIZE_LIMIT",
    "PROVIDER_IMAGE_LIMITS",
    "ImageValidationResult",
    "extract_dimensions",
    "estimate_tokens",
    "get_size_limit",
    "sniff_media_type",
    "validate_image",
]
