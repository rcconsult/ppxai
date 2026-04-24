"""Shared text-formatting helpers used by user-visible UI strings.

Every formatter here has JS/TS mirrors in:
    ppxai/web/shared/formatters.js          (function `formatTokens`,
                                              `formatUsageBadge`)
    vscode-extension/src/shared/formatters.ts  (same names, typed)

The three copies are not auto-generated — when editing any of them,
update the other two to match and run the cross-language parity tests
(`tests/test_usage_format.py`) which invoke node on the JS/TS outputs
and assert byte-for-byte equality with this Python source.

Why not DRY across languages? The Rich TUI runs Python; the web and
VSCode clients run JS/TS in a webview where pulling Python at runtime
isn't possible. Three small mirrors is cheaper than a cross-language
RPC per badge render.
"""

from __future__ import annotations


def format_tokens(count: int) -> str:
    """Compact token-count display: "15.3K" for >= 1000, raw int otherwise.

    The K suffix uses one decimal place (e.g. "1.2K" not "1200" or
    "1K"). Callers that want a different precision (zero decimals for
    context windows — "128K") should pass the rounded value in
    themselves rather than threading a precision argument through
    every call site; the default is the right fit for token counts
    that drift gradually.

    Examples:
        >>> format_tokens(0)
        '0'
        >>> format_tokens(999)
        '999'
        >>> format_tokens(1000)
        '1.0K'
        >>> format_tokens(15300)
        '15.3K'
    """
    if count >= 1000:
        return f"{count / 1000:.1f}K"
    return str(count)


def format_usage_badge(
    prompt_tokens: int,
    completion_tokens: int,
    estimated_cost: float,
) -> str:
    """Short usage-badge string: "1.2K↓/0.5K↑ $0.0045".

    Arrow glyphs: down = input / prompt, up = output / completion.
    When estimated_cost is zero (free-tier / local models) the "$..."
    suffix is omitted entirely — a "$0.0000" suffix is visual noise
    and wasted width. When cost is present it shows four decimal
    places so the badge width stays stable as cost accumulates from
    pennies to dollars.

    Mirrored verbatim in web (`formatters.js`), VSCode extension host
    (`formatters.ts`), and the VSCode webview (inline copy in
    `main.js`). The Rich TUI uses this for its session status line.
    Cross-language parity is verified byte-for-byte by
    `tests/test_usage_format.py`.

    Examples:
        >>> format_usage_badge(0, 0, 0.0)
        '0↓/0↑'
        >>> format_usage_badge(1200, 450, 0.0)
        '1.2K↓/450↑'
        >>> format_usage_badge(1200, 450, 0.0045)
        '1.2K↓/450↑ $0.0045'
    """
    prompt_str = format_tokens(prompt_tokens)
    completion_str = format_tokens(completion_tokens)
    tokens = f"{prompt_str}↓/{completion_str}↑"
    if estimated_cost > 0:
        return f"{tokens} ${estimated_cost:.4f}"
    return tokens
