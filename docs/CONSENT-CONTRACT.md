# Consent Contract

**Status:** Reference. Update when consent layer behavior changes.
**Audience:** ppxai contributors and security reviewers.
**Last verified:** 2026-04-26 (covered by `tests/test_tool_security.py` +
`tests/test_file_editing_tools.py`).

This doc is the single source of truth for what triggers a consent
prompt in ppxai, what the prompt covers, what bypasses it, and what
remains the user's responsibility outside the consent layer.

The contract is enforced by:

- [`ppxai/engine/consent_ops.py`](../ppxai/engine/consent_ops.py)
  — file edit + shell consent flows
- [`ppxai/common/consent.py`](../ppxai/common/consent.py)
  — `classify_shell_command` + ConsentResponse normalization
- [`ppxai/engine/tools/builtin/editor.py`](../ppxai/engine/tools/builtin/editor.py)
  — every editor tool calls `request_file_edit_consent` first
- [`ppxai/engine/tools/builtin/shell.py`](../ppxai/engine/tools/builtin/shell.py)
  — `ShellExecuteTool` calls `request_shell_consent` first
- [`ppxai/engine/tools/builtin/container.py`](../ppxai/engine/tools/builtin/container.py)
  — `ConsentCLITool` (and subclasses: `DockerConsentTool`,
  `KubeConsentTool`) call `request_shell_consent` before subprocess

## TL;DR

| Operation | Triggers consent? | Default if no callback | Persistence |
|---|---|---|---|
| `apply_patch` / `replace_block` / `insert_text` / `delete_lines` | YES | **Allow** (back-compat) | Per-file in session.allowed_files; mode YES/ALWAYS/NEVER session-wide |
| `read_file` / `list_directory` / `search_files` | NO | n/a | n/a — read-only |
| `shell_execute` (NEVER pattern) | NO — blocked | n/a | n/a |
| `shell_execute` (SAFE pattern) | NO — bypasses | n/a | n/a |
| `shell_execute` (DANGEROUS or unclassified) | YES | **Deny** (fail-safe) | Per-command in session.allowed_commands; mode YES/ALWAYS/NEVER session-wide |
| `ConsentCLITool` (Docker, kubectl write paths) | YES (via shell consent) | **Deny** | Same as shell_execute |
| Document tool reads (CSV/PDF/DOCX/XLSX/PPTX) | NO | n/a | n/a — read-only |
| Network/HTTP tools | NO | n/a | n/a — see "What's NOT covered" below |

## File edit consent

Triggered by every editor tool's first call per file in a session. Flow:

```
editor.execute(file_path, ...)
  → engine.request_file_edit_consent(file_path)
    → resolve to absolute path (Path.resolve())
    → if agent_mode AND first edit AND checkpoint_manager: create checkpoint
    → if session.edit_consent_mode == ALWAYS: return True
    → if session.edit_consent_mode == NEVER: return False
    → if path in session.allowed_files: return True (already consented)
    → if no callback: return True (back-compat default)
    → emit CONSENT_REQUEST event
    → await consent_callback(absolute_path)
    → response in {YES, ALWAYS, NEVER, NO}
        YES    → add to allowed_files, return True
        ALWAYS → set session.edit_consent_mode = ALWAYS, return True
        NEVER  → set session.edit_consent_mode = NEVER, return False
        NO     → return False (does NOT add to allowed_files)
```

### What this covers

- **Path traversal at the consent layer** — the path is resolved via
  `Path.resolve()` *before* the callback fires, so the user sees the
  fully-normalized absolute path. A malicious LLM passing `../../etc/passwd`
  cannot hide the target.
- **Symlinks** — `Path.resolve()` follows them. The callback sees the
  *real* target, not the link path. The user-facing prompt shows where
  the edit will land.
- **Per-file granularity** — saying YES to `/path/a.txt` does not
  pre-approve `/path/b.txt`. Each file gets its own prompt unless the
  user picks ALWAYS.
- **Session-wide modes** — ALWAYS and NEVER persist across all
  subsequent file edits in the current session, but NOT across sessions
  (the next ppxai run starts fresh in mode NORMAL).
- **Agent-mode checkpoint** — first file edit in agent_mode creates a
  recovery checkpoint before the change. `/undo` rolls back to the
  pre-edit state.

### What this does NOT cover

- **Read-only operations** — `read_file`, `list_directory`,
  `search_files`. The LLM may legitimately need to read system config
  (`/etc/hosts`, `~/.gitconfig`, `/proc/meminfo`) to give correct
  advice. Reads are unrestricted at the tool layer; sensitivity of
  what's accessible is controlled by the **OS-level permissions** of
  the user running ppxai, not the consent layer.
- **Cross-session memory** — ALWAYS in session A does not affect
  session B. Each new session boots into mode NORMAL.
- **Per-edit checkpoints in non-agent mode** — `/undo` works only
  inside agent_mode and only for the first edit per file. For
  long edit chains the user is expected to use git.
- **Path-traversal at the tool layer** — the consent layer is the
  only barrier. Tools accept any path the consent layer approves.
  This is intentional: the security boundary is the human, not the
  filename string.

## Shell command consent

Triggered by every `shell_execute` call. Flow:

```
shell.execute(command, working_dir)
  → engine.request_shell_consent(command, working_dir)
    → classify_shell_command(command, shell_config)
        match never_allow regex   → NEVER  → return False (no callback)
        match allowed_commands    → SAFE   → return True (no callback)
        match dangerous_commands  → DANGEROUS → continue
        no match                  → DANGEROUS (fail-safe default)
    → if session.shell_consent_mode == ALWAYS: return True
    → if session.shell_consent_mode == NEVER: return False
    → if command in session.allowed_commands: return True
    → if no callback: return False (FAIL-SAFE — different from file edit!)
    → emit CONSENT_REQUEST event with risk_level
    → await shell_consent_callback(command, working_dir, risk_level)
    → response in {YES, ALWAYS, NEVER, NO}
        YES    → add to allowed_commands (verbatim string), return True
        ALWAYS → set session.shell_consent_mode = ALWAYS, return True
        NEVER  → set session.shell_consent_mode = NEVER, return False
        NO     → return False
```

### Default fail-safe behavior

The contract is **deliberately asymmetric**:

| Layer | No callback installed | Reason |
|---|---|---|
| File edit | Allow | Back-compat with pre-v1.11.0 — file edits had no consent layer at all and tests / scripts relied on it. |
| Shell | **Deny** | New feature in v1.11.2; no back-compat surface. Shell can `rm -rf` or exfiltrate, the cost of a missed prompt is too high. |

Shell-tool callers in production ALWAYS install a callback (Rich
TUI's `console_consent_callback`, Textual TUI's
`textual_consent_callback`, web's HTTP callback). The "no callback"
branch is a safety net for embedding contexts where the host
forgot to wire it.

### NEVER patterns (catastrophic — can't be overridden)

Configured in `~/.ppxai/ppxai-config.json` under `tools.shell.never_allow`.
Default install ships with patterns for:

- `rm -rf /` and similar root-of-filesystem deletions
- `dd of=/dev/...` block-device writes
- `mkfs.*` filesystem reformat
- `:(){ :|:& };:` fork bombs

A NEVER classification short-circuits **before** the callback runs.
The user can NOT override it — the pattern would have to be removed
from config, which is an explicit, out-of-band action. Tests in
[`tests/test_tool_security.py::TestShellSecurityContract`](../tests/test_tool_security.py)
pin this — even an always-yes callback can't unblock a NEVER command.

### SAFE patterns (bypass — no prompt)

Configured under `tools.shell.allowed_commands`. Default ships with
common read-only and dev commands: `ls`, `cat`, `pwd`, `git status`,
`git diff`, `pytest`, etc. Matching these returns True immediately
— no callback, no event, no log.

### DANGEROUS (default — prompts each time unless ALWAYS)

Anything not matching NEVER or SAFE is DANGEROUS. The default config
ships explicit dangerous patterns (`git push`, `git reset --hard`,
`npm install`) but the catch-all rule "unknown command → DANGEROUS"
is the real protection — adding a new binary to the system doesn't
silently grant it free execution.

### What this covers

- **Catastrophic commands always blocked** — NEVER patterns survive
  all consent overrides.
- **Per-exact-string memory** — `git push origin main` consented
  doesn't pre-approve `git push --force`. The string match is
  literal.
- **Risk-level visible to UI** — the `risk_level` argument lets
  TUI/web render different prompt styling for DANGEROUS vs
  unclassified.
- **Container CLI tools** — every `ConsentCLITool` (Docker, kubectl
  write ops) routes through `request_shell_consent`, so the same
  classification + per-command memory applies.

### What this does NOT cover

- **Argument injection in safe-classified commands** — if `ls` is
  in `allowed_commands` and the LLM sends `ls; rm -rf /`, the regex
  matches `^ls\b` and the consent layer returns SAFE. The shell
  tool's compound-command detection (`&&`, `||`, `;`, `|`) is
  intended to catch this, but the contract is: **shell metacharacters
  in args are the user's risk surface**. Don't put broad regex
  patterns in `allowed_commands`.
- **Process group escapes** — `nohup`, `setsid`, etc., backgrounded
  processes outlive the timeout. Subprocess timeout (default 30s)
  kills the immediate child, not detached descendants.
- **Working directory traversal** — the `working_dir` argument is
  not validated against the engine's tracked working directory.
  Tools can be invoked with any cwd; this is intentional (LLM might
  legitimately want to run a command in a sibling project).
- **Env vars / FD inheritance** — subprocess inherits the parent's
  environment. API keys, etc., visible to spawned commands.

## Document tool reads (CSV/PDF/DOCX/XLSX/PPTX)

These tools (`read_csv`, `read_pdf`, `get_pdf_page_image`,
`read_excel`, `read_pptx`, etc.) are **read-only** and bypass consent.

Rationale: they're functionally equivalent to `read_file` —
extracting text/structure from a file the user has already given the
LLM access to via attachment or filesystem permission. The trust
boundary is the OS-level read permission of the ppxai process.

The document parsers are the OS-level read; corruption or
malformed-input crashes (e.g., a malicious PDF) are tested per-tool
in `test_pdf_tools.py`, `test_csv_tools.py`, `test_excel_pptx_tools.py`.

## What's NOT covered by the consent layer

These categories are **out of scope** for this doc and need
separate review/hardening:

1. **Network/HTTP tools** — provider API calls, web search, URL
   fetches. The consent layer does not prompt before sending data
   to OpenAI/Perplexity/Gemini/etc. The user accepts this when
   they configure the provider.

2. **Plugin/MCP tools** — third-party MCP servers register tools
   with arbitrary semantics. The consent layer doesn't classify
   them. Plugin authors are responsible for their own prompts. See
   [`docs/MCP-TRUST-MODEL.md`](MCP-TRUST-MODEL.md) (TODO — not yet
   written).

3. **Engine reload of config** — `engine.reload_config()` re-reads
   `ppxai-config.json` on every chat. A user-edited config takes
   effect immediately, including changes to `never_allow` and
   `allowed_commands`. There is no signature-checking — the user
   is trusted to manage their own config file.

4. **Session restore** — loading a previously-saved session restores
   the message history but **not** `allowed_files` or
   `allowed_commands`. Restored sessions start with empty allow-lists
   so prior consent decisions don't silently carry forward into a
   new working context. Session-wide mode (ALWAYS/NEVER/NORMAL) is
   also reset.

5. **Tool argument logging** — full tool arguments are logged at
   DEBUG level. Sensitive args (API keys passed as command args,
   tokens in URLs) end up in `~/.ppxai/logs/` if debug logging is
   on. The consent layer does not redact.

## Test coverage

Behavior pinned by the following test classes:

| Class | File | What it pins |
|---|---|---|
| `TestEditorPathHandling` | tests/test_tool_security.py | relative-via-engine-working-dir, absolute verbatim, symlink follow, malformed patch no-op, consent denial blocks all 4 editor tools |
| `TestFilesystemPathHandling` | tests/test_tool_security.py | relative-via-engine-working-dir, absolute bypass, symlink follow, missing file returns error string, directory target returns error |
| `TestShellSecurityContract` | tests/test_tool_security.py | NEVER blocks pre-callback, SAFE bypasses callback, DANGEROUS+no-callback denies, DANGEROUS+callback works, per-command memory, timeout returns error message |
| `TestContainerConsentFlow` | tests/test_tool_security.py | ConsentCLITool denial blocks subprocess, runtime_check short-circuits consent |
| `Test*` (consent flow) | tests/test_file_editing_tools.py | YES/ALWAYS/NEVER/NO responses, mode persistence, default-allow without callback |

## When to update this doc

- **A new tool gets a consent prompt.** Add it to the TL;DR table
  and to "What this covers" / "What this does NOT cover."
- **The fail-safe default for an existing tool family changes.** The
  asymmetry between file-edit (default-allow) and shell
  (default-deny) is load-bearing — flipping either needs an explicit
  ADR.
- **A new ConsentResponse value is added.** Currently {YES, ALWAYS,
  NEVER, NO} — anything else needs the response normalization
  function in `ppxai/common/consent.py` updated and a test class
  added under `test_file_editing_tools.py`.
- **NEVER patterns or the catch-all "unknown → dangerous" rule
  changes.** Update the test in
  `TestShellSecurityContract::test_dangerous_without_callback_denied_failsafe`.

## Related documents

- [docs/ARCHITECTURE.md](ARCHITECTURE.md) — broader engine architecture
- [docs/MODEL-SELECTION-GUIDE.md](MODEL-SELECTION-GUIDE.md) — planner/executor pattern
- [docs/DEBUG-LOGGING.md](DEBUG-LOGGING.md) — log persistence flow
