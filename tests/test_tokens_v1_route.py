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

    def test_loopback_mint_allowed_when_empty(self, monkeypatch, tmp_path):
        self._empty_file_chain(monkeypatch, tmp_path)
        req = self._request(
            method="POST", path="/v1/tokens", client_host="127.0.0.1"
        )
        assert check_request(req) is None  # loopback mint exemption

    def test_loopback_mint_allowed_even_with_existing_tokens(self, monkeypatch, tmp_path):
        # Loopback mint is ALWAYS allowed (not gated on empty store) so a
        # local operator can mint more tokens without an admin bearer.
        fp = FileSecretProvider(path=str(tmp_path / "t.json"))
        fp.mint(owner="alice")  # store non-empty
        monkeypatch.delenv("PPXAI_API_TOKEN", raising=False)
        monkeypatch.setattr(state, "_secret_provider", ProviderChain([fp]))
        req = self._request(
            method="POST", path="/v1/tokens", client_host="127.0.0.1"
        )
        assert check_request(req) is None

    def test_remote_mint_denied(self, monkeypatch, tmp_path):
        self._empty_file_chain(monkeypatch, tmp_path)
        req = self._request(
            method="POST", path="/v1/tokens", client_host="10.0.0.5"
        )
        resp = check_request(req)
        assert resp is not None and resp.status_code == 401

    def test_loopback_list_still_requires_auth(self, monkeypatch, tmp_path):
        # Only mint is loopback-exempt; list/revoke still need a bearer.
        fp = FileSecretProvider(path=str(tmp_path / "t.json"))
        fp.mint(owner="alice")
        monkeypatch.delenv("PPXAI_API_TOKEN", raising=False)
        monkeypatch.setattr(state, "_secret_provider", ProviderChain([fp]))
        req = self._request(
            method="GET", path="/v1/tokens", client_host="127.0.0.1"
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


class TestLoopbackUIExemption:
    """When auth is enforced (file store), a LOCAL browser carries no bearer,
    so the loopback UI/static/chat surface is exempt — but the v1 agent/token
    API stays protected even from loopback, and remote is never exempt."""

    def _request(self, method="GET", path="/", client_host="127.0.0.1", header=None):
        scope = {
            "type": "http",
            "method": method,
            "headers": ([(b"authorization", header.encode())] if header else []),
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "client": (client_host, 12345),
            "scheme": "http",
            "server": ("127.0.0.1", 54320),
        }
        return Request(scope)

    def _enforced_file_chain(self, monkeypatch, tmp_path):
        fp = FileSecretProvider(path=str(tmp_path / "t.json"))
        fp.mint(owner="alice")                 # active token → auth enforced
        monkeypatch.delenv("PPXAI_API_TOKEN", raising=False)
        monkeypatch.setattr(state, "_secret_provider", ProviderChain([fp]))

    def test_loopback_index_exempt(self, monkeypatch, tmp_path):
        self._enforced_file_chain(monkeypatch, tmp_path)
        assert check_request(self._request(path="/")) is None

    def test_loopback_chat_exempt(self, monkeypatch, tmp_path):
        self._enforced_file_chain(monkeypatch, tmp_path)
        assert check_request(self._request(method="POST", path="/chat")) is None

    def test_loopback_static_and_state_exempt(self, monkeypatch, tmp_path):
        self._enforced_file_chain(monkeypatch, tmp_path)
        assert check_request(self._request(path="/app.js")) is None
        assert check_request(self._request(path="/state")) is None

    def test_loopback_v1_agent_STILL_protected(self, monkeypatch, tmp_path):
        # The sensitive surface is NOT exempt even from loopback.
        self._enforced_file_chain(monkeypatch, tmp_path)
        r = check_request(self._request(path="/v1/agent/runs"))
        assert r is not None and r.status_code == 401

    def test_loopback_v1_tokens_GET_still_protected(self, monkeypatch, tmp_path):
        # GET/DELETE /v1/tokens stay protected on loopback (only POST mint
        # is the separate bootstrap exemption).
        self._enforced_file_chain(monkeypatch, tmp_path)
        r = check_request(self._request(method="GET", path="/v1/tokens"))
        assert r is not None and r.status_code == 401

    def test_remote_ui_NOT_exempt(self, monkeypatch, tmp_path):
        # A non-loopback client must still authenticate, even for the UI.
        self._enforced_file_chain(monkeypatch, tmp_path)
        r = check_request(self._request(path="/", client_host="10.0.0.9"))
        assert r is not None and r.status_code == 401

    def test_loopback_v1_agent_with_valid_token_ok(self, monkeypatch, tmp_path):
        # Sanity: the protected v1 path still works WITH a valid token locally.
        fp = FileSecretProvider(path=str(tmp_path / "t.json"))
        material, _ = fp.mint(owner="alice")
        monkeypatch.delenv("PPXAI_API_TOKEN", raising=False)
        monkeypatch.setattr(state, "_secret_provider", ProviderChain([fp]))
        assert check_request(
            self._request(path="/v1/agent/runs", header=f"Bearer {material}")
        ) is None

    # ---- /v1/agent/run carve-out (tool-free oneshot tier) -----------------
    # POST /v1/agent/run is behaviorally identical to /v1/oneshot (no tools,
    # no egress) and is the web client's /agentrun target, so it is exempt on
    # loopback — but ONLY that exact path. Everything else under /v1/agent
    # (launch-with-tools, run records, monitor channels) stays protected.

    def test_loopback_v1_agent_RUN_exempt(self, monkeypatch, tmp_path):
        self._enforced_file_chain(monkeypatch, tmp_path)
        assert check_request(
            self._request(method="POST", path="/v1/agent/run")
        ) is None

    def test_loopback_v1_agent_run_trailing_slash_exempt(self, monkeypatch, tmp_path):
        # rstrip-normalized so /v1/agent/run/ matches the carve-out too.
        self._enforced_file_chain(monkeypatch, tmp_path)
        assert check_request(
            self._request(method="POST", path="/v1/agent/run/")
        ) is None

    def test_loopback_v1_agent_TASK_still_protected(self, monkeypatch, tmp_path):
        # The tool-capable tier is NEVER exempt — even on loopback.
        self._enforced_file_chain(monkeypatch, tmp_path)
        r = check_request(self._request(method="POST", path="/v1/agent/task"))
        assert r is not None and r.status_code == 401

    def test_loopback_v1_agent_runs_still_protected(self, monkeypatch, tmp_path):
        # The carve-out is EXACT-path: /v1/agent/runs must NOT be exempted by a
        # loose prefix match against /v1/agent/run.
        self._enforced_file_chain(monkeypatch, tmp_path)
        r = check_request(self._request(path="/v1/agent/runs"))
        assert r is not None and r.status_code == 401

    def test_loopback_v1_agent_run_events_still_protected(self, monkeypatch, tmp_path):
        # Monitor channel (transcript + tool output) stays protected — this is
        # the endpoint a "protect only /task" rule would have wrongly leaked.
        self._enforced_file_chain(monkeypatch, tmp_path)
        r = check_request(
            self._request(path="/v1/agent/runs/abc123/events")
        )
        assert r is not None and r.status_code == 401

    def test_loopback_v1_agent_cancel_still_protected(self, monkeypatch, tmp_path):
        self._enforced_file_chain(monkeypatch, tmp_path)
        r = check_request(
            self._request(method="POST", path="/v1/agent/runs/abc123/cancel")
        )
        assert r is not None and r.status_code == 401

    def test_remote_v1_agent_run_NOT_exempt(self, monkeypatch, tmp_path):
        # The carve-out is loopback-only. A remote caller still needs a token
        # even for the tool-free run tier.
        self._enforced_file_chain(monkeypatch, tmp_path)
        r = check_request(
            self._request(method="POST", path="/v1/agent/run",
                          client_host="10.0.0.9")
        )
        assert r is not None and r.status_code == 401

    # ---- scoped read exemption: UNOWNED run meta + events on loopback -----
    # The web /agentrun command tails GET /runs/{id}/events and reads
    # GET /runs/{id}. Those are exempt on loopback ONLY for an UNOWNED run
    # (owner=None) — the kind a token-less local browser creates. Owned runs
    # (every /task run) and unknown runs stay protected.

    def _registry_with_run(self, monkeypatch, run_id, owner):
        class _FakeMeta:
            def __init__(self, owner):
                self.owner = owner

        class _FakeRegistry:
            def __init__(self, runs):
                self._runs = runs

            def get_run(self, rid):
                return self._runs.get(rid)

        reg = _FakeRegistry({run_id: _FakeMeta(owner)} if run_id else {})
        monkeypatch.setattr(state, "_agent_run_registry", reg)

    def test_loopback_unowned_run_meta_exempt(self, monkeypatch, tmp_path):
        self._enforced_file_chain(monkeypatch, tmp_path)
        self._registry_with_run(monkeypatch, "run_abc", owner=None)
        assert check_request(
            self._request(path="/v1/agent/runs/run_abc")
        ) is None

    def test_loopback_unowned_run_events_exempt(self, monkeypatch, tmp_path):
        self._enforced_file_chain(monkeypatch, tmp_path)
        self._registry_with_run(monkeypatch, "run_abc", owner=None)
        assert check_request(
            self._request(path="/v1/agent/runs/run_abc/events")
        ) is None

    def test_loopback_OWNED_run_meta_still_protected(self, monkeypatch, tmp_path):
        # A run created WITH a token (owned) is NOT exempt — its transcript
        # stays bearer-gated even from loopback. This is the /task case.
        self._enforced_file_chain(monkeypatch, tmp_path)
        self._registry_with_run(monkeypatch, "run_owned", owner="alice")
        r = check_request(self._request(path="/v1/agent/runs/run_owned"))
        assert r is not None and r.status_code == 401

    def test_loopback_OWNED_run_events_still_protected(self, monkeypatch, tmp_path):
        self._enforced_file_chain(monkeypatch, tmp_path)
        self._registry_with_run(monkeypatch, "run_owned", owner="alice")
        r = check_request(
            self._request(path="/v1/agent/runs/run_owned/events")
        )
        assert r is not None and r.status_code == 401

    def test_loopback_unknown_run_read_protected(self, monkeypatch, tmp_path):
        # Nonexistent run → fail-closed (401), not exempt.
        self._enforced_file_chain(monkeypatch, tmp_path)
        self._registry_with_run(monkeypatch, None, owner=None)
        r = check_request(self._request(path="/v1/agent/runs/ghost"))
        assert r is not None and r.status_code == 401

    def test_loopback_unowned_run_cancel_still_protected(self, monkeypatch, tmp_path):
        # cancel is a POST and a mutation — never exempt, even for unowned.
        self._enforced_file_chain(monkeypatch, tmp_path)
        self._registry_with_run(monkeypatch, "run_abc", owner=None)
        r = check_request(
            self._request(method="POST", path="/v1/agent/runs/run_abc/cancel")
        )
        assert r is not None and r.status_code == 401

    def test_remote_unowned_run_read_NOT_exempt(self, monkeypatch, tmp_path):
        # Read exemption is loopback-only.
        self._enforced_file_chain(monkeypatch, tmp_path)
        self._registry_with_run(monkeypatch, "run_abc", owner=None)
        r = check_request(
            self._request(path="/v1/agent/runs/run_abc", client_host="10.0.0.9")
        )
        assert r is not None and r.status_code == 401


class TestLoopbackHonorsProvidedBearer:
    """A loopback caller that DOES present a bearer must have it validated, not
    silently bypassed by the loopback exemption — else the run is stamped
    owner=None instead of the token's owner, losing isolation (Gemini #4)."""

    def _request(self, method="POST", path="/v1/agent/run",
                 client_host="127.0.0.1", header=None):
        scope = {
            "type": "http",
            "method": method,
            "headers": ([(b"authorization", header.encode())] if header else []),
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "client": (client_host, 12345),
            "scheme": "http",
            "server": ("127.0.0.1", 54320),
        }
        return Request(scope)

    def _file_chain(self, monkeypatch, tmp_path):
        fp = FileSecretProvider(path=str(tmp_path / "t.json"))
        material, _ = fp.mint(owner="alice")
        monkeypatch.delenv("PPXAI_API_TOKEN", raising=False)
        monkeypatch.setattr(state, "_secret_provider", ProviderChain([fp]))
        return material

    def test_valid_bearer_on_exempt_path_sets_principal(self, monkeypatch, tmp_path):
        # /v1/agent/run is loopback-exempt, but a presented valid token must
        # still be resolved so the principal (owner) is stamped on the run.
        material = self._file_chain(monkeypatch, tmp_path)
        req = self._request(header=f"Bearer {material}")
        assert check_request(req) is None
        assert getattr(req.state, "principal", None) is not None
        assert req.state.principal.owner == "alice"

    def test_no_bearer_on_exempt_path_still_exempt(self, monkeypatch, tmp_path):
        # The whole point of the carve-out: no token → still allowed (no
        # principal). Owner is None (token-less local client).
        self._file_chain(monkeypatch, tmp_path)
        req = self._request(header=None)
        assert check_request(req) is None
        assert getattr(req.state, "principal", None) is None

    def test_invalid_bearer_on_exempt_path_rejected(self, monkeypatch, tmp_path):
        # A present-but-invalid token must NOT be silently exempted — it falls
        # through to 401, never accepted via the loopback bypass.
        self._file_chain(monkeypatch, tmp_path)
        r = check_request(self._request(header="Bearer not-a-real-token"))
        assert r is not None and r.status_code == 401
