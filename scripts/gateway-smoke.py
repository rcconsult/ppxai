#!/usr/bin/env python3
"""Gateway smoke test — exercise the v1 API surface of an INSTALLED ppxai-server.

The llm-eval benchmark deliberately drives models in-process through
EngineClient, so nothing routinely exercises the installed binary's HTTP
surface end-to-end. This script closes that gap as a post-install acceptance
step (see .claude/skills/build-install/SKILL.md step 8): it spawns the
installed server (or targets a running one), then walks the stable v1
gateway:

  1. GET  /status                      → server up
  2. GET  /v1/agent/runs               → run registry up
  3. POST /v1/oneshot                  → one cheap LLM round-trip, shape check
  4. POST /v1/agent/run  + poll        → tool-free run lifecycle to `completed`
  5. POST /v1/agent/task + poll + ack  → sandboxed tier to `finalized`
                                         (SKIP when task_tier_enabled=false —
                                         403 from the gate is the default)

Steps 3-5 cost one trivial LLM call each; --skip-llm keeps the run free
(steps 1-2 only). stdlib-only on purpose: runs against a frozen binary on a
host with no repo venv.

Usage:
  python3 scripts/gateway-smoke.py                     # spawn installed server
  python3 scripts/gateway-smoke.py --server dist/ppxai-server   # a fresh build
  python3 scripts/gateway-smoke.py --base-url http://127.0.0.1:54320  # running
  python3 scripts/gateway-smoke.py --skip-llm          # free, perimeter only
  python3 scripts/gateway-smoke.py --token <bearer>    # auth-enforcing host

On an auth-enforcing host (a `server.secrets` file token store) the script
auto-provisions its own bearer via the loopback bootstrap mint (`POST
/v1/tokens`) when no --token / PPXAI_API_TOKEN is given, so the protected
steps still run. Pass --token to use a specific bearer instead.

Exit code 0 = every non-skipped step passed.
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

def _force_utf8_console() -> None:
    """Make stdout/stderr able to carry this script's non-ASCII output.

    The progress lines use `—`, `→` and `…`. On Windows the default console
    encoding is the legacy ANSI codepage (cp1252 under the Windows Store
    Python), so printing any of them raises UnicodeEncodeError and aborts the
    run *mid-acceptance* — and because that happens after the server is
    spawned, it also orphans the server on the port, poisoning the next run
    (see _signal_tree / stale-server-invalidates-acceptance.md).

    Reconfiguring here fixes every print site at once — including future ones —
    instead of ASCII-ifying individual strings and hoping nobody adds an arrow
    back. `errors="replace"` is the belt-and-braces fallback for a stream that
    still cannot represent a character after the switch.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            # Non-reconfigurable stream (redirected/wrapped). Printing may
            # still fail on exotic characters, but never abort the import.
            pass


DEFAULT_PORT = 54320
STARTUP_WAIT_S = 20
RUN_POLL_TIMEOUT_S = 180
RUN_POLL_INTERVAL_S = 1.5

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


def installed_server_path() -> Path:
    if os.name == "nt":
        return Path.home() / ".ppxai" / "bin" / "ppxai-server.exe"
    return Path.home() / ".local" / "bin" / "ppxai-server"


def _signal_tree(proc, how: str):
    """SIGTERM/SIGKILL the process's whole group (POSIX) or the proc (Windows).

    The installed ppxai-server is a PyInstaller onefile: a bootloader parent
    plus the real server as a CHILD. Signalling only the Popen (parent) can
    leave the child alive and holding the port. We spawn it in its own session
    (start_new_session) and kill the group here so nothing is orphaned. See
    docs/lessons/stale-server-invalidates-acceptance.md.
    """
    if proc is None:
        return
    if os.name == "nt":
        # `taskkill /T` is the Windows analogue of killpg: it walks the child
        # tree. Without /T we kill only the PyInstaller bootloader parent and
        # the real server CHILD survives holding the port — the exact orphan
        # this function's docstring warns about (observed live 2026-07-15).
        # /F is required to take down the child; the graceful path is tried
        # first via terminate() so a well-behaved server can still exit clean.
        if how != "kill":
            proc.terminate()
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True, timeout=15, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            # taskkill missing/blocked — fall back to the parent-only kill.
            (proc.kill if how == "kill" else proc.terminate)()
        return
    import signal
    sig = signal.SIGKILL if how == "kill" else signal.SIGTERM
    try:
        os.killpg(os.getpgid(proc.pid), sig)
    except (ProcessLookupError, PermissionError):
        (proc.kill if how == "kill" else proc.terminate)()


class Gateway:
    def __init__(self, base_url: str, token: str = ""):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def request(self, method: str, path: str, body: dict = None, timeout: float = 30):
        """Return (status_code, parsed_json_or_None). Network errors raise."""
        req = urllib.request.Request(self.base_url + path, method=method)
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        data = json.dumps(body).encode() if body is not None else None
        try:
            with urllib.request.urlopen(req, data=data, timeout=timeout) as resp:
                return resp.status, json.loads(resp.read().decode() or "null")
        except urllib.error.HTTPError as e:
            try:
                payload = json.loads(e.read().decode() or "null")
            except (ValueError, UnicodeDecodeError):
                payload = None
            return e.code, payload

    def bootstrap_token(self, owner: str = "gateway-smoke"):
        """Mint a bearer via the loopback bootstrap path (auth-enabled hosts).

        When `server.secrets` configures a file (mint-capable) token store,
        auth is enforced and the protected surfaces (`/v1/agent/runs` list,
        `POST /v1/agent/task`, monitor channels) reject a bearer-less caller
        even on loopback — only `/v1/oneshot` and `POST /v1/agent/run` stay
        exempt (see ppxai/server/auth.py `_LOOPBACK_EXEMPT_AGENT_PATHS`). But
        `POST /v1/tokens` is loopback-exempt precisely so a local operator can
        mint the first token, so the smoke test provisions its own. Returns
        the token material, or None if minting isn't available.
        """
        code, body = self.request("POST", "/v1/tokens", {"owner": owner})
        if code == 201 and isinstance(body, dict) and body.get("token"):
            self.token = body["token"]
            return self.token
        return None

    def poll_run(self, run_id: str, terminal: set) -> dict:
        """Poll run meta until its status enters `terminal` (or timeout)."""
        deadline = time.monotonic() + RUN_POLL_TIMEOUT_S
        meta = {}
        while time.monotonic() < deadline:
            status_code, meta = self.request("GET", f"/v1/agent/runs/{run_id}")
            if status_code != 200:
                raise AssertionError(f"poll GET runs/{run_id} → {status_code}")
            if (meta or {}).get("status") in terminal:
                return meta
            time.sleep(RUN_POLL_INTERVAL_S)
        raise AssertionError(
            f"run {run_id} not terminal after {RUN_POLL_TIMEOUT_S}s "
            f"(last status: {(meta or {}).get('status')})"
        )


def port_in_use(host: str, port: int) -> bool:
    """True if something is already listening on host:port.

    Critical guard: if we spawn a fresh binary while a stale ppxai-server
    still holds the port, the new process dies on `address already in use`
    and every request silently hits the OLD binary — the acceptance run
    then "passes" against exactly the build we were trying to replace.
    Caught live 2026-07-12 (a stale server made a new build's PPTX preview
    return a 500 from the old process). See
    docs/lessons/stale-server-invalidates-acceptance.md.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex((host, port)) == 0


def reap_port_listener(host: str, port: int, timeout_s: float = 8.0) -> bool:
    """Last-resort cleanup: kill whatever still LISTENs on host:port.

    Signalling the spawned process is not sufficient on Windows. The
    installed server is a PyInstaller onefile — a bootloader PARENT plus the
    real server CHILD. When the bootloader exits first the child is
    reparented and escapes `taskkill /T` (which walks the tree of a PID that
    no longer exists), so it survives holding the port. Observed live
    2026-07-15: parent 27464 gone, child 44632 still LISTENING on 54320.

    Killing by *port ownership* rather than by parentage closes that hole —
    it is the same thing a human does with netstat + taskkill, and it is what
    makes the next run's port_in_use guard trustworthy.

    Returns True when the port ends up free.
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not port_in_use(host, port):
            return True
        pids = _pids_listening_on(port)
        if not pids:
            # Held by something we can't identify (or a lingering socket in
            # TIME_WAIT, which does not accept connections anyway).
            break
        for pid in pids:
            try:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                                   capture_output=True, timeout=10, check=False)
                else:
                    os.kill(pid, 9)
            except (OSError, subprocess.SubprocessError):
                pass
        time.sleep(0.5)
    return not port_in_use(host, port)


def _pids_listening_on(port: int) -> list:
    """PIDs LISTENing on `port`, via netstat (stdlib-only, both platforms)."""
    flags = ["-ano"] if os.name == "nt" else ["-tlnp"]
    try:
        out = subprocess.run(["netstat", *flags], capture_output=True,
                             text=True, timeout=10, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    pids = set()
    for line in out.splitlines():
        if f":{port} " not in line and not line.rstrip().endswith(f":{port}"):
            continue
        if "LISTEN" not in line.upper():
            continue
        token = line.split()[-1]
        # Windows: trailing PID column. POSIX -tlnp: trailing "PID/name".
        pid_str = token.split("/")[0] if "/" in token else token
        if pid_str.isdigit():
            pids.add(int(pid_str))
    return sorted(pids)


def wait_for_server(gw: Gateway) -> bool:
    deadline = time.monotonic() + STARTUP_WAIT_S
    while time.monotonic() < deadline:
        try:
            code, _ = gw.request("GET", "/status", timeout=2)
            if code == 200:
                return True
        except (urllib.error.URLError, OSError, TimeoutError):
            pass
        time.sleep(0.5)
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--server", type=Path, default=None,
                    help="ppxai-server binary to spawn (default: installed location)")
    ap.add_argument("--base-url", default=None,
                    help="target an already-running server instead of spawning")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--provider", default=None, help="provider override for LLM steps")
    ap.add_argument("--model", default=None, help="model override for LLM steps")
    ap.add_argument("--skip-llm", action="store_true",
                    help="perimeter checks only — no LLM calls, no cost")
    ap.add_argument("--token", default=os.environ.get("PPXAI_API_TOKEN", ""),
                    help="bearer token for auth-enforcing hosts (env: PPXAI_API_TOKEN)")
    args = ap.parse_args()

    results = []  # (step, verdict, detail)
    proc = None
    base_url = args.base_url or f"http://127.0.0.1:{args.port}"
    gw = Gateway(base_url, args.token)

    def record(step: str, verdict: str, detail: str = ""):
        results.append((step, verdict, detail))
        print(f"  [{verdict}] {step}" + (f" — {detail}" if detail else ""))

    try:
        if not args.base_url:
            # Guard: refuse to spawn if the port is already held. Otherwise a
            # stale server would absorb the bind failure and we'd test the OLD
            # binary while believing we tested the fresh one (see port_in_use).
            if port_in_use("127.0.0.1", args.port):
                print(
                    f"port {args.port} already in use — a stale ppxai-server is "
                    f"holding it. A freshly spawned binary would die silently and "
                    f"this run would test the OLD server. Free it first "
                    f"(pkill -f ppxai-server) or target it explicitly with "
                    f"--base-url http://127.0.0.1:{args.port}.",
                    file=sys.stderr,
                )
                return 2
            server = args.server or installed_server_path()
            if not server.exists():
                print(f"server binary not found: {server}", file=sys.stderr)
                return 2
            print(f"spawning {server} …")
            popen_kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
            if os.name != "nt":
                popen_kwargs["start_new_session"] = True  # own group → kill the whole tree
            proc = subprocess.Popen([str(server)], **popen_kwargs)
        if not wait_for_server(gw):
            print(f"server did not answer /status within {STARTUP_WAIT_S}s", file=sys.stderr)
            return 2

        # 1. /status
        code, _ = gw.request("GET", "/status")
        record("GET /status", PASS if code == 200 else FAIL, f"http {code}")

        # Auth probe: if the run-registry list 401s and we have no token, the
        # host runs a mint-capable token store (server.secrets file provider).
        # Provision a bearer via the loopback bootstrap so the protected steps
        # (runs list, /task) still exercise instead of failing. --token / env
        # override this entirely.
        if not gw.token:
            probe, _ = gw.request("GET", "/v1/agent/runs")
            if probe == 401:
                if gw.bootstrap_token():
                    record("auth: loopback bootstrap-mint", PASS, "token store detected → minted")
                else:
                    record("auth: loopback bootstrap-mint", FAIL,
                           "runs list 401 but /v1/tokens mint failed — pass --token")

        # 2. run registry
        code, body = gw.request("GET", "/v1/agent/runs")
        ok = code == 200 and isinstance(body, dict) and "runs" in body
        record("GET /v1/agent/runs", PASS if ok else FAIL, f"http {code}")

        if args.skip_llm:
            record("POST /v1/oneshot", SKIP, "--skip-llm")
            record("POST /v1/agent/run lifecycle", SKIP, "--skip-llm")
            record("POST /v1/agent/task lifecycle", SKIP, "--skip-llm")
        else:
            overrides = {}
            if args.provider:
                overrides["provider"] = args.provider
            if args.model:
                overrides["model"] = args.model

            # 3. oneshot — the surface ppxai-sre consumes; shape must hold.
            code, body = gw.request(
                "POST", "/v1/oneshot",
                {"prompt": "Reply with exactly: ok", **overrides}, timeout=120,
            )
            if code == 401:
                record("POST /v1/oneshot", FAIL,
                       "401 — auth-enforcing host; pass --token (mint via /v1/tokens)")
            else:
                shape = isinstance(body, dict) and all(
                    k in body for k in ("content", "finish_reason", "model", "usage"))
                ok = code == 200 and shape and (body.get("content") or "").strip()
                record("POST /v1/oneshot", PASS if ok else FAIL,
                       f"http {code}, model={isinstance(body, dict) and body.get('model')}")

            # 4. tool-free run tier: create → background exec → terminal.
            #    U4 (ADR 0011): under execution.collect="yes" (the default)
            #    a /run result is HELD (completed_pending_ack) until
            #    collected — ack it to finalized, like the task tier below.
            #    "auto"/"no" land straight in completed.
            code, body = gw.request(
                "POST", "/v1/agent/run",
                {"task": "Reply with exactly: ok", **overrides}, timeout=60,
            )
            if code != 200 or not isinstance(body, dict) or not body.get("run_id"):
                record("POST /v1/agent/run lifecycle", FAIL, f"create → http {code}")
            else:
                run_id = body["run_id"]
                meta = gw.poll_run(
                    run_id, {"completed", "completed_pending_ack", "failed"}
                )
                status = meta.get("status")
                if status == "completed_pending_ack":
                    ack_code, _ = gw.request(
                        "POST", f"/v1/agent/runs/{run_id}/ack"
                    )
                    _, meta = gw.request("GET", f"/v1/agent/runs/{run_id}")
                    ok = (ack_code == 200
                          and (meta or {}).get("status") == "finalized")
                    record("POST /v1/agent/run lifecycle", PASS if ok else FAIL,
                           f"{run_id} → held → ack http {ack_code} → "
                           f"{(meta or {}).get('status')}")
                else:
                    ok = status == "completed"
                    record("POST /v1/agent/run lifecycle", PASS if ok else FAIL,
                           f"{run_id} → {status}")

            # 5. sandboxed task tier: gated default-off, so 403 = expected SKIP.
            #    A granted-but-unused tool keeps the run trivial; a top-level
            #    task HOLDs its result (T6) so we must /ack to finalized.
            code, body = gw.request(
                "POST", "/v1/agent/task",
                {"task": "Do not use any tools. Reply with exactly: ok",
                 "tools": ["read_file"], **overrides}, timeout=60,
            )
            if code == 403:
                record("POST /v1/agent/task lifecycle", SKIP,
                       "task tier disabled (tools.agent.task_tier_enabled=false)")
            elif code != 200 or not isinstance(body, dict) or not body.get("run_id"):
                record("POST /v1/agent/task lifecycle", FAIL, f"create → http {code}")
            else:
                run_id = body["run_id"]
                # U4: collect="yes" (default) → held → ack; "auto"/"no" →
                # straight to completed (both are the healthy lifecycle).
                meta = gw.poll_run(
                    run_id, {"completed", "completed_pending_ack", "failed"}
                )
                status = meta.get("status")
                if status == "completed":
                    record("POST /v1/agent/task lifecycle", PASS,
                           f"{run_id} → completed (collect=auto/no — no hold)")
                elif status != "completed_pending_ack":
                    record("POST /v1/agent/task lifecycle", FAIL,
                           f"{run_id} → {status}")
                else:
                    code, _ = gw.request("POST", f"/v1/agent/runs/{run_id}/ack")
                    _, meta = gw.request("GET", f"/v1/agent/runs/{run_id}")
                    ok = code == 200 and (meta or {}).get("status") == "finalized"
                    record("POST /v1/agent/task lifecycle", PASS if ok else FAIL,
                           f"{run_id} → ack http {code} → {(meta or {}).get('status')}")

    finally:
        if proc is not None:
            _signal_tree(proc, "term")
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                _signal_tree(proc, "kill")
            # Signalling the spawned PID is not proof the port was released —
            # a reparented PyInstaller child survives it (see
            # reap_port_listener). Verify, and reap by port ownership if the
            # listener is still up, so the NEXT run's port_in_use guard isn't
            # tripped by our own leftovers.
            if not args.base_url and not reap_port_listener("127.0.0.1", args.port):
                print(f"warning: port {args.port} still held after cleanup — "
                      f"free it before the next run", file=sys.stderr)

    failed = [r for r in results if r[1] == FAIL]
    print(f"\ngateway-smoke: {len([r for r in results if r[1] == PASS])} passed, "
          f"{len(failed)} failed, {len([r for r in results if r[1] == SKIP])} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    _force_utf8_console()
    sys.exit(main())
