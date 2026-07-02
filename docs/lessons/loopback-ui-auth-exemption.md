# The loopback UI auth exemption trusts ANY local process, not just the operator's browser

**TL;DR:** When bearer auth is enabled (a `file` token store, or
`PPXAI_API_TOKEN` set), `server/auth.py` still lets an **unauthenticated**
loopback request reach the interactive surface — `/chat`, `/files/read`,
`/command/*`, `/config/*` — with **no** `Authorization` header. The gate keys
on **source IP only** (`127.0.0.1`/`::1`/`localhost`), not on process or user
identity. So on a shared / multi-user host, *any* local process (not just the
operator's browser) can read files under the served tree and drive chat
without a credential. This is a **deliberate, documented** design choice for
the single-user desktop UX — **not a bug** — but it is a real trust-boundary
widening vs. master, and it is easy to mistake for an oversight.

**Verify with:**
```bash
# The ONLY prefixes that stay bearer-protected on loopback:
grep -n "_LOOPBACK_PROTECTED_PREFIXES" ppxai/server/auth.py
#   -> ("/v1/agent", "/v1/tokens")   — everything else is exempt on loopback

# The exemption + its IP-only trust basis:
grep -n "_is_loopback\b\|_is_loopback_ui_request\|_LOOPBACK_HOSTS" ppxai/server/auth.py
```
`_is_loopback_ui_request()` returns `True` (auth-exempt) for every loopback
path that is NOT under `/v1/agent` or `/v1/tokens`; `_is_loopback()` checks
only `request.client.host in {"127.0.0.1","::1","localhost"}`.

## Why this is the way it is (and what master did)

- **Intent:** the local desktop / web / VSCode clients talk to ppxai-server on
  loopback and carry **no** bearer. When a `file` token store turns auth on,
  those clients must still work — hence the exemption. The docstrings in
  `auth.py` (`_is_loopback_ui_request`, `check_request`) state this explicitly:
  "a request from 127.0.0.1/::1 is physically on the host."
- **What changed:** on `master`, enabling `PPXAI_API_TOKEN` required a valid
  bearer on **every** non-OPTIONS request, including loopback. v1.19.0 (Inc 8a)
  added the loopback carve-out, so loopback `/chat` + `/files/read` went from
  *bearer-required* to *bearer-exempt*.
- **Still protected on loopback:** `/v1/agent/*` (agent-run monitor channels,
  owner-scoped transcripts, tool output) and `/v1/tokens` (mint/list/revoke).
  Only the tool-free `/v1/agent/run` oneshot tier and reads of **unowned** runs
  are carved back out (see `_LOOPBACK_EXEMPT_AGENT_PATHS`,
  `_is_loopback_unowned_run_read`).

## The trap

A code review (PR #20, v1.19.0) verified this as finding #9 and it was
**deliberately left unchanged** — the fix is a threat-model decision (single-
user desktop = intended; multi-user host = privilege gap), not a code
correctness issue. If you re-scan `auth.py` and flag "loopback bypasses auth
for `/files/read`!", check this lesson first: it is known, documented, and
scoped. Reopen it only with an explicit decision to change the threat model
(e.g. bind the UI surface to a per-session loopback token, or drop the
exemption behind a config flag) — not as a drive-by "bug fix."

## Spoofing hardening — LANDED (v1.19.x)

An earlier version of this lesson claimed "the gate ignores forwarded headers,
which is safer." **That was imprecise** — uvicorn runs with `proxy_headers=True`,
so behind a local reverse proxy it can rewrite `request.client.host` from a
client-supplied `X-Forwarded-For`, making the IP alone spoofable to loopback
(caught in a Gemini/antigravity review). Two independent defenses now close it:

1. **`_is_loopback` rejects forwarded requests** — it requires a loopback peer
   IP AND the **absence** of any forwarding header (`X-Forwarded-For`/`-Host`,
   `X-Real-IP`, `Forwarded`). A genuine local browser connects directly and
   sends none; a proxied request always carries one. (`server/auth.py`)
2. **uvicorn trusts no proxy client-IP by default** — `forwarded_allow_ips=""`
   (from `_forwarded_allow_ips()` in `server/http.py`), so `client.host` is the
   real TCP peer. Operators behind a TRUSTED proxy opt in via
   `PPXAI_FORWARDED_ALLOW_IPS` and own their proxy's XFF sanitization.

Verify: `grep -n "_FORWARDING_HEADERS\|forwarded" ppxai/server/auth.py`;
`grep -n "_forwarded_allow_ips" ppxai/server/http.py`. Tests:
`tests/test_auth_middleware.py::TestLoopbackHardening`.

## Still open — the "any local process" trust

The spoofing is closed, but the deliberate design choice below remains: on a
shared host, ANY local process (not just the operator's browser) still gets the
exemption, since it keys on the peer being loopback, not on process/user
identity. Options if you decide to close THAT too:
- Mint a per-session loopback UI token at startup and have the local clients
  send it (removes the "any local process" hole while keeping desktop UX).
- Gate the exemption behind an explicit `server.auth.trust_loopback_ui` flag,
  default on for desktop builds, off for server/cluster builds.
