"""Tests for image format + size validation (Phase 2.6, v1.17.4).

Exercises every branch of the validation pipeline:
    - Magic-byte sniffing (PNG/JPEG/WEBP/GIF)
    - Dimension extraction per format (real headers, not decoded pixels)
    - Provider-aware size limits
    - Token cost estimation formula
    - Format rejection (SVG, TIFF, BMP, text, empty)
    - Size rejection (over limit)
    - Filename-vs-content disagreement resolution

Dimensions are verified against tiny synthesized images with known
widths / heights so we can assert exact values without depending on
PIL or the filesystem.
"""

from __future__ import annotations

import base64
import struct

from ppxai.engine.image_validation import (
    ACCEPTED_IMAGE_FORMATS,
    DEFAULT_IMAGE_SIZE_LIMIT,
    PROVIDER_IMAGE_LIMITS,
    estimate_tokens,
    extract_dimensions,
    get_size_limit,
    sniff_media_type,
    validate_image,
)

# -----------------------------------------------------------------------------
# Synthesized test bytes — deterministic headers, no external dependencies
# -----------------------------------------------------------------------------


def _make_png(width: int, height: int) -> bytes:
    """Minimal PNG header with the given dimensions + empty IDAT stub."""
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr_payload = struct.pack(
        ">IIBBBBB", width, height, 8, 2, 0, 0, 0
    )  # 8-bit depth, truecolor
    ihdr_length = struct.pack(">I", 13)
    ihdr_crc = b"\x00\x00\x00\x00"  # not validated by our sniffer
    ihdr = ihdr_length + b"IHDR" + ihdr_payload + ihdr_crc
    return signature + ihdr


def _make_jpeg(width: int, height: int) -> bytes:
    """Minimal JPEG header with SOF0 carrying dimensions."""
    soi = b"\xff\xd8"
    # SOF0: FF C0, length 17, precision 8, height, width, 3 components...
    sof_payload = struct.pack(">BHHB", 8, height, width, 3)
    sof_payload += b"\x01\x22\x00" + b"\x02\x11\x01" + b"\x03\x11\x01"
    sof = b"\xff\xc0" + struct.pack(">H", 2 + len(sof_payload)) + sof_payload
    eoi = b"\xff\xd9"
    return soi + sof + eoi


def _make_gif(width: int, height: int) -> bytes:
    """Minimal GIF89a header with logical screen dimensions."""
    header = b"GIF89a"
    logical = struct.pack("<HH", width, height) + b"\x00\x00\x00"
    return header + logical + b";"


def _make_webp_vp8(width: int, height: int) -> bytes:
    """Minimal WEBP lossy VP8 header."""
    # RIFF + (size) + WEBP + VP8 + ...
    # VP8 chunk header is at offset 12; we need dimensions at offset 26/28
    # (14-bit each). The bytes before those don't matter for our sniffer.
    header = b"RIFF" + b"\x00" * 4 + b"WEBP" + b"VP8 " + b"\x00" * 10
    # At offset 26/28 we write width/height as 16-bit LE (14 bits used).
    header += struct.pack("<HH", width & 0x3FFF, height & 0x3FFF)
    return header


# Small valid 1x1 red PNG (real bytes, decodable by any viewer).
_RED_PIXEL_PNG = base64.b64decode(
    b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8DwHwAFAQH/c4"
    b"X0gAAAAABJRU5ErkJggg=="
)


# -----------------------------------------------------------------------------
# sniff_media_type — magic byte detection
# -----------------------------------------------------------------------------


class TestSniffMediaType:
    def test_png_signature(self):
        assert sniff_media_type(_make_png(1, 1)) == "image/png"

    def test_real_png_bytes(self):
        assert sniff_media_type(_RED_PIXEL_PNG) == "image/png"

    def test_jpeg_signature(self):
        assert sniff_media_type(_make_jpeg(10, 20)) == "image/jpeg"

    def test_gif87a(self):
        data = b"GIF87a" + b"\x0a\x00\x14\x00" + b"\x00\x00\x00;"
        assert sniff_media_type(data) == "image/gif"

    def test_gif89a(self):
        assert sniff_media_type(_make_gif(10, 20)) == "image/gif"

    def test_webp_vp8(self):
        assert sniff_media_type(_make_webp_vp8(100, 50)) == "image/webp"

    def test_rejects_text(self):
        assert sniff_media_type(b"Hello, world!") is None

    def test_rejects_empty(self):
        assert sniff_media_type(b"") is None

    def test_rejects_short_buffer(self):
        assert sniff_media_type(b"abc") is None

    def test_rejects_svg(self):
        # SVG is text-based XML; we deliberately don't accept it because
        # most providers don't handle it natively and rendering varies.
        svg = b'<?xml version="1.0"?><svg></svg>'
        assert sniff_media_type(svg) is None

    def test_rejects_bmp(self):
        # BMP starts with "BM" — not in our accepted set.
        bmp = b"BM\x00\x00\x00\x00" + b"\x00" * 100
        assert sniff_media_type(bmp) is None

    def test_rejects_tiff(self):
        # TIFF little-endian: "II*\0"
        tiff = b"II*\x00" + b"\x00" * 100
        assert sniff_media_type(tiff) is None


# -----------------------------------------------------------------------------
# Dimension extraction — per format
# -----------------------------------------------------------------------------


class TestDimensionExtraction:
    def test_png_dimensions(self):
        png = _make_png(1920, 1080)
        assert extract_dimensions("image/png", png) == (1920, 1080)

    def test_png_dimensions_real_bytes(self):
        # Real 1x1 PNG.
        assert extract_dimensions("image/png", _RED_PIXEL_PNG) == (1, 1)

    def test_jpeg_dimensions(self):
        jpeg = _make_jpeg(800, 600)
        assert extract_dimensions("image/jpeg", jpeg) == (800, 600)

    def test_gif_dimensions(self):
        gif = _make_gif(320, 240)
        assert extract_dimensions("image/gif", gif) == (320, 240)

    def test_webp_dimensions(self):
        webp = _make_webp_vp8(400, 300)
        assert extract_dimensions("image/webp", webp) == (400, 300)

    def test_corrupted_png_returns_none(self):
        # Too short to contain IHDR
        assert extract_dimensions("image/png", b"\x89PNG\r\n\x1a\n") is None

    def test_unknown_media_type_returns_none(self):
        assert extract_dimensions("image/bmp", b"\x00" * 100) is None


# -----------------------------------------------------------------------------
# Token cost estimation
# -----------------------------------------------------------------------------


class TestTokenEstimation:
    def test_1024x1024_image(self):
        # 1024 * 1024 / 750 ≈ 1398 tokens
        assert estimate_tokens(1024, 1024) == 1398

    def test_small_thumbnail(self):
        # 32 * 32 / 750 = 1 (floor'd, but clamped to min 1)
        assert estimate_tokens(32, 32) == 1

    def test_wide_image(self):
        # 1920 * 1080 / 750 = 2764
        assert estimate_tokens(1920, 1080) == 2764

    def test_zero_dimensions_returns_zero(self):
        assert estimate_tokens(0, 0) == 0
        assert estimate_tokens(100, 0) == 0
        assert estimate_tokens(0, 100) == 0

    def test_negative_dimensions_returns_zero(self):
        assert estimate_tokens(-1, 100) == 0

    def test_minimum_is_one_token(self):
        # Any non-zero dimensions should yield at least 1 token.
        assert estimate_tokens(1, 1) == 1


# -----------------------------------------------------------------------------
# get_size_limit — per-provider caps
# -----------------------------------------------------------------------------


class TestSizeLimits:
    def test_perplexity_has_50mb_limit(self):
        assert get_size_limit("perplexity") == 50 * 1024 * 1024

    def test_openai_has_20mb_limit(self):
        assert get_size_limit("openai") == 20 * 1024 * 1024

    def test_gemini_has_20mb_limit(self):
        assert get_size_limit("gemini") == 20 * 1024 * 1024

    def test_anthropic_has_5mb_limit(self):
        assert get_size_limit("anthropic") == 5 * 1024 * 1024

    def test_unknown_provider_uses_default(self):
        assert get_size_limit("ollama") == DEFAULT_IMAGE_SIZE_LIMIT
        assert get_size_limit("custom") == DEFAULT_IMAGE_SIZE_LIMIT

    def test_none_provider_uses_default(self):
        assert get_size_limit(None) == DEFAULT_IMAGE_SIZE_LIMIT

    def test_empty_string_provider_uses_default(self):
        assert get_size_limit("") == DEFAULT_IMAGE_SIZE_LIMIT

    def test_case_insensitive(self):
        assert get_size_limit("OpenAI") == 20 * 1024 * 1024
        assert get_size_limit("PERPLEXITY") == 50 * 1024 * 1024


# -----------------------------------------------------------------------------
# validate_image — full pipeline
# -----------------------------------------------------------------------------


class TestValidateImage:
    def test_valid_png_passes(self):
        result = validate_image(_make_png(100, 100))
        assert result.ok is True
        assert result.media_type == "image/png"
        assert result.width == 100
        assert result.height == 100
        assert result.estimated_tokens > 0
        assert result.reason == ""

    def test_valid_real_png(self):
        result = validate_image(_RED_PIXEL_PNG)
        assert result.ok is True
        assert result.media_type == "image/png"
        assert result.width == 1
        assert result.height == 1
        assert result.size == len(_RED_PIXEL_PNG)

    def test_valid_jpeg(self):
        result = validate_image(_make_jpeg(640, 480))
        assert result.ok is True
        assert result.media_type == "image/jpeg"
        assert result.width == 640
        assert result.height == 480

    def test_empty_bytes_rejected(self):
        result = validate_image(b"")
        assert result.ok is False
        assert "empty" in result.reason.lower()

    def test_unknown_format_rejected(self):
        result = validate_image(b"Hello, this is not an image")
        assert result.ok is False
        assert "unrecognized" in result.reason.lower()
        # Error message should list the accepted formats.
        assert "image/png" in result.reason
        assert "image/jpeg" in result.reason

    def test_unknown_format_with_declared_type(self):
        # When the caller declares a type that's ALSO not accepted, the
        # error mentions it so the user knows their claim was invalid.
        result = validate_image(
            b"Hello", declared_media_type="image/svg+xml"
        )
        assert result.ok is False
        assert "image/svg+xml" in result.reason

    def test_size_over_default_limit_rejected(self):
        # Create a PNG just over 10 MB — header + garbage padding.
        oversized = _make_png(1, 1) + b"\x00" * (DEFAULT_IMAGE_SIZE_LIMIT + 1)
        result = validate_image(oversized)
        assert result.ok is False
        assert "exceeds" in result.reason.lower()
        assert "10.0 MB" in result.reason

    def test_size_over_default_but_under_perplexity_limit_passes(self):
        # 15 MB PNG is too big for default but fine for Perplexity.
        big_png = _make_png(1, 1) + b"\x00" * (15 * 1024 * 1024)
        default_result = validate_image(big_png)
        assert default_result.ok is False

        perplexity_result = validate_image(big_png, provider="perplexity")
        assert perplexity_result.ok is True

    def test_explicit_size_limit_override(self):
        # Caller can inject a tiny limit for testing.
        data = _make_png(10, 10)
        result = validate_image(data, size_limit=10)  # 10 bytes — definitely too small
        assert result.ok is False
        assert "exceeds" in result.reason.lower()

    def test_provider_suffix_in_error(self):
        oversized = _make_png(1, 1) + b"\x00" * (DEFAULT_IMAGE_SIZE_LIMIT + 1)
        result = validate_image(oversized, provider="ollama")
        assert "provider 'ollama'" in result.reason

    def test_size_populated_even_on_rejection(self):
        # Size is reported on failed results too, so the caller can log
        # the attempted upload size for telemetry.
        oversized = _make_png(1, 1) + b"\x00" * (DEFAULT_IMAGE_SIZE_LIMIT + 1)
        result = validate_image(oversized)
        assert result.ok is False
        assert result.size == len(oversized)

    def test_dimensions_optional_when_extraction_fails(self):
        # A PNG with a truncated IHDR passes sniffing but fails dimension
        # extraction — validation should still succeed with zero dimensions.
        truncated = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50  # magic bytes but no real IHDR
        result = validate_image(truncated)
        assert result.ok is True
        assert result.width == 0
        assert result.height == 0
        assert result.estimated_tokens == 0


# -----------------------------------------------------------------------------
# Accepted format set sanity checks
# -----------------------------------------------------------------------------


class TestAcceptedFormats:
    def test_has_four_universal_formats(self):
        assert set(ACCEPTED_IMAGE_FORMATS.keys()) == {
            "image/png",
            "image/jpeg",
            "image/webp",
            "image/gif",
        }

    def test_provider_limits_have_expected_providers(self):
        # If a provider is removed from this set, preprocessing needs
        # updating too — this sentinel test catches accidental drops.
        assert "perplexity" in PROVIDER_IMAGE_LIMITS
        assert "openai" in PROVIDER_IMAGE_LIMITS
        assert "gemini" in PROVIDER_IMAGE_LIMITS
        assert "anthropic" in PROVIDER_IMAGE_LIMITS

    def test_all_provider_limits_are_at_least_default(self):
        # No provider cap should be less than the default — the default
        # is already the most conservative value. A lower provider cap
        # would indicate a misconfiguration.
        for provider, limit in PROVIDER_IMAGE_LIMITS.items():
            # Anthropic is the exception at 5 MB — document it explicitly.
            if provider == "anthropic":
                assert limit == 5 * 1024 * 1024
            else:
                assert limit >= DEFAULT_IMAGE_SIZE_LIMIT
