# A VS Code shell terminal is not yours alone: run long-lived processes in a pseudoterminal

**TL;DR:** Any extension can type into a shell terminal your extension
created, and VS Code types Ctrl+C into a busy one first. A server
started with `terminal.sendText(<command>)` can be killed by someone
else's command; start it as the terminal's own process (a
`Pseudoterminal` with `child_process.spawn`) instead.

**Verify with:** `grep -n "sendText\|pty" vscode-extension/src/extension.ts`
(the server terminal is a `Pseudoterminal` since `5b06fa01`; any new
`createTerminal(...)` + `sendText(...)` pair for a long-lived process
reintroduces the hazard). Reproduce the old behaviour: workspace with a
`.venv`, Python Environments at its default
`python-envs.terminal.autoActivationType: "command"`, an extension that
`sendText`s a server command into a new shell terminal.

## Why this trips people up

`createTerminal()` + `sendText()` looks like "my terminal, my process".
It works in every test without a `.venv`, and with one it fails only
when the race goes the wrong way, so it reads as flakiness or as a
server crash. The server log says `reason: ctrl_c`, which points at the
user, not at another extension.

The 2026-10-14 incident: the ppxai Start Server button typed the
server path into a new shell terminal. Python Environments 1.38 waits
up to 5000 ms for shell integration on a new terminal, then runs
`source .venv/bin/activate` through
`terminal.shellIntegration.executeCommand`. The terminal was busy
running the server, the server got SIGINT about 5 s after the terminal
opened (3.0–3.1 s uptime), and the terminal showed `^C` followed by
` source …/activate`. Reproduced 3 of 3; once, activation won the race
and the server survived, which is why nobody had seen it.

The evidence that pinned it, in order: `~/.ppxai/logs/server-debug.log`
(`Received SIGINT`, `reason: ctrl_c`; the Stop button logs
`api_request`), the "Python Environments" output log (`Shell execution
timed out: source …/activate` ~200 ms after each SIGINT), and the
extension's own code (`grep -n "x03\|sendText" vscode-extension/src/*.ts`
showed nothing of ours sends Ctrl+C there).

## What's actually true

- Other extensions write into every new shell terminal: Python
  Environments' `command` activation mode does, and VS Code's
  `executeCommand` interrupts a running command first. Whether a
  `sendText`-started process survives depends on timing you don't
  control.
- A `Pseudoterminal` has no shell: input goes to its `handleInput`,
  which can ignore it, and nothing can interrupt the process the
  extension spawned. `vscode-extension/src/extension.ts`
  `createServerTerminal()` is the pattern: spawn, forward stdout/stderr
  with `\n` → `\r\n`, kill the child in `close()`, set
  `PYTHONUNBUFFERED=1` because stdout is now a pipe.
- One-shot user commands (`runCommandInTerminal` in `chatPanel.ts`) can
  stay on `sendText`: they run in the user's shell on purpose and end on
  their own.

## Related

- [stale-server-invalidates-acceptance.md](stale-server-invalidates-acceptance.md)
  — the other way a ppxai-server "dies" in a client test: it never got
  the port.
