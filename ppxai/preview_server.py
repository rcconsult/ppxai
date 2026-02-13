"""
Standalone HTML preview server for TUI clients.

Spawns a minimal HTTPServer in a daemon thread that:
- Serves the HTML file with an injected reload script
- Provides a /poll endpoint returning file mtime as JSON
- Serves sibling static assets (CSS/JS/images)
- Auto-picks a free port on localhost
- Shuts down when preview is closed or TUI exits

Zero new dependencies: http.server, threading, webbrowser are all stdlib.

v1.16.0: Initial implementation
"""

import json
import os
import threading
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Optional

from .common.preview import inject_reload_script


class PreviewHandler(SimpleHTTPRequestHandler):
    """HTTP handler for live preview with reload support."""

    def do_GET(self):
        if self.path == '/poll':
            self._serve_poll()
            return

        if self.path in ('/', '/index', '/index.html'):
            self._serve_html()
            return

        # Fallback: serve static assets from file's directory
        super().do_GET()

    def _serve_poll(self):
        """Return newest mtime of HTML file + sibling assets."""
        try:
            mtime = self.server.target_file.stat().st_mtime
            # Check sibling CSS/JS/image files so edits to them trigger reload
            for sibling in self.server.target_file.parent.iterdir():
                if sibling.is_file() and sibling.suffix.lower() in (
                    '.css', '.js', '.html', '.htm', '.json', '.svg', '.png', '.jpg'
                ):
                    sib_mtime = sibling.stat().st_mtime
                    if sib_mtime > mtime:
                        mtime = sib_mtime
        except OSError:
            mtime = 0
        payload = json.dumps({"mtime": mtime}).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(payload)

    def _serve_html(self):
        """Serve HTML file with injected reload script."""
        try:
            content = self.server.target_file.read_text(encoding='utf-8')
        except Exception:
            self.send_error(500, "Failed to read HTML file")
            return
        poll_url = f'http://localhost:{self.server.server_address[1]}/poll'
        content = inject_reload_script(content, poll_url)
        encoded = content.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(encoded)))
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(encoded)

    def end_headers(self):
        """Add no-cache to all responses so live-reload picks up changes."""
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    def translate_path(self, path):
        """Resolve paths relative to target file's directory, not cwd.

        This avoids calling os.chdir() which would affect global state.
        """
        # Get the default translation (resolves against cwd)
        default = super().translate_path(path)
        # Compute relative part and rebase onto serve_dir
        try:
            rel = os.path.relpath(default, os.getcwd())
        except ValueError:
            # Different drives on Windows
            return default
        return os.path.join(self.server.serve_dir, rel)

    def log_message(self, format, *args):
        """Silence request logs."""
        pass


class PreviewServer:
    """Lightweight preview server for TUI clients.

    Usage:
        server = PreviewServer("/path/to/index.html", "/working/dir")
        url = server.start()       # Opens browser tab, returns URL
        # ... later ...
        server.stop()
    """

    def __init__(self, filepath: str, working_dir: str):
        target = Path(filepath)
        if not target.is_absolute():
            target = Path(working_dir) / filepath
        self.target = target.resolve()
        self.serve_dir = str(self.target.parent)
        self._httpd: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self.port: int = 0

    def start(self, open_browser: bool = True) -> str:
        """Start the preview server and optionally open the browser.

        Args:
            open_browser: Whether to call webbrowser.open()

        Returns:
            URL string (e.g., "http://localhost:54321/")
        """
        self._httpd = HTTPServer(('127.0.0.1', 0), PreviewHandler)
        self._httpd.target_file = self.target
        self._httpd.serve_dir = self.serve_dir
        self.port = self._httpd.server_address[1]

        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            daemon=True
        )
        self._thread.start()

        url = f"http://localhost:{self.port}/"
        if open_browser:
            webbrowser.open(url)
        return url

    def stop(self):
        """Shut down the server."""
        if self._httpd:
            self._httpd.shutdown()
            self._httpd = None

    @property
    def is_running(self) -> bool:
        """Whether the server thread is alive."""
        return self._thread is not None and self._thread.is_alive()
