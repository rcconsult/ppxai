# Killing a PyInstaller one-file binary kills only its bootloader

**TL;DR:** Every installed ppxai binary is a PyInstaller one-file build,
so the process you spawn is a bootloader and the real program is its
**child**. On Windows, `proc.kill()` / `terminate()` (TerminateProcess)
ends the bootloader alone and the real server lives on, holding port 54320.
Ask the server to stop first (`POST /shutdown`), then force-kill the whole
tree (`taskkill /PID <pid> /T /F`), never only the PID you spawned.

**Verify with:**
`grep -n "taskkill" vscode-extension/src/extension.ts scripts/gateway-smoke.py`.
Both spawn sites that stop a server use `/T`. Live check on Windows: start
`ppxai-server.exe` from Python, call `proc.kill()`, and `netstat -ano | findstr 54320`
still lists a listener, owned by a PID that is not `proc.pid`.

## Why this trips people up

The obvious model is "I spawned it, so `kill()` on my handle stops it". With
a one-file build the handle points at the wrong process. Nothing reports the
mistake: `kill()` succeeds, the handle reads as exited, and the orphan logs
no shutdown at all, because it was never asked to stop. The damage turns up
later, somewhere else:

- **The next start dies on the bind.** The fresh server can't take 54320 and
  exits. Before `44ea976a` it logged `reason: unknown`; now it logs
  `bind_failed`.
- **The client reattaches to the orphan.** Callers find the port answering
  and carry on, so a test or acceptance run talks to the OLD process. See
  [stale-server-invalidates-acceptance.md](stale-server-invalidates-acceptance.md).

It happened live twice. In 2026-07-15 `scripts/gateway-smoke.py` left an
orphan holding the port. In 2026-10-17 closing the VSCode server terminal
on Windows 11 left the installed 1.19.4 server running; that is the
`2e2b833b` fix.

POSIX is gentler but not safe. The bootloader forwards catchable signals
(SIGTERM, SIGINT) to its child, so `proc.terminate()` usually works there.
SIGKILL cannot be forwarded, so `proc.kill()` on the bootloader orphans the
child on macOS and Linux as well.

## What's actually true

Every site that stops a spawned server now takes the whole tree:

1. **`vscode-extension/src/extension.ts::stopChild`** (`2e2b833b`): it sends
   `POST /shutdown`, waits up to the grace period (5 s, shorter on the
   `deactivate()` path because VS Code gives that 5 s in all), then runs
   `taskkill /PID <pid> /T /F` on win32 or `proc.kill()` elsewhere. All three
   exits go through it: the terminal's close button, Start's stale-terminal
   dispose, and `deactivate()`. Guarded by
   `tests/test_session_end_workflows.py` Part 7
   (`TestVscodeTerminalCloseStopsServer`, with a mutation class).
2. **`scripts/gateway-smoke.py::_signal_tree`** spawns with
   `start_new_session=True` and kills the process group (`os.killpg`) on
   POSIX, or uses `taskkill /F /T` on Windows after a `terminate()`.
3. **`ppxai-desktop.py::stop_server`** (2026-10-25): until then the
   launcher's start-up timeout called `process.terminate()` and could leave
   a slow-starting server alive on Windows. It now uses `taskkill /T /F` on
   Windows and signals the process group on Unix. Guarded by
   `tests/test_desktop_server_stop.py`, which includes a control showing that
   a parent-only terminate orphans the child.

When you add a site that spawns a ppxai binary and later stops it, use
`/shutdown` first and a tree kill after it. On POSIX, spawn it in its own
session and signal the group. Test the stop against the **installed binary**,
because a source run (`uv run ppxai-server`) has no bootloader and passes
either way.

## Related

- [stale-server-invalidates-acceptance.md](stale-server-invalidates-acceptance.md):
  what a surviving server does to the next run.
- [a-check-that-never-ran-reports-success.md](a-check-that-never-ran-reports-success.md):
  a `kill()` that "succeeded" is the same shape.
- `44ea976a`: a bind failure is reported as `bind_failed`, the symptom an
  orphan leaves behind.
