# Shell wrapper framework

ppxai v1.18.5 adds a **wrapper framework** for the shell tool. A wrapper
is a transparent CLI proxy that ppxai applies to commands the shell tool
is about to run — the model asks for `git status`, ppxai's engine
forwards it through a wrapper that filters or transforms the output, the
model receives the wrapper's output. Two layers, both gated on the
wrapper being installed and not opted out:

- **Engine-side rewrite.** Before spawning the subprocess, ppxai asks
  the wrapper "should this command be wrapped?" and uses the rewritten
  form on yes.
- **System-prompt hint.** When wrappers are active, ppxai appends a
  small markdown block to the system prompt explaining that shell-tool
  output may be in a wrapped form. Helps the model interpret what it
  sees without confabulating raw output shapes.

The framework is **JSON-driven**. Each wrapper is declared in
`tools.shell.wrappers` in `~/.ppxai/ppxai-config.json`. Adding a
wrapper that fits one of the two generic patterns (probe / always)
requires zero ppxai code changes.

The first wrapper that ships with ppxai is **rtk** (Rust Token Killer,
https://github.com/rtk-ai/rtk) — see [§rtk](#rtk-the-first-concrete-wrapper) below.

## Why bother

Agent loops that shell out a lot — running `git status`, checking CI,
searching files, listing directories — consume LLM context proportional
to the raw tool output. A wrapper that filters / compresses that output
before it enters the conversation directly reduces token cost per
iteration.

Real-world reference numbers (rtk against Claude Code): 47% savings on
Windows manual mode (1355 commands), 66% on a Unix bash hook (4338
commands). ppxai's integration sits in the same category — engine-side
rewrite, transparent to the user, opt-out via config.

## Adding a wrapper (recipe)

1. Pick the pattern:
   - **Probe** — wrapper has its own dry-run command (e.g., `rtk hook check <cmd>` returns the rewritten command on exit 0, "No rewrite for: ..." on exit 1).
   - **Always** — no dry-run; user opted in, so wrap every command (e.g. `time`, `nice`, perf profilers).
2. Write a JSON entry in your `~/.ppxai/ppxai-config.json`:
   ```json
   {
     "tools": {
       "shell": {
         "wrappers": [
           {
             "name": "myperf",
             "type": "probe",
             "binary": "myperf",
             "probe_args": ["dry-run"],
             "no_rewrite_marker": "skip:",
             "transparent_for_safety": true,
             "prompt_block_path": "MYPERF.md",
             "enabled": "auto"
           }
         ]
       }
     }
   }
   ```
3. (Optional) Drop a markdown hint file at the resolved path — for
   user-declared wrappers the search order is absolute → `~/.ppxai/wrappers/<path>` → ppxai package data. The file content goes into the system prompt under the wrapper's section header so the model knows about the wrapping.
4. Restart ppxai (the wrapper registry is built at engine startup;
   detection cache is per-process).

## Schema reference

Every entry needs:

| Field | Required | Type | Meaning |
|---|---|---|---|
| `name` | yes | str | Identifier; conflict with default entries resolves "user wins" — your fields override the default's. |
| `type` | yes | `"probe"` \| `"always"` | Decision strategy. |
| `binary` | yes | str | Name to look up via `shutil.which`. |
| `enabled` | no | `"auto"` \| `"always"` \| `"never"` (default `"auto"`) | `auto` = wrap iff binary is on PATH; `always` = error if missing; `never` = disabled. |
| `transparent_for_safety` | no | bool (default `true`) | Consent classifier strips this wrapper's prefix before classification, so safety verdicts are invariant under wrapping. |
| `prompt_block_path` | no | str | Path to a markdown file injected into the system prompt. Resolution order: absolute → `~/.ppxai/wrappers/<path>` → ppxai package data. |
| `failure_markers` | no | list[str] | Stderr substrings that signal wrapper-side failure (used by graceful-fallback retry, when enabled). |
| `retry_raw_on_failure` | no | bool (default `false`) | Whether to retry the raw command if a wrapper-side failure is detected. |

Probe-only:

| Field | Required | Type | Meaning |
|---|---|---|---|
| `probe_args` | yes | list[str] | Arguments to the dry-run command. ppxai calls `<binary> <probe_args> <command>`. |
| `no_rewrite_marker` | no | str (default `""`) | Stdout starts with this on no-rewrite. |
| `probe_timeout_seconds` | no | float (default `5.0`) | Probe call timeout. |

Always-only:

| Field | Required | Type | Meaning |
|---|---|---|---|
| `prefix` | yes | str | String to prepend to the command. |

## Decision rules

- Wrappers iterate in declaration order from the config (defaults first, then user entries).
- **First-match-wins.** The first wrapper whose `maybe_rewrite()` returns a non-None form wraps the command; subsequent wrappers don't see the wrapped form. (No pipelining today; if pipelined wrapping is ever wanted, a `chain: bool` field can be added.)
- A wrapper with `enabled: never` is skipped entirely — neither engine-side rewrite nor prompt-hint injection.
- `enabled: auto` skips the wrapper when its binary isn't on PATH (silent no-op).
- `enabled: always` raises a clear error if the binary is missing — useful for cluster deployments that mandate a wrapper.

## Safety classification interaction

The shell tool requests user consent on the **raw** command, before any
wrapping happens. So in normal flow the consent classifier sees `git
status`, not `rtk git status`, and the wrapping doesn't change the
safety verdict.

Even so, the classifier strips leading wrapper tokens via the registry
before pattern matching. This handles the corner case where a user
or model types `rtk git status` directly: the safety verdict is
invariant under wrapping. Only **active** wrappers with
`transparent_for_safety: true` license stripping; an inactive wrapper
or a non-transparent one (e.g. a hypothetical sandbox where you DO
want consent on the wrapped form) is left alone.

## rtk: the first concrete wrapper

[rtk](https://github.com/rtk-ai/rtk) is a Rust CLI proxy that filters
and compresses common dev-tool outputs (`git`, `ls`, `grep`, `pytest`,
`docker`, `kubectl`, etc.). It ships in ppxai's defaults as:

```json
{
  "name": "rtk",
  "type": "probe",
  "binary": "rtk",
  "probe_args": ["hook", "check"],
  "no_rewrite_marker": "No rewrite for:",
  "transparent_for_safety": true,
  "prompt_block_path": "RTK.md",
  "enabled": "auto"
}
```

When rtk is on PATH:
- ppxai calls `rtk hook check <cmd>` before each shell-tool spawn.
- On exit 0, the stdout IS the rewritten form; ppxai spawns it (`rtk git status` instead of `git status`).
- On exit 1 + "No rewrite for: ...", ppxai spawns the raw form.
- The system prompt gains a section pointing at `RTK.md` so the model knows compact-format output may arrive.

### Installing rtk

```bash
brew install rtk                                      # macOS Homebrew
curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/master/install.sh | sh    # Linux / manual
winget install rtk-ai.rtk                             # Windows
```

Verify with `rtk --version` then restart ppxai (detection cache is
per-process).

### rtk-specific config (overriding the default)

Common patterns, all going under `tools.shell.wrappers` keyed by `name: "rtk"`:

```json
// Disable rtk wrapping entirely
{"name": "rtk", "enabled": "never"}

// Wrap silently but skip the prompt-hint block (saves ~1KB on the system prompt)
{"name": "rtk", "prompt_block_path": null}

// Require rtk — fail loudly if missing (cluster deployment)
{"name": "rtk", "enabled": "always"}
```

The legacy `tools.shell.use_rtk` (string) and `use_rtk_prompt_hint`
(bool) fields are recognized as a back-compat shim and translated
internally into the rtk default's `enabled` and `prompt_block_path`
fields. Plan to migrate to the wrappers form before v1.20.x.

## Troubleshooting

**Wrapping isn't happening.** Check:
1. `<binary> --version` works in the same shell that started ppxai.
2. The wrapper entry's `enabled` is not `"never"`.
3. ppxai was restarted after the wrapper became installed (detection cache is per-process).

**Specific command fails when wrapped.** This is a wrapper-upstream issue;
file at the wrapper's repo. Workarounds: (a) set `enabled: "never"` on
the wrapper to disable; (b) once Phase 4 graceful fallback ships,
configure `failure_markers` + `retry_raw_on_failure` so ppxai retries
raw on detected wrapper-side breakage.

**Performance overhead.** Each shell call adds one probe subprocess
(~10-30 ms typical for `rtk hook check`). On hot tool-call loops this
adds up; if latency regressions show up, set `enabled: "never"` for the
expensive wrapper. Token-cost savings generally outweigh latency cost
by a wide margin but YMMV.

## Reference

- v1.18.5 plan: [`docs/TODO-v1.18.5-shell-wrappers.md`](TODO-v1.18.5-shell-wrappers.md)
- ROADMAP entry: [`ROADMAP.md`](../ROADMAP.md) §"v1.18.5 - Shell wrapper framework"
- rtk upstream: https://github.com/rtk-ai/rtk
- Framework code: `ppxai/engine/tools/wrappers/`
