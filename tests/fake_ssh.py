"""A stand-in for the `ssh` binary, for `OpenSSHTransport` tests.

`OpenSSHTransport(ssh_command=(sys.executable, "tests/fake_ssh.py"))` runs
this instead of ssh. It parses the same argv the real client would get and:

- **command mode** (a remote command after the destination): runs it with
  the local `sh -c`, exactly as the remote login shell would, and passes its
  stdout, stderr and exit status through. That makes the quoting tests
  end-to-end: whatever `quote_remote_argv` produced is parsed by a real
  POSIX shell.
- **forward mode** (`-N -L <local>:<remote>`): listens on the local end (a
  unix socket path or `127.0.0.1:<port>`) and relays each connection to the
  remote unix socket, until SIGTERM.

Failure injection, via the environment:

- `FAKE_SSH_STDERR` + `FAKE_SSH_RC` -- print that stderr and exit with that
  status before doing anything (an ssh-level failure).
- `FAKE_SSH_SLEEP` -- sleep that many seconds first.
- `FAKE_SSH_NO_LISTEN=1` -- in forward mode, never open the local end.
- `FAKE_SSH_ARGV_LOG` -- append this process's argv (JSON) to that file.

Stdlib only; never reaches the network.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time

_FLAGS_WITH_VALUE = {"-o", "-L", "-p", "-i", "-J", "-F", "-l"}


def _parse(argv: list[str]) -> tuple[dict[str, str], list[str], str, str | None]:
    options: dict[str, str] = {}
    flags: list[str] = []
    forward = ""
    i = 0
    while i < len(argv) and argv[i].startswith("-"):
        flag = argv[i]
        if flag in _FLAGS_WITH_VALUE:
            value = argv[i + 1]
            if flag == "-o":
                key, _, val = value.partition("=")
                options[key] = val
            elif flag == "-L":
                forward = value
            i += 2
        else:
            flags.append(flag)
            i += 1
    destination = argv[i]
    command = " ".join(argv[i + 1:]) if len(argv) > i + 1 else None
    return options, flags + ([f"-L{forward}"] if forward else []), destination, command


def _pipe(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        for s in (src, dst):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def _serve_forward(spec: str) -> None:
    # `<local>:<remote>` where local is a path or `127.0.0.1:<port>`.
    local, remote = spec.rsplit(":", 1)
    if os.environ.get("FAKE_SSH_NO_LISTEN") == "1":
        while True:
            time.sleep(1)
    if local.startswith("127.0.0.1:"):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", int(local.rsplit(":", 1)[1])))
    else:
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        if os.path.exists(local):
            os.unlink(local)
        listener.bind(local)
        os.chmod(local, 0o600)
    listener.listen(16)
    while True:
        client, _ = listener.accept()
        upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            upstream.connect(remote)
        except OSError as exc:
            # Real ssh keeps running and logs a channel failure.
            print(f"channel 2: open failed: connect failed: {exc}",
                  file=sys.stderr, flush=True)
            client.close()
            continue
        for a, b in ((client, upstream), (upstream, client)):
            threading.Thread(target=_pipe, args=(a, b), daemon=True).start()


def main() -> int:
    argv = sys.argv[1:]
    log = os.environ.get("FAKE_SSH_ARGV_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(argv) + "\n")
    if os.environ.get("FAKE_SSH_SLEEP"):
        time.sleep(float(os.environ["FAKE_SSH_SLEEP"]))
    if "FAKE_SSH_RC" in os.environ:
        # Bytes, not text: text-mode stderr turns \n into \r\n on Windows,
        # and the tests assert OpenSSH's stderr is kept verbatim.
        sys.stderr.buffer.write(os.environ.get("FAKE_SSH_STDERR", "").encode())
        sys.stderr.buffer.flush()
        return int(os.environ["FAKE_SSH_RC"])

    options, flags, _destination, command = _parse(argv)
    if options.get("BatchMode") != "yes":
        print("fake_ssh: refusing to run without BatchMode=yes", file=sys.stderr)
        return 255
    forward = next((f[2:] for f in flags if f.startswith("-L")), "")
    if forward:
        signal.signal(signal.SIGTERM, lambda *_: os._exit(0))
        _serve_forward(forward)
        return 0
    if command is None:
        print("fake_ssh: no command and no forward", file=sys.stderr)
        return 255
    done = subprocess.run(["sh", "-c", command], capture_output=True)
    sys.stdout.buffer.write(done.stdout)
    sys.stderr.buffer.write(done.stderr)
    return done.returncode


if __name__ == "__main__":
    sys.exit(main())
