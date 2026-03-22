"""
Image display support for terminals.

Supports multiple protocols:
- iTerm2 inline images (OSC 1337)
- Kitty graphics protocol
- Sixel graphics

Uses terminal capability detection to choose the best protocol.
"""

import base64
import io
import os
import sys
from pathlib import Path

# Optional image library (not in any extras group)
try:
    from PIL import Image as PILImage
    HAS_PIL = True
except ImportError:
    PILImage = None  # type: ignore[assignment,misc]
    HAS_PIL = False

# Optional sixel library
try:
    import libsixel
    from libsixel import encoder as sixel_encoder
    HAS_SIXEL = True
except ImportError:
    libsixel = None  # type: ignore[assignment]
    sixel_encoder = None  # type: ignore[assignment]
    HAS_SIXEL = False
from typing import Optional, Tuple

from .terminal import ImageProtocol, detect_image_protocol, can_display_images


# Image file extensions
IMAGE_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp',
    '.ico', '.tiff', '.tif', '.svg'
}


def is_image_file(path: Path) -> bool:
    """Check if a file is an image based on extension.

    Args:
        path: Path to check

    Returns:
        True if file has an image extension
    """
    return path.suffix.lower() in IMAGE_EXTENSIONS


def get_image_size(data: bytes) -> Optional[Tuple[int, int]]:
    """Get image dimensions from raw bytes.

    Args:
        data: Raw image data

    Returns:
        Tuple of (width, height) or None if unable to determine
    """
    if HAS_PIL:
        try:
            img = PILImage.open(io.BytesIO(data))
            return img.size
        except Exception:
            pass

    # Fallback: Try to parse PNG header
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        try:
            width = int.from_bytes(data[16:20], 'big')
            height = int.from_bytes(data[20:24], 'big')
            return (width, height)
        except Exception:
            pass

    return None


def display_image_iterm2(
    data: bytes,
    width: Optional[str] = None,
    height: Optional[str] = None,
    preserve_aspect: bool = True,
    inline: bool = True,
) -> str:
    """Generate iTerm2 inline image escape sequence.

    Args:
        data: Raw image data
        width: Width (e.g., "80", "50%", "auto")
        height: Height (e.g., "24", "50%", "auto")
        preserve_aspect: Preserve aspect ratio
        inline: Display inline (vs download)

    Returns:
        Escape sequence string to display image
    """
    b64_data = base64.b64encode(data).decode('ascii')

    # Build arguments
    args = [f"inline={1 if inline else 0}"]

    if width:
        args.append(f"width={width}")
    if height:
        args.append(f"height={height}")
    if preserve_aspect:
        args.append("preserveAspectRatio=1")

    args_str = ";".join(args)

    # OSC 1337 ; File=<args> : <base64 data> ST
    return f"\033]1337;File={args_str}:{b64_data}\a"


def display_image_kitty(
    data: bytes,
    width: Optional[int] = None,
    height: Optional[int] = None,
) -> str:
    """Generate Kitty graphics protocol escape sequence.

    Args:
        data: Raw image data
        width: Width in pixels
        height: Height in pixels

    Returns:
        Escape sequence string to display image
    """
    b64_data = base64.b64encode(data).decode('ascii')

    # Kitty uses chunked transmission for large images
    # For simplicity, we'll use direct transmission (a=T)
    # Format: ESC_G<control data>;<payload>ESC\

    # Control data: a=action, f=format, t=transmission
    # a=T: transmit and display
    # f=100: PNG format (auto-detect)
    # t=d: direct transmission

    chunks = []
    chunk_size = 4096  # Kitty recommends 4KB chunks

    for i in range(0, len(b64_data), chunk_size):
        chunk = b64_data[i:i + chunk_size]
        is_last = i + chunk_size >= len(b64_data)

        if i == 0:
            # First chunk includes format info
            ctrl = f"a=T,f=100,m={'0' if is_last else '1'}"
        else:
            # Continuation chunk
            ctrl = f"m={'0' if is_last else '1'}"

        chunks.append(f"\033_G{ctrl};{chunk}\033\\")

    return "".join(chunks)


def display_image_sixel(
    data: bytes,
    width: Optional[int] = None,
    height: Optional[int] = None,
) -> Optional[str]:
    """Generate Sixel graphics data.

    Args:
        data: Raw image data
        width: Target width in pixels
        height: Target height in pixels

    Returns:
        Sixel data string or None if conversion fails
    """
    if not HAS_PIL:
        return None

    try:
        img = PILImage.open(io.BytesIO(data))

        # Resize if dimensions specified
        if width or height:
            orig_w, orig_h = img.size
            if width and height:
                new_size = (width, height)
            elif width:
                ratio = width / orig_w
                new_size = (width, int(orig_h * ratio))
            else:
                ratio = height / orig_h
                new_size = (int(orig_w * ratio), height)
            img = img.resize(new_size, PILImage.Resampling.LANCZOS)

        # Convert to palette mode (Sixel uses indexed colors)
        if img.mode != 'P':
            img = img.convert('P', palette=PILImage.Palette.ADAPTIVE, colors=256)

        # Try to use libsixel if available
        if HAS_SIXEL:
            try:
                output = io.BytesIO()
                enc = sixel_encoder.Encoder()
                enc.setopt(libsixel.SIXEL_OPTFLAG_OUTPUT, output)

                # Convert to RGB for libsixel
                rgb_img = img.convert('RGB')
                rgb_data = rgb_img.tobytes()
                enc.encode_bytes(rgb_data, rgb_img.width, rgb_img.height)

                return output.getvalue().decode('ascii')
            except Exception:
                pass

        # Fallback: basic sixel generation (limited quality)
        return _generate_basic_sixel(img)

    except Exception:
        return None


def _generate_basic_sixel(img) -> str:
    """Generate basic sixel data without libsixel.

    This is a simplified implementation with limited quality.

    Args:
        img: PIL Image in palette mode

    Returns:
        Sixel data string
    """
    width, height = img.size
    palette = img.getpalette()

    # Start sixel data
    output = ["\033Pq"]  # DCS q (sixel)

    # Define palette
    if palette:
        for i in range(min(256, len(palette) // 3)):
            r = palette[i * 3] * 100 // 255
            g = palette[i * 3 + 1] * 100 // 255
            b = palette[i * 3 + 2] * 100 // 255
            output.append(f"#{i};2;{r};{g};{b}")

    # Convert pixels to sixel rows (6 pixels per row)
    pixels = list(img.getdata())

    for row_start in range(0, height, 6):
        row_end = min(row_start + 6, height)

        # Group pixels by color for this band
        color_runs = {}

        for x in range(width):
            # Build sixel value for this column (6 pixels stacked)
            sixel_val = 0
            for dy in range(row_end - row_start):
                y = row_start + dy
                pixel = pixels[y * width + x]
                if pixel > 0:  # Non-background
                    sixel_val |= (1 << dy)

            # Get color (use first non-zero pixel's color)
            color = 0
            for dy in range(row_end - row_start):
                y = row_start + dy
                pixel = pixels[y * width + x]
                if pixel > 0:
                    color = pixel
                    break

            if color not in color_runs:
                color_runs[color] = []
            color_runs[color].append((x, sixel_val))

        # Output each color's data
        for color, positions in sorted(color_runs.items()):
            if color == 0:
                continue  # Skip background

            output.append(f"#{color}")

            prev_x = -1
            for x, val in positions:
                if prev_x >= 0 and x > prev_x + 1:
                    # Gap - move cursor
                    gap = x - prev_x - 1
                    output.append("!" + str(gap) + "?")  # Repeat background
                output.append(chr(63 + val))
                prev_x = x

        output.append("-")  # Graphics new line

    output.append("\033\\")  # ST (string terminator)

    return "".join(output)


def display_image(
    path: Path,
    max_width: Optional[int] = None,
    max_height: Optional[int] = None,
) -> Optional[str]:
    """Display an image using the best available protocol.

    Args:
        path: Path to image file
        max_width: Maximum width (interpretation varies by protocol)
        max_height: Maximum height

    Returns:
        Escape sequence to display image, or None if not supported
    """
    if not can_display_images():
        return None

    if not path.exists() or not path.is_file():
        return None

    try:
        data = path.read_bytes()
    except Exception:
        return None

    protocol = detect_image_protocol()

    if protocol == ImageProtocol.ITERM2:
        # iTerm2 uses character cells or percentages
        width = f"{max_width}" if max_width else "auto"
        height = f"{max_height}" if max_height else "auto"
        return display_image_iterm2(data, width=width, height=height)

    elif protocol == ImageProtocol.KITTY:
        return display_image_kitty(data, width=max_width, height=max_height)

    elif protocol == ImageProtocol.SIXEL:
        return display_image_sixel(data, width=max_width, height=max_height)

    return None


def print_image(
    path: Path,
    max_width: Optional[int] = None,
    max_height: Optional[int] = None,
) -> bool:
    """Print an image to the terminal.

    Args:
        path: Path to image file
        max_width: Maximum width
        max_height: Maximum height

    Returns:
        True if image was displayed, False otherwise
    """
    escape_seq = display_image(path, max_width, max_height)
    if escape_seq:
        sys.stdout.write(escape_seq)
        sys.stdout.flush()
        return True
    return False
