"""Per-run authorization e2e (v1.19.0, Inc 8b).

A run is owned by the principal that created it; only that owner may read
its meta / events / cancel it. A foreign token gets 403. When auth is
disabled, no scoping applies (loopback UX).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import ppxai.server.state as state
from ppxai.engine.agent_runs import (
    AgentRunRegistry,
    FilesystemAgentRunStore,
)
from ppxai.server.auth import check_request
from ppxai.server.routes import agent_v1
from ppxai.server.secrets import FileSecretProvider, ProviderChain


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Registry + a file-backed chain with two minted tokens (alice, bob)."""
    reg = AgentRunRegistry(FilesystemAgentRunStore(tmp_path / "runs"))
    monkeypatch.setattr(state, "_agent_run_registry", reg)

    fp = FileSecretProvider(path=str(tmp_path / "tokens.json"))
    alice_tok, _ = fp.mint(owner="alice")
    bob_tok, _ = fp.mint(owner="bob")
    monkeypatch.delenv("PPXAI_API_TOKEN", raising=False)
    chain = ProviderChain([fp])
    monkeypatch.setattr(state, "_secret_provider", chain)

    # Wire the same auth middleware the real app uses, so requests carry a
    # resolved principal on request.state.
    app = FastAPI()

    @app.middleware("http")
    async def _auth(request, call_next):
        rejected = check_request(request)
        if rejected is not None:
            return rejected
        return await call_next(request)

    app.include_router(agent_v1.router)
    client = TestClient(app, raise_server_exceptions=False)
    return client, reg, alice_tok, bob_tok


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


class TestOwnerStamping:
    def test_run_stamped_with_creator_owner(self, env, monkeypatch):
        client, reg, alice, _ = env
        # Stub run creation to avoid a real provider call: hit start_run path
        # by minting a run directly through the registry as the route would.
        meta = reg.start_run(task="x", owner="alice")
        got = client.get(f"/v1/agent/runs/{meta.run_id}", headers=_h(alice))
        assert got.status_code == 200
        assert got.json()["owner"] == "alice"


class TestPerRunAuthz:
    def _make_run(self, reg, owner):
        return reg.start_run(task="secret task", owner=owner)

    def test_owner_can_read_meta(self, env):
        client, reg, alice, _ = env
        m = self._make_run(reg, "alice")
        r = client.get(f"/v1/agent/runs/{m.run_id}", headers=_h(alice))
        assert r.status_code == 200

    def test_foreign_token_403_on_meta(self, env):
        client, reg, alice, bob = env
        m = self._make_run(reg, "alice")
        r = client.get(f"/v1/agent/runs/{m.run_id}", headers=_h(bob))
        assert r.status_code == 403

    def test_foreign_token_403_on_events(self, env):
        client, reg, alice, bob = env
        m = self._make_run(reg, "alice")
        r = client.get(f"/v1/agent/runs/{m.run_id}/events", headers=_h(bob))
        assert r.status_code == 403

    def test_owner_can_read_events(self, env):
        client, reg, alice, _ = env
        m = self._make_run(reg, "alice")
        r = client.get(f"/v1/agent/runs/{m.run_id}/events", headers=_h(alice))
        assert r.status_code == 200

    def test_foreign_token_403_on_cancel(self, env):
        client, reg, alice, bob = env
        m = self._make_run(reg, "alice")
        r = client.post(f"/v1/agent/runs/{m.run_id}/cancel", headers=_h(bob))
        assert r.status_code == 403

    def test_missing_token_401(self, env):
        client, reg, alice, _ = env
        m = self._make_run(reg, "alice")
        r = client.get(f"/v1/agent/runs/{m.run_id}")  # no header
        assert r.status_code == 401

    def test_unknown_run_404_even_for_valid_token(self, env):
        client, reg, alice, _ = env
        r = client.get("/v1/agent/runs/run_doesnotexist", headers=_h(alice))
        assert r.status_code == 404

    def test_unowned_run_readable_by_any_authenticated(self, env):
        # A run created before auth (owner=None) is readable by any valid token.
        client, reg, alice, bob = env
        m = reg.start_run(task="legacy", owner=None)
        assert client.get(f"/v1/agent/runs/{m.run_id}", headers=_h(alice)).status_code == 200
        assert client.get(f"/v1/agent/runs/{m.run_id}", headers=_h(bob)).status_code == 200


class TestRunListScoping:
    def test_list_filtered_to_caller(self, env):
        client, reg, alice, bob = env
        reg.start_run(task="a1", owner="alice")
        reg.start_run(task="b1", owner="bob")
        reg.start_run(task="legacy", owner=None)

        alice_runs = client.get("/v1/agent/runs", headers=_h(alice)).json()["runs"]
        owners = {r["owner"] for r in alice_runs}
        # alice sees her own + unowned, never bob's.
        assert "bob" not in owners
        assert "alice" in owners
        assert None in owners  # the legacy/unowned run


class TestAuthDisabledNoScoping:
    """With auth disabled (env-only, unset), no per-run scoping applies."""

    @pytest.fixture
    def open_env(self, tmp_path, monkeypatch):
        reg = AgentRunRegistry(FilesystemAgentRunStore(tmp_path / "runs"))
        monkeypatch.setattr(state, "_agent_run_registry", reg)
        from ppxai.server.secrets import EnvSecretProvider

        monkeypatch.delenv("PPXAI_API_TOKEN", raising=False)
        monkeypatch.setattr(
            state, "_secret_provider", ProviderChain([EnvSecretProvider()])
        )
        app = FastAPI()

        @app.middleware("http")
        async def _auth(request, call_next):
            rejected = check_request(request)
            if rejected is not None:
                return rejected
            return await call_next(request)

        app.include_router(agent_v1.router)
        return TestClient(app, raise_server_exceptions=False), reg

    def test_any_caller_reads_any_run(self, open_env):
        client, reg = open_env
        m = reg.start_run(task="x", owner=None)
        # No auth header, no token configured => allowed.
        assert client.get(f"/v1/agent/runs/{m.run_id}").status_code == 200
