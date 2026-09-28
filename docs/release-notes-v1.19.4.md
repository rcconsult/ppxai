# Release Notes — v1.19.4

> **Scope:** A security patch to v1.19.3, one fix. **Upgrade if you run
> `ppxai-server` or `ppxai-desktop` on a machine where you also browse the
> web, or if you run the k8s coder deployment.** No config-shape changes,
> no command changes. The v1 API gateway (`POST /v1/oneshot`) and the
> `/v1/agent/*` surface are **byte-identical to v1.19.3**; ppxai-sre and any
> other consumer are unaffected.

## Branch

`fix/v1.19.4` (from master @ v1.19.3).

## Security

### A web page could open a shell through the terminal websocket

**What was wrong.** The web UI's terminal is a websocket at `/ws/terminal`
that runs a PTY shell on the server's machine. The server's three
protections are HTTP middleware:

- the Host check that stops DNS rebinding;
- the bearer-token gate (`PPXAI_API_TOKEN`);
- CORS.

Starlette never passes a websocket through HTTP middleware, and browsers do
not apply CORS to websockets. So while `ppxai-server` or `ppxai-desktop`
was running, **any web page the user visited could open
`ws://127.0.0.1:<port>/ws/terminal` and run commands as the user**. Setting
`PPXAI_API_TOKEN` did not help.

**Who was exposed.**

- **Desktop and local web UI users**, whenever the server was running. On
  Windows the terminal reports "requires a Unix host" and runs no shell, but
  the handshake was still accepted unchecked.
- **k8s coder users**, to a lesser degree. The session cookie is
  `SameSite=Lax`, so other sites could not ride it. A page on the same parent
  domain, such as another app under the same `*.example.com`, could.
- **Remote servers announced for ADR 0013** (`ppxai-server --uds --announce`)
  were not reachable from a browser: they listen only on a 0600 unix socket.

**The fix.** A websocket handshake is now refused, and the client sees HTTP
403, unless all three hold:

1. its `Host` passes the same allowlist as HTTP requests;
2. its `Origin`, when it sends one, is allowed: listed in
   `PPXAI_ALLOWED_ORIGINS`, a loopback origin, or the server's own origin
   (the same host and port as a `Host` that passed step 1). A client that
   sends no `Origin` is not a browser and is judged by steps 1 and 3 alone;
3. the bearer-token gate passes, exactly as it would for a GET of the same
   path. The local UI stays exempt on loopback, as it is for HTTP.

The guard wraps the whole app, so a websocket route added later is covered
without further work.

**What keeps working** (each case is pinned by `tests/test_websocket_guard.py`):

| Client | Result |
|---|---|
| The desktop/web UI's own terminal (`http://127.0.0.1:<port>`, `http://localhost:<port>`) | opens, with or without a token |
| A coder pod (wide bind, `PPXAI_TRUSTED_HOSTS` and `PPXAI_ALLOWED_ORIGINS` as the session-manager sets them) | its UI opens its terminal; a sibling-domain page is refused |
| A gateway bound wide without either variable | its same-origin UI opens its terminal; other origins are refused |
| A non-browser client with no `Origin` | same as before, subject to Host and token |

## Verification

- `tests/test_websocket_guard.py`: 18 tests. With the guard disabled, the
  9 tests that expect a refusal fail, the attack among them.
- Against a live `ppxai-server` over TCP (uvicorn, not the test client):
  the UI's own origins get a working shell; `http://evil.example` gets
  HTTP 403.
- Full suite on macOS: 6,935 passed, 5 skipped.

## Upgrade

Nothing to change. If a browser client of yours opens the terminal from an
origin other than the server's own, add that origin to
`PPXAI_ALLOWED_ORIGINS`.
