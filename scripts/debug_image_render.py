#!/usr/bin/env python3
"""Debug script to test terminal image rendering protocols.

Usage:
    python scripts/debug_image_render.py <image_path> [--protocol <protocol>]

Protocols:
    iterm2  - iTerm2 inline image protocol (WezTerm, iTerm2, mintty)
    sixel   - Sixel graphics (Windows Terminal, xterm, mlterm)
    kitty   - Kitty graphics protocol
    auto    - Auto-detect based on terminal

Examples:
    python scripts/debug_image_render.py docs/future-agentic-flow.png
    python scripts/debug_image_render.py docs/future-agentic-flow.png --protocol iterm2
    python scripts/debug_image_render.py docs/future-agentic-flow.png --protocol sixel
"""

import argparse
import base64
import os
import sys
from pathlib import Path


def detect_terminal():
    """Detect the current terminal."""
    term_program = os.environ.get("TERM_PROGRAM", "")
    if term_program:
        return term_program

    if os.environ.get("WT_SESSION"):
        return "Windows Terminal"

    if os.environ.get("KITTY_WINDOW_ID"):
        return "Kitty"

    return os.environ.get("TERM", "unknown")


def render_iterm2(image_path: Path, width: str = "auto", height: str = "auto"):
    """Render image using iTerm2 inline image protocol.

    Works with: iTerm2, WezTerm, mintty
    """
    ESC = '\x1b'
    BEL = '\x07'

    # Read image data
    image_data = image_path.read_bytes()
    b64_data = base64.b64encode(image_data).decode('ascii')
    b64_name = base64.b64encode(image_path.name.encode()).decode('ascii')

    # Build escape sequence
    args = [
        f"name={b64_name}",
        f"size={len(image_data)}",
        f"width={width}",
        f"height={height}",
        "preserveAspectRatio=1",
        "inline=1",
    ]

    escape_seq = f"{ESC}]1337;File={';'.join(args)}:{b64_data}{BEL}"

    # Output directly to terminal
    sys.stdout.write(escape_seq)
    sys.stdout.write("\n")
    sys.stdout.flush()


def render_sixel(image_path: Path, width: int = 800, height: int = 600):
    """Render image using Sixel graphics protocol.

    Works with: Windows Terminal (experimental), xterm, mlterm
    """
    try:
        from PIL import Image
    except ImportError:
        print("ERROR: PIL/Pillow required for Sixel rendering")
        print("Install with: pip install Pillow")
        return

    # Load and resize image
    img = Image.open(image_path)
    img.thumbnail((width, height), Image.Resampling.LANCZOS)

    # Convert to palette mode (Sixel requires indexed colors)
    if img.mode != 'P':
        img = img.convert('P', palette=Image.Palette.ADAPTIVE, colors=256)

    width, height = img.size
    palette = img.getpalette()
    pixels = list(img.getdata())

    # Build Sixel sequence
    ESC = '\x1b'
    sixel_start = f"{ESC}Pq"
    sixel_end = f"{ESC}\\"

    output = [sixel_start]

    # Define color palette
    for i in range(256):
        if palette:
            r = palette[i * 3] * 100 // 255
            g = palette[i * 3 + 1] * 100 // 255
            b = palette[i * 3 + 2] * 100 // 255
            output.append(f"#{i};2;{r};{g};{b}")

    # Generate sixel data (simplified - 6 rows at a time)
    for band_start in range(0, height, 6):
        for color in range(256):
            color_data = []
            has_pixels = False

            for x in range(width):
                sixel_value = 0
                for bit in range(6):
                    y = band_start + bit
                    if y < height:
                        pixel_idx = y * width + x
                        if pixel_idx < len(pixels) and pixels[pixel_idx] == color:
                            sixel_value |= (1 << bit)
                            has_pixels = True

                color_data.append(chr(63 + sixel_value))

            if has_pixels:
                output.append(f"#{color}")
                output.append(''.join(color_data))
                output.append('$')  # Carriage return

        output.append('-')  # New line

    output.append(sixel_end)

    sys.stdout.write(''.join(output))
    sys.stdout.write("\n")
    sys.stdout.flush()


def render_kitty(image_path: Path):
    """Render image using Kitty graphics protocol.

    Works with: Kitty
    """
    ESC = '\x1b'

    image_data = image_path.read_bytes()
    b64_data = base64.b64encode(image_data).decode('ascii')

    # Kitty protocol: split into chunks
    chunk_size = 4096
    chunks = [b64_data[i:i+chunk_size] for i in range(0, len(b64_data), chunk_size)]

    for i, chunk in enumerate(chunks):
        # m=0 for intermediate chunks, m=1 for last chunk
        m = 1 if i == len(chunks) - 1 else 0

        if i == 0:
            # First chunk: include format and action
            sys.stdout.write(f"{ESC}_Ga=T,f=100,m={m};{chunk}{ESC}\\")
        else:
            # Continuation chunks
            sys.stdout.write(f"{ESC}_Gm={m};{chunk}{ESC}\\")

    sys.stdout.write("\n")
    sys.stdout.flush()


def render_halfblock(image_path: Path, width: int = 80):
    """Render image using Unicode half-block characters.

    Works with: Any terminal with Unicode support (fallback)
    """
    try:
        from PIL import Image
    except ImportError:
        print("ERROR: PIL/Pillow required for half-block rendering")
        print("Install with: pip install Pillow")
        return

    img = Image.open(image_path)

    # Calculate height to maintain aspect ratio (2 pixels per character vertically)
    aspect = img.height / img.width
    height = int(width * aspect / 2)

    img = img.resize((width, height * 2), Image.Resampling.LANCZOS)
    img = img.convert('RGB')

    pixels = list(img.getdata())

    for y in range(0, height * 2, 2):
        line = []
        for x in range(width):
            top_idx = y * width + x
            bot_idx = (y + 1) * width + x

            top = pixels[top_idx] if top_idx < len(pixels) else (0, 0, 0)
            bot = pixels[bot_idx] if bot_idx < len(pixels) else (0, 0, 0)

            # Use upper half block with foreground=top, background=bottom
            fg = f"\x1b[38;2;{top[0]};{top[1]};{top[2]}m"
            bg = f"\x1b[48;2;{bot[0]};{bot[1]};{bot[2]}m"
            line.append(f"{fg}{bg}▀")

        print(''.join(line) + "\x1b[0m")


def render_textual_image(image_path: Path):
    """Render using textual-image library (for comparison)."""
    try:
        from rich.console import Console
        from textual_image.renderable import Image

        console = Console()
        console.print(f"textual-image auto-selected: {Image.__module__}")
        console.print(Image(str(image_path)))
    except ImportError:
        print("ERROR: textual-image not installed")
        print("Install with: pip install textual-image")


def main():
    parser = argparse.ArgumentParser(
        description="Test terminal image rendering protocols",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("image_path", type=Path, help="Path to image file")
    parser.add_argument(
        "--protocol", "-p",
        choices=["iterm2", "sixel", "kitty", "halfblock", "textual", "auto", "all"],
        default="auto",
        help="Rendering protocol to use (default: auto)"
    )
    parser.add_argument(
        "--width", "-w",
        type=str,
        default="auto",
        help="Width (auto, N cells, Npx, N%%)"
    )

    args = parser.parse_args()

    if not args.image_path.exists():
        print(f"ERROR: Image not found: {args.image_path}")
        sys.exit(1)

    terminal = detect_terminal()
    print(f"Terminal: {terminal}")
    print(f"Image: {args.image_path} ({args.image_path.stat().st_size:,} bytes)")
    print(f"Protocol: {args.protocol}")
    print("-" * 50)

    if args.protocol == "auto":
        # Auto-detect best protocol
        term_lower = terminal.lower()
        if term_lower in ("wezterm", "iterm.app", "iterm2"):
            args.protocol = "iterm2"
        elif "kitty" in term_lower:
            args.protocol = "kitty"
        elif term_lower == "windows terminal" or os.environ.get("WT_SESSION"):
            args.protocol = "sixel"
        else:
            args.protocol = "halfblock"
        print(f"Auto-selected protocol: {args.protocol}")
        print("-" * 50)

    if args.protocol == "all":
        print("\n=== iTerm2 Protocol ===")
        render_iterm2(args.image_path, args.width)

        print("\n=== Sixel Protocol ===")
        render_sixel(args.image_path)

        print("\n=== Half-block (fallback) ===")
        render_halfblock(args.image_path, width=60)

        print("\n=== textual-image library ===")
        render_textual_image(args.image_path)

    elif args.protocol == "iterm2":
        render_iterm2(args.image_path, args.width)

    elif args.protocol == "sixel":
        render_sixel(args.image_path)

    elif args.protocol == "kitty":
        render_kitty(args.image_path)

    elif args.protocol == "halfblock":
        render_halfblock(args.image_path)

    elif args.protocol == "textual":
        render_textual_image(args.image_path)

    print("-" * 50)
    print("Done.")


if __name__ == "__main__":
    main()
