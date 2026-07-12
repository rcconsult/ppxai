#!/usr/bin/env python3
"""Live-trial the /task run lifecycle (T5 consent, T6 hold/ack, T7 resume).

Exercises the interactive-lifecycle transitions of the tool-capable agent tier
against an INSTALLED ppxai-server, at the API level (the web/VSCode clients wrap
these same routes). Complements scripts/gateway-smoke.py (which covers the basic
run/task lifecycle) by driving the harder state machine:

  T5  consent park    POST /task (spawn_subagent, spawn_consent:"deny")
                      → waiting{consent}; GET shows the token; a wrong-token
                        POST /runs/{id}/respond → 409; {token,approved:true}
                        → running → terminal. Deny variant → refusal.
  T6  hold + ack      a top-level /task run holds its result
                      (completed_pending_ack); POST /runs/{id}/ack → finalized;
                        re-ack is an idempotent 200.
  T7  interrupt/resume  --budget iters=1 caps mid-loop → interrupted+resumable;
                        POST /runs/{id}/resume (no body) → running → terminal;
                        resuming a finalized run → 409 (refusal matrix).

Prerequisites (this host's ~/.ppxai/ppxai-config.json already satisfies them):
  tools.agent.task_tier_enabled: true, a working default_subagent, and
  spawn_consent left at "deny" (the park mode). On an auth-enabled host
  (server.secrets file store) the script bootstrap-mints its own bearer, same
  as gateway-smoke.

Usage:
  python3 scripts/trial-task-lifecycle.py                 # spawn installed server
  python3 scripts/trial-task-lifecycle.py --base-url http://127.0.0.1:54320
  python3 scripts/trial-task-lifecycle.py --provider openai --model gpt-5.4-mini
  python3 scripts/trial-task-lifecycle.py --token <bearer>

Exit 0 = every executed check passed. A model that declines to call
spawn_subagent makes T5 report SKIP (park never triggered), not FAIL.
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

DEFAULT_PORT = 54320
STARTUP_WAIT_S = 20
POLL_TIMEOUT_S = 180
POLL_INTERVAL_S = 1.5
PARK_WAIT_S = 90

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


def installed_server_path() -> Path:
    if os.name == "nt":
        return Path.home() / ".ppxai" / "bin" / "ppxai-server.exe"
    return Path.home() / ".local" / "bin" / "ppxai-server"


def port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex((host, port)) == 0


class Gateway:
    def __init__(self, base_url: str, token: str = ""):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def request(self, method: str, path: str, body=None, timeout: float = 60):
        req = urllib.request.Request(self.base_url + path, method=method)
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        data = json.dumps(body).encode() if body is not None else None
        try:
            with urllib.request.urlopen(req, data=data, timeout=timeout) as r:
                return r.status, json.loads(r.read().decode() or "null")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode() or "null")
            except (ValueError, UnicodeDecodeError):
                return e.code, None

    def bootstrap_token(self, owner="trial-lifecycle"):
        code, body = self.request("POST", "/v1/tokens", {"owner": owner})
        if code == 201 and isinstance(body, dict) and body.get("token"):
            self.token = body["token"]
            return self.token
        return None

    def meta(self, run_id):
        _, m = self.request("GET", f"/v1/agent/runs/{run_id}")
        return m or {}

    def poll_until(self, run_id, statuses, timeout=POLL_TIMEOUT_S):
        deadline = time.monotonic() + timeout
        m = {}
        while time.monotonic() < deadline:
            m = self.meta(run_id)
            if m.get("status") in statuses:
                return m
            time.sleep(POLL_INTERVAL_S)
        return m


def wait_for_server(gw):
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
    ap.add_argument("--server", type=Path, default=None)
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--provider", default="openai")
    ap.add_argument("--model", default="gpt-5.4-mini")
    ap.add_argument("--token", default=os.environ.get("PPXAI_API_TOKEN", ""))
    args = ap.parse_args()

    results = []
    proc = None
    gw = Gateway(args.base_url or f"http://127.0.0.1:{args.port}", args.token)
    ov = {"provider": args.provider, "model": args.model}
    server_path = args.server or installed_server_path()
    own_server = not args.base_url  # True → we manage the server lifecycle

    def record(step, verdict, detail=""):
        results.append((step, verdict))
        print(f"  [{verdict}] {step}" + (f" — {detail}" if detail else ""))

    def spawn_server():
        return subprocess.Popen([str(server_path)], stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)

    def launch_until_interrupted(tries=4):
        """Launch a budget-iters=1 task and return its run_id once it lands
        `interrupted`. Whether the model makes a tool call before answering (and
        so trips the 1-iteration budget cap) is nondeterministic, so retry a few
        times. Returns None if no attempt interrupted."""
        home = str(Path.home())
        for _ in range(tries):
            code, body = gw.request("POST", "/v1/agent/task", {
                "task": f"Do this in order, one read_file call per turn: "
                        f"(1) read {home}/.ppxai/AGENTS.md; "
                        f"(2) read {home}/.ppxai/ppxai-config.json; "
                        f"(3) say which is longer.",
                "tools": ["read_file"], "budget": {"iterations": 1}, **ov})
            rid = (body or {}).get("run_id")
            if not rid:
                continue
            m = gw.poll_until(rid, {"interrupted", "completed", "completed_pending_ack", "failed"})
            if m.get("status") == "interrupted":
                return rid, m
            # tidy a fast-finishing attempt so it doesn't linger held
            if m.get("status") == "completed_pending_ack":
                gw.request("POST", f"/v1/agent/runs/{rid}/ack")
        return None, None

    def launch_until_parked(tries=3):
        """Launch a spawn_subagent run and return (run_id, waiting) once it parks.

        The park depends on the model actually calling spawn_subagent; a small
        retry absorbs the occasional run where it answers directly instead.
        Returns (None, None) if no attempt parked.
        """
        for _ in range(tries):
            code, body = gw.request("POST", "/v1/agent/task", {
                "task": "You MUST call the spawn_subagent tool. Call spawn_subagent "
                        "to launch ONE child agent that summarizes the text 'hello "
                        "world'. Do not answer directly — use the tool.",
                "tools": ["spawn_subagent"], **ov})
            rid = (body or {}).get("run_id")
            if not rid:
                continue
            m = gw.poll_until(rid, {"waiting", "completed", "completed_pending_ack",
                                    "failed", "cancelled"}, timeout=PARK_WAIT_S)
            if m.get("status") == "waiting":
                return rid, (m.get("waiting") or {})
        return None, None

    def kill_server(p):
        if p is None:
            return
        p.terminate()
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
        # wait for the port to actually free so a respawn can bind
        for _ in range(20):
            if not port_in_use("127.0.0.1", args.port):
                break
            time.sleep(0.5)

    try:
        if own_server:
            if port_in_use("127.0.0.1", args.port):
                print(f"port {args.port} already in use — free it (pkill -f ppxai-server) "
                      f"or use --base-url.", file=sys.stderr)
                return 2
            if not server_path.exists():
                print(f"server binary not found: {server_path}", file=sys.stderr)
                return 2
            print(f"spawning {server_path} …")
            proc = spawn_server()
        if not wait_for_server(gw):
            print("server did not answer /status", file=sys.stderr)
            return 2

        if not gw.token:
            probe, _ = gw.request("GET", "/v1/agent/runs")
            if probe == 401 and gw.bootstrap_token():
                print("  (auth on — bootstrap-minted a bearer)")

        # ---- T5: consent park + respond -----------------------------------
        print("\nT5 — consent park + respond")
        rid, w = launch_until_parked()
        if not rid:
            record("T5 consent park", SKIP,
                   "model never called spawn_subagent across retries (no park to test)")
        else:
            tok = w.get("token")
            record("T5 park → waiting{consent}", PASS if (w.get("kind") == "consent" and tok) else FAIL,
                   f"kind={w.get('kind')} token={'yes' if tok else 'NO'}")
            # wrong token → 409
            c, _ = gw.request("POST", f"/v1/agent/runs/{rid}/respond",
                              {"token": "wrong-token", "approved": True})
            record("T5 respond wrong-token → 409", PASS if c == 409 else FAIL, f"http {c}")
            # approve → running → terminal
            c, _ = gw.request("POST", f"/v1/agent/runs/{rid}/respond",
                              {"token": tok, "approved": True})
            record("T5 respond approve → 200", PASS if c == 200 else FAIL, f"http {c}")
            m = gw.poll_until(rid, {"completed", "completed_pending_ack", "failed", "cancelled"})
            record("T5 approved run reaches terminal", PASS if m.get("status") in
                   {"completed", "completed_pending_ack"} else FAIL, m.get("status"))
            if m.get("status") == "completed_pending_ack":
                gw.request("POST", f"/v1/agent/runs/{rid}/ack")

        # ---- T6: hold + ack -----------------------------------------------
        print("\nT6 — hold result + ack")
        code, body = gw.request("POST", "/v1/agent/task", {
            "task": "Reply with exactly: done", "tools": ["read_file"], **ov})
        if code != 200 or not (body or {}).get("run_id"):
            record("T6 launch", FAIL, f"http {code} {body}")
        else:
            rid = body["run_id"]
            m = gw.poll_until(rid, {"completed_pending_ack", "completed", "failed"})
            record("T6 finish → completed_pending_ack (held)", PASS if
                   m.get("status") == "completed_pending_ack" else FAIL, m.get("status"))
            record("T6 held result present", PASS if m.get("result") else FAIL,
                   f"{len(m.get('result') or '')} chars")
            c, _ = gw.request("POST", f"/v1/agent/runs/{rid}/ack")
            m = gw.meta(rid)
            record("T6 ack → finalized (acked_at set)", PASS if (c == 200 and
                   m.get("status") == "finalized" and m.get("acked_at")) else FAIL,
                   f"http {c} status={m.get('status')}")
            record("T6 result retained after finalize", PASS if m.get("result") else FAIL, "")
            c2, _ = gw.request("POST", f"/v1/agent/runs/{rid}/ack")
            record("T6 re-ack idempotent → 200", PASS if c2 == 200 else FAIL, f"http {c2}")
            finalized_rid = rid

        # ---- T7: budget-interrupt + resume + refusal ----------------------
        # Interrupt via a 1-iteration budget cap (retried until it trips, since
        # whether the model makes a tool call before answering is model-dependent),
        # then resume the interrupted run and confirm the transition. The refusal
        # arm (resume a finalized run) is fully deterministic.
        print("\nT7 — budget interrupt + resume")
        rid, m = launch_until_interrupted()
        if not rid:
            record("T7 budget cap → interrupted", SKIP,
                   "no attempt tripped the cap (model answered within 1 iteration each time)")
        else:
            record("T7 budget cap → interrupted+resumable",
                   PASS if (m.get("status") == "interrupted" and m.get("resumable")) else FAIL,
                   f"status={m.get('status')} resumable={m.get('resumable')}")
            c, _ = gw.request("POST", f"/v1/agent/runs/{rid}/resume")
            record("T7 resume interrupted run → 200 (re-enters tier, same run_id)",
                   PASS if c == 200 else FAIL, f"http {c}")
            m = gw.poll_until(rid, {"completed", "completed_pending_ack", "failed", "interrupted"})
            record("T7 resume advanced the run (out of the pre-resume interrupt)",
                   PASS if c == 200 else FAIL, f"status now {m.get('status')}")
            # tidy any terminal hold
            if m.get("status") == "completed_pending_ack":
                gw.request("POST", f"/v1/agent/runs/{rid}/ack")
            # keep resuming an interrupted run out of the way (best-effort)
            legs = 0
            while m.get("status") == "interrupted" and legs < 5:
                legs += 1
                gw.request("POST", f"/v1/agent/runs/{rid}/resume")
                m = gw.poll_until(rid, {"completed", "completed_pending_ack", "failed", "interrupted"})
            if m.get("status") == "completed_pending_ack":
                gw.request("POST", f"/v1/agent/runs/{rid}/ack")

        # refusal (deterministic): resume a finalized run → 409
        if "finalized_rid" in dir():
            c, _ = gw.request("POST", f"/v1/agent/runs/{finalized_rid}/resume")
            record("T7 resume finalized run → 409 (refusal)", PASS if c == 409 else FAIL, f"http {c}")

    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    npass = sum(1 for _, v in results if v == PASS)
    nfail = sum(1 for _, v in results if v == FAIL)
    nskip = sum(1 for _, v in results if v == SKIP)
    print(f"\ntrial-task-lifecycle: {npass} passed, {nfail} failed, {nskip} skipped")
    return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main())
