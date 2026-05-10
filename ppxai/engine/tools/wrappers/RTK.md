**Tool output may be rtk-compressed.** This host has rtk (Rust Token
Killer, https://github.com/rtk-ai/rtk) installed. ppxai's engine
automatically wraps shell commands like `git status`, `ls`, and `grep`
through rtk before running them, so the output you receive from the
`execute_shell_command` tool may be in rtk's compact form rather than
the verbose raw form.

What this means for you:
- Don't pattern-match on raw output formats. `git status` output via
  rtk is structurally different (single-line summary instead of the
  full porcelain v1 layout). Treat the output as authoritative for
  what it says, not for what it doesn't say.
- File listings via `rtk ls` may show counts and grouped extensions
  instead of one row per file. This is intentional — full detail is
  available on demand by asking for `ls -la <specific path>`.
- Search output via `rtk grep` strips redundant whitespace and groups
  matches by file. Match positions and line numbers are preserved.
- `git diff`, `git log`, and `gh` outputs are similarly summarized.

You don't need to do anything differently. The wrapping is transparent
and the engine retries the raw command if rtk fails. Just interpret
tool output as it arrives without assuming a particular layout.
