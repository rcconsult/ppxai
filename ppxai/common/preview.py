"""
Shared HTML preview utilities.

Provides the reload script injection used by both FastAPI server
and stdlib PreviewServer for live-reloading HTML previews.

v1.15.4: Initial implementation
"""

import re
from pathlib import Path
from typing import Optional

# The reload polling script injected before </body>.
# {poll_url} is replaced with the actual endpoint URL.
_RELOAD_SCRIPT_TEMPLATE = """<script>
(function() {
  var lastMtime = null;
  var pollUrl = '{poll_url}';
  function poll() {
    fetch(pollUrl)
      .then(function(r) { return r.json(); })
      .then(function(d) {
        if (lastMtime !== null && d.mtime !== lastMtime) {
          window.location.reload();
        }
        lastMtime = d.mtime;
      })
      .catch(function() {});
    setTimeout(poll, 500);
  }
  poll();
})();
</script>"""


def rewrite_asset_paths(html: str, static_base: str, cache_buster: str = '') -> str:
    """Rewrite relative src/href attributes to use the static asset endpoint.

    Handles: src="style.css", href="./lib/app.js", src="images/logo.png"
    Skips: absolute URLs (http://, https://), data URIs, anchors (#),
           protocol-relative (//), and empty paths.

    Args:
        html: Raw HTML content
        static_base: Base URL for static assets (e.g., "/preview/static/?session=xxx")
                     Should end with "/" or include query string.
        cache_buster: Optional value appended as &_t= or ?_t= to bust browser cache.
                      Pass a timestamp or mtime to force reload of changed assets.

    Returns:
        HTML with rewritten asset paths
    """
    def _rewrite(match):
        attr = match.group(1)    # e.g., 'src="' or 'href="'
        quote = match.group(2)   # quote character
        path = match.group(3)    # relative path
        if not path.strip():
            return match.group(0)
        # Build the rewritten URL
        # static_base may contain ? for query params, use appropriate separator
        if '?' in static_base:
            # e.g., /preview/static/?session=xxx → /preview/static/styles.css?session=xxx
            base, query = static_base.split('?', 1)
            url = f'{base}{path}?{query}'
        else:
            url = f'{static_base}{path}'
        # Append cache buster to force browser to re-fetch changed assets
        if cache_buster:
            sep = '&' if '?' in url else '?'
            url = f'{url}{sep}_t={cache_buster}'
        return f'{attr}{quote}{url}{quote}'

    # Match src="..." and href="..." with relative paths
    # Skip: http://, https://, data:, #, //, javascript:
    return re.sub(
        r'((?:src|href)\s*=\s*)(["\'])((?!https?://|data:|#|//|javascript:).*?)\2',
        _rewrite,
        html,
        flags=re.IGNORECASE
    )


def inject_reload_script(html: str, poll_url: str) -> str:
    """Inject a mtime-polling reload script into HTML content.

    Inserts the script just before </body> if present, otherwise
    appends it to the end of the document.

    Args:
        html: Raw HTML content
        poll_url: Full URL to the poll endpoint (returns {"mtime": float})

    Returns:
        HTML with injected reload script
    """
    script = _RELOAD_SCRIPT_TEMPLATE.replace('{poll_url}', poll_url)

    # Insert before </body> if present (case-insensitive)
    pattern = re.compile(r'(</body>)', re.IGNORECASE)
    if pattern.search(html):
        return pattern.sub(script + r'\1', html, count=1)
    else:
        return html + '\n' + script


def resolve_preview_path(
    filepath: str,
    working_dir: str,
    restrict_extension: bool = True
) -> Path:
    """Resolve and validate a preview file path.

    Args:
        filepath: User-provided file path (relative or absolute)
        working_dir: Current working directory for relative resolution
        restrict_extension: If True, only allow .html/.htm files

    Returns:
        Resolved absolute Path

    Raises:
        FileNotFoundError: If file does not exist
        ValueError: If file is not .html/.htm or path traversal detected
    """
    path = Path(filepath).expanduser()
    if not path.is_absolute():
        path = Path(working_dir) / filepath
    path = path.resolve()

    # Path traversal guard: must be within working_dir or home
    wd = Path(working_dir).resolve()
    home = Path.home().resolve()
    try:
        path.relative_to(wd)
    except ValueError:
        if not str(path).startswith(str(home)):
            raise ValueError(
                f"Path traversal blocked: {filepath} is outside "
                f"working directory and home directory"
            )

    if not path.exists():
        raise FileNotFoundError(f"File not found: {filepath}")

    if not path.is_file():
        raise ValueError(f"Not a file: {filepath}")

    if restrict_extension and path.suffix.lower() not in ('.html', '.htm'):
        raise ValueError(
            f"Not an HTML file: {path.name} "
            f"(expected .html or .htm)"
        )

    return path
