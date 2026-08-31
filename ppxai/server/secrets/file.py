"""File-backed secret provider (v1.19.0, Inc 8a) — the single-machine MVP.

Stores token **hashes** (never raw material) in a JSON file, typically
``~/.ppxai/tokens.json``. ``mint`` returns the raw material EXACTLY ONCE
(GitHub-PAT style); thereafter only the hash exists, so a stolen
``tokens.json`` cannot be replayed.

Fully mutable: advertises resolve/list/mint/revoke. File is created
``0600`` (owner read/write only); on Windows the same is approximated
via an owner-only ACL (best-effort — a failure to tighten the ACL is
logged, not fatal).

On-disk shape::

    {
      "version": 1,
      "tokens": [
        {"token_id": "...", "owner": "...", "hash": "sha256:...",
         "roles": ["..."], "expires_at": null, "revoked": false,
         "created_at": 1234567890.0}
      ]
    }

Hashing: ``sha256(salt || material)`` with a per-record random salt,
stored as ``sha256:<salt_hex>:<digest_hex>``. SHA-256 (not a slow KDF) is
adequate here because the material is a 256-bit random token, not a
human-chosen password — there is no dictionary to attack.
"""

from __future__ import annotations

import builtins
import hashlib
import hmac
import json
import os
import secrets as _secrets
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from ...common.logger import get_logger
from .base import (
    ALL_CAPABILITIES,
    SecretProvider,
    SecretRef,
    TokenRecord,
)

logger = get_logger(__name__)

_SCHEMA_VERSION = 1
_TOKEN_BYTES = 32  # 256-bit material
_SALT_BYTES = 16


def _hash_material(material: str, salt: bytes) -> str:
    digest = hashlib.sha256(salt + material.encode("utf-8")).hexdigest()
    return f"sha256:{salt.hex()}:{digest}"


def _verify_material(material: str, stored: str) -> bool:
    try:
        algo, salt_hex, digest_hex = stored.split(":", 2)
    except ValueError:
        return False
    if algo != "sha256":
        return False
    try:
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    candidate = hashlib.sha256(salt + material.encode("utf-8")).hexdigest()
    return hmac.compare_digest(candidate, digest_hex)


def _tighten_perms(path: Path) -> None:
    """Make the token file owner-only. Best-effort; never fatal."""
    try:
        if sys.platform == "win32":
            # Owner-only ACL via icacls: remove inheritance, grant the
            # current user full control, strip everyone else.
            import getpass
            import subprocess

            user = os.environ.get("USERNAME") or getpass.getuser()
            subprocess.run(
                ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
                check=False,
                capture_output=True,
            )
        else:
            os.chmod(path, 0o600)
    except Exception as exc:  # pragma: no cover - platform-dependent
        logger.warning(f"could not tighten perms on {path}: {exc}")


class FileSecretProvider:
    """Mutable, hash-at-rest token store backed by a JSON file."""

    def __init__(self, path: str) -> None:
        self.path = Path(path).expanduser()
        self.name = f"file:{self.path}"

    # -- capabilities -------------------------------------------------
    def capabilities(self) -> frozenset:
        return ALL_CAPABILITIES

    # -- persistence --------------------------------------------------
    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": _SCHEMA_VERSION, "tokens": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.error(f"token store {self.path} unreadable: {exc}")
            # Fail closed: an unreadable store authenticates nobody, but we
            # must not silently wipe it, so raise rather than return empty.
            raise
        if not isinstance(data, dict) or "tokens" not in data:
            raise ValueError(f"token store {self.path} has unexpected shape")
        return data

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a UNIQUE temp file (mkstemp) then replace, so a crash can't
        # truncate the store AND two concurrent writers never race on the same
        # temp path (harmless today — loopback mint/revoke serialize on one
        # event loop — but correct under a future multi-worker deployment;
        # Gemini review #4, defense-in-depth). Tighten perms on the temp file
        # BEFORE it holds secrets' hashes and before the rename exposes it.
        fd, tmp_path = tempfile.mkstemp(
            dir=self.path.parent, prefix="tokens-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            _tighten_perms(Path(tmp_path))
            os.replace(tmp_path, self.path)
            _tighten_perms(self.path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    @staticmethod
    def _record_from_row(row: dict[str, Any]) -> TokenRecord:
        return TokenRecord(
            token_id=row["token_id"],
            owner=row["owner"],
            secret_ref=SecretRef(kind="file", locator=row["token_id"]),
            roles=tuple(row.get("roles", ())),
            expires_at=row.get("expires_at"),
            revoked=bool(row.get("revoked", False)),
        )

    # -- resolve ------------------------------------------------------
    def resolve(self, presented: str) -> TokenRecord | None:
        try:
            data = self._load()
        except Exception:
            return None  # backend fault → authenticate nobody (fail closed)
        now = time.time()
        for row in data["tokens"]:
            if not _verify_material(presented, row.get("hash", "")):
                continue
            record = self._record_from_row(row)
            if not record.is_active(now):
                return None
            return record
        return None

    # -- list ---------------------------------------------------------
    def list(self) -> builtins.list[TokenRecord]:
        data = self._load()
        return [self._record_from_row(row) for row in data["tokens"]]

    # -- mint ---------------------------------------------------------
    def mint(
        self,
        owner: str,
        roles: tuple[str, ...] = (),
        ttl_s: float | None = None,
    ) -> tuple[str, TokenRecord]:
        if not owner:
            raise ValueError("owner is required to mint a token")
        data = self._load()
        material = _secrets.token_urlsafe(_TOKEN_BYTES)
        token_id = _secrets.token_hex(8)
        salt = _secrets.token_bytes(_SALT_BYTES)
        now = time.time()
        expires_at = (now + ttl_s) if ttl_s else None
        row = {
            "token_id": token_id,
            "owner": owner,
            "hash": _hash_material(material, salt),
            "roles": list(roles),
            "expires_at": expires_at,
            "revoked": False,
            "created_at": now,
        }
        data["tokens"].append(row)
        self._save(data)
        return material, self._record_from_row(row)

    # -- revoke -------------------------------------------------------
    def revoke(self, token_id: str) -> bool:
        data = self._load()
        changed = False
        for row in data["tokens"]:
            if row["token_id"] == token_id and not row.get("revoked"):
                row["revoked"] = True
                changed = True
        if changed:
            self._save(data)
        return changed


# Structural conformance check.
_: SecretProvider = FileSecretProvider(path="~/.ppxai/tokens.json")
