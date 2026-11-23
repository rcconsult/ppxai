# ADR 0020: Terminals by alias; a command is typed, never run

- **Status:** Implemented (2026-11-23, `feature/v1.19.5`). Accepted 2026-11-23 (owner).
- **Deciders:** owner (owns both ppxai and tai)
- **Target:** v1.19.5.
- **Related:** tai's ADR 0013 "Terminals by alias" (a different record from
  ppxai's ADR 0013, the SSH hub), tai's `docs/upstream/ppxai-terminals-by-alias.md`
  (the change request), `tests/test_terminal_alias.py` (the fence).

## Context

tai, a terminal client, keeps several terminals and wants `/terminal` to
reach one of them by name: open it, or type a command into it. Three things
stood in the way:

1. **`/terminal` took no arguments.** `handle_terminal` ignored `args` and
   emitted `open_terminal {cwd}`, so a client could not say which terminal.
2. **Every HTTP client got the TUI's help as the answer.** The handler fell
   back to a notification only on `ImportError` of `ppxai.tui.terminal`,
   which ships in every install, so web, VS Code and tai all showed the
   Rich/Textual image-protocol help.
3. **Clients disagreed on whether a command runs.** VS Code's `run_shell`
   and its "Run in Terminal" path (`chatPanel.ts::runCommandInTerminal`, used
   by the shell-consent dialog) called `sendText(command)`, which presses
   Enter. The web client only showed the command as a chat message.

## Decision

1. **`/terminal [alias] [-- command]`.** No arguments: `open_terminal {cwd}`,
   as before. `alias`: `open_terminal {cwd, name}`. `alias -- command`:
   `run_shell {command, cwd, name}`. `-- command`: `run_shell {command, cwd}`,
   for the focused terminal. Everything after the first `--` is the command,
   verbatim: it is never shell-split. The slash-command parser splits the
   command name off once and passes the rest raw, so `--` collides with
   nothing.
2. **`name` is an optional payload field** on `open_terminal` and
   `run_shell`. It is the terminal's alias: a number from 1 (`[1-9][0-9]*`,
   tai's terminal numbers), or a Kubernetes DNS label (RFC 1123: 1–63
   characters of `a-z`, `0-9` and `-`, starting and ending with a letter or
   digit) that contains a letter. `ppxai.commands.system.TERMINAL_NAME_RE` is
   the one definition. A bad alias is an error result with no side effect.
   The field is `name`, not `alias`, because `alias` already names command
   aliases in `CommandSpec`, and VS Code calls the same thing `name`.
3. **ppxai stores nothing about a client's terminals.** The client keeps the
   alias map; ppxai only carries the alias. Absent means "the focused
   terminal, or a new one", as before.
4. **A command is typed, never run, in every client.** The user presses
   Enter. VS Code uses `sendText(command, false)` for `run_shell` and for
   `runCommandInTerminal`; web uses `TerminalView.typeText`, which writes to
   the PTY socket without a newline and queues text until the socket opens;
   tai types only at a shell prompt (its ADR 0013).
5. **The answer depends on the context, not on an import.** Over HTTP
   (`ServerCommandContext`: web, VS Code, tai) `/terminal` answers with a short
   notification. The Rich and Textual TUIs have no terminals to address, so
   there plain `/terminal` keeps the image-protocol help and an alias or a
   command is an error.

## Consequences

- **Behaviour change in VS Code:** the shell-consent dialog's "Run in
  Terminal" choice now leaves the command typed in a new terminal instead of
  running it. No Python command emitted `run_shell` before this record, so
  nothing else changes.
- **Web:** a named terminal is one panel per alias (`TerminalView.pathFor`),
  reused when it is on the right-panel stack. The stack unmounts a view that
  is not on top, which closes its PTY socket, so a named terminal brought
  back to the top starts a fresh shell. That is the existing panel
  behaviour, not new with this record.
- **tai sends no client id yet.** `KNOWN_CLIENTS` is
  `{rich, textual, web, vscode}` and the route refuses any other id; adding
  `tai` is a separate decision.
- No `client_action` is added, so the command parity fence is unchanged.
  `tests/test_terminal_alias.py` holds the alias rule, the payloads per
  context, VS Code's reuse and `sendText(..., false)`, and the real web
  modules under Node.
