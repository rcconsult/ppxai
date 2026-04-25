"""Shared helper for resolving relative paths in markdown content.

Both the Rich TUI (`rendering/rich_renderer.py`) and the Textual TUI
(`rendering/textual_renderer.py`) need the same path-rewriting logic
for `![alt](path)` and `[text](path)` so terminal-level OSC 8
hyperlinks resolve to actual files instead of "this link is invalid"
pop-ups.

Living in `ppxai/common/` (a leaf module with no upstream deps) keeps
the helper out of the rendering import cycle — `rich_renderer` is
imported by `commands/handler.py` which is imported by ppxai's startup
chain, so any helper that lived inside rich_renderer couldn't be
imported by tests at module load without triggering a partial-init
ImportError.
"""

from __future__ import annotations

import re
from pathlib import Path

# Match markdown link/image syntax: `[text](url)` or `![alt](url)`,
# with an optional `"title"` after the URL. The URL is everything up
# to the first whitespace or `)`.
_MARKDOWN_LINK_RE = re.compile(r'(!?\[[^\]]*\])\(([^)\s]+)(\s+"[^"]*")?\)')


def rewrite_relative_links(content: str, source_path: str) -> str:
    """Rewrite relative `![alt](path)` and `[text](path)` to absolute
    `file://` URIs using `source_path`'s directory as the base.

    Without this, terminals that auto-link markdown URLs (WezTerm,
    iTerm2 OSC 8) hand the raw relative path to the OS, which can't
    resolve `docs/foo.png` because it has no notion of "the markdown
    file's directory" — the user sees a "this link is invalid" popup.
    Rewriting to `file:///abs/path/docs/foo.png` lets the terminal
    open the file correctly.

    Skips:
      - absolute paths (already useful)
      - http(s) / mailto / data / fragment URLs
      - Windows drive-letter paths (C:\\foo)

    Caveat: the regex doesn't excise code blocks first, so a literal
    `![alt](rel)` inside a fenced code example will also be rewritten
    in the output. Trade-off accepted: Rich's Markdown widget renders
    code blocks via Syntax which doesn't parse `![alt]()` syntax
    anyway, so the user-visible impact is nil for the common case.
    """
    if not source_path:
        return content
    try:
        base = Path(source_path).resolve().parent
    except Exception:
        return content

    def _rewrite(match: re.Match) -> str:
        prefix = match.group(1)
        path = match.group(2)
        title = match.group(3) or ''
        skip = (
            path.startswith(('http://', 'https://', 'mailto:', '#',
                             '/', 'data:', 'file://', 'tel:'))
            or (len(path) >= 2 and path[1] == ':')  # Windows drive letter
        )
        if skip:
            return match.group(0)
        try:
            absolute = (base / path).resolve()
        except Exception:
            return match.group(0)
        return f"{prefix}({absolute.as_uri()}{title})"

    return _MARKDOWN_LINK_RE.sub(_rewrite, content)
