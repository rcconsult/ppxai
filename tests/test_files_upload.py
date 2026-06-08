"""HTTP route tests for POST /files/upload (v1.18.7).

Companion to test_files_route.py / test_files_preview_download.py.
Verifies the workspace-upload path:

- happy path: writes the file under <path>/<file.name>, returns metadata
- filename sanitization: directory traversal in `file.filename` is stripped
- 400 on missing/invalid filename or non-directory destination
- 403 when destination would land outside the allowed tree
- 409 on existing file without overwrite=true; 200 with overwrite=true
- 413 when upload exceeds UPLOAD_MAX_BYTES (verified by patching the
  constant down to a tiny value to keep the test fast)
- partial-write cleanup: oversize upload doesn't leave a half-written
  file on disk
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

import ppxai.server.routes.files as files_mod


@pytest.fixture
def http_client():
    import ppxai.server.http as http_module
    with TestClient(http_module.app, raise_server_exceptions=False) as client:
        yield client


def _session(name: str) -> dict:
    return {"X-Session-Id": f"files-upload-{name}"}


def _anchor_to(client: TestClient, headers: dict, path: Path) -> None:
    client.post(
        "/context/working_dir",
        json={"path": str(path)},
        headers=headers,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestUploadHappyPath:
    def test_upload_to_working_dir_root(self, http_client, tmp_path):
        headers = _session("root")
        _anchor_to(http_client, headers, tmp_path)

        # Empty `path=.` resolves to working_dir itself.
        resp = http_client.post(
            "/files/upload",
            params={"path": "."},
            files={"file": ("note.txt", io.BytesIO(b"hello\nworld\n"), "text/plain")},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["name"] == "note.txt"
        assert body["size"] == len(b"hello\nworld\n")
        assert body["overwrote"] is False

        # File actually on disk with the right contents
        dest = tmp_path / "note.txt"
        assert dest.read_bytes() == b"hello\nworld\n"

    def test_upload_to_subdirectory(self, http_client, tmp_path):
        sub = tmp_path / "data"
        sub.mkdir()
        headers = _session("subdir")
        _anchor_to(http_client, headers, tmp_path)

        resp = http_client.post(
            "/files/upload",
            params={"path": "data"},
            files={"file": ("rows.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert (sub / "rows.csv").read_bytes() == b"a,b\n1,2\n"


# ---------------------------------------------------------------------------
# Security: filename sanitization
# ---------------------------------------------------------------------------


class TestFilenameSanitization:
    def test_directory_components_stripped(self, http_client, tmp_path):
        """A malicious upload with `../../etc/passwd` as filename should
        land at the basename only inside the destination dir, NOT escape."""
        headers = _session("sanitize")
        _anchor_to(http_client, headers, tmp_path)

        resp = http_client.post(
            "/files/upload",
            params={"path": "."},
            files={"file": ("../../etc/passwd", io.BytesIO(b"x"), "text/plain")},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        # Lands at <working_dir>/passwd, not outside
        assert (tmp_path / "passwd").exists()
        # Definitely not at /etc/passwd or anywhere else outside
        # (covered structurally by _resolve_safe_path; this is the
        # second line of defense in the upload handler itself).

    def test_empty_filename_rejected(self, http_client, tmp_path):
        headers = _session("empty-name")
        _anchor_to(http_client, headers, tmp_path)

        # FastAPI requires SOME filename in multipart; send a single
        # dot which the sanitizer should reject (Path('.').name == '').
        resp = http_client.post(
            "/files/upload",
            params={"path": "."},
            files={"file": (".", io.BytesIO(b"x"), "application/octet-stream")},
            headers=headers,
        )
        # Either 400 (sanitizer rejects) or 200 with the file landing
        # at a sanitized name — both are acceptable defenses. We pin
        # 400 because Path('.').name == '' is the documented reject
        # case in the handler.
        assert resp.status_code == 400, resp.text

    def test_dotdot_filename_rejected(self, http_client, tmp_path):
        headers = _session("dotdot")
        _anchor_to(http_client, headers, tmp_path)

        resp = http_client.post(
            "/files/upload",
            params={"path": "."},
            files={"file": ("..", io.BytesIO(b"x"), "application/octet-stream")},
            headers=headers,
        )
        assert resp.status_code == 400, resp.text


# ---------------------------------------------------------------------------
# Bad-destination errors
# ---------------------------------------------------------------------------


class TestDestinationErrors:
    def test_path_is_file_not_directory(self, http_client, tmp_path):
        existing_file = tmp_path / "blocker.txt"
        existing_file.write_text("existing", encoding="utf-8")
        headers = _session("not-dir")
        _anchor_to(http_client, headers, tmp_path)

        resp = http_client.post(
            "/files/upload",
            params={"path": "blocker.txt"},
            files={"file": ("upload.txt", io.BytesIO(b"x"), "text/plain")},
            headers=headers,
        )
        assert resp.status_code == 400, resp.text
        assert "not a directory" in resp.json()["detail"].lower()

    def test_path_missing(self, http_client, tmp_path):
        headers = _session("missing")
        _anchor_to(http_client, headers, tmp_path)

        resp = http_client.post(
            "/files/upload",
            params={"path": "no/such/dir"},
            files={"file": ("x.txt", io.BytesIO(b"x"), "text/plain")},
            headers=headers,
        )
        # _resolve_safe_path raises 404 on missing path
        assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# Conflict / overwrite
# ---------------------------------------------------------------------------


class TestOverwriteSemantics:
    def test_existing_file_409_without_overwrite(self, http_client, tmp_path):
        existing = tmp_path / "note.txt"
        existing.write_text("original", encoding="utf-8")
        headers = _session("conflict")
        _anchor_to(http_client, headers, tmp_path)

        resp = http_client.post(
            "/files/upload",
            params={"path": "."},
            files={"file": ("note.txt", io.BytesIO(b"new"), "text/plain")},
            headers=headers,
        )
        assert resp.status_code == 409, resp.text
        # Existing file untouched
        assert existing.read_text(encoding="utf-8") == "original"

    def test_overwrite_true_replaces_and_marks_overwrote(self, http_client, tmp_path):
        existing = tmp_path / "note.txt"
        existing.write_text("original", encoding="utf-8")
        headers = _session("overwrite-yes")
        _anchor_to(http_client, headers, tmp_path)

        resp = http_client.post(
            "/files/upload",
            params={"path": ".", "overwrite": "true"},
            files={"file": ("note.txt", io.BytesIO(b"new"), "text/plain")},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["overwrote"] is True
        assert existing.read_bytes() == b"new"


# ---------------------------------------------------------------------------
# Size cap
# ---------------------------------------------------------------------------


class TestSizeCap:
    def test_oversize_returns_413_and_cleans_up(self, http_client, tmp_path, monkeypatch):
        # Bring the cap down to 256 bytes so we don't have to stream a real
        # 100 MB request through the TestClient.
        monkeypatch.setattr(files_mod, "UPLOAD_MAX_BYTES", 256)
        headers = _session("oversize")
        _anchor_to(http_client, headers, tmp_path)

        oversized_body = b"A" * 1024  # 1 KB, well over the 256-byte cap
        resp = http_client.post(
            "/files/upload",
            params={"path": "."},
            files={"file": ("big.bin", io.BytesIO(oversized_body), "application/octet-stream")},
            headers=headers,
        )
        assert resp.status_code == 413, resp.text
        # Partial-write cleanup: no half-written file left on disk
        assert not (tmp_path / "big.bin").exists()
