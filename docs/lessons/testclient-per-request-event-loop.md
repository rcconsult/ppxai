# Default TestClient runs one event loop PER REQUEST — cross-request background tasks die

**TL;DR:** `TestClient(app)` used without a `with` block gives every request
its own portal/event loop, so a background `asyncio.Task` that must stay
alive *across* requests (e.g. a T5 consent park awaiting `POST /respond`)
is orphaned on a dead loop; use `with TestClient(app) as c:` for one
persistent loop.

**Verify with:** `Grep "ctx_client" tests/test_agent_runs.py` (the fixture
docstring documents it), or flip `TestConsentParkE2E` back to the plain
`client` fixture and watch all three tests hang in `waiting`.

## Why this trips people up

Every earlier `/v1/agent/*` e2e test passed with the plain, non-context
`client` fixture — including tests that poll a *background* run to a
terminal status across many GETs (`_poll_terminal`). That reads as proof
that "background tasks survive across TestClient requests." It isn't.
Those runs complete (or are drained) within their launching POST's
portal lifetime because the stubbed runners finish in microseconds; the
subsequent polls only *read* `meta.json` from disk.

The first feature whose background task must still be RUNNING when a
later request arrives — the T5 `waiting` park, which blocks on an
`asyncio.Future` until `/respond` resolves it — exposed the truth:

- the run parks (meta says `waiting`), the POST returns;
- the POST's portal/event loop goes away, taking the parked task's loop
  with it;
- the TTL timer never fires (no loop to run it), `respond_run` from a
  later request sets a result on a future no loop will ever resume;
- the run is stuck `waiting` forever. No error anywhere.

## What's actually true

Starlette's `TestClient` only keeps a persistent `anyio` blocking portal
when used as a context manager (`with TestClient(app) as c:` — the same
mode that runs lifespan). Outside the context manager, each request
creates and tears down its own portal, i.e. its own event loop.

In this repo: `tests/test_agent_runs.py` has both fixtures —

- `client` (non-context) — fine for routes and for background runs that
  finish within their launching request;
- `ctx_client` (context-managed) — REQUIRED for anything that parks,
  holds, or otherwise keeps an `asyncio` object alive across requests
  (`TestConsentParkE2E`; T6 `completed_pending_ack` holds and T7 resume
  tests will need it too).

Production is unaffected — a real uvicorn server has exactly one loop
for its whole life. This is purely a test-harness trap.

## Related

- `ppxai/engine/agent_runs.py` — `park_run` docstring (the in-memory
  future vs. on-disk `state.json` checkpoint distinction).
- `docs/plan-task-command-sequencing.md` §T5 — the increment that
  surfaced this.
