"""The remote hub (ADR 0013) must not change anything for the k8s coder pods.

Owner requirement, 2026-09-28. How a coder pod runs ppxai (deploy/images/
session-manager/main.py): `python -m ppxai.server.http --host 0.0.0.0`,
PPXAI_TRUSTED_HOSTS=<ingress host>, PPXAI_ALLOWED_ORIGINS=https://<ingress
host>, no `remote` block in its config, requests arriving from the ingress
controller (a non-loopback peer, `/s/<slug>/` already stripped by the
ingress rewrite). The hub is gated on `remote.hosts`, so for that pod:

- every hub path answers byte-for-byte as an unknown path did before;
- no manager exists and no subprocess (ssh) is ever started;
- even a pod that somehow HAD `remote.hosts` would not expose the hub to the
  ingress: the hub answers direct loopback peers only.

These tests run the REAL server app, not the hub router in isolation.
"""

from __future__ import annotations

import asyncio
import json
import logging

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from ppxai.config import loader
from ppxai.server import http as http_module
from ppxai.server.routes import remote_hub

POD_PEER = ("10.1.2.3", 50123)
HOST = "coder.example.com"
ORIGIN = f"https://{HOST}"
HOSTS_CONFIG = {"hosts": [{"id": "gpu01", "ssh": "gpu01"}]}


@pytest.fixture(autouse=True)
def coder_pod(monkeypatch):
    monkeypatch.delenv("PPXAI_API_TOKEN", raising=False)
    monkeypatch.setattr(http_module, "_BIND_HOST", "0.0.0.0")
    monkeypatch.setenv("PPXAI_TRUSTED_HOSTS", HOST)
    monkeypatch.setenv("PPXAI_ALLOWED_ORIGINS", ORIGIN)
    monkeypatch.setattr(http_module, "get_remote_config", lambda: {})
    yield
    asyncio.run(remote_hub.stop_hub())


@pytest.fixture
def no_subprocesses(monkeypatch):
    spawned = []

    async def refuse(*args, **kwargs):
        spawned.append(args)
        raise AssertionError(f"the hub started a subprocess: {args[:3]}")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", refuse)
    return spawned


def _pod_client():
    return TestClient(http_module.app, client=POD_PEER, base_url=f"https://{HOST}")


@pytest.fixture(scope="class")
def off_pod():
    """ONE app start shared by the read-only checks below: a start is ~3 s on
    Windows, and these tests only send requests. The env is re-applied per
    test by `coder_pod`; this fixture pins what the lifespan reads at startup."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(http_module, "_BIND_HOST", "0.0.0.0")
        mp.setenv("PPXAI_TRUSTED_HOSTS", HOST)
        mp.setenv("PPXAI_ALLOWED_ORIGINS", ORIGIN)
        mp.delenv("PPXAI_API_TOKEN", raising=False)
        mp.setattr(http_module, "get_remote_config", lambda: {})
        with _pod_client() as client:
            yield client


class TestHubIsOffWithoutRemoteHosts:
    def test_no_hub_exists(self, off_pod):
        assert remote_hub.hub() is None

    @pytest.mark.parametrize("method,path", [
        ("GET", "/h/gpu01/9f2c0000aaaa1111/"),
        ("GET", "/h/gpu01/9f2c0000aaaa1111/state"),
        ("POST", "/h/gpu01/9f2c0000aaaa1111/chat"),
        ("GET", "/h/gpu01/9f2c0000aaaa1111"),
        ("GET", "/hub/hosts"),
        ("GET", "/hub/hosts/gpu01/servers"),
        ("POST", "/hub/hosts/gpu01/servers"),
        ("POST", "/hub/hosts/gpu01/servers/9f2c0000aaaa1111/attach"),
    ])
    def test_hub_paths_answer_exactly_like_an_unknown_path(self, off_pod, method, path):
        unknown = off_pod.request(method, "/no/such/route/here", headers={"origin": ORIGIN})
        hub = off_pod.request(method, path, headers={"origin": ORIGIN})
        assert (hub.status_code, hub.content) == (unknown.status_code, unknown.content) \
            == (404, b'{"detail":"Not Found"}')

    def test_a_hub_websocket_is_refused(self, off_pod):
        with pytest.raises(WebSocketDisconnect):
            with off_pod.websocket_connect("/h/gpu01/9f2c0000aaaa1111/ws/terminal",
                                           headers={"host": HOST, "origin": ORIGIN}):
                pass

    def test_the_pods_own_terminal_still_opens(self, off_pod):
        with off_pod.websocket_connect("/ws/terminal", headers={"host": HOST, "origin": ORIGIN}):
            pass

    def test_nothing_is_spawned(self, no_subprocesses):
        with _pod_client() as c:
            c.get("/h/gpu01/9f2c0000aaaa1111/")
            c.get("/hub/hosts")
            c.get("/health")
        assert no_subprocesses == []

    def test_health_and_ready_are_unchanged(self, off_pod):
        assert off_pod.get("/health", headers={"host": "10.1.2.3:54320"}).status_code == 200
        assert off_pod.get("/ready", headers={"host": HOST}).status_code in (200, 503)


class TestEvenWithRemoteHostsTheIngressSeesNothing:
    """Belt and braces: a pod config that DID carry remote.hosts still does not
    hand the hub to anything arriving through the ingress."""

    @pytest.fixture(autouse=True)
    def with_hosts(self, monkeypatch):
        monkeypatch.setattr(http_module, "get_remote_config", lambda: HOSTS_CONFIG)

    def test_a_pod_peer_gets_404(self, no_subprocesses):
        with _pod_client() as c:
            assert remote_hub.hub() is not None
            assert c.get("/hub/hosts").status_code == 404
            assert c.get("/h/gpu01/9f2c0000aaaa1111/").status_code == 404
        assert no_subprocesses == []

    def test_a_loopback_peer_behind_the_ingress_is_still_refused(self, no_subprocesses):
        # ingress-nginx sets X-Forwarded-For; a forwarded request is never loopback.
        with TestClient(http_module.app, client=("127.0.0.1", 5), base_url=f"https://{HOST}") as c:
            r = c.get("/hub/hosts", headers={"x-forwarded-for": "198.51.100.7"})
        assert r.status_code == 404
        assert no_subprocesses == []


class TestStartupNeverBreaks:
    @pytest.mark.parametrize("bad", [
        "not-an-object",
        {"hosts": "gpu01"},
        {"hosts": [{"id": "Bad Id", "ssh": "x"}]},
        {"hosts": [{"id": "gpu01", "ssh": "-oProxyCommand=x"}]},
    ])
    def test_a_malformed_remote_block_logs_and_leaves_the_hub_off(self, monkeypatch, caplog, bad):
        monkeypatch.setattr(http_module, "get_remote_config", lambda: bad)
        with caplog.at_level(logging.ERROR):
            with _pod_client() as c:
                assert remote_hub.hub() is None
                assert c.get("/health", headers={"host": HOST}).status_code == 200
        assert any("remote hub disabled" in r.getMessage() for r in caplog.records)

    def test_an_announced_server_never_runs_a_hub(self, monkeypatch):
        monkeypatch.setattr(http_module, "get_remote_config", lambda: HOSTS_CONFIG)
        monkeypatch.setattr(http_module, "_HUB_ALLOWED", False)
        with _pod_client():
            assert remote_hub.hub() is None


class TestTheRealLoaderKeepsTheRemoteBlock:
    """`load_config()` returns a WHITELIST of top-level keys; a key not listed
    there is silently dropped (file_tree, execution, network all hit this).
    Without `remote` in it the hub could never turn on, however it was
    configured."""

    def test_remote_survives_the_loader(self, tmp_path, monkeypatch):
        cfg = tmp_path / "ppxai-config.json"
        cfg.write_text(json.dumps({"version": "1", "providers": {}, "remote": HOSTS_CONFIG}),
                       encoding="utf-8")
        monkeypatch.setenv("PPXAI_CONFIG_FILE", str(cfg))
        assert loader.load_config().get("remote") == HOSTS_CONFIG

    def test_no_remote_block_loads_as_empty(self, tmp_path, monkeypatch):
        cfg = tmp_path / "ppxai-config.json"
        cfg.write_text(json.dumps({"version": "1", "providers": {}}), encoding="utf-8")
        monkeypatch.setenv("PPXAI_CONFIG_FILE", str(cfg))
        assert loader.load_config().get("remote") == {}
