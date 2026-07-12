# A stale ppxai-server on port 54320 silently invalidates acceptance runs

**TL;DR:** ppxai-server binds a **fixed** port (54320). If a stale
server already holds it, a freshly spawned binary dies on `address
already in use` and every request hits the OLD process — so a
post-build acceptance run "passes" against exactly the build you were
trying to replace.

**Verify with:** `grep -rn "54320" ppxai/server/ scripts/gateway-smoke.py`
(the port is a hardcoded default, not auto-negotiated) — and reproduce:
start one server, spawn a second; the second logs `[Errno 48] address
already in use` and exits while the first keeps answering.

## Why this trips people up

The obvious mental model is "I spawned the new binary, so I'm testing
the new binary." But ppxai-server does not fail loud to the *caller*
when the bind fails — the spawned process just exits, and any client
request (curl, the gateway-smoke script, a browser) transparently
connects to whatever is still listening. Nothing in the request path
signals "you're talking to a different process than you launched."

Two live incidents, same root cause:
- **2026-07-12 build-install:** a new build's PPTX preview returned
  `HTTP 500 "Error -3 while decompressing data: incorrect header
  check"`. Looked like a `[data]`-extras / rendering regression in the
  fresh binary. It was a **stale server** on 54320 — the freshly
  installed binary never bound. After `pkill -9 -f ppxai-server` and
  freeing the port, the same test passed `200 image/png`.
- The failure mode is worse than a crash: it can also produce a
  **false PASS**. If the stale server happens to be a *working* older
  build, acceptance goes green and you ship believing the new binary
  was exercised when it never ran.

## What's actually true

The port is fixed, so "is the port free?" is a precondition for any
spawn-and-test flow, not an afterthought. Two mitigations are in the
repo:

1. **`scripts/gateway-smoke.py` refuses to spawn over a held port.**
   `port_in_use("127.0.0.1", port)` is checked before `Popen`; if the
   port is occupied the script exits 2 with a message pointing at
   `pkill -f ppxai-server` or `--base-url` (to deliberately target an
   already-running server). It never silently tests the wrong process.

2. **The build-install skill's step-8 acceptance** (office-preview +
   gateway-smoke) inherits that guard for the HTTP checks. The
   office-preview curl block does NOT yet self-guard — when running it
   by hand, `pkill -f ppxai-server` and confirm 54320 is free first,
   or the 500 you debug may be a ghost.

Rule of thumb: **any acceptance step that spawns ppxai-server must
first prove 54320 is free, or target a known server explicitly.** A
green (or red) result against an unverified port is evidence about
*some* process, not necessarily the one you built.

## Related

- `scripts/gateway-smoke.py` — `port_in_use()` guard + `--base-url`
  escape hatch
- `.claude/skills/build-install/SKILL.md` — step 8 acceptance
- [config-source-resolution.md](config-source-resolution.md) — a
  sibling "you're not testing what you think you're testing" hazard
  (wrong config source rather than wrong process)
