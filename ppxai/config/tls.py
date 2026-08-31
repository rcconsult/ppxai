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
import ssl
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Union

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
    def cert_file(self) -> str | None:
        """The custom CA bundle in use, if any."""
        return self.verify if isinstance(self.verify, str) else None


def _ssl_config_block() -> dict[str, Any]:
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


def _is_true(raw: Any) -> bool:
    """Whether an env value explicitly states verification-on.

    `SSL_VERIFY=true` must be able to override a committed/ConfigMap
    `network.ssl.verify: false` — env is the higher-priority layer in
    both directions, not only for the opt-out spelling. Unrecognised
    values are neither an opt-in nor an opt-out.
    """
    return str(raw).strip().lower() in ("true", "1", "yes", "on")


def resolve_tls_verify() -> TLSSetting:
    """Resolve the outbound TLS setting from env, then config, then default."""
    # 1. SSL_VERIFY (env) — the explicit, highest-priority layer, in BOTH
    #    directions: `false` disables verification outright, and `true`
    #    re-enables it over a config `network.ssl.verify: false` (which a
    #    ConfigMap or committed JSON may carry that the operator cannot
    #    easily edit). Without the `true` half, config `false` silently
    #    won over the layer documented as higher priority — and /doctor
    #    reported the config value, agreeing with the wrong answer.
    env_verify = os.getenv("SSL_VERIFY")
    if env_verify is not None and _is_false(env_verify):
        return TLSSetting(False, "env", "SSL_VERIFY=false")
    env_forces_on = env_verify is not None and _is_true(env_verify)

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

    # 3. network.ssl.verify (json) — unless SSL_VERIFY=true overrode it.
    config_verify_off = "verify" in block and _is_false(block.get("verify"))
    if config_verify_off and not env_forces_on:
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

    # 5. System trust store. When SSL_VERIFY=true overrode a config
    #    opt-out, say so — /doctor must explain the decision, not
    #    contradict the operator's config file.
    if config_verify_off and env_forces_on:
        return TLSSetting(
            True,
            "env",
            "SSL_VERIFY=true overrides network.ssl.verify=false; system certificate store",
        )
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


def _system_roots_context() -> ssl.SSLContext:
    """A base context trusting the SYSTEM roots regardless of SSL_CERT_FILE/DIR.

    OpenSSL itself honours `SSL_CERT_FILE`/`SSL_CERT_DIR` inside
    `set_default_verify_paths()`, substituting the bundle for the system
    roots — the exact replacement this module exists to prevent,
    happening underneath `create_default_context()` on the env path.
    Measured: with SSL_CERT_FILE pointing at a one-CA bundle the
    "default" context held 1 root (vs 124), and the follow-up
    `load_verify_locations` re-loaded the same file as a no-op.
    Neutralise the vars while the base roots load; the caller then
    layers the custom CA on top additively. The brief env mutation is
    bounded by `_build_context`'s cache — this runs once per resolved
    policy, not per request.
    """
    saved: dict[str, str] = {}
    for var in ("SSL_CERT_FILE", "SSL_CERT_DIR"):
        val = os.environ.pop(var, None)
        if val is not None:
            saved[var] = val
    try:
        return ssl.create_default_context()
    finally:
        os.environ.update(saved)


@lru_cache(maxsize=8)
def _build_context(verify: VerifyValue) -> ssl.SSLContext:
    """Build (and memoise) the context for a resolved policy.

    Keyed by the resolved policy — False, a CA bundle path, or True — so
    a config change to a different bundle gets a fresh context while
    steady-state callers share one. Sharing an `SSLContext` across
    connections is the documented pattern; building one per request was
    re-parsing the whole OS trust store (~10 ms) at four per-request
    sites in web.py alone. A changed file at the SAME path is
    deliberately not detected — call `reset_tls_context_cache()`
    (tests, config reload) for that.
    """
    ctx = _system_roots_context()
    if verify is False:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    if isinstance(verify, str):
        ctx.load_verify_locations(cafile=verify)
    return ctx


def reset_tls_context_cache() -> None:
    """Drop memoised contexts (config reload, tests)."""
    _build_context.cache_clear()


def tls_ssl_context() -> ssl.SSLContext:
    """The resolved decision as an `ssl.SSLContext`.

    A custom CA is **added to** the system trust store, not substituted
    for it — on BOTH the config path and the `SSL_CERT_FILE` env path
    (see `_system_roots_context` for why the env path needs help).
    `ssl.create_default_context(cafile=...)` *replaces* the default
    roots, which breaks every public endpoint the moment the machine
    leaves the inspecting network — a laptop that roams between a
    TLS-inspecting corporate network and a direct connection would need
    its config edited on every move. Loading both means one static
    configuration works on both: the corporate CA validates the
    inspected chain at the office, the system roots validate real
    certificates everywhere else.

    Verified on a direct connection: cafile-only fails
    `CERTIFICATE_VERIFY_FAILED` against api.perplexity.ai, while
    default-plus-corporate-CA succeeds.
    """
    setting = resolve_tls_verify()
    return _build_context(setting.verify)


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
