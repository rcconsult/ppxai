"""Tests for the pluggable secret-source framework (v1.19.0, Inc 8a).

Covers the provider abstraction (ADR 0003 §C2): env (read-only), file
(mutable, hash-at-rest), the chain composition, and config-driven
construction with backward compatibility.
"""

from __future__ import annotations

import json

import pytest

from ppxai.server.secrets import (
    CAP_LIST,
    CAP_MINT,
    CAP_RESOLVE,
    CAP_REVOKE,
    CapabilityError,
    EnvSecretProvider,
    FileSecretProvider,
    ProviderChain,
    build_chain_from_config,
)


# --------------------------------------------------------------------------
# EnvSecretProvider — read-only, wraps PPXAI_API_TOKEN
# --------------------------------------------------------------------------
class TestEnvProvider:
    def test_resolve_matches_configured_token(self, monkeypatch):
        monkeypatch.setenv("PPXAI_API_TOKEN", "s3cret")
        p = EnvSecretProvider()
        rec = p.resolve("s3cret")
        assert rec is not None
        assert rec.owner == "env"
        assert rec.secret_ref.kind == "env"

    def test_resolve_rejects_wrong_token(self, monkeypatch):
        monkeypatch.setenv("PPXAI_API_TOKEN", "s3cret")
        assert EnvSecretProvider().resolve("nope") is None

    def test_unset_var_resolves_nothing(self, monkeypatch):
        monkeypatch.delenv("PPXAI_API_TOKEN", raising=False)
        p = EnvSecretProvider()
        assert p.resolve("anything") is None
        assert p.is_active() is False

    def test_empty_var_is_disabled(self, monkeypatch):
        monkeypatch.setenv("PPXAI_API_TOKEN", "   ")
        assert EnvSecretProvider().is_active() is False

    def test_capabilities_resolve_only(self):
        assert EnvSecretProvider().capabilities() == frozenset({CAP_RESOLVE})

    def test_mint_revoke_list_raise(self, monkeypatch):
        p = EnvSecretProvider()
        with pytest.raises(CapabilityError):
            p.mint(owner="x")
        with pytest.raises(CapabilityError):
            p.revoke("id")
        with pytest.raises(CapabilityError):
            p.list()


# --------------------------------------------------------------------------
# FileSecretProvider — mutable, hash-at-rest
# --------------------------------------------------------------------------
class TestFileProvider:
    def _provider(self, tmp_path):
        return FileSecretProvider(path=str(tmp_path / "tokens.json"))

    def test_mint_then_resolve(self, tmp_path):
        p = self._provider(tmp_path)
        material, rec = p.mint(owner="alice", roles=("oncall",))
        assert rec.owner == "alice"
        assert rec.roles == ("oncall",)
        resolved = p.resolve(material)
        assert resolved is not None
        assert resolved.token_id == rec.token_id

    def test_resolve_rejects_unknown(self, tmp_path):
        p = self._provider(tmp_path)
        p.mint(owner="alice")
        assert p.resolve("not-a-real-token") is None

    def test_material_never_on_disk(self, tmp_path):
        path = tmp_path / "tokens.json"
        p = FileSecretProvider(path=str(path))
        material, _ = p.mint(owner="alice")
        raw = path.read_text(encoding="utf-8")
        assert material not in raw
        on_disk = json.loads(raw)
        assert on_disk["tokens"][0]["hash"].startswith("sha256:")

    def test_revoke_blocks_resolve(self, tmp_path):
        p = self._provider(tmp_path)
        material, rec = p.mint(owner="alice")
        assert p.revoke(rec.token_id) is True
        assert p.resolve(material) is None

    def test_revoke_unknown_returns_false(self, tmp_path):
        p = self._provider(tmp_path)
        assert p.revoke("missing") is False

    def test_list_returns_metadata_only(self, tmp_path):
        p = self._provider(tmp_path)
        p.mint(owner="alice")
        p.mint(owner="bob")
        records = p.list()
        assert {r.owner for r in records} == {"alice", "bob"}

    def test_ttl_expiry(self, tmp_path):
        p = self._provider(tmp_path)
        material, rec = p.mint(owner="alice", ttl_s=-1)  # already expired
        assert rec.expires_at is not None
        assert p.resolve(material) is None

    def test_active_ttl_resolves(self, tmp_path):
        p = self._provider(tmp_path)
        material, _ = p.mint(owner="alice", ttl_s=3600)
        assert p.resolve(material) is not None

    def test_mint_requires_owner(self, tmp_path):
        p = self._provider(tmp_path)
        with pytest.raises(ValueError):
            p.mint(owner="")

    def test_capabilities_full(self, tmp_path):
        caps = self._provider(tmp_path).capabilities()
        assert {CAP_RESOLVE, CAP_LIST, CAP_MINT, CAP_REVOKE} <= caps

    def test_unreadable_store_fails_closed(self, tmp_path):
        path = tmp_path / "tokens.json"
        path.write_text("{ not valid json", encoding="utf-8")
        p = FileSecretProvider(path=str(path))
        # resolve must not raise on a corrupt store — it authenticates nobody.
        assert p.resolve("anything") is None

    def test_persists_across_instances(self, tmp_path):
        path = str(tmp_path / "tokens.json")
        material, _ = FileSecretProvider(path=path).mint(owner="alice")
        # A fresh instance reading the same file resolves the token.
        assert FileSecretProvider(path=path).resolve(material) is not None


# --------------------------------------------------------------------------
# ProviderChain — composition
# --------------------------------------------------------------------------
class TestChain:
    def test_resolve_first_match_wins(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PPXAI_API_TOKEN", "envtok")
        fp = FileSecretProvider(path=str(tmp_path / "t.json"))
        fmat, _ = fp.mint(owner="alice")
        chain = ProviderChain([EnvSecretProvider(), fp])
        assert chain.resolve("envtok").owner == "env"
        assert chain.resolve(fmat).owner == "alice"

    def test_mint_routes_to_first_capable(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PPXAI_API_TOKEN", "envtok")
        fp = FileSecretProvider(path=str(tmp_path / "t.json"))
        chain = ProviderChain([EnvSecretProvider(), fp])
        material, rec = chain.mint(owner="bob")
        assert rec.owner == "bob"
        assert chain.resolve(material) is not None

    def test_mint_without_capable_provider_raises(self, monkeypatch):
        monkeypatch.setenv("PPXAI_API_TOKEN", "envtok")
        chain = ProviderChain([EnvSecretProvider()])
        with pytest.raises(CapabilityError):
            chain.mint(owner="x")

    def test_list_concatenates_capable_providers(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PPXAI_API_TOKEN", "envtok")
        fp = FileSecretProvider(path=str(tmp_path / "t.json"))
        fp.mint(owner="alice")
        chain = ProviderChain([EnvSecretProvider(), fp])
        # env can't list; chain returns only the file records.
        owners = {r.owner for r in chain.list()}
        assert owners == {"alice"}

    def test_capabilities_is_union(self, tmp_path):
        fp = FileSecretProvider(path=str(tmp_path / "t.json"))
        chain = ProviderChain([EnvSecretProvider(), fp])
        assert CAP_MINT in chain.capabilities()
        assert CAP_RESOLVE in chain.capabilities()

    def test_empty_chain(self):
        chain = ProviderChain([])
        assert chain.is_empty()
        assert chain.resolve("anything") is None


# --------------------------------------------------------------------------
# build_chain_from_config — config-driven + backward compat
# --------------------------------------------------------------------------
class TestBuildFromConfig:
    def test_no_secrets_config_defaults_to_env(self):
        chain = build_chain_from_config({})
        assert len(chain.providers) == 1
        assert isinstance(chain.providers[0], EnvSecretProvider)

    def test_empty_providers_defaults_to_env(self):
        chain = build_chain_from_config({"secrets": {"providers": []}})
        assert isinstance(chain.providers[0], EnvSecretProvider)

    def test_file_provider_from_config(self, tmp_path):
        cfg = {
            "secrets": {
                "providers": [
                    {"type": "file", "path": str(tmp_path / "t.json")}
                ]
            }
        }
        chain = build_chain_from_config(cfg)
        assert isinstance(chain.providers[0], FileSecretProvider)

    def test_mixed_providers_order_preserved(self, tmp_path):
        cfg = {
            "secrets": {
                "providers": [
                    {"type": "file", "path": str(tmp_path / "t.json")},
                    {"type": "env", "var": "PPXAI_API_TOKEN"},
                ]
            }
        }
        chain = build_chain_from_config(cfg)
        assert isinstance(chain.providers[0], FileSecretProvider)
        assert isinstance(chain.providers[1], EnvSecretProvider)

    def test_unknown_provider_type_skipped(self, tmp_path):
        cfg = {
            "secrets": {
                "providers": [
                    {"type": "vault", "addr": "https://vault"},  # not yet impl
                    {"type": "file", "path": str(tmp_path / "t.json")},
                ]
            }
        }
        chain = build_chain_from_config(cfg)
        # Unknown skipped; file kept.
        assert len(chain.providers) == 1
        assert isinstance(chain.providers[0], FileSecretProvider)

    def test_all_unknown_falls_back_to_env(self):
        cfg = {"secrets": {"providers": [{"type": "vault"}]}}
        chain = build_chain_from_config(cfg)
        assert isinstance(chain.providers[0], EnvSecretProvider)
