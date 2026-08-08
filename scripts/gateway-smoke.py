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
import hashlib
import json
import os
import re
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


# ── response recording (--record) ────────────────────────────────────────────
# Why this exists: the v1 seam guarantee is the word *byte-identical*, and a
# pass/fail run cannot support that claim. Two greens only prove both runs
# satisfied whatever assertions this script happens to make today; a
# before/after diff of the actual responses proves the contract itself.
# A pre-change baseline is also perishable — once a line moves, the
# opportunity to capture it is gone permanently.
#
# Diff the *.normalized.json files. The raw bodies are kept for forensics but
# will differ on every run by design (run ids, timestamps, minted tokens), so
# diffing those reports 100% noise and hides the signal.

_HEXISH = re.compile(r"[0-9a-fA-F]{8,}(?:-[0-9a-fA-F]{4,}){0,4}")

# Keys whose values legitimately change run-to-run. Exact names plus suffixes.
_VOLATILE_KEYS = frozenset({
    "run_id", "parent_run_id", "id", "token", "resume_token", "owner",
    "created_at", "updated_at", "started_at", "finished_at", "expires_at",
    "pid", "session_id", "trace_id", "session_name",
    # Model-derived counters: the contract is "usage carries these three int
    # fields", not their magnitudes. total_tokens is genuinely nondeterministic
    # here (Gemini thinking tokens moved it 82→93 across two identical calls);
    # the other two ride along so a provider swap doesn't read as a break.
    # _volatile() keeps the type, so int→str would still surface.
    "total_tokens", "prompt_tokens", "completion_tokens",
    # Model output is never a wire contract — only its type is. The structured
    # step's content is generated JSON whose keys the model picks, so keeping
    # the value would make that file differ on every run and destroy the
    # baseline's reproducibility. _volatile() still catches str -> dict.
    "content",
})
# Deliberately narrow. A broad `_id`/`_s` suffix would also erase
# `allowlist_rule_id` and `consent_ttl_s` — stable values whose change is
# exactly what this diff exists to catch. Over-normalizing defeats the check
# as thoroughly as not recording at all; add exact names above instead.
_VOLATILE_SUFFIXES = ("_at", "_ms", "_token", "_seconds")


def _is_volatile(key: str) -> bool:
    return key in _VOLATILE_KEYS or key.endswith(_VOLATILE_SUFFIXES)


def _scrub(text: str) -> str:
    """Replace embedded ids in free text / paths so they don't drive the diff."""
    return _HEXISH.sub("<ID>", text)


def _fs_slug(path: str) -> str:
    """Filesystem-safe endpoint slug. Angle brackets are illegal on Windows,
    so this cannot reuse _scrub's `<ID>` placeholder."""
    slug = _HEXISH.sub("ID", path.strip("/")).replace("/", "_")
    return re.sub(r"[^A-Za-z0-9_.-]", "_", slug) or "root"


def _normalize(value):
    """Structure-preserving, volatility-erasing view of a response body.

    Keys are sorted so dict ordering never shows up as a diff. Volatile
    values become a placeholder — the SHAPE and every stable value survive,
    which is exactly the part the seam guarantee is about.
    """
    if isinstance(value, dict):
        return {
            k: (_volatile(v) if _is_volatile(k) else _normalize(v))
            for k, v in sorted(value.items())
        }
    if isinstance(value, list):
        # A long homogeneous list is machine history, not contract. GET
        # /v1/agent/runs returns every run this host ever made (160 entries /
        # 159 KB here, growing every smoke run), so diffing the entries reports
        # accumulation instead of contract change. Collapse to the union of
        # entry keys: that still catches a field added to or removed from the
        # run shape, which IS the seam question.
        if len(value) > 2 and all(isinstance(v, dict) for v in value):
            keys = sorted({k for d in value for k in d})
            # The COUNT is the accumulation itself — recording it would put
            # back exactly the noise this branch removes.
            return [{"<elided_entries>": _volatile(len(value)),
                     "<union_keys>": keys}]
        return [_normalize(v) for v in value]
    if isinstance(value, str):
        return _scrub(value)
    return value


def _volatile(value):
    """Placeholder for a volatile value that PRESERVES its type.

    A bare "<VOLATILE>" would hide a field flipping int→str, which is exactly
    the kind of silent contract break this diff exists to catch. Model-derived
    counters (usage.total_tokens varies with Gemini thinking tokens) are
    volatile in magnitude but not in type.
    """
    return f"<VOLATILE:{type(value).__name__}>"


def _json_content_keys(parsed):
    """Sorted key set of a JSON-object-bearing `content`, else None.

    Plain-text content (the unstructured oneshot returns "ok") yields None, so
    the field only appears where there is a structure to compare.
    """
    if not isinstance(parsed, dict):
        return None
    content = parsed.get("content")
    if not isinstance(content, str):
        return None
    try:
        inner = json.loads(content)
    except (ValueError, TypeError):
        return None
    return sorted(inner) if isinstance(inner, dict) else None


class Recorder:
    """Writes one file per HTTP exchange into a directory."""

    def __init__(self, outdir: Path):
        self.dir = outdir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.n = 0
        self.seen: dict = {}

    def capture(self, method, path, status, headers, raw: bytes,
                slug_override: str = None) -> None:
        # One file per (method, endpoint), NOT per call. The run-poll loop hits
        # GET /v1/agent/runs/<id> an unpredictable number of times depending on
        # timing, so numbering per call would make the file COUNT vary run to
        # run and a diff would report spurious adds/removes. Keyed + overwritten,
        # the last write per endpoint wins — for a poll that's the terminal
        # state, which is the response actually worth comparing.
        # slug_override disambiguates two calls to the SAME endpoint that are
        # different contracts — /v1/oneshot plain vs response_format. Without
        # it the second overwrites the first and the baseline silently loses a
        # surface it appears to cover.
        slug = _fs_slug(slug_override or path)
        key = f"{method}-{slug}"
        if key not in self.seen:
            self.n += 1
            self.seen[key] = self.n
        stem = f"{self.seen[key]:02d}-{key}"
        try:
            parsed = json.loads(raw.decode() or "null")
        except (ValueError, UnicodeDecodeError):
            parsed = None
        # Header NAMES are part of the contract; values (dates, lengths) are not.
        header_names = sorted({k.lower() for k in headers})
        entry = {
            "method": method,
            "path": _scrub(path),
            "status": status,
            "header_names": header_names,
            "body": _normalize(parsed),
        }
        (self.dir / f"{stem}.normalized.json").write_text(
            json.dumps(entry, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        # PROVIDER BEHAVIOUR, not seam contract — hence its own file.
        # When `content` carries JSON, its key set shows whether a
        # response_format schema was actually honoured. It goes here rather
        # than in the normalized artifact because it is currently UNSTABLE:
        # Gemini ignores the schema and picks its own keys, so two identical
        # requests differ. Mixing it into the diff target would make every
        # future seam comparison noisy. Its instability is itself the evidence
        # of non-enforcement — were the schema honoured, it would be constant.
        keys = _json_content_keys(parsed)
        if keys is not None:
            (self.dir / f"{stem}.contentkeys.json").write_text(
                json.dumps({"content_json_keys": keys}, indent=2) + "\n",
                encoding="utf-8",
            )
        (self.dir / f"{stem}.raw.json").write_text(
            json.dumps({
                "status": status,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "body": raw.decode(errors="replace"),
            }, indent=2) + "\n",
            encoding="utf-8",
        )


class Gateway:
    def __init__(self, base_url: str, token: str = "", recorder: "Recorder" = None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.recorder = recorder

    def request(self, method: str, path: str, body: dict = None, timeout: float = 30,
                record_as: str = None):
        """Return (status_code, parsed_json_or_None). Network errors raise.

        record_as names the recording slot when one endpoint carries more than
        one contract (see Recorder.capture).
        """
        req = urllib.request.Request(self.base_url + path, method=method)
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        data = json.dumps(body).encode() if body is not None else None
        try:
            with urllib.request.urlopen(req, data=data, timeout=timeout) as resp:
                # Read the bytes ONCE, record them, then parse from the same
                # buffer — the stream can't be re-read after json.loads.
                raw = resp.read()
                if self.recorder:
                    self.recorder.capture(method, path, resp.status, resp.headers,
                                          raw, record_as)
                return resp.status, json.loads(raw.decode() or "null")
        except urllib.error.HTTPError as e:
            raw = e.read()
            if self.recorder:
                self.recorder.capture(method, path, e.code, e.headers, raw,
                                      record_as)
            try:
                payload = json.loads(raw.decode() or "null")
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
    ap.add_argument("--record", type=Path, default=None, metavar="DIR",
                    help="write every HTTP exchange to DIR (one file per call). "
                         "Take a baseline BEFORE a seam-touching change, then "
                         "diff DIR/*.normalized.json after — pass/fail cannot "
                         "evidence a byte-identical guarantee.")
    args = ap.parse_args()

    results = []  # (step, verdict, detail)
    proc = None
    health_version = "unknown"  # read while the server is up; see below
    base_url = args.base_url or f"http://127.0.0.1:{args.port}"
    gw = Gateway(base_url, args.token,
                 recorder=Recorder(args.record) if args.record else None)

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
            # Pass --port through: without it the spawned server binds its own
            # default while we probe args.port, so any non-default --port died
            # with a confusing "did not answer /status" instead of running.
            proc = subprocess.Popen(
                [str(server), "--port", str(args.port)], **popen_kwargs
            )
        if not wait_for_server(gw):
            print(f"server did not answer /status within {STARTUP_WAIT_S}s", file=sys.stderr)
            return 2

        # Must be read HERE: the spawned process is terminated in the finally
        # block, before the manifest is written.
        health_version = probe_health_version(base_url)

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

            # 3b. oneshot WITH response_format — the structured half of the
            #     same endpoint. Step 3 proves only that an unstructured call
            #     returns a stable envelope; it is blind to the schema-enforced
            #     path, which is the half ppxai-sre's Pattern A classifier is
            #     actually built on. Its pinned shape is mirrored here so a
            #     baseline diff would catch the plumbing changing under it.
            #     response_format forwards to the provider as-is, and support
            #     varies (see module docstring), so a provider that rejects
            #     schema mode SKIPs rather than failing the run.
            structured = {
                "prompt": (
                    "Classify the intent of this message and reply with JSON "
                    'only. Message: "The server is down, please help."'
                ),
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "classification",
                        "schema": {
                            "type": "object",
                            "properties": {
                                "intent": {"type": "string"},
                                "confidence": {"type": "number"},
                                "suggested_action": {"type": "string"},
                                "reasoning": {"type": "string"},
                            },
                            "required": [
                                "intent", "confidence",
                                "suggested_action", "reasoning",
                            ],
                            "additionalProperties": False,
                        },
                    },
                },
                **overrides,
            }
            code, body = gw.request(
                "POST", "/v1/oneshot", structured, timeout=120,
                record_as="/v1/oneshot#structured",
            )
            if code == 400:
                detail = body.get("detail") if isinstance(body, dict) else body
                record("POST /v1/oneshot (response_format)", SKIP,
                       f"provider rejected schema mode: {str(detail)[:120]}")
            elif code != 200 or not isinstance(body, dict):
                record("POST /v1/oneshot (response_format)", FAIL, f"http {code}")
            else:
                # The envelope must be the SAME as the plain call — a
                # structured request must not reshape the response.
                envelope = all(
                    k in body for k in ("content", "finish_reason", "model", "usage"))
                try:
                    parsed = json.loads(body.get("content") or "")
                except (ValueError, TypeError):
                    parsed = None
                conformant = isinstance(parsed, dict) and set(parsed) == {
                    "intent", "confidence", "suggested_action", "reasoning"}
                # Conformance is REPORTED, not asserted. What the gateway owes
                # the caller is that response_format REACHES the model and the
                # envelope is unchanged; whether the model then honours the
                # schema is the provider's business and varies by endpoint. A
                # non-conformant answer from a provider that merely forwards
                # is not a gateway fault, and failing on it would paint a
                # working gateway red.
                #
                # This step earned its keep on first run: it caught the Gemini
                # path accepting response_format and DROPPING it, so a pinned
                # schema returned 200 with unconstrained output and no error
                # anywhere. Fixed in v1.19.1 by mapping it onto
                # response_mime_type / response_schema — this now reports
                # schema=enforced against gemini-3.1-pro-preview.
                #
                # The key set is recorded to *.contentkeys.json, outside the
                # diff target: it is provider behaviour, not seam contract.
                ok = envelope and isinstance(parsed, dict)
                record(
                    "POST /v1/oneshot (response_format)", PASS if ok else FAIL,
                    f"http {code}, envelope={'ok' if envelope else 'CHANGED'}, "
                    f"json={'valid' if isinstance(parsed, dict) else 'INVALID'}, "
                    f"schema={'enforced' if conformant else 'NOT enforced by provider'}",
                )

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
    if args.record:
        # A capture directory that can't say what it is gets mistaken for one
        # that can. Written automatically rather than by hand: a convention
        # nobody enforces decays exactly like an undocumented path does.
        _write_manifest(args.record, args, results, base_url, health_version)
    print(f"\ngateway-smoke: {len([r for r in results if r[1] == PASS])} passed, "
          f"{len(failed)} failed, {len([r for r in results if r[1] == SKIP])} skipped")
    return 1 if failed else 0


def _git(*args_) -> str:
    """Best-effort git query; '' when unavailable (frozen-binary hosts)."""
    try:
        out = subprocess.run(
            ["git", *args_], capture_output=True, timeout=10, check=False,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        return out.stdout.decode(errors="replace").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def probe_health_version(base_url: str) -> str:
    """The server's OWN account of its version, via /health.

    Deliberately not routed through Gateway.request: that would add a tenth
    artifact and renumber the baseline. Must be read while the server is still
    up — the spawned process is terminated before the manifest is written.

    Weak evidence (a version string, not a commit) but it is the only
    self-identification the server offers, and it is the difference between
    "some server on :8850" and "a server claiming 1.19.1".
    """
    try:
        with urllib.request.urlopen(
            base_url.rstrip("/") + "/health", timeout=5
        ) as resp:
            body = json.loads(resp.read().decode() or "{}") or {}
        return str(body.get("version") or "unreported")
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError):
        return "unreachable"


def _provenance_warnings(binary_mtime) -> list:
    """Is the spawned binary actually newer than the code it claims to be?

    The manifest already recorded the build time faithfully — and inertly.
    Recording a fact nobody compares to anything still needs a reader who
    knows which commits matter, which is the "detectable if you look" state
    this tooling exists to replace with "detected".

    Compared against the last commit touching `ppxai/`, NOT against HEAD: a
    docs-only HEAD (as when this was written) would otherwise raise a false
    alarm on a perfectly current binary.

    The concrete failure this prevents: someone reruns the default invocation
    to "refresh the baseline", silently captures the INSTALLED binary — days
    older than the tree — diffs it against a post-change capture, and
    attributes the older binary's differences to their change.
    """
    if binary_mtime is None:
        return ["*** WEAK PROVENANCE — binary build time unreadable. ***"]
    out = []
    last_src = _git("log", "-1", "--format=%ct", "--", "ppxai")
    if last_src.isdigit():
        if binary_mtime < int(last_src):
            when = time.strftime("%Y-%m-%d %H:%M:%S",
                                 time.localtime(int(last_src)))
            out.append(
                "*** WEAK PROVENANCE — the binary PREDATES the last commit "
                f"touching ppxai/ ({when}). It does not contain that code. "
                "Rebuild (pyinstaller ppxai-server.spec --noconfirm) and "
                "re-capture before using this as a baseline. ***"
            )
    if _git("status", "--porcelain", "--", "ppxai"):
        out.append(
            "*** WEAK PROVENANCE — ppxai/ has uncommitted changes, which the "
            "binary may or may not contain. Commit, rebuild, re-capture. ***"
        )
    return out


def _write_manifest(outdir: Path, args, results, base_url: str,
                    health_version: str = "unknown") -> None:
    """Describe what this capture IS, so the next reader needn't infer it.

    A baseline is only usable as evidence if you know which commit, which
    server build and which provider produced it — otherwise a directory of
    identical-looking JSON is indistinguishable from six others beside it.
    """
    warnings: list = []
    if args.base_url:
        server = (f"already-running server at {args.base_url} — the script did "
                  f"NOT start it and cannot vouch for what it is. A baseline "
                  f"captured this way carries weaker provenance than a spawned "
                  f"one; prefer letting the script spawn a binary.")
    else:
        binary = args.server or installed_server_path()
        try:
            mtime = Path(binary).stat().st_mtime
            built = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime))
        except OSError:
            mtime, built = None, "unknown"
        server = f"spawned binary {binary} (built {built})"
        warnings.extend(_provenance_warnings(mtime))

    dirty = "dirty" if _git("status", "--porcelain") else "clean"
    # The provider that actually answered, read back from the recording rather
    # than from config — config says what was requested, not what replied.
    provider = model = "unknown"
    for name in ("04-POST-v1_oneshot", "05-POST-v1_oneshot_structured"):
        # Try both oneshot captures: a transient provider 503 leaves the first
        # holding an error detail with no provider/model, and a manifest that
        # then says "unknown" is less useful than one that looks at the other.
        try:
            body = json.loads(
                (outdir / f"{name}.normalized.json").read_text(encoding="utf-8")
            ).get("body") or {}
        except (OSError, ValueError):
            continue
        if body.get("model"):
            provider, model = body.get("provider", "?"), body["model"]
            break

    lines = [
        "gateway-smoke capture",
        "=====================",
        f"captured    : {time.strftime('%Y-%m-%d %H:%M:%S %z')}",
        f"commit      : {_git('rev-parse', 'HEAD') or 'unknown'} ({dirty})",
        f"branch      : {_git('rev-parse', '--abbrev-ref', 'HEAD') or 'unknown'}",
        f"server      : {server}",
        f"reports     : version {health_version} (self-reported via /health)",
        f"answered by : provider={provider} model={model}",
        f"result      : {len([r for r in results if r[1] == PASS])} passed, "
        f"{len([r for r in results if r[1] == FAIL])} failed, "
        f"{len([r for r in results if r[1] == SKIP])} skipped",
        ("" if not [r for r in results if r[1] == FAIL] else
         "*** NOT A USABLE BASELINE — a step failed; re-capture before "
         "diffing against this. ***"),
        *warnings,
        "",
        "Diff *.normalized.json only. *.raw.json and *.contentkeys.json vary",
        "every run by design (ids, timestamps, model output) and will report",
        "noise. A capture is comparable only against one taken the same way —",
        "check `server` above before trusting a clean diff.",
        "",
        "steps:",
    ]
    lines += [f"  [{verdict}] {step}" + (f" — {detail}" if detail else "")
              for step, verdict, detail in results]
    (outdir / "MANIFEST.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    _force_utf8_console()
    sys.exit(main())
