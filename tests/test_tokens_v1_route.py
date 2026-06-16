"""Route + auth e2e for the secret-source framework (v1.19.0, Inc 8a).

Exercises ``/v1/tokens`` CRUD over a TestClient and the auth middleware's
delegation to the provider chain — including the load-bearing
backward-compat property (no ``server.secrets`` config behaves exactly as
the v1.18.3 single-shared-token model).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import ppxai.server.state as state
from ppxai.server.auth import check_request
from ppxai.server.routes import tokens_v1
from ppxai.server.secrets import EnvSecretProvider, FileSecretProvider, ProviderChain


@pytest.fixture
def file_chain(tmp_path, monkeypatch):
    """Install a file-backed chain as the server singleton."""
    chain = ProviderChain([FileSecretProvider(path=str(tmp_path / "t.json"))])
    monkeypatch.setattr(state, "_secret_provider", chain)
    return chain


@pytest.fixture
def client(file_chain):
    app = FastAPI()
    app.include_router(tokens_v1.router)
    return TestClient(app), file_chain


class TestTokensCrud:
    def test_mint_returns_material_once(self, client):
        c, _ = client
        r = c.post("/v1/tokens", json={"owner": "alice", "roles": ["oncall"]})
        assert r.status_code == 201
        body = r.json()
        assert body["token"]  # raw material present in the mint response
        assert body["meta"]["owner"] == "alice"
        assert body["meta"]["roles"] == ["oncall"]
        assert body["meta"]["source"] == "file"

    def test_list_never_returns_material(self, client):
        c, _ = client
        mint = c.post("/v1/tokens", json={"owner": "alice"}).json()
        material = mint["token"]
        listed = c.get("/v1/tokens").json()
        assert len(listed) == 1
        # No field in the listing equals the raw material.
        assert all(material not in str(v) for v in listed[0].values())

    def test_mint_then_resolve_via_chain(self, client):
        c, chain = client
        material = c.post("/v1/tokens", json={"owner": "bob"}).json()["token"]
        # The same singleton the auth middleware uses now resolves it.
        assert chain.resolve(material).owner == "bob"

    def test_revoke(self, client):
        c, chain = client
        mint = c.post("/v1/tokens", json={"owner": "alice"}).json()
        tid = mint["meta"]["token_id"]
        r = c.delete(f"/v1/tokens/{tid}")
        assert r.status_code == 200
        assert chain.resolve(mint["token"]) is None

    def test_revoke_unknown_404(self, client):
        c, _ = client
        assert c.delete("/v1/tokens/does-not-exist").status_code == 404

    def test_mint_empty_owner_422(self, client):
        c, _ = client
        assert c.post("/v1/tokens", json={"owner": ""}).status_code == 422


class TestReadOnlyBackend405:
    """Against an env-only (read-only) chain, mutating ops return 405."""

    @pytest.fixture
    def env_client(self, monkeypatch):
        monkeypatch.setenv("PPXAI_API_TOKEN", "shared")
        chain = ProviderChain([EnvSecretProvider()])
        monkeypatch.setattr(state, "_secret_provider", chain)
        app = FastAPI()
        app.include_router(tokens_v1.router)
        return TestClient(app)

    def test_mint_405(self, env_client):
        assert env_client.post("/v1/tokens", json={"owner": "x"}).status_code == 405

    def test_list_405(self, env_client):
        assert env_client.get("/v1/tokens").status_code == 405

    def test_revoke_405(self, env_client):
        assert env_client.delete("/v1/tokens/anything").status_code == 405


class TestAuthDelegation:
    """check_request now validates against the chain and stays
    backward-compatible when nothing enforces a token."""

    def _request(self, header_value=None, method="GET", path="/x", client_host="1.2.3.4"):
        scope = {
            "type": "http",
            "method": method,
            "headers": (
                [(b"authorization", header_value.encode())] if header_value else []
            ),
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "client": (client_host, 12345),
            "scheme": "http",
            "server": ("127.0.0.1", 54320),
        }
        return Request(scope)

    def test_no_provider_enforces_allows(self, monkeypatch):
        # Empty chain → auth disabled → request passes (loopback UX).
        monkeypatch.setattr(state, "_secret_provider", ProviderChain([]))
        monkeypatch.delenv("PPXAI_API_TOKEN", raising=False)
        assert check_request(self._request()) is None

    def test_env_token_still_works(self, monkeypatch):
        monkeypatch.setenv("PPXAI_API_TOKEN", "legacy")
        monkeypatch.setattr(
            state, "_secret_provider", ProviderChain([EnvSecretProvider()])
        )
        # Correct token passes; the principal is stashed.
        req = self._request("Bearer legacy")
        assert check_request(req) is None
        assert req.state.principal.owner == "env"

    def test_wrong_token_401(self, monkeypatch):
        monkeypatch.setenv("PPXAI_API_TOKEN", "legacy")
        monkeypatch.setattr(
            state, "_secret_provider", ProviderChain([EnvSecretProvider()])
        )
        resp = check_request(self._request("Bearer wrong"))
        assert resp is not None and resp.status_code == 401

    def test_missing_header_401_when_enforced(self, monkeypatch, tmp_path):
        fp = FileSecretProvider(path=str(tmp_path / "t.json"))
        fp.mint(owner="alice")  # at least one active token → enforced
        monkeypatch.delenv("PPXAI_API_TOKEN", raising=False)
        monkeypatch.setattr(state, "_secret_provider", ProviderChain([fp]))
        resp = check_request(self._request())
        assert resp is not None and resp.status_code == 401

    def test_file_token_authenticates(self, monkeypatch, tmp_path):
        fp = FileSecretProvider(path=str(tmp_path / "t.json"))
        material, _ = fp.mint(owner="alice")
        monkeypatch.delenv("PPXAI_API_TOKEN", raising=False)
        monkeypatch.setattr(state, "_secret_provider", ProviderChain([fp]))
        req = self._request(f"Bearer {material}")
        assert check_request(req) is None
        assert req.state.principal.owner == "alice"


class TestEmptyStorePolicy:
    """A configured mutable (file) store enforces auth even when empty,
    and a loopback POST /v1/tokens bootstraps the first token."""

    def _request(self, header_value=None, method="GET", path="/x", client_host="1.2.3.4"):
        scope = {
            "type": "http",
            "method": method,
            "headers": (
                [(b"authorization", header_value.encode())] if header_value else []
            ),
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "client": (client_host, 12345),
            "scheme": "http",
            "server": ("127.0.0.1", 54320),
        }
        return Request(scope)

    def _empty_file_chain(self, monkeypatch, tmp_path):
        fp = FileSecretProvider(path=str(tmp_path / "t.json"))  # no tokens
        monkeypatch.delenv("PPXAI_API_TOKEN", raising=False)
        monkeypatch.setattr(state, "_secret_provider", ProviderChain([fp]))
        return fp

    def test_empty_file_store_still_enforces(self, monkeypatch, tmp_path):
        from ppxai.server.auth import is_auth_enabled

        self._empty_file_chain(monkeypatch, tmp_path)
        # The footgun fix: empty mutable store => auth ON, not open.
        assert is_auth_enabled() is True
        resp = check_request(self._request(path="/v1/agent/runs"))
        assert resp is not None and resp.status_code == 401

    def test_revoking_last_token_does_not_open_server(self, monkeypatch, tmp_path):
        fp = FileSecretProvider(path=str(tmp_path / "t.json"))
        material, rec = fp.mint(owner="alice")
        monkeypatch.delenv("PPXAI_API_TOKEN", raising=False)
        monkeypatch.setattr(state, "_secret_provider", ProviderChain([fp]))
        fp.revoke(rec.token_id)
        # Revoked token must NOT authenticate, and the server must NOT
        # silently fall open just because the store is now empty.
        resp = check_request(self._request(f"Bearer {material}", path="/v1/agent/runs"))
        assert resp is not None and resp.status_code == 401

    def test_loopback_bootstrap_mint_allowed_when_empty(self, monkeypatch, tmp_path):
        self._empty_file_chain(monkeypatch, tmp_path)
        req = self._request(
            method="POST", path="/v1/tokens", client_host="127.0.0.1"
        )
        assert check_request(req) is None  # bootstrap exemption

    def test_remote_bootstrap_mint_denied(self, monkeypatch, tmp_path):
        self._empty_file_chain(monkeypatch, tmp_path)
        req = self._request(
            method="POST", path="/v1/tokens", client_host="10.0.0.5"
        )
        resp = check_request(req)
        assert resp is not None and resp.status_code == 401

    def test_bootstrap_closes_once_token_exists(self, monkeypatch, tmp_path):
        fp = FileSecretProvider(path=str(tmp_path / "t.json"))
        fp.mint(owner="alice")  # store no longer empty
        monkeypatch.delenv("PPXAI_API_TOKEN", raising=False)
        monkeypatch.setattr(state, "_secret_provider", ProviderChain([fp]))
        # Even from loopback, mint now requires auth (not a standing hole).
        req = self._request(
            method="POST", path="/v1/tokens", client_host="127.0.0.1"
        )
        resp = check_request(req)
        assert resp is not None and resp.status_code == 401

    def test_env_only_unset_stays_open(self, monkeypatch):
        # Backward-compat: env-only + unset => unauthenticated loopback UX.
        from ppxai.server.auth import is_auth_enabled

        monkeypatch.delenv("PPXAI_API_TOKEN", raising=False)
        monkeypatch.setattr(
            state, "_secret_provider", ProviderChain([EnvSecretProvider()])
        )
        assert is_auth_enabled() is False
        assert check_request(self._request(path="/v1/agent/runs")) is None
