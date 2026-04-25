"""cwd_anchor + 409 conflict tests (v1.18.1 state-sync Phase D).

Pre-v1.18.1, the file-tree showed entries from the cwd it loaded
against, but `/files/read` resolved relpaths against engine's
CURRENT cwd. When engine cwd had drifted (agent loop, REST race,
multi-tab), clicking a stale entry produced a confusing
`404 file not found` even though the file appeared in the tree.

Phase D names the drift: client passes `cwd_anchor` with
read/write requests; server returns 409 + `{expected, actual,
events}` on mismatch. The client surfaces a recovery message and
re-anchors AppState from the events, refreshing the file tree
against the new cwd.

These tests cover the server side. The client recovery path
(handleCwdAnchorMismatch) is exercised by the e2e suite (Step 6).
"""

from __future__ import annotations

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


def _new_session_headers(name: str) -> dict:
    return {"X-Session-Id": f"phase-d-{name}"}


# ---------------------------------------------------------------------------
# /files/list returns the working_dir it resolved against
# ---------------------------------------------------------------------------

class TestFilesListReturnsAnchor:
    def test_root_listing_includes_working_dir(self, http_client, tmp_path):
        # Set engine cwd via /context/working_dir
        headers = _new_session_headers("list-anchor")
        http_client.post(
            "/context/working_dir",
            json={"path": str(tmp_path)},
            headers=headers,
        )
        resp = http_client.get("/files/list", headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "working_dir" in body, (
            "/files/list response must include working_dir for "
            "client-side cwd_anchor capture"
        )
        # Path resolution may normalize separators / case
        assert Path(body["working_dir"]).resolve() == tmp_path.resolve()

    def test_subpath_listing_includes_working_dir(self, http_client, tmp_path):
        sub = tmp_path / "src"
        sub.mkdir()
        headers = _new_session_headers("subpath-anchor")
        http_client.post(
            "/context/working_dir",
            json={"path": str(tmp_path)},
            headers=headers,
        )
        resp = http_client.get("/files/list?path=src", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        # Subpath listings still anchor to the WORKING dir (not the
        # listed subpath), so the client tracks ONE anchor for the tree
        assert "working_dir" in body
        assert Path(body["working_dir"]).resolve() == tmp_path.resolve()


# ---------------------------------------------------------------------------
# /files/read returns 409 on cwd_anchor mismatch
# ---------------------------------------------------------------------------

class TestFilesReadCwdAnchor:
    def test_matching_anchor_returns_200(self, http_client, tmp_path):
        target = tmp_path / "hello.txt"
        target.write_text("hi", encoding="utf-8")
        headers = _new_session_headers("read-match")
        http_client.post(
            "/context/working_dir",
            json={"path": str(tmp_path)},
            headers=headers,
        )
        resp = http_client.post(
            "/files/read",
            json={"path": "hello.txt", "cwd_anchor": str(tmp_path)},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text

    def test_no_anchor_is_backward_compatible(self, http_client, tmp_path):
        """Callers that don't pass cwd_anchor still work — the anchor
        check no-ops when None. Phase D is opt-in."""
        target = tmp_path / "hello.txt"
        target.write_text("hi", encoding="utf-8")
        headers = _new_session_headers("read-noanchor")
        http_client.post(
            "/context/working_dir",
            json={"path": str(tmp_path)},
            headers=headers,
        )
        resp = http_client.post(
            "/files/read",
            json={"path": "hello.txt"},  # no cwd_anchor
            headers=headers,
        )
        assert resp.status_code == 200

    def test_stale_anchor_returns_409(self, http_client, tmp_path):
        # Client thinks it's anchored to /a but engine is at /b
        dir_a = tmp_path / "a"
        dir_a.mkdir()
        dir_b = tmp_path / "b"
        dir_b.mkdir()
        (dir_a / "file.txt").write_text("a", encoding="utf-8")
        (dir_b / "file.txt").write_text("b", encoding="utf-8")

        headers = _new_session_headers("read-stale")
        # Engine cwd is /b
        http_client.post(
            "/context/working_dir",
            json={"path": str(dir_b)},
            headers=headers,
        )
        # Client passes anchor=/a (stale)
        resp = http_client.post(
            "/files/read",
            json={"path": "file.txt", "cwd_anchor": str(dir_a)},
            headers=headers,
        )
        assert resp.status_code == 409, (
            f"Expected 409 on stale anchor, got {resp.status_code}: {resp.text}"
        )

    def test_409_body_carries_expected_actual_events(self, http_client, tmp_path):
        dir_a = tmp_path / "a"
        dir_a.mkdir()
        dir_b = tmp_path / "b"
        dir_b.mkdir()
        headers = _new_session_headers("read-409-shape")
        http_client.post(
            "/context/working_dir",
            json={"path": str(dir_b)},
            headers=headers,
        )
        resp = http_client.post(
            "/files/read",
            json={"path": "file.txt", "cwd_anchor": str(dir_a)},
            headers=headers,
        )
        assert resp.status_code == 409
        body = resp.json()
        # FastAPI HTTPException body wraps under `detail`
        detail = body.get("detail", body)
        assert "expected" in detail, f"409 missing 'expected': {detail}"
        assert "actual" in detail, f"409 missing 'actual': {detail}"
        assert "events" in detail, f"409 missing 'events': {detail}"
        assert isinstance(detail["events"], list)
        # actual = engine's current cwd
        assert Path(detail["actual"]).resolve() == dir_b.resolve()
        # expected = client's stale anchor
        assert Path(detail["expected"]).resolve() == dir_a.resolve()

    def test_absolute_path_skips_anchor_check(self, http_client, tmp_path):
        """Absolute paths don't depend on cwd, so the anchor check
        is bypassed even if the anchor disagrees with engine cwd."""
        target = tmp_path / "abs.txt"
        target.write_text("absolute", encoding="utf-8")
        # Engine cwd elsewhere
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        headers = _new_session_headers("read-abs")
        http_client.post(
            "/context/working_dir",
            json={"path": str(elsewhere)},
            headers=headers,
        )
        # Pass an absolute path with a stale anchor — should still work
        resp = http_client.post(
            "/files/read",
            json={"path": str(target), "cwd_anchor": str(tmp_path / "stale")},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# /files/write returns 409 on cwd_anchor mismatch
# ---------------------------------------------------------------------------

class TestFilesWriteCwdAnchor:
    def test_stale_anchor_returns_409_before_writing(self, http_client, tmp_path):
        dir_a = tmp_path / "a"
        dir_a.mkdir()
        dir_b = tmp_path / "b"
        dir_b.mkdir()
        headers = _new_session_headers("write-stale")
        http_client.post(
            "/context/working_dir",
            json={"path": str(dir_b)},
            headers=headers,
        )
        # Stale anchor; the file MUST NOT be created in either dir
        resp = http_client.post(
            "/files/write",
            json={
                "path": "should-not-exist.txt",
                "content": "should-not-be-written",
                "cwd_anchor": str(dir_a),
            },
            headers=headers,
        )
        assert resp.status_code == 409
        # Confirm side-effect-free: nothing got written
        assert not (dir_a / "should-not-exist.txt").exists()
        assert not (dir_b / "should-not-exist.txt").exists()

    def test_matching_anchor_writes_normally(self, http_client, tmp_path):
        headers = _new_session_headers("write-match")
        http_client.post(
            "/context/working_dir",
            json={"path": str(tmp_path)},
            headers=headers,
        )
        resp = http_client.post(
            "/files/write",
            json={
                "path": "wrote.txt",
                "content": "ok",
                "cwd_anchor": str(tmp_path),
            },
            headers=headers,
        )
        assert resp.status_code == 200
        assert (tmp_path / "wrote.txt").read_text(encoding="utf-8") == "ok"


# ---------------------------------------------------------------------------
# /files/image with cwd_anchor query string
# ---------------------------------------------------------------------------

class TestFilesImageCwdAnchor:
    def test_image_endpoint_accepts_cwd_anchor_query(self, http_client, tmp_path):
        """The image endpoint takes the anchor via query string
        (it's a GET path-param route)."""
        # 1x1 PNG
        png = bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
            "890000000d49444154789c626001000000ffff03000006000557bff8730000"
            "00004945" + "4e44ae426082"
        )
        target = tmp_path / "pixel.png"
        target.write_bytes(png)
        headers = _new_session_headers("image-match")
        http_client.post(
            "/context/working_dir",
            json={"path": str(tmp_path)},
            headers=headers,
        )
        # Matching anchor → 200
        resp = http_client.get(
            f"/files/image/pixel.png?cwd_anchor={tmp_path}",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text

    def test_image_endpoint_409s_on_stale_anchor(self, http_client, tmp_path):
        png = bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
            "890000000d49444154789c626001000000ffff03000006000557bff8730000"
            "00004945" + "4e44ae426082"
        )
        dir_a = tmp_path / "a"
        dir_a.mkdir()
        (dir_a / "pixel.png").write_bytes(png)
        dir_b = tmp_path / "b"
        dir_b.mkdir()
        headers = _new_session_headers("image-stale")
        http_client.post(
            "/context/working_dir",
            json={"path": str(dir_b)},
            headers=headers,
        )
        resp = http_client.get(
            f"/files/image/pixel.png?cwd_anchor={dir_a}",
            headers=headers,
        )
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Anchor normalisation — separators, trailing slashes, ../ segments
# ---------------------------------------------------------------------------

class TestAnchorNormalisation:
    def test_trailing_slash_does_not_cause_false_mismatch(self, http_client, tmp_path):
        target = tmp_path / "f.txt"
        target.write_text("ok", encoding="utf-8")
        headers = _new_session_headers("trailing-slash")
        http_client.post(
            "/context/working_dir",
            json={"path": str(tmp_path)},
            headers=headers,
        )
        # Anchor with trailing slash
        anchor_with_slash = str(tmp_path) + os.sep
        resp = http_client.post(
            "/files/read",
            json={"path": "f.txt", "cwd_anchor": anchor_with_slash},
            headers=headers,
        )
        assert resp.status_code == 200, (
            f"Trailing slash on anchor should normalise; got "
            f"{resp.status_code}: {resp.text}"
        )

    def test_dotdot_segment_does_not_cause_false_mismatch(self, http_client, tmp_path):
        target = tmp_path / "f.txt"
        target.write_text("ok", encoding="utf-8")
        sub = tmp_path / "sub"
        sub.mkdir()
        headers = _new_session_headers("dotdot")
        http_client.post(
            "/context/working_dir",
            json={"path": str(tmp_path)},
            headers=headers,
        )
        # Anchor uses sub/.. which should resolve to tmp_path
        anchor = str(sub / "..")
        resp = http_client.post(
            "/files/read",
            json={"path": "f.txt", "cwd_anchor": anchor},
            headers=headers,
        )
        assert resp.status_code == 200, (
            f"Anchor with .. should normalise; got "
            f"{resp.status_code}: {resp.text}"
        )
