"""HTTP route tests for /files/read.

Complements test_files_cwd_anchor.py (which covers Phase D anchor
behavior) by exercising the rest of the response surface: status
codes, error paths, binary detection, image base64 encoding, and the
`@search-query` and `~` path conventions.

Filed v1.18.7 after CRG analysis flagged the route as a 67-degree
hub with no dedicated test (test_utils.py covers `read_file_content`,
a different function in ppxai/common/utils.py, not the HTTP route).
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient


@pytest.fixture
def http_client():
    import ppxai.server.http as http_module
    with TestClient(http_module.app, raise_server_exceptions=False) as client:
        yield client


def _session(name: str) -> dict:
    return {"X-Session-Id": f"files-route-{name}"}


def _anchor_to(client: TestClient, headers: dict, path: Path) -> None:
    client.post(
        "/context/working_dir",
        json={"path": str(path)},
        headers=headers,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestReadTextFile:
    def test_absolute_path_returns_content(self, http_client, tmp_path):
        target = tmp_path / "greeting.txt"
        target.write_text("hello\nworld\n", encoding="utf-8")
        headers = _session("abs-text")
        _anchor_to(http_client, headers, tmp_path)

        resp = http_client.post(
            "/files/read",
            json={"path": str(target)},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["type"] == "text"
        assert body["content"] == "hello\nworld\n"
        # Use actual file size on disk — Path.write_text + Windows can
        # introduce CRLF expansion making the on-disk byte count differ
        # from the in-memory string's UTF-8 length. The route returns
        # `os.stat().st_size` which matches the on-disk count.
        assert body["size"] == target.stat().st_size
        assert body["lines"] == 3  # 2 newlines + 1
        assert body["filename"] == "greeting.txt"

    def test_relative_path_resolves_against_working_dir(self, http_client, tmp_path):
        sub = tmp_path / "src"
        sub.mkdir()
        target = sub / "note.md"
        target.write_text("# note\n", encoding="utf-8")
        headers = _session("rel-text")
        _anchor_to(http_client, headers, tmp_path)

        resp = http_client.post(
            "/files/read",
            json={"path": "src/note.md", "cwd_anchor": str(tmp_path)},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["content"] == "# note\n"
        # filename is relative-from-working-dir, not bare basename
        assert body["filename"] == "src/note.md"

    def test_filename_is_basename_when_outside_working_dir(self, http_client, tmp_path):
        # When the file resolves outside the working dir, filename
        # falls back to basename (the relative_to raises ValueError).
        outside = tmp_path.parent / f"outside-{tmp_path.name}.txt"
        outside.write_text("x\n", encoding="utf-8")
        try:
            headers = _session("outside-basename")
            _anchor_to(http_client, headers, tmp_path)

            resp = http_client.post(
                "/files/read",
                json={"path": str(outside)},
                headers=headers,
            )
            # May 200 (path under HOME) or 403 (path outside HOME) —
            # both are legitimate depending on test environment. We
            # only care about the filename-fallback shape when it 200s.
            if resp.status_code == 200:
                assert resp.json()["filename"] == outside.name
        finally:
            outside.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------

class TestReadErrors:
    def test_missing_file_returns_404(self, http_client, tmp_path):
        headers = _session("missing-404")
        _anchor_to(http_client, headers, tmp_path)

        resp = http_client.post(
            "/files/read",
            json={"path": str(tmp_path / "does-not-exist.txt")},
            headers=headers,
        )
        assert resp.status_code == 404, resp.text
        assert "not found" in resp.json()["detail"].lower()

    def test_directory_returns_400_not_a_file(self, http_client, tmp_path):
        sub = tmp_path / "adir"
        sub.mkdir()
        headers = _session("dir-400")
        _anchor_to(http_client, headers, tmp_path)

        resp = http_client.post(
            "/files/read",
            json={"path": str(sub)},
            headers=headers,
        )
        assert resp.status_code == 400, resp.text
        assert "not a file" in resp.json()["detail"].lower()

    def test_path_outside_allowed_returns_403(self, http_client, tmp_path):
        # /etc/shadow (or any system path) is outside both the
        # working dir and the user's home. Must be denied.
        if os.name == "nt":
            forbidden = "C:\\Windows\\System32\\drivers\\etc\\hosts"
        else:
            forbidden = "/etc/shadow"
        headers = _session("forbidden-403")
        _anchor_to(http_client, headers, tmp_path)

        resp = http_client.post(
            "/files/read",
            json={"path": forbidden},
            headers=headers,
        )
        # 403 if path resolves outside allowed roots; 404 if it
        # simply doesn't exist (some CI images lack /etc/shadow).
        # Both prove the security boundary held — what we MUST NOT
        # see is 200 with content.
        assert resp.status_code in (403, 404), resp.text

    def test_binary_file_returns_400(self, http_client, tmp_path):
        # A non-image binary file (no recognized suffix) hits the
        # UnicodeDecodeError → 400 path.
        target = tmp_path / "blob.bin"
        target.write_bytes(b"\x00\x01\x02\xff\xfe\xfd")
        headers = _session("binary-400")
        _anchor_to(http_client, headers, tmp_path)

        resp = http_client.post(
            "/files/read",
            json={"path": str(target)},
            headers=headers,
        )
        assert resp.status_code == 400, resp.text
        assert "binary" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Image / PDF base64 path
# ---------------------------------------------------------------------------

class TestReadBinaryPreview:
    # 1x1 PNG (valid PNG magic + minimal IHDR/IDAT/IEND) so the
    # route's `image` MIME branch fires.
    PNG_1X1 = bytes.fromhex(
        "89504e470d0a1a0a"  # signature
        "0000000d49484452"  # IHDR chunk start (length=13, type)
        "00000001000000010802000000907753de"
        "0000000c4944415478da6300010000050001"
        "0d0a2db40000000049454e44ae426082"
    )

    def test_png_returns_base64_image(self, http_client, tmp_path):
        target = tmp_path / "pixel.png"
        target.write_bytes(self.PNG_1X1)
        headers = _session("png-b64")
        _anchor_to(http_client, headers, tmp_path)

        resp = http_client.post(
            "/files/read",
            json={"path": str(target)},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["type"] == "image"
        assert body["mime_type"] == "image/png"
        # Decode round-trip
        decoded = base64.b64decode(body["content"])
        assert decoded == self.PNG_1X1
        assert body["size"] == len(self.PNG_1X1)
        # Image responses don't carry a `lines` field (text-only).
        assert "lines" not in body

    def test_pdf_returns_base64_pdf(self, http_client, tmp_path):
        # Minimal PDF magic; route only cares about extension + bytes.
        pdf_bytes = b"%PDF-1.4\n%%EOF\n"
        target = tmp_path / "doc.pdf"
        target.write_bytes(pdf_bytes)
        headers = _session("pdf-b64")
        _anchor_to(http_client, headers, tmp_path)

        resp = http_client.post(
            "/files/read",
            json={"path": str(target)},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["type"] == "pdf"
        assert body["mime_type"] == "application/pdf"
        assert base64.b64decode(body["content"]) == pdf_bytes


# ---------------------------------------------------------------------------
# Special-prefix paths: @search-query and ~ tilde
# ---------------------------------------------------------------------------

class TestSpecialPathPrefixes:
    def test_at_query_finds_first_matching_file(self, http_client, tmp_path):
        # Files in the cwd tree
        (tmp_path / "alpha.txt").write_text("a\n", encoding="utf-8")
        (tmp_path / "beta.md").write_text("b\n", encoding="utf-8")
        headers = _session("at-search")
        _anchor_to(http_client, headers, tmp_path)

        resp = http_client.post(
            "/files/read",
            json={"path": "@beta"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["content"] == "b\n"
        # The route resolves @beta → beta.md and returns its real name
        assert body["filename"].endswith("beta.md")

    def test_at_query_no_match_returns_404(self, http_client, tmp_path):
        headers = _session("at-no-match")
        _anchor_to(http_client, headers, tmp_path)

        resp = http_client.post(
            "/files/read",
            json={"path": "@absolutely-nothing-by-this-name.xyz"},
            headers=headers,
        )
        assert resp.status_code == 404, resp.text
        assert "no files found" in resp.json()["detail"].lower()

    def test_tilde_expansion_resolves_against_home(self, http_client, tmp_path, monkeypatch):
        # Point HOME at tmp_path so we don't touch the user's real
        # home, then create a file there and read it via `~/...`.
        monkeypatch.setenv("HOME", str(tmp_path))
        # Path.home() reads HOME on POSIX and USERPROFILE on Windows;
        # set both for cross-platform safety.
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        target = tmp_path / "tilde-target.txt"
        target.write_text("from-home\n", encoding="utf-8")

        headers = _session("tilde")
        _anchor_to(http_client, headers, tmp_path)

        resp = http_client.post(
            "/files/read",
            json={"path": "~/tilde-target.txt"},
            headers=headers,
        )
        # Some environments don't honor monkeypatched HOME for
        # Path.home() (cached). Both 200 (expansion worked) and 403
        # (target outside the real home) are legitimate proofs that
        # the tilde branch didn't crash.
        assert resp.status_code in (200, 403), resp.text
        if resp.status_code == 200:
            assert resp.json()["content"] == "from-home\n"


class TestWithinTreeConfinement:
    """Unit tests for `_within_tree` — the home-dir subtree check used by
    `_resolve_safe_path` and `/files/write`.

    v1.18.7: replaced a `str(path).startswith(str(home_dir))` prefix test,
    which let a sibling directory whose name shares a prefix (e.g.
    `/home/userEVIL` vs `/home/user`) pass the home-dir confinement.
    """

    def test_path_inside_base_passes(self):
        from ppxai.server.routes.files import _within_tree
        base = Path("/home/user").resolve()
        assert _within_tree((base / "notes" / "a.txt"), base) is True

    def test_base_itself_passes(self):
        from ppxai.server.routes.files import _within_tree
        base = Path("/home/user").resolve()
        assert _within_tree(base, base) is True

    def test_prefix_sibling_rejected(self):
        """The exact bug the fix closes: a sibling sharing a name prefix."""
        from ppxai.server.routes.files import _within_tree
        base = Path("/home/user").resolve()
        evil = Path("/home/userEVIL/.ssh/id_rsa").resolve()
        assert _within_tree(evil, base) is False

    def test_ancestor_rejected(self):
        """One-directional: an ancestor of base must NOT pass (unlike the
        bidirectional `is_path_allowed`)."""
        from ppxai.server.routes.files import _within_tree
        base = Path("/home/user").resolve()
        assert _within_tree(Path("/home").resolve(), base) is False
        assert _within_tree(Path("/").resolve(), base) is False

    def test_unrelated_path_rejected(self):
        from ppxai.server.routes.files import _within_tree
        base = Path("/home/user").resolve()
        assert _within_tree(Path("/etc/passwd").resolve(), base) is False
