"""The single resolver for outbound TLS verification.

Every outbound HTTPS client in ppxai — provider SDK clients and the
built-in web tools alike — must obtain its verification setting from
`resolve_tls_verify()` here. Before this module the same two env vars
were re-read at six independent sites, and they had already drifted:

- `tools/builtin/web.py` guarded `SSL_CERT_FILE` with `os.path.exists()`;
  the provider sites did not, so a stale path silently became a hard
  connection failure instead of falling back.
- `tools/builtin/web_premium.py` honoured `SSL_VERIFY` but ignored
  `SSL_CERT_FILE` entirely, so a custom-CA install had verification
  quietly enforced against the system store on that one path.

That divergence is the reason this is a resolver and not a helper each
caller may reimplement: the *differences* were the defects.

Precedence (highest first)::

    SSL_VERIFY=false        env    → no verification at all
    SSL_CERT_FILE=<path>    env    → verify against that CA bundle
    network.ssl.verify      json   → false = no verification
    network.ssl.cert_file   json   → verify against that CA bundle
    (nothing)                      → verify against the system store

Env beats JSON because `.env` is the per-machine/secret layer in this
project's hybrid-config split (see CLAUDE.md) and is what CI and
container deployments set; `ppxai-config.json` is the committed,
shareable layer.

A configured CA bundle is **added to** the system trust store, never
substituted for it, so a laptop that roams between a TLS-inspecting
corporate network and a direct connection needs no config change: the
corporate CA validates the inspected chain at the office, the system
roots validate real certificates everywhere else. This is why callers
must use `tls_verify()` / `tls_ssl_context()` rather than passing a
bundle path to httpx themselves — both `httpx(verify="<path>")` and
`ssl.create_default_context(cafile=...)` REPLACE the default roots.

`verify=False` disables certificate checking for every request the
client makes. With an additive CA bundle it should rarely be needed even
behind TLS inspection; it is reported by `describe_tls()` so the
condition is visible rather than silent.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Union

from .store import get_config

#: The resolved policy as stored on `TLSSetting`: False (off), a CA bundle
#: path (str), or True (system store). NOTE this is the *decision*, not
#: what to hand httpx — use `tls_verify()`, which converts a bundle path
#: into a context so the corporate CA ADDS to the system roots instead of
#: replacing them.
VerifyValue = Union[bool, str]


@dataclass(frozen=True)
class TLSSetting:
    """A resolved TLS decision plus why it was made.

    `verify` is the resolved *policy* — True, False, or a CA bundle path.
    Do not pass it to httpx directly; call `tls_verify()`, which turns a
    bundle path into a context that trusts the corporate CA **and** the
    system roots. `source` and `reason` exist so `/doctor` and the
    startup warning can explain the decision without re-deriving it —
    the re-derivation is what drifted last time.
    """

    verify: VerifyValue
    source: str  # "env" | "config" | "default"
    reason: str

    @property
    def is_insecure(self) -> bool:
        """True when certificates are not checked at all."""
        return self.verify is False

    @property
    def cert_file(self) -> Optional[str]:
        """The custom CA bundle in use, if any."""
        return self.verify if isinstance(self.verify, str) else None


def _ssl_config_block() -> Dict[str, Any]:
    """`network.ssl` from ppxai-config.json (absent/unreadable → {})."""
    try:
        cfg = get_config() or {}
    except Exception:  # noqa: BLE001 — unreadable config must not break TLS
        return {}
    network = cfg.get("network", {}) or {}
    if not isinstance(network, dict):
        return {}
    ssl_block = network.get("ssl", {}) or {}
    return ssl_block if isinstance(ssl_block, dict) else {}


def _is_false(raw: Any) -> bool:
    """Whether a config/env value states verification-off.

    Accepts the JSON boolean `false` and the string spellings an env var
    can carry. Anything else (including a bare `"true"`) is not an
    opt-out — an unrecognised value must never silently disable TLS.
    """
    if raw is False:
        return True
    return str(raw).strip().lower() in ("false", "0", "no", "off")


def resolve_tls_verify() -> TLSSetting:
    """Resolve the outbound TLS setting from env, then config, then default."""
    # 1. SSL_VERIFY=false (env) — the explicit, highest-priority opt-out.
    env_verify = os.getenv("SSL_VERIFY")
    if env_verify is not None and _is_false(env_verify):
        return TLSSetting(False, "env", "SSL_VERIFY=false")

    # 2. SSL_CERT_FILE (env) — custom CA. A configured-but-missing bundle
    #    falls through rather than being handed to httpx, which would fail
    #    every request with an opaque error. web.py already did this; the
    #    provider sites did not.
    env_cert = (os.getenv("SSL_CERT_FILE") or "").strip().strip('"').strip("'")
    if env_cert:
        if Path(env_cert).is_file():
            return TLSSetting(env_cert, "env", f"SSL_CERT_FILE={env_cert}")
        return TLSSetting(
            True,
            "default",
            f"SSL_CERT_FILE={env_cert} does not exist; using the system store",
        )

    block = _ssl_config_block()

    # 3. network.ssl.verify (json)
    if "verify" in block and _is_false(block.get("verify")):
        return TLSSetting(False, "config", "network.ssl.verify=false")

    # 4. network.ssl.cert_file (json)
    cfg_cert = str(block.get("cert_file") or "").strip()
    if cfg_cert:
        if Path(cfg_cert).is_file():
            return TLSSetting(cfg_cert, "config", f"network.ssl.cert_file={cfg_cert}")
        return TLSSetting(
            True,
            "default",
            f"network.ssl.cert_file={cfg_cert} does not exist; using the system store",
        )

    # 5. System trust store.
    return TLSSetting(True, "default", "system certificate store")


def tls_verify() -> VerifyValue:
    """What to pass as `verify=` to an httpx client.

    Returns `False` when verification is off, otherwise an
    `ssl.SSLContext` — **not** a bare path. httpx treats
    `verify="<path>"` the same way `create_default_context(cafile=...)`
    does: the bundle REPLACES the system roots, so a corporate CA alone
    breaks every public endpoint off the inspecting network. Returning
    the context keeps both trust anchors, so one config roams. See
    `tls_ssl_context`.

    Always a context when verifying, even with no custom CA configured:
    httpx's own default trusts **certifi only**, while
    `ssl.create_default_context()` also loads the OS trust store. On a
    machine whose corporate CA was installed system-wide (the normal IT
    route on Windows/macOS), certifi does not have it and the OS store
    does — so returning `True` here would leave the httpx-based clients
    failing under TLS inspection while the `ssl`-based web tools worked.
    Verified on this host: the OS store carries the inspection CAs,
    certifi does not.
    """
    setting = resolve_tls_verify()
    if setting.is_insecure:
        return False
    return tls_ssl_context()


def tls_ssl_context():
    """The resolved decision as an `ssl.SSLContext`.

    A custom CA is **added to** the system trust store, not substituted
    for it. `ssl.create_default_context(cafile=...)` *replaces* the
    default roots, which breaks every public endpoint the moment the
    machine leaves the inspecting network — a laptop that roams between
    a TLS-inspecting corporate network and a direct connection would
    need its config edited on every move. Loading both means one static
    configuration works on both: the corporate CA validates the
    inspected chain at the office, the system roots validate real
    certificates everywhere else.

    Verified on a direct connection: cafile-only fails
    `CERTIFICATE_VERIFY_FAILED` against api.perplexity.ai, while
    default-plus-corporate-CA succeeds.
    """
    import ssl

    setting = resolve_tls_verify()
    ctx = ssl.create_default_context()
    if setting.is_insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    if setting.cert_file:
        ctx.load_verify_locations(cafile=setting.cert_file)
    return ctx


def describe_tls() -> str:
    """One line about the effective TLS posture, for /doctor and startup."""
    s = resolve_tls_verify()
    if s.is_insecure:
        return (
            f"TLS certificate verification is DISABLED ({s.reason}). "
            "Connections can be intercepted; use network.ssl.cert_file "
            "with your proxy's CA instead where possible."
        )
    if s.cert_file:
        return f"TLS verified against a custom CA bundle ({s.reason})."
    return f"TLS verified against the {s.reason}."
